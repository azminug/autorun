"""Verification Handler for captcha and verification challenges"""
import time
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import VERIFICATION_WAIT_TIMEOUT, VERIFICATION_CHECK_INTERVAL


class VerificationHandler:
    """
    Handles captcha/verification detection and waits for manual solving.
    Detects when verification is required and waits until it's completed.
    """
    
    # Selectors for various verification/captcha elements
    CAPTCHA_SELECTORS = [
        "iframe[src*='captcha']",
        "iframe[src*='arkose']",
        "iframe[src*='funcaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='recaptcha']",
        "div[id*='captcha']",
        "div[class*='captcha']",
        "#challenge-stage",
        ".challenge-container",
        "#arkose-container",
        ".funcaptcha-container",
        "[data-testid='challenge']",
        ".verification-modal",
        ".modal-challenge",
    ]
    
    # Selectors for verification success indicators
    SUCCESS_INDICATORS = [
        # Logged in indicators
        "a[href*='/users/']",  # Profile link
        ".age-bracket-label",  # Age display
        "[data-testid='user-menu']",
        ".navbar-icon-home",
        # Game page indicators  
        "button[class*='play']",
        ".game-call-to-action",
    ]
    
    # Error message selectors
    ERROR_SELECTORS = [
        "#login-error-message",
        ".alert-warning",
        ".alert-danger", 
        ".text-error",
        ".error-message",
    ]
    
    def __init__(self, driver, timeout=None, check_interval=None):
        """
        Initialize Verification Handler
        
        Args:
            driver: Selenium WebDriver instance
            timeout: Max seconds to wait for verification (default: 300)
            check_interval: Seconds between checks (default: 2)
        """
        self.driver = driver
        self.timeout = timeout or VERIFICATION_WAIT_TIMEOUT
        self.check_interval = check_interval or VERIFICATION_CHECK_INTERVAL
        
        # Callbacks
        self.on_verification_detected = None
        self.on_verification_solved = None
        self.on_verification_timeout = None
    
    def is_captcha_present(self):
        """
        Check if any captcha/verification element is visible.
        
        Returns:
            bool: True if captcha is detected
        """
        for selector in self.CAPTCHA_SELECTORS:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    if elem.is_displayed():
                        return True
            except:
                continue
        
        # Also check for error messages mentioning verification
        for selector in self.ERROR_SELECTORS:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    if elem.is_displayed():
                        text = elem.text.lower()
                        if any(word in text for word in ['captcha', 'verification', 'challenge', 'verify']):
                            return True
            except:
                continue
        
        return False
    
    def is_verification_solved(self):
        """
        Check if verification has been solved (login successful or on game page).
        
        Returns:
            bool: True if verification appears solved
        """
        try:
            current_url = self.driver.current_url.lower()
            
            # Check URL patterns for success
            success_urls = ['home', 'games/', 'discover', 'users/']
            if any(pattern in current_url for pattern in success_urls):
                return True
            
            # Check for success elements
            for selector in self.SUCCESS_INDICATORS:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        if elem.is_displayed():
                            return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def is_still_on_login(self):
        """Check if still on login page"""
        try:
            return 'login' in self.driver.current_url.lower()
        except:
            return False
    
    def wait_for_verification(self, username=None):
        """
        Wait for verification to be solved.
        Blocks until verification is complete or timeout.
        
        Args:
            username: Optional username for logging
        
        Returns:
            bool: True if verification was solved, False if timeout
        """
        if not self.is_captcha_present():
            return True  # No verification needed
        
        user_str = f" for {username}" if username else ""
        print(f"\n{'='*60}")
        print(f"⚠️  VERIFICATION REQUIRED{user_str}")
        print(f"{'='*60}")
        print(f"📋 Please complete the captcha/verification challenge")
        print(f"⏳ Waiting up to {self.timeout} seconds...")
        print(f"{'='*60}\n")
        
        if self.on_verification_detected:
            self.on_verification_detected(username)
        
        start_time = time.time()
        
        while time.time() - start_time < self.timeout:
            # Check if solved
            if self.is_verification_solved():
                elapsed = time.time() - start_time
                print(f"\n✅ Verification solved! (took {elapsed:.1f}s)")
                
                if self.on_verification_solved:
                    self.on_verification_solved(username, elapsed)
                
                return True
            
            # Check if captcha still present
            if not self.is_captcha_present() and not self.is_still_on_login():
                print(f"\n✅ Verification appears to be solved")
                
                if self.on_verification_solved:
                    self.on_verification_solved(username, time.time() - start_time)
                
                return True
            
            # Wait before next check
            time.sleep(self.check_interval)
        
        print(f"\n❌ Verification timeout ({self.timeout}s)")
        
        if self.on_verification_timeout:
            self.on_verification_timeout(username)
        
        return False
    
    def detect_and_wait(self, username=None, post_login_wait=5):
        """
        Detect if verification needed and wait for it.
        
        Args:
            username: Optional username for logging
            post_login_wait: Seconds to wait after login click before checking
        
        Returns:
            dict: {
                'needed': bool - whether verification was needed,
                'solved': bool - whether it was solved,
                'elapsed': float - time spent waiting
            }
        """
        time.sleep(post_login_wait)
        
        start_time = time.time()
        
        # First check if already successful
        if self.is_verification_solved():
            return {'needed': False, 'solved': True, 'elapsed': 0}
        
        # Check for verification
        if self.is_captcha_present():
            solved = self.wait_for_verification(username)
            return {
                'needed': True,
                'solved': solved,
                'elapsed': time.time() - start_time
            }
        
        # Neither success nor verification - might be error
        if self.is_still_on_login():
            # Check for error message
            for selector in self.ERROR_SELECTORS:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if elem.is_displayed():
                        print(f"⚠️ Login error: {elem.text}")
                        return {'needed': False, 'solved': False, 'elapsed': 0, 'error': elem.text}
                except:
                    continue
        
        return {'needed': False, 'solved': True, 'elapsed': 0}
    
    def get_captcha_type(self):
        """
        Try to identify the type of captcha present.
        
        Returns:
            str: Captcha type or 'unknown'
        """
        type_indicators = {
            'arkose': ['arkose', 'funcaptcha'],
            'hcaptcha': ['hcaptcha'],
            'recaptcha': ['recaptcha', 'google.com/recaptcha'],
            'roblox': ['roblox', 'verification']
        }
        
        try:
            page_source = self.driver.page_source.lower()
            
            for captcha_type, indicators in type_indicators.items():
                if any(ind in page_source for ind in indicators):
                    return captcha_type
        except:
            pass
        
        return 'unknown'


if __name__ == "__main__":
    print("VerificationHandler - Use with Selenium WebDriver")
    print("Example usage:")
    print("  handler = VerificationHandler(driver)")
    print("  result = handler.detect_and_wait('username')")
