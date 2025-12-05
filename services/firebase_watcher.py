"""
Firebase Watcher Service
========================
Continuously monitors Firebase for account status changes.
Detects online/offline state based on heartbeat timeout.
"""

import time
import threading
from datetime import datetime
from typing import Dict, Callable, Optional, List
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firebase.firebase_client import get_firebase_client
from utils.logger import get_logger


class FirebaseWatcher:
    """
    Watches Firebase for account status changes.
    Triggers callbacks when accounts go online/offline.
    """
    
    # Heartbeat timeout in seconds (2 minutes)
    HEARTBEAT_TIMEOUT = 120
    
    # Poll interval in seconds
    POLL_INTERVAL = 10
    
    def __init__(self):
        self.firebase = get_firebase_client()
        self.logger = get_logger()
        
        # State tracking
        self._previous_states: Dict[str, bool] = {}  # username -> is_online
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Callbacks
        self._on_offline_callbacks: List[Callable] = []
        self._on_online_callbacks: List[Callable] = []
        self._on_status_change_callbacks: List[Callable] = []
        
        # Lock for thread safety
        self._lock = threading.Lock()
        
    def on_offline(self, callback: Callable[[str, dict], None]):
        """
        Register callback for when account goes offline.
        Callback receives (username, account_data)
        """
        self._on_offline_callbacks.append(callback)
        return self
        
    def on_online(self, callback: Callable[[str, dict], None]):
        """
        Register callback for when account comes online.
        Callback receives (username, account_data)
        """
        self._on_online_callbacks.append(callback)
        return self
        
    def on_status_change(self, callback: Callable[[str, bool, dict], None]):
        """
        Register callback for any status change.
        Callback receives (username, is_online, account_data)
        """
        self._on_status_change_callbacks.append(callback)
        return self
    
    def _normalize_username(self, username: str) -> str:
        """Normalize username to lowercase for consistent matching"""
        return username.lower().strip() if username else ""
    
    def _get_current_timestamp(self) -> int:
        """Get current Unix timestamp"""
        return int(datetime.now().timestamp())
    
    def _is_account_online(self, account_data: dict) -> bool:
        """
        Determine if account is online based on roblox.inGame and roblox.timestamp.
        
        Firebase structure:
        {
            "roblox": {
                "inGame": true,
                "status": "online",
                "timestamp": 1764913317
            }
        }
        
        Online conditions:
        - roblox.inGame == True AND
        - roblox.status == "online" AND
        - roblox.timestamp within HEARTBEAT_TIMEOUT seconds
        """
        if not account_data:
            return False
        
        # Get roblox data (the status info is nested in 'roblox' object)
        roblox_data = account_data.get("roblox", {})
        
        if not roblox_data:
            return False
        
        # Check inGame status
        is_in_game = roblox_data.get("inGame", False)
        status = roblox_data.get("status", "").lower()
        
        # Must be inGame=True OR status=online
        if not is_in_game and status != "online":
            return False
            
        # Check heartbeat timeout using roblox.timestamp
        last_heartbeat = roblox_data.get("timestamp", 0)
        if not last_heartbeat:
            return False
            
        now = self._get_current_timestamp()
        seconds_since_heartbeat = now - last_heartbeat
        
        return seconds_since_heartbeat <= self.HEARTBEAT_TIMEOUT
    
    def _check_and_notify(self):
        """Check Firebase and notify on status changes"""
        try:
            # Get all accounts from Firebase
            firebase_accounts = self.firebase.get_all_accounts()
            
            if not firebase_accounts:
                return
                
            current_states: Dict[str, bool] = {}
            
            for username, data in firebase_accounts.items():
                normalized = self._normalize_username(username)
                is_online = self._is_account_online(data)
                current_states[normalized] = is_online
                
                # Check for state change
                with self._lock:
                    previous_online = self._previous_states.get(normalized)
                    
                    if previous_online is not None and previous_online != is_online:
                        # State changed
                        self._notify_status_change(normalized, is_online, data)
                        
                        if is_online:
                            self._notify_online(normalized, data)
                        else:
                            self._notify_offline(normalized, data)
                    
                    elif previous_online is None:
                        # First time seeing this account
                        self._previous_states[normalized] = is_online
            
            # Update all states
            with self._lock:
                self._previous_states = current_states
                
        except Exception as e:
            self.logger.error(f"Firebase watcher error: {e}")
    
    def _notify_offline(self, username: str, data: dict):
        """Trigger offline callbacks"""
        self.logger.info(f"🔴 Account offline: {username}")
        for callback in self._on_offline_callbacks:
            try:
                callback(username, data)
            except Exception as e:
                self.logger.error(f"Offline callback error: {e}")
    
    def _notify_online(self, username: str, data: dict):
        """Trigger online callbacks"""
        self.logger.info(f"🟢 Account online: {username}")
        for callback in self._on_online_callbacks:
            try:
                callback(username, data)
            except Exception as e:
                self.logger.error(f"Online callback error: {e}")
    
    def _notify_status_change(self, username: str, is_online: bool, data: dict):
        """Trigger status change callbacks"""
        for callback in self._on_status_change_callbacks:
            try:
                callback(username, is_online, data)
            except Exception as e:
                self.logger.error(f"Status change callback error: {e}")
    
    def _watch_loop(self):
        """Main watch loop"""
        self.logger.info(f"👁️ Firebase watcher started (poll: {self.POLL_INTERVAL}s, timeout: {self.HEARTBEAT_TIMEOUT}s)")
        
        while self._running:
            self._check_and_notify()
            time.sleep(self.POLL_INTERVAL)
        
        self.logger.info("👁️ Firebase watcher stopped")
    
    def get_all_offline_accounts(self) -> List[str]:
        """
        Get list of all currently offline accounts.
        Returns list of normalized usernames.
        """
        offline = []
        
        try:
            firebase_accounts = self.firebase.get_all_accounts()
            
            if not firebase_accounts:
                return []
                
            for username, data in firebase_accounts.items():
                normalized = self._normalize_username(username)
                if not self._is_account_online(data):
                    offline.append(normalized)
                    
        except Exception as e:
            self.logger.error(f"Error getting offline accounts: {e}")
            
        return offline
    
    def get_all_online_accounts(self) -> List[str]:
        """
        Get list of all currently online accounts.
        Returns list of normalized usernames.
        """
        online = []
        
        try:
            firebase_accounts = self.firebase.get_all_accounts()
            
            if not firebase_accounts:
                return []
                
            for username, data in firebase_accounts.items():
                normalized = self._normalize_username(username)
                if self._is_account_online(data):
                    online.append(normalized)
                    
        except Exception as e:
            self.logger.error(f"Error getting online accounts: {e}")
            
        return online
    
    def get_account_status(self, username: str) -> Optional[bool]:
        """
        Get online status for specific account.
        Returns True if online, False if offline, None if not found.
        """
        normalized = self._normalize_username(username)
        
        try:
            data = self.firebase.get(f"accounts/{normalized}")
            if data:
                return self._is_account_online(data)
        except:
            pass
            
        return None
    
    def start(self, blocking=False):
        """
        Start watching Firebase.
        
        Args:
            blocking: If True, blocks current thread. Otherwise runs in background.
        """
        self._running = True
        
        # Do initial check
        self._check_and_notify()
        
        if blocking:
            self._watch_loop()
        else:
            self._thread = threading.Thread(target=self._watch_loop, daemon=True)
            self._thread.start()
            
        return self
    
    def stop(self):
        """Stop watching Firebase"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        return self


# Singleton instance
_watcher_instance = None


def get_firebase_watcher() -> FirebaseWatcher:
    """Get global Firebase watcher instance"""
    global _watcher_instance
    if _watcher_instance is None:
        _watcher_instance = FirebaseWatcher()
    return _watcher_instance


if __name__ == "__main__":
    # Test the watcher
    print("Testing Firebase Watcher...")
    
    watcher = FirebaseWatcher()
    
    # Get current state
    online = watcher.get_all_online_accounts()
    offline = watcher.get_all_offline_accounts()
    
    print(f"\nOnline accounts ({len(online)}): {online}")
    print(f"Offline accounts ({len(offline)}): {offline}")
    
    # Test callback registration
    def on_offline(username, data):
        print(f"[CALLBACK] {username} went offline")
    
    def on_online(username, data):
        print(f"[CALLBACK] {username} came online")
    
    watcher.on_offline(on_offline).on_online(on_online)
    
    print("\nStarting watcher (Ctrl+C to stop)...")
    try:
        watcher.start(blocking=True)
    except KeyboardInterrupt:
        print("\nStopped")
        watcher.stop()
