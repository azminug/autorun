"""
Roblox Auto Login Bot v6
========================
Simplified architecture:
- Removed PID detection (handled by roblox_heartbeat.lua)
- No double instance launch
- Clean browser automation
- Firebase-driven monitoring
"""

import time
import sys
import os
import atexit
from datetime import datetime

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Local imports
from config import ACCOUNTS_FILE, DEFAULT_SERVER_LINK, MAX_LOGIN_ATTEMPTS
from utils.hwid import get_hwid, get_machine_info
from utils.helpers import safe_json_load, safe_json_save, get_timestamp
from utils.logger import get_logger
from firebase.firebase_client import get_firebase_client
from verification.verification_handler import VerificationHandler
from verification.browser_alert_handler import BrowserAlertHandler


class RobloxAutoLoginV6:
    """
    Simplified Roblox Auto Login Bot.
    - PID tracking delegated to roblox_heartbeat.lua
    - No redundant Roblox launching
    - Clean browser flow
    """

    def __init__(self, accounts_file=None, server_link=None):
        self.accounts_file = accounts_file or ACCOUNTS_FILE
        self.server_link = server_link or DEFAULT_SERVER_LINK
        self.max_login_attempts = MAX_LOGIN_ATTEMPTS

        # Logger
        self.logger = get_logger()

        # Accounts
        self.accounts = self.load_accounts()

        # Browser
        self.driver = None

        # Services
        self.firebase = get_firebase_client()
        self.hwid = get_hwid()
        self.machine_info = get_machine_info()

        # Track processed accounts
        self.processed_accounts = []

        # Cleanup on exit
        atexit.register(self.cleanup)

    def load_accounts(self):
        """Load active accounts"""
        try:
            all_accounts = safe_json_load(self.accounts_file, [])
            if not all_accounts:
                self.logger.warning(f"No accounts in {self.accounts_file}")
                return []

            active = [a for a in all_accounts if a.get("active", True)]
            self.logger.info(
                f"📊 Loaded {len(active)}/{len(all_accounts)} active accounts"
            )
            return active
        except Exception as e:
            self.logger.error(f"Failed to load accounts: {e}")
            return []

    def setup_driver(self):
        """Setup Chrome with protocol auto-allow configuration"""
        options = webdriver.ChromeOptions()

        # Anti-detection + suppress logging
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option(
            "excludeSwitches", ["enable-automation", "enable-logging"]
        )
        options.add_experimental_option("useAutomationExtension", False)

        # Performance
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")

        # Suppress console logs and GPU errors
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_argument("--disable-logging")
        options.add_argument("--disable-software-rasterizer")

        # Auto-allow protocol handlers (from v5 - critical for Bloxstrap)
        prefs = {
            # Auto-allow roblox-player protocol
            "protocol_handler.allowed_origin_protocol_pairs": {
                "https://www.roblox.com": {"roblox-player": True},
                "https://roblox.com": {"roblox-player": True},
            },
            # Skip "external protocol" dialog
            "protocol_handler.excluded_schemes": {"roblox-player": False},
            # Disable safe browsing for external protocols
            "safebrowsing.enabled": False,
            # Allow external apps without asking
            "external_protocol_dialog.show_always_open_checkbox": True,
        }
        options.add_experimental_option("prefs", prefs)

        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Initialize alert handler for protocol dialogs
        self.alert_handler = BrowserAlertHandler(self.driver)

        # Initialize notification service
        from services.notification_service import NotificationService

        self.notifier = NotificationService()

        self.logger.info("🌐 Browser ready")

    def login_roblox(self, username, password):
        """Login to Roblox with captcha/verification detection"""
        self.logger.info(f"🔐 Logging in: {username}")

        # Update Firebase
        self._update_status(username, "logging_in")

        for attempt in range(1, self.max_login_attempts + 1):
            try:
                self.driver.get("https://www.roblox.com/login")
                time.sleep(2)

                # Fill credentials
                user_field = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "login-username"))
                )
                user_field.clear()
                user_field.send_keys(username)

                pass_field = self.driver.find_element(By.ID, "login-password")
                pass_field.clear()
                pass_field.send_keys(password)

                # Click login
                self.driver.find_element(By.ID, "login-button").click()
                self.logger.info(f"   Attempt {attempt}: Submitted")

                # Wait for redirect or error
                time.sleep(3)

                # Detect what type of challenge is present
                challenge_type = self._detect_challenge_type()

                if challenge_type:
                    self.logger.info(f"⚠️ {challenge_type} detected for {username}")
                    self._update_status(
                        username, challenge_type.lower().replace(" ", "_")
                    )

                    # Send notification for manual assistance
                    self._notify_manual_required(username, challenge_type, attempt)

                    # Wait for user to solve
                    solved = self._wait_for_challenge_solved(username, challenge_type)

                    if solved:
                        self.logger.info(f"✅ {challenge_type} solved for {username}")
                        # Check login success after solving
                        time.sleep(2)
                        if self._check_login_success():
                            self.logger.info(f"✅ Login success: {username}")
                            self._notify_challenge_solved(username, challenge_type)
                            return True
                    else:
                        self.logger.warning(
                            f"⏱️ {challenge_type} timeout for {username}"
                        )
                        continue

                # Check success
                if self._check_login_success():
                    self.logger.info(f"✅ Login success: {username}")
                    return True

                # Check for error message
                error = self._get_login_error()
                if error:
                    self.logger.warning(f"   Error: {error}")

            except Exception as e:
                self.logger.error(f"   Attempt {attempt} failed: {e}")

            time.sleep(2)

        # All attempts failed - send notification
        self._update_status(username, "login_failed")
        self._notify_login_failed(username)
        return False

    def _detect_challenge_type(self):
        """
        Detect what type of challenge is present.
        Returns: 'Captcha', 'Verification', 'Captcha + Verification', or None
        """
        captcha_present = False
        verification_present = False

        # Captcha selectors (FunCaptcha/Arkose)
        captcha_selectors = [
            "iframe[title*='arkose']",
            "iframe[title*='captcha']",
            "iframe[src*='funcaptcha']",
            "iframe[src*='arkoselabs']",
            "#arkose-container",
            "#fc-iframe-wrap",
            "[data-testid='captcha-container']",
        ]

        # Verification selectors (2FA, email verification, etc)
        verification_selectors = [
            "#two-step-verification-container",
            ".two-step-verification",
            "[data-testid='two-step-verification']",
            "input[name='code']",
            ".verification-code-input",
            "[data-testid='verification-code']",
            ".email-verification",
            "#security-question-container",
        ]

        # Check for captcha
        for selector in captcha_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(e.is_displayed() for e in elements):
                    captcha_present = True
                    break
            except:
                continue

        # Check for verification
        for selector in verification_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(e.is_displayed() for e in elements):
                    verification_present = True
                    break
            except:
                continue

        # Also check page text for verification keywords
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            if any(
                kw in page_text
                for kw in [
                    "verification code",
                    "verify your email",
                    "two-step",
                    "2-step",
                    "enter code",
                ]
            ):
                verification_present = True
        except:
            pass

        if captcha_present and verification_present:
            return "Captcha + Verification"
        elif captcha_present:
            return "Captcha"
        elif verification_present:
            return "Verification"

        return None

    def _wait_for_challenge_solved(self, username, challenge_type, timeout=300):
        """Wait for challenge to be solved manually"""
        start = time.time()
        check_interval = 3

        while time.time() - start < timeout:
            time.sleep(check_interval)

            # Check if challenge is gone
            current_challenge = self._detect_challenge_type()

            if not current_challenge:
                return True

            # Check if login succeeded (redirected away from login)
            if self._check_login_success():
                return True

            # Still waiting
            elapsed = int(time.time() - start)
            if elapsed % 30 == 0:  # Log every 30 seconds
                self.logger.info(
                    f"⏳ Waiting for {challenge_type} to be solved... ({elapsed}s)"
                )

        return False

    def _notify_manual_required(self, username, challenge_type, attempt):
        """Send Discord notification that manual intervention is needed"""
        try:
            hostname = self.machine_info.get("hostname", "Unknown")

            embed = {
                "title": "🚨 Manual Assistance Required",
                "description": f"**{username}** needs manual intervention",
                "color": 0xFF9900,  # Orange
                "fields": [
                    {"name": "Challenge Type", "value": challenge_type, "inline": True},
                    {
                        "name": "Attempt",
                        "value": f"{attempt}/{self.max_login_attempts}",
                        "inline": True,
                    },
                    {"name": "Device", "value": hostname, "inline": True},
                    {
                        "name": "Action Required",
                        "value": self._get_action_instructions(challenge_type),
                        "inline": False,
                    },
                ],
                "footer": {"text": "Waiting for manual solve..."},
                "timestamp": datetime.now().isoformat(),
            }

            if hasattr(self, "notifier"):
                self.notifier.send_discord(embed=embed)
                self.logger.info(f"📤 Notification sent for {username}")
        except Exception as e:
            self.logger.warning(f"Failed to send notification: {e}")

    def _get_action_instructions(self, challenge_type):
        """Get instructions based on challenge type"""
        if challenge_type == "Captcha":
            return "🎯 Complete the FunCaptcha puzzle"
        elif challenge_type == "Verification":
            return "📧 Enter the verification code from your email/authenticator"
        elif challenge_type == "Captcha + Verification":
            return "🎯 Complete captcha first, then 📧 enter verification code"
        return "⚠️ Solve the challenge manually"

    def _notify_challenge_solved(self, username, challenge_type):
        """Send notification that challenge was solved"""
        try:
            embed = {
                "title": "✅ Challenge Solved",
                "description": f"**{username}** - {challenge_type} completed",
                "color": 0x00FF00,  # Green
                "timestamp": datetime.now().isoformat(),
            }

            if hasattr(self, "notifier"):
                self.notifier.send_discord(embed=embed)
        except:
            pass

    def _notify_login_failed(self, username):
        """Send notification that login failed after all attempts"""
        try:
            hostname = self.machine_info.get("hostname", "Unknown")

            embed = {
                "title": "❌ Login Failed",
                "description": f"**{username}** - All {self.max_login_attempts} attempts failed",
                "color": 0xFF0000,  # Red
                "fields": [
                    {"name": "Device", "value": hostname, "inline": True},
                    {
                        "name": "Status",
                        "value": "Skipped - needs manual login",
                        "inline": True,
                    },
                ],
                "footer": {"text": "Account will be retried in next cycle"},
                "timestamp": datetime.now().isoformat(),
            }

            if hasattr(self, "notifier"):
                self.notifier.send_discord(embed=embed)
                self.logger.info(f"📤 Login failed notification sent for {username}")
        except Exception as e:
            self.logger.warning(f"Failed to send notification: {e}")

    def _check_verification(self, username):
        """Legacy method - now uses _detect_challenge_type"""
        return self._detect_challenge_type() is not None

    def _check_login_success(self):
        """Check if login was successful"""
        try:
            current_url = self.driver.current_url.lower()
            return "home" in current_url or "discover" in current_url
        except:
            return False

    def _get_login_error(self):
        """Get login error message if any"""
        try:
            error_el = self.driver.find_element(By.ID, "login-error-message")
            if error_el.is_displayed():
                return error_el.text
        except:
            pass
        return None

    def join_server(self, username):
        """Navigate to server link - Roblox launches automatically"""
        self.logger.info(f"🎮 Opening server link for {username}")
        self._update_status(username, "joining")

        try:
            self.driver.get(self.server_link)
            time.sleep(3)

            # Wait for page load
            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Click play button to trigger roblox-player protocol
            if self._click_play_button():
                self.logger.info(
                    f"✅ Play button clicked - waiting for protocol dialog"
                )

                # Handle browser protocol dialog (v5 behavior restored)
                # This allows "Open roblox-player?" popup
                if hasattr(self, "alert_handler") and self.alert_handler:
                    self.alert_handler.reset()  # Reset for new account
                    self.alert_handler.wait_and_handle(pre_wait=2)

                self._update_status(username, "launched")
                self._log_event("launch", username, "Roblox protocol triggered")
                return True
            else:
                self.logger.warning(f"⚠️ Could not click play button")
                return False

        except Exception as e:
            self.logger.error(f"Join server failed: {e}")
            return False

    def _click_play_button(self):
        """Click the play button using JavaScript to avoid intercepts"""
        selectors = [
            "button[data-testid='game-details-play-button']",
            "button[class*='play-button']",
            ".game-play-button-container button",
            "button[class*='btn-primary-md']",
            "button[class*='btn-growth-md']",
        ]

        # First, try to dismiss any overlays
        self._dismiss_overlays()
        time.sleep(1)

        for selector in selectors:
            try:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for btn in buttons:
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        return True
            except:
                continue

        # Fallback: find by text
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                text = btn.text.lower()
                if any(kw in text for kw in ["play", "join", "main"]):
                    if btn.is_displayed():
                        self.driver.execute_script("arguments[0].click();", btn)
                        return True
        except:
            pass

        return False

    def _dismiss_overlays(self):
        """Hide overlays that might intercept clicks"""
        try:
            self.driver.execute_script(
                """
                // Hide carousel and modal overlays
                var selectors = [
                    '[class*="carousel"]',
                    '[class*="modal"]',
                    '[class*="overlay"]',
                    '[class*="banner"]'
                ];
                selectors.forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        if (el && el.style) {
                            el.style.display = 'none';
                            el.style.visibility = 'hidden';
                        }
                    });
                });
                
                // Scroll to play button area
                window.scrollTo(0, 200);
            """
            )
        except:
            pass

    def wait_for_roblox_launch(self, username, wait_time=60):
        """
        Wait period after clicking play.
        Actual monitoring is done by roblox_heartbeat.lua
        """
        self.logger.info(f"⏳ Waiting {wait_time}s for Roblox to launch...")

        # The heartbeat.lua will update Firebase when player joins
        # We just wait here to give time for the protocol handler
        time.sleep(wait_time)

        # Update status - heartbeat.lua will change to 'in_game' when active
        self._update_status(username, "waiting_heartbeat")
        return True

    def process_account(self, account, index, total):
        """Process a single account"""
        username = account["username"].lower()  # Normalize to lowercase
        password = account["password"]

        print(f"\n{'='*50}")
        print(f"[{index}/{total}] {username}")
        print(f"{'='*50}")

        # Login
        if not self.login_roblox(username, password):
            self.logger.warning(f"❌ Skipping {username} - login failed")
            return

        # Join server
        if not self.join_server(username):
            self.logger.warning(f"❌ Failed to join for {username}")

        # Wait for Roblox launch (60s to allow time for Bloxstrap)
        self.wait_for_roblox_launch(username, wait_time=60)

        self.processed_accounts.append(username)

        # Close browser for next account
        self._close_browser()

    def _close_browser(self):
        """Close browser safely"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
            time.sleep(2)

    def _update_status(self, username, status):
        """Update account status in Firebase"""
        try:
            self.firebase.update_account_status(
                username,
                {
                    "status": status,
                    "hwid": self.hwid,
                    "hostname": self.machine_info.get("hostname", "unknown"),
                    "last_update": get_timestamp(),
                },
            )
        except Exception as e:
            self.logger.error(f"Firebase update failed: {e}")

    def run(self):
        """Run the bot for all accounts"""
        print("\n" + "=" * 50)
        print("🚀 Roblox Auto Login Bot v6")
        print("=" * 50)

        self.logger.info(f"🔑 HWID: {self.hwid[:16]}...")
        self.logger.info(f"💻 Host: {self.machine_info.get('hostname')}")

        if not self.accounts:
            self.logger.error("No accounts to process!")
            return

        self.logger.info(f"📊 Processing {len(self.accounts)} accounts")

        # Mark device online
        self._update_device_status("online")

        try:
            for i, account in enumerate(self.accounts, 1):
                try:
                    # Setup fresh browser for each account
                    self.setup_driver()
                    self.process_account(account, i, len(self.accounts))
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self.logger.error(f"Error with {account['username']}: {e}")
                    self._close_browser()
                    continue

            print("\n" + "=" * 50)
            print(f"✅ Processed {len(self.processed_accounts)} accounts")
            print("=" * 50)
            print("\n📡 Heartbeat monitoring via roblox_heartbeat.lua")
            print("   Check Firebase/Dashboard for live status")

        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
        finally:
            self.cleanup()

    def _update_device_status(self, status):
        """Update device status in Firebase"""
        try:
            self.firebase.update(
                f"devices/{self.hwid}",
                {
                    "status": status,
                    "hostname": self.machine_info.get("hostname"),
                    "last_heartbeat": get_timestamp(),
                    "active_accounts": len(self.accounts),
                },
            )
        except:
            pass

    def _log_event(self, event_type, username, message):
        """Log event to Firebase activity log"""
        try:
            self.firebase.push(
                "logs",
                {
                    "type": event_type,
                    "username": username.lower() if username else None,
                    "message": message,
                    "hwid": self.hwid,
                    "hostname": self.machine_info.get("hostname"),
                    "timestamp": get_timestamp(),
                },
            )
        except Exception as e:
            self.logger.debug(f"Log event failed: {e}")

    def run_persistent(self):
        """
        Run the bot and keep sending device heartbeat indefinitely.
        The project will not die after accounts are processed.
        """
        print("\n" + "=" * 50)
        print("🚀 Roblox Auto Login Bot v6 (Persistent Mode)")
        print("=" * 50)

        self.logger.info(f"🔑 HWID: {self.hwid[:16]}...")
        self.logger.info(f"💻 Host: {self.machine_info.get('hostname')}")

        # Mark device online
        self._update_device_status("online")
        self._log_event(
            "device_online", None, f"Device {self.machine_info.get('hostname')} started"
        )

        try:
            # Process accounts if any
            if self.accounts:
                self.logger.info(f"📊 Processing {len(self.accounts)} accounts")

                for i, account in enumerate(self.accounts, 1):
                    try:
                        self.setup_driver()
                        self.process_account(account, i, len(self.accounts))
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        self.logger.error(f"Error with {account['username']}: {e}")
                        self._close_browser()
                        continue

                print(f"\n✅ Processed {len(self.processed_accounts)} accounts")

            print("\n" + "=" * 50)
            print("📡 Device heartbeat running... (Ctrl+C to stop)")
            print("=" * 50)

            # Persistent device heartbeat loop
            heartbeat_interval = 30  # seconds
            while True:
                self._update_device_status("online")
                time.sleep(heartbeat_interval)

        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
            self._log_event(
                "device_offline",
                None,
                f"Device {self.machine_info.get('hostname')} stopped by user",
            )
        finally:
            self.cleanup()

    def cleanup(self):
        """Cleanup on exit"""
        self.logger.info("🧹 Cleaning up...")
        self._close_browser()
        self._update_device_status("offline")
    
    def run_single_account(self, username: str, password: str = None):
        """
        Run autorun for a single account.
        Used by AutorunController for individual account processing.
        
        Args:
            username: Account username
            password: Account password (if not provided, will look up from accounts.json)
        """
        self.logger.info(f"🎯 Single account run: {username}")
        
        # Find password if not provided
        if not password:
            all_accounts = safe_json_load(self.accounts_file, [])
            for acc in all_accounts:
                if acc.get("username", "").lower() == username.lower():
                    password = acc.get("password")
                    break
        
        if not password:
            self.logger.error(f"❌ Password not found for {username}")
            return False
        
        account = {"username": username, "password": password}
        
        try:
            self.setup_driver()
            self.process_account(account, 1, 1)
            return True
        except Exception as e:
            self.logger.error(f"❌ Error processing {username}: {e}")
            return False
        finally:
            self._close_browser()


def run_autorun_mode():
    """
    Run in autorun mode - continuously monitor Firebase and auto-run offline accounts.
    """
    from services.autorun_controller import AutorunController
    from services.account_sync import AccountSyncManager
    
    print("\n" + "=" * 60)
    print("🤖 Roblox Auto Login Bot v6 - AUTORUN MODE")
    print("=" * 60)
    print("This mode continuously monitors Firebase for offline accounts")
    print("and automatically runs them when detected.")
    print("=" * 60 + "\n")
    
    # Create bot instance
    bot = RobloxAutoLoginV6()
    
    # Create controller
    controller = AutorunController()
    
    # Set callback to run account
    def run_account_callback(username: str, data: dict):
        """Callback to run single account"""
        bot.run_single_account(username)
    
    controller.set_run_callback(run_account_callback)
    
    # Mark device online
    bot._update_device_status("online")
    bot._log_event("device_online", None, f"Device {bot.machine_info.get('hostname')} started (autorun mode)")
    
    try:
        controller.run_idle(check_interval=30)
    finally:
        bot.cleanup()


def run_sync_mode():
    """
    Run in sync mode - sync Firebase status to local accounts.json once and exit.
    """
    from services.account_sync import AccountSyncManager
    
    print("\n" + "=" * 60)
    print("🔄 Roblox Auto Login Bot v6 - SYNC MODE")
    print("=" * 60)
    
    manager = AccountSyncManager()
    
    # Do sync
    active, inactive = manager.sync_status_to_local()
    
    print(f"\n✅ Sync complete:")
    print(f"   - {active} accounts set to active (offline in Firebase)")
    print(f"   - {inactive} accounts set to inactive (online in Firebase)")
    
    # Show accounts needing autorun
    needs_run = manager.get_accounts_needing_autorun()
    if needs_run:
        print(f"\n📋 Accounts needing autorun ({len(needs_run)}):")
        for acc in needs_run:
            print(f"   - {acc.get('username')}")
    else:
        print("\n✅ All accounts are online!")
    
    print("\n" + "=" * 60)


def run_watch_mode():
    """
    Run in watch mode - continuously watch Firebase and update accounts.json.
    Does NOT auto-run accounts, just syncs status.
    """
    from services.account_sync import AccountSyncManager
    
    print("\n" + "=" * 60)
    print("👁️ Roblox Auto Login Bot v6 - WATCH MODE")
    print("=" * 60)
    print("This mode watches Firebase and syncs status to accounts.json")
    print("but does NOT auto-run accounts.")
    print("Press Ctrl+C to stop.")
    print("=" * 60 + "\n")
    
    manager = AccountSyncManager()
    manager.start_auto_sync(interval=30)
    
    try:
        while True:
            stats = manager.get_sync_stats()
            print(f"📊 Status: {stats['online_accounts']} online, {stats['offline_accounts']} offline, syncs: {stats['sync_count']}")
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    finally:
        manager.stop_auto_sync()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Roblox Auto Login Bot v6")
    parser.add_argument("--accounts", "-a", default=ACCOUNTS_FILE)
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER_LINK)
    parser.add_argument(
        "--no-persistent",
        "-np",
        action="store_true",
        help="Exit after processing accounts (default is persistent mode)",
    )
    parser.add_argument(
        "--autorun",
        action="store_true",
        help="Run in autorun mode - continuously monitor and auto-run offline accounts",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync Firebase status to accounts.json once and exit",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch mode - continuously sync status but don't auto-run",
    )

    args = parser.parse_args()

    # Handle different modes
    if args.autorun:
        run_autorun_mode()
    elif args.sync:
        run_sync_mode()
    elif args.watch:
        run_watch_mode()
    else:
        # Default behavior
        bot = RobloxAutoLoginV6(accounts_file=args.accounts, server_link=args.server)

        # Run persistent by default, use --no-persistent to exit after accounts
        if args.no_persistent:
            bot.run()
        else:
            bot.run_persistent()


if __name__ == "__main__":
    main()
