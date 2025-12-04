"""
Improved Browser Alert Handler for Roblox Player launch prompts
Uses Windows API for more reliable dialog handling
"""
import time
import ctypes
from ctypes import wintypes
import sys
import os

# Conditional imports with fallbacks
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except ImportError:
    PYGETWINDOW_AVAILABLE = False

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoAlertPresentException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BROWSER_ALERT_TIMEOUT

# Windows API for window manipulation
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Virtual Key Codes
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SPACE = 0x20


class BrowserAlertHandler:
    """
    Handles browser-level alerts and prompts for Roblox Player launch.
    Uses Windows API for reliable dialog handling.
    """
    
    def __init__(self, driver, timeout=None):
        """
        Initialize Browser Alert Handler
        
        Args:
            driver: Selenium WebDriver instance
            timeout: Max seconds to wait for alerts
        """
        self.driver = driver
        self.timeout = timeout or BROWSER_ALERT_TIMEOUT
        self._handled = False  # Prevent double execution
    
    def _send_key(self, vk_code):
        """Send a key press using Windows API."""
        user32.keybd_event(vk_code, 0, 0, 0)  # Key down
        time.sleep(0.05)
        user32.keybd_event(vk_code, 0, 2, 0)  # Key up (KEYEVENTF_KEYUP = 2)
    
    def _find_dialog_window(self):
        """
        Find Chrome's external protocol dialog using Windows API.
        Returns window handle (HWND) if found.
        """
        dialog_hwnd = [None]  # Use list to allow modification in nested function
        
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(hwnd, lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                
                # Get window title
                length = user32.GetWindowTextLengthW(hwnd) + 1
                buffer = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(hwnd, buffer, length)
                title = buffer.value.lower()
                
                # Get class name
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buffer, 256)
                class_name = class_buffer.value
                
                # Chrome dialog patterns - include Bloxstrap
                dialog_patterns = [
                    'roblox-player',
                    'external protocol',
                    'open roblox',
                    'buka roblox',  # Indonesian
                    'bloxstrap',
                    'open bloxstrap',
                    'buka bloxstrap',
                ]
                
                if any(p in title for p in dialog_patterns):
                    dialog_hwnd[0] = hwnd
                    return False  # Stop enumeration
                
                # Chrome widget window with protocol text
                if 'Chrome_WidgetWin' in class_name:
                    if any(p in title for p in dialog_patterns):
                        dialog_hwnd[0] = hwnd
                        return False
            except:
                pass
            return True
        
        user32.EnumWindows(enum_callback, 0)
        return dialog_hwnd[0]
    
    def handle_via_windows_api(self):
        """
        Handle protocol dialog using Windows API directly.
        More reliable than pyautogui for system dialogs.
        """
        try:
            hwnd = self._find_dialog_window()
            if not hwnd:
                return False
            
            # Bring window to foreground
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.3)
            
            # Tab to checkbox, Space to check, Tab to button, Enter to click
            self._send_key(VK_TAB)
            time.sleep(0.1)
            self._send_key(VK_SPACE)  # Check "Always allow"
            time.sleep(0.1)
            self._send_key(VK_TAB)
            time.sleep(0.1)
            self._send_key(VK_RETURN)  # Click "Open"
            
            print("✅ Protocol dialog handled via Windows API")
            return True
        except Exception as e:
            print(f"⚠️ Windows API handling failed: {e}")
            return False
    
    def handle_selenium_alert(self):
        """Handle standard Selenium alert if present."""
        try:
            alert = WebDriverWait(self.driver, 2).until(EC.alert_is_present())
            alert_text = alert.text
            print(f"📋 Alert detected: {alert_text}")
            alert.accept()
            print("✅ Alert accepted")
            return True
        except (TimeoutException, NoAlertPresentException):
            return False
    
    def handle_roblox_protocol_dialog(self):
        """
        Handle the "Open roblox-player?" protocol dialog using multiple methods.
        Returns True if dialog was handled.
        """
        # Try Windows API first (most reliable)
        if self.handle_via_windows_api():
            return True
        
        # Fallback to pyautogui
        if PYAUTOGUI_AVAILABLE:
            try:
                time.sleep(0.5)
                # Tab through dialog elements and press Enter
                pyautogui.press('tab')
                time.sleep(0.1)
                pyautogui.press('space')  # Toggle checkbox
                time.sleep(0.1)
                pyautogui.press('tab')
                time.sleep(0.1)
                pyautogui.press('enter')
                print("⌨️ Protocol dialog handled via pyautogui")
                return True
            except Exception as e:
                print(f"⚠️ pyautogui failed: {e}")
        
        return False
    
    def find_and_click_chrome_dialog(self):
        """
        Find and click Chrome's dialog using pygetwindow.
        Returns True if successful.
        """
        if not PYGETWINDOW_AVAILABLE:
            return False
        
        try:
            dialog_titles = [
                "External protocol request",
                "Open roblox-player",
                "roblox-player",
            ]
            
            for title in dialog_titles:
                try:
                    windows = gw.getWindowsWithTitle(title)
                    if windows:
                        win = windows[0]
                        win.activate()
                        time.sleep(0.3)
                        
                        if PYAUTOGUI_AVAILABLE:
                            # Use keyboard navigation
                            pyautogui.press('tab')
                            time.sleep(0.1)
                            pyautogui.press('space')
                            time.sleep(0.1)
                            pyautogui.press('tab')
                            time.sleep(0.1)
                            pyautogui.press('enter')
                            print("✅ Clicked dialog via pygetwindow")
                            return True
                except:
                    continue
            
            return False
        except Exception as e:
            print(f"⚠️ Error finding Chrome dialog: {e}")
            return False
    
    def handle_in_page_dialog(self):
        """
        Handle in-page dialog for Roblox Player launch.
        Some browsers show this as an in-page modal.
        
        Returns:
            bool: True if handled
        """
        try:
            # Look for in-page dialog elements
            selectors = [
                # Chrome's in-page dialog
                "button[data-action='accept']",
                "button.accept",
                "button.allow",
                "button.open-link",
                # Generic dialog buttons
                ".modal button.btn-primary",
                ".dialog button.confirm",
                "[role='dialog'] button[type='submit']",
            ]
            
            for selector in selectors:
                try:
                    buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for button in buttons:
                        if button.is_displayed():
                            button.click()
                            print(f"✅ Clicked in-page dialog button: {selector}")
                            return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def handle_all_alerts(self, max_attempts=5):
        """
        Attempt to handle all types of alerts/dialogs.
        Uses priority order: Windows API > Selenium > In-page > pyautogui
        
        Returns:
            bool: True if any alert was handled
        """
        if self._handled:
            return True
        
        for attempt in range(max_attempts):
            time.sleep(0.3)
            
            # Priority 1: Windows API (most reliable for Chrome dialogs)
            if self.handle_via_windows_api():
                self._handled = True
                return True
            
            # Priority 2: Selenium alert
            if self.handle_selenium_alert():
                self._handled = True
                return True
            
            # Priority 3: In-page dialog
            if self.handle_in_page_dialog():
                self._handled = True
                return True
            
            # Priority 4: pygetwindow
            if self.find_and_click_chrome_dialog():
                self._handled = True
                return True
            
            # Priority 5: Blind keyboard (last resort on final attempts)
            if attempt >= 3 and PYAUTOGUI_AVAILABLE:
                try:
                    pyautogui.press('enter')
                    time.sleep(0.2)
                except:
                    pass
        
        return False
    
    def wait_and_handle(self, pre_wait=1):
        """
        Wait for and handle any Roblox protocol dialogs.
        
        Args:
            pre_wait: Seconds to wait before checking
        
        Returns:
            bool: True if successful or no dialog needed
        """
        if self._handled:
            print("⚠️ Alert already handled, skipping")
            return True
        
        print("🔔 Checking for protocol dialogs...")
        time.sleep(pre_wait)
        
        start_time = time.time()
        dialog_found = False
        
        while time.time() - start_time < self.timeout:
            if self.handle_all_alerts():
                print("✅ Protocol dialog handled")
                return True
            
            # Check if dialog exists but wasn't handled
            if self._find_dialog_window():
                dialog_found = True
            
            time.sleep(0.3)
        
        # Final attempt with Windows API
        if self.handle_via_windows_api():
            print("✅ Protocol dialog handled (final attempt)")
            return True
        
        if dialog_found:
            print("⚠️ Protocol dialog detected but could not be handled")
            return False
        else:
            # No dialog = Chrome auto-allowed the protocol (good!)
            print("✅ No dialog needed - protocol auto-allowed by Chrome")
            return True
    
    def reset(self):
        """Reset handler state for next account."""
        self._handled = False


class AutoClickHandler:
    """Alternative handler for edge cases."""
    
    @staticmethod
    def send_key_via_api(vk_code):
        """Send key using Windows API."""
        user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(vk_code, 0, 2, 0)
    
    @staticmethod
    def click_at_screen_center_offset(x_offset=0, y_offset=100):
        """Click relative to screen center."""
        if not PYAUTOGUI_AVAILABLE:
            return False
        try:
            screen_width, screen_height = pyautogui.size()
            x = screen_width // 2 + x_offset
            y = screen_height // 2 + y_offset
            pyautogui.click(x, y)
            return True
        except:
            return False
    
    @staticmethod
    def press_tab_and_enter():
        """Press Tab then Enter using Windows API."""
        try:
            AutoClickHandler.send_key_via_api(VK_TAB)
            time.sleep(0.1)
            AutoClickHandler.send_key_via_api(VK_RETURN)
            return True
        except:
            return False


if __name__ == "__main__":
    print("BrowserAlertHandler - Improved with Windows API support")
    print("\nFeatures:")
    print("  - Windows API for reliable key sending")
    print("  - Multiple fallback strategies")
    print("  - Handles Chrome protocol dialogs")
