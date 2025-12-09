"""
Roblox Auto Login Bot v6.8
==========================
Features:
- Firebase sync + continuous monitoring
- RAM optimization for multi-instance (24/7)
- Captcha bypass: first captcha → Ctrl+Shift+R → retry
- Window minimize after launch
- Timeout/2FA/Captcha Discord webhooks
- Lowercase username normalization
"""

import time
import sys
import os
import atexit
import ctypes
from datetime import datetime

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys

# Local imports
from config import ACCOUNTS_FILE, DEFAULT_SERVER_LINK, MAX_LOGIN_ATTEMPTS
from utils.hwid import get_hwid, get_machine_info
from utils.helpers import safe_json_load, safe_json_save, get_timestamp
from utils.logger import get_logger
from firebase.firebase_client import get_firebase_client
from verification.verification_handler import VerificationHandler
from verification.browser_alert_handler import BrowserAlertHandler


# ============================================
# WINDOW MANAGEMENT (Windows API)
# ============================================
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

if sys.platform == 'win32':
    user32 = ctypes.windll.user32
    SW_MINIMIZE = 6
    SW_HIDE = 0
    
    def minimize_roblox_windows():
        """Minimize all Roblox windows"""
        if not PSUTIL_AVAILABLE:
            return 0
        
        minimized = 0
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if 'roblox' in proc.info['name'].lower():
                    # Find and minimize window
                    def enum_callback(hwnd, lparam):
                        nonlocal minimized
                        try:
                            pid = ctypes.c_ulong()
                            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                            if pid.value == proc.info['pid']:
                                if user32.IsWindowVisible(hwnd):
                                    user32.ShowWindow(hwnd, SW_MINIMIZE)
                                    minimized += 1
                        except:
                            pass
                        return True
                    
                    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
            except:
                continue
        return minimized
else:
    def minimize_roblox_windows():
        return 0


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

        # Suppress console logs
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_argument("--disable-logging")

        # Auto-allow protocol handlers (critical for Bloxstrap)
        prefs = {
            "protocol_handler.allowed_origin_protocol_pairs": {
                "https://www.roblox.com": {"roblox-player": True},
                "https://roblox.com": {"roblox-player": True},
            },
            "protocol_handler.excluded_schemes": {"roblox-player": False},
            "safebrowsing.enabled": False,
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
        """
        Login to Roblox with captcha bypass logic:
        1. Submit login
        2. If captcha detected → Ctrl+Shift+R
        3. If captcha gone → success, continue
        4. If captcha still there → notify webhook for manual assist
        """
        self.logger.info(f"🔐 Logging in: {username}")
        self._update_status(username, "logging_in")

        for attempt in range(1, self.max_login_attempts + 1):
            try:
                self.driver.get("https://www.roblox.com/login")
                time.sleep(2)

                # Fill credentials (fast mode)
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
                time.sleep(3)

                # === CAPTCHA BYPASS LOGIC ===
                first_challenge = self._detect_challenge_type()
                
                if first_challenge:
                    self.logger.info(f"⚠️ First {first_challenge} detected - trying bypass (Ctrl+Shift+R)")
                    self._hard_refresh()
                    time.sleep(3)
                    
                    # Re-submit login after refresh
                    try:
                        user_field = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((By.ID, "login-username"))
                        )
                        user_field.clear()
                        user_field.send_keys(username)
                        
                        pass_field = self.driver.find_element(By.ID, "login-password")
                        pass_field.clear()
                        pass_field.send_keys(password)
                        
                        self.driver.find_element(By.ID, "login-button").click()
                        time.sleep(3)
                    except:
                        pass
                    
                    # Check if captcha still appears after bypass attempt
                    second_challenge = self._detect_challenge_type()
                    
                    if second_challenge:
                        # Bypass FAILED - need manual assistance
                        self.logger.warning(f"❌ Bypass failed - {second_challenge} still present")
                        self._update_status(username, second_challenge.lower().replace(" ", "_"))
                        
                        # Send webhook notification
                        self._notify_captcha_bypass_failed(username, second_challenge, attempt)
                        
                        # Wait for manual solve
                        solved = self._wait_for_challenge_solved(username, second_challenge)
                        if solved:
                            self.logger.info(f"✅ {second_challenge} solved manually for {username}")
                            time.sleep(2)
                            if self._check_login_success():
                                self._notify_challenge_solved(username, second_challenge)
                                return True
                        else:
                            self.logger.warning(f"⏱️ {second_challenge} timeout for {username}")
                            continue
                    else:
                        # Bypass SUCCESS - no captcha after refresh
                        self.logger.info(f"✅ Captcha bypassed successfully!")

                # Check login success
                if self._check_login_success():
                    self.logger.info(f"✅ Login success: {username}")
                    return True

                # Check for 2FA/Verification (not captcha)
                verification = self._detect_verification_only()
                if verification:
                    self.logger.info(f"🔑 {verification} required for {username}")
                    self._update_status(username, "verification")
                    self._notify_manual_required(username, verification, attempt)
                    
                    solved = self._wait_for_challenge_solved(username, verification)
                    if solved and self._check_login_success():
                        self._notify_challenge_solved(username, verification)
                        return True
                    continue

                # Check for error
                error = self._get_login_error()
                if error:
                    self.logger.warning(f"   Error: {error}")

            except Exception as e:
                self.logger.error(f"   Attempt {attempt} failed: {e}")

            time.sleep(2)

        self._update_status(username, "login_failed")
        self._notify_login_failed(username)
        return False
    
    def _detect_verification_only(self):
        """Detect only 2FA/email verification (not captcha)"""
        verification_selectors = [
            "#two-step-verification-container",
            ".two-step-verification",
            "[data-testid='two-step-verification']",
            "input[name='code']",
            ".verification-code-input",
            ".email-verification",
        ]
        
        for selector in verification_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and any(e.is_displayed() for e in elements):
                    return "2FA Verification"
            except:
                continue
        
        try:
            page_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
            if any(kw in page_text for kw in ["verification code", "verify your email", "two-step", "enter code"]):
                return "2FA Verification"
        except:
            pass
        
        return None
    
    def _notify_captcha_bypass_failed(self, username, challenge_type, attempt):
        """Send Discord webhook when captcha bypass fails and needs manual assist"""
        try:
            hostname = self.machine_info.get("hostname", "Unknown")
            
            embed = {
                "title": "🤖 Captcha Bypass FAILED - Manual Required",
                "description": f"**{username}** needs manual captcha solving",
                "color": 0xFF0000,  # Red
                "fields": [
                    {"name": "Challenge Type", "value": challenge_type, "inline": True},
                    {"name": "Device", "value": hostname, "inline": True},
                    {"name": "Attempt", "value": str(attempt), "inline": True},
                    {"name": "Status", "value": "⏳ Waiting for manual solve (5 min timeout)", "inline": False},
                ],
                "timestamp": datetime.utcnow().isoformat(),
                "footer": {"text": "Roblox Auto Login Bot v6.8"}
            }
            
            if hasattr(self, 'notifier') and self.notifier:
                result = self.notifier.send_discord(embed=embed)
                if result:
                    self.logger.info(f"📤 Webhook sent: Captcha bypass failed for {username}")
                else:
                    self.logger.warning("Webhook send returned False - check Discord config")
            else:
                self.logger.warning("Notifier not available for webhook")
                
        except Exception as e:
            self.logger.error(f"Failed to send captcha bypass webhook: {e}")

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
        self._update_status(username.lower(), "joining")

        try:
            self.driver.get(self.server_link)
            time.sleep(2)
            
            # Bypass "Verifying browser" POW check
            self._bypass_verifying_browser()
            
            # Wait for page load
            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # Click play button to trigger roblox-player protocol
            if self._click_play_button():
                self.logger.info(f"✅ Play button clicked - launching Roblox")

                # Handle browser protocol dialog
                if hasattr(self, "alert_handler") and self.alert_handler:
                    self.alert_handler.reset()
                    self.alert_handler.wait_and_handle(pre_wait=2)

                self._update_status(username.lower(), "launched")
                self._log_event("launch", username.lower(), "Roblox launched successfully")
                return True
            else:
                self.logger.warning(f"⚠️ Could not click play button")
                self._notify_error(username, "Could not click play button")
                return False

        except Exception as e:
            self.logger.error(f"Join server failed: {e}")
            self._notify_error(username, f"Join server failed: {e}")
            return False
    
    def _check_verifying_browser(self):
        """Check if page shows 'Verifying browser' captcha"""
        try:
            # Method 1: Check for #text-loading element with "Verifying"
            try:
                loading_el = self.driver.find_element(By.ID, "text-loading")
                if loading_el.is_displayed():
                    text = loading_el.text.lower()
                    if "verifying" in text or "checking" in text:
                        self.logger.debug(f"Found verifying text in #text-loading: {text}")
                        return True
            except:
                pass
            
            # Method 2: Check page source
            page_source = self.driver.page_source.lower()
            if "verifying browser" in page_source or "checking your browser" in page_source:
                return True
            
            # Method 3: Check for loading/verification screens
            loading_elements = self.driver.find_elements(By.CSS_SELECTOR, ".loading, .verification-screen, .challenge-container, [class*='captcha']")
            for el in loading_elements:
                try:
                    if el.is_displayed() and ("verifying" in el.text.lower() or "checking" in el.text.lower()):
                        return True
                except:
                    pass
        except:
            pass
        return False
    
    def _hard_refresh(self):
        """Perform hard refresh (Ctrl+Shift+R) to bypass captcha"""
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(self.driver)
            actions.key_down(Keys.CONTROL).key_down(Keys.SHIFT).send_keys('r').key_up(Keys.SHIFT).key_up(Keys.CONTROL).perform()
            self.logger.info("🔄 Hard refresh performed (Ctrl+Shift+R)")
        except Exception as e:
            self.logger.debug(f"ActionChains failed: {e}, using JS reload")
            # Fallback: execute refresh via JS
            self.driver.execute_script("location.reload(true);")
    
    def _check_pow_verifying(self):
        """
        Check specifically for FunCaptcha POW 'Verifying browser...' screen.
        This appears in #FunCaptcha iframe or #challenge container.
        """
        try:
            # Method 1: Check for pow-iframe with verifying
            try:
                pow_iframe = self.driver.find_element(By.ID, "pow-iframe")
                if pow_iframe.is_displayed():
                    # Switch to iframe to check content
                    self.driver.switch_to.frame(pow_iframe)
                    try:
                        body_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                        if "verifying" in body_text:
                            return True
                    finally:
                        self.driver.switch_to.default_content()
            except:
                pass
            
            # Method 2: Check #FunCaptcha container
            try:
                funcaptcha = self.driver.find_element(By.ID, "FunCaptcha")
                if funcaptcha.is_displayed():
                    # Check page source for POW verifying text
                    page_source = self.driver.page_source.lower()
                    if '"pow.loading_info":"verifying browser"' in page_source or "verifying browser" in page_source:
                        # Only return True if it's the POW check, not actual captcha
                        # Check if there's NO visual challenge yet
                        try:
                            visual_challenge = self.driver.find_element(By.CSS_SELECTOR, "iframe[title*='Visual challenge']")
                            if visual_challenge.is_displayed():
                                return False  # It's actual captcha, not POW
                        except:
                            pass
                        return True
            except:
                pass
            
            # Method 3: Check #challenge container for POW
            try:
                challenge = self.driver.find_element(By.ID, "challenge")
                if challenge.is_displayed() and "active" in challenge.get_attribute("class"):
                    html = challenge.get_attribute("innerHTML").lower()
                    if "verifying browser" in html and "pow-iframe" in html:
                        return True
            except:
                pass
                
        except:
            pass
        return False
    
    def _bypass_verifying_browser(self):
        """
        Bypass 'Verifying browser...' POW check by hard refresh.
        Only triggers on POW verification, not actual captcha challenges.
        """
        max_attempts = 5
        for attempt in range(max_attempts):
            # Check both general verifying and specific POW verifying
            if self._check_verifying_browser() or self._check_pow_verifying():
                self.logger.info(f"🔄 Detected 'Verifying browser' POW (attempt {attempt + 1}/{max_attempts}) - hard refresh")
                self._hard_refresh()
                time.sleep(3)
            else:
                return True  # No verifying, continue
        
        # Still verifying after max attempts
        if self._check_verifying_browser() or self._check_pow_verifying():
            self.logger.warning("⚠️ Still in 'Verifying browser' after max retries")
            return False
        return True
    
    def _notify_error(self, username, error_message):
        """Send Discord notification for error"""
        try:
            hostname = self.machine_info.get("hostname", "Unknown")
            embed = {
                "title": "⚠️ Error Detected",
                "description": f"**{username}** encountered an error",
                "color": 0xFF6600,
                "fields": [
                    {"name": "Error", "value": error_message[:200], "inline": False},
                    {"name": "Device", "value": hostname, "inline": True},
                ],
                "timestamp": datetime.now().isoformat(),
            }
            if hasattr(self, "notifier"):
                self.notifier.send_discord(embed=embed)
        except:
            pass
    
    def _notify_timeout(self, username, timeout_type="heartbeat"):
        """Send Discord notification for timeout"""
        try:
            hostname = self.machine_info.get("hostname", "Unknown")
            embed = {
                "title": "⏱️ Timeout Detected",
                "description": f"**{username}** - {timeout_type} timeout",
                "color": 0xFFCC00,
                "fields": [
                    {"name": "Type", "value": timeout_type, "inline": True},
                    {"name": "Device", "value": hostname, "inline": True},
                ],
                "timestamp": datetime.now().isoformat(),
            }
            if hasattr(self, "notifier"):
                self.notifier.send_discord(embed=embed)
            
            # Log to Firebase
            self._log_event("timeout", username.lower(), f"{timeout_type} timeout detected")
        except:
            pass

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

    def wait_for_roblox_launch(self, username, wait_time=20):
        """
        Wait period after clicking play, then minimize window.
        Actual monitoring is done by roblox_heartbeat.lua
        """
        self.logger.info(f"⏳ Waiting {wait_time}s for Roblox to launch...")

        # Wait for Roblox to start
        time.sleep(wait_time)
        
        # Minimize Roblox windows after launch
        minimized = minimize_roblox_windows()
        if minimized > 0:
            self.logger.info(f"🪟 Minimized {minimized} Roblox window(s)")

        # Update status - heartbeat.lua will change to 'in_game' when active
        self._update_status(username.lower(), "waiting_heartbeat")
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
            return

        # Wait for Roblox launch (20s then minimize)
        self.wait_for_roblox_launch(username, wait_time=20)

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
        """Update account status in Firebase (normalized lowercase)"""
        try:
            self.firebase.update_account_status(
                username.lower(),
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
    bot._log_event(
        "device_online",
        None,
        f"Device {bot.machine_info.get('hostname')} started (autorun mode)",
    )

    try:
        controller.run_idle(check_interval=30)
    finally:
        bot.cleanup()


def run_default_mode(accounts_file=None, server_link=None, enable_ram_optimizer=True):
    """
    Default run mode:
    1. Initial sync from Firebase
    2. Process all offline accounts
    3. Continuous sync + monitoring
    4. RAM optimization (background)

    This is the unified mode that combines initial run + continuous monitoring.
    """
    from services.account_sync import AccountSyncManager
    from services.firebase_watcher import FirebaseWatcher
    from services.ram_optimizer import get_ram_optimizer, RamOptimizerConfig

    print("\n" + "=" * 60)
    print("🚀 Roblox Auto Login Bot v6.8 - UNIFIED MODE")
    print("=" * 60)
    print("1. Initial sync from Firebase")
    print("2. Process offline accounts")
    print("3. Continuous sync + monitoring")
    print(
        "4. RAM optimization (background)"
        if enable_ram_optimizer
        else "4. RAM optimization (disabled)"
    )
    print("5. Window auto-minimize after launch")
    print("=" * 60 + "\n")

    # Initialize components
    sync_manager = AccountSyncManager()
    watcher = FirebaseWatcher()

    # Create bot instance
    bot = RobloxAutoLoginV6(
        accounts_file=accounts_file or ACCOUNTS_FILE,
        server_link=server_link or DEFAULT_SERVER_LINK,
    )

    bot.logger.info(f"🔑 HWID: {bot.hwid[:16]}...")
    bot.logger.info(f"💻 Host: {bot.machine_info.get('hostname')}")

    # Initialize RAM optimizer with Firebase logging callback
    ram_optimizer = None
    if enable_ram_optimizer:
        try:
            ram_config = RamOptimizerConfig(
                max_instances=20,
                check_interval_seconds=300,  # Check every 5 minutes
                ram_threshold_percent=85.0,  # Start optimization at 85%
                aggressive_threshold_percent=92.0,  # Aggressive at 92%
                working_set_limit_mb=512,
                min_working_set_mb=128,
                safe_mode=True,
                process_priority="below_normal",
            )
            ram_optimizer = get_ram_optimizer(ram_config)
            
            # Log RAM optimization events to Firebase
            def on_ram_optimized(result):
                if result.get("optimized") and result.get("total_saved_mb", 0) > 0:
                    bot._log_event(
                        "ram_optimization",
                        None,
                        f"Saved {result['total_saved_mb']:.1f} MB across {result['instance_count']} instances"
                    )
            
            ram_optimizer._on_optimization_callback = on_ram_optimized
            bot.logger.info(
                f"🧠 RAM Optimizer: enabled (threshold {ram_config.ram_threshold_percent}%)"
            )
        except Exception as e:
            bot.logger.warning(f"⚠️ RAM Optimizer failed to initialize: {e}")
        except Exception as e:
            bot.logger.warning(f"⚠️ RAM Optimizer failed to initialize: {e}")

    # Mark device online
    bot._update_device_status("online")
    bot._log_event(
        "device_online", None, f"Device {bot.machine_info.get('hostname')} started"
    )

    # ========================================
    # PHASE 1: Initial Sync
    # ========================================
    print("\n" + "-" * 40)
    print("📡 PHASE 1: Initial Sync from Firebase")
    print("-" * 40)

    active_count, inactive_count = sync_manager.sync_status_to_local()
    print(f"   ✅ Synced: {active_count} need run, {inactive_count} already online")

    # Get accounts needing run
    needs_run = sync_manager.get_accounts_needing_autorun()

    # ========================================
    # PHASE 2: Process Offline Accounts
    # ========================================
    print("\n" + "-" * 40)
    print(f"🎮 PHASE 2: Processing {len(needs_run)} Offline Accounts")
    print("-" * 40)

    if needs_run:
        for i, account in enumerate(needs_run, 1):
            username = account.get("username", "")

            try:
                print(f"\n[{i}/{len(needs_run)}] Processing: {username}")

                # Mark as running to prevent double-run
                sync_manager.mark_account_running(username)

                # Run the account
                bot.run_single_account(username)

                bot.logger.info(f"✅ Finished processing {username}")

            except KeyboardInterrupt:
                print("\n⚠️ Interrupted by user")
                break
            except Exception as e:
                bot.logger.error(f"❌ Error processing {username}: {e}")
                continue

        print(f"\n✅ Finished processing {len(needs_run)} accounts")
    else:
        print("   ✅ All accounts are already online!")

    # ========================================
    # PHASE 3: Continuous Sync + Monitoring
    # ========================================
    print("\n" + "-" * 40)
    print("🔄 PHASE 3: Continuous Sync + Monitoring")
    print("-" * 40)
    print("   Sync interval: 60 seconds")
    print("   Device heartbeat: 30 seconds")
    print("   RAM check: 300 seconds")
    print("   Press Ctrl+C to stop")
    print("-" * 40 + "\n")

    # Start RAM optimizer background monitoring
    if ram_optimizer and ram_optimizer.enabled:
        ram_optimizer.start_monitoring()
        bot.logger.info("🧠 RAM optimizer monitoring started")

    # Tracking for throttling
    last_sync_time = time.time()
    sync_interval = 60  # seconds between syncs
    heartbeat_interval = 30  # seconds between device heartbeats
    last_heartbeat = time.time()

    # Track processed accounts to prevent re-run (username -> timestamp)
    recently_processed: dict = {}
    cooldown_time = 300  # 5 minutes cooldown per account

    try:
        while True:
            current_time = time.time()

            # Device heartbeat (every 30s)
            if current_time - last_heartbeat >= heartbeat_interval:
                bot._update_device_status("online")
                last_heartbeat = current_time

            # Sync check (every 60s)
            if current_time - last_sync_time >= sync_interval:
                # Get current status without modifying local file
                online = set(watcher.get_all_online_accounts())
                offline = set(watcher.get_all_offline_accounts())

                # Clear expired cooldowns
                expired = [
                    u
                    for u, t in list(recently_processed.items())
                    if current_time - t > cooldown_time
                ]
                for u in expired:
                    del recently_processed[u]

                # Find accounts that need run (offline and not recently processed)
                needs_run_now = []
                for username in offline:
                    if username not in recently_processed:
                        needs_run_now.append(username)

                bot.logger.info(
                    f"📊 Sync: {len(online)} online, {len(offline)} offline, "
                    f"{len(needs_run_now)} need run"
                )

                # Process any newly offline accounts
                if needs_run_now:
                    bot.logger.info(
                        f"🎯 Found {len(needs_run_now)} accounts to process"
                    )

                    for username in needs_run_now:
                        try:
                            # Add to recently processed with timestamp
                            recently_processed[username] = current_time

                            # Sync update
                            sync_manager.mark_account_running(username)

                            # Run the account
                            bot.run_single_account(username)

                            bot.logger.info(f"✅ Auto-processed {username}")

                        except Exception as e:
                            bot.logger.error(
                                f"❌ Error auto-processing {username}: {e}"
                            )

                last_sync_time = current_time

            # Sleep to prevent CPU spinning
            time.sleep(5)

    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        bot._log_event(
            "device_offline",
            None,
            f"Device {bot.machine_info.get('hostname')} stopped by user",
        )
    finally:
        # Stop RAM optimizer
        if ram_optimizer:
            ram_optimizer.stop_monitoring()
            stats = ram_optimizer.stats
            bot.logger.info(
                f"🧠 RAM optimizer stats: {stats['optimizations']} optimizations, "
                f"{stats['total_saved_mb']:.1f} MB saved"
            )

        bot.cleanup()
        watcher.stop()


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
            print(
                f"📊 Status: {stats['online_accounts']} online, {stats['offline_accounts']} offline, syncs: {stats['sync_count']}"
            )
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    finally:
        manager.stop_auto_sync()


def run_ram_status():
    """Show RAM optimizer status and Roblox processes"""
    from services.ram_optimizer import get_ram_optimizer, RamOptimizerConfig

    print("\n" + "=" * 60)
    print("🧠 Roblox RAM Optimizer - Status")
    print("=" * 60)

    config = RamOptimizerConfig(
        ram_threshold_percent=85.0, aggressive_threshold_percent=92.0
    )
    optimizer = get_ram_optimizer(config)

    if not optimizer.enabled:
        print("\n⚠️ RAM Optimizer is disabled (psutil not installed)")
        print("   Install with: pip install psutil")
        return

    optimizer.print_status()

    # Show process list
    processes = optimizer.get_roblox_processes()
    if processes:
        print("\n🎮 Roblox Processes:")
        print("-" * 50)
        print(f"{'PID':<10} {'RAM (MB)':<12} {'CPU %':<10} {'Priority'}")
        print("-" * 50)
        for p in sorted(processes, key=lambda x: x.ram_mb, reverse=True):
            print(f"{p.pid:<10} {p.ram_mb:<12.1f} {p.cpu_percent:<10.1f} {p.priority}")
        print("-" * 50)
        print(
            f"Total: {sum(p.ram_mb for p in processes):.1f} MB across {len(processes)} instances"
        )
    else:
        print("\n📭 No Roblox processes running")

    print("\n" + "=" * 60)


def run_ram_optimize():
    """Force RAM optimization now"""
    from services.ram_optimizer import get_ram_optimizer, RamOptimizerConfig

    print("\n" + "=" * 60)
    print("🧠 Roblox RAM Optimizer - Force Optimization")
    print("=" * 60)

    config = RamOptimizerConfig(
        ram_threshold_percent=0,  # Force optimization regardless of usage
        safe_mode=True,
    )
    optimizer = get_ram_optimizer(config)

    if not optimizer.enabled:
        print("\n⚠️ RAM Optimizer is disabled (psutil not installed)")
        return

    print("\n🔧 Running optimization...")
    result = optimizer.optimize_all(force=True)

    if result.get("optimized"):
        print(f"\n✅ Optimization complete!")
        print(f"   Instances: {result.get('instance_count', 0)}")
        print(f"   Total Roblox RAM: {result.get('total_roblox_mb', 0):.1f} MB")
        print(f"   RAM saved: {result.get('total_saved_mb', 0):.1f} MB")

        if result.get("results"):
            print("\n   Per-process results:")
            for r in result["results"]:
                status = "✅" if r.get("success") else "❌"
                print(
                    f"   {status} PID {r.get('pid')}: {r.get('before_mb', 0):.1f} → {r.get('after_mb', 0):.1f} MB"
                )
    else:
        print(f"\n📊 {result.get('message', 'No optimization needed')}")

    print("\n" + "=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Roblox Auto Login Bot v6.8")
    parser.add_argument("--accounts", "-a", default=ACCOUNTS_FILE)
    parser.add_argument("--server", "-s", default=DEFAULT_SERVER_LINK)
    parser.add_argument(
        "--no-persistent",
        "-np",
        action="store_true",
        help="Exit after processing accounts (no continuous monitoring)",
    )
    parser.add_argument(
        "--autorun",
        action="store_true",
        help="Legacy autorun mode - use queue-based processing",
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
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy persistent mode (old behavior)",
    )
    parser.add_argument(
        "--ram-status",
        action="store_true",
        help="Show RAM optimizer status and Roblox processes",
    )
    parser.add_argument(
        "--ram-optimize",
        action="store_true",
        help="Force RAM optimization now",
    )
    parser.add_argument(
        "--no-ram-optimizer",
        action="store_true",
        help="Disable RAM optimizer in unified mode",
    )

    args = parser.parse_args()

    # Handle different modes
    if args.ram_status:
        run_ram_status()
    elif args.ram_optimize:
        run_ram_optimize()
    elif args.autorun:
        run_autorun_mode()
    elif args.sync:
        run_sync_mode()
    elif args.watch:
        run_watch_mode()
    elif args.legacy:
        # Legacy persistent mode
        bot = RobloxAutoLoginV6(accounts_file=args.accounts, server_link=args.server)
        if args.no_persistent:
            bot.run()
        else:
            bot.run_persistent()
    else:
        # NEW DEFAULT: Unified mode with sync + run + monitoring + RAM optimization
        run_default_mode(
            accounts_file=args.accounts,
            server_link=args.server,
            enable_ram_optimizer=not args.no_ram_optimizer,
        )


if __name__ == "__main__":
    main()
