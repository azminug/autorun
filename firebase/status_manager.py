"""Status Manager for coordinating Firebase updates"""
import threading
import time
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firebase.firebase_client import FirebaseClient, get_firebase_client
from utils.hwid import get_hwid, get_machine_info
from utils.helpers import safe_json_save, safe_json_load, get_timestamp


class StatusManager:
    """
    Manages status updates to Firebase and local storage.
    Handles device heartbeats, account status, and PID tracking.
    """
    
    def __init__(self, firebase_client=None, local_status_file="status.json"):
        self.firebase = firebase_client or get_firebase_client()
        self.local_status_file = local_status_file
        self.hwid = get_hwid()
        self.machine_info = get_machine_info()
        
        # Heartbeat management
        self._heartbeat_thread = None
        self._stop_heartbeat = threading.Event()
        self._heartbeat_interval = 30  # seconds
        
        # Account tracking
        self.active_accounts = {}  # username -> {pid, status, start_time}
        
        # Initialize local status
        self._init_local_status()
    
    def _init_local_status(self):
        """Initialize local status file"""
        status = safe_json_load(self.local_status_file, {
            "hwid": self.hwid,
            "machine_info": self.machine_info,
            "accounts": {},
            "last_update": get_timestamp()
        })
        status["hwid"] = self.hwid
        status["machine_info"] = self.machine_info
        safe_json_save(self.local_status_file, status)
    
    def start(self):
        """Start the status manager and device heartbeat"""
        print(f"📡 StatusManager started | HWID: {self.hwid[:16]}...")
        
        # Mark device online
        self.firebase.set_device_online(self.hwid, self.machine_info)
        
        # Start heartbeat thread
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()
    
    def stop(self):
        """Stop the status manager and mark device offline"""
        print("📡 StatusManager stopping...")
        
        # Stop heartbeat
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        
        # Mark all accounts as stopped
        for username in list(self.active_accounts.keys()):
            self.update_account_stopped(username)
        
        # Mark device offline
        self.firebase.set_device_offline(self.hwid)
        print("📡 StatusManager stopped")
    
    def _heartbeat_loop(self):
        """Background heartbeat loop"""
        while not self._stop_heartbeat.is_set():
            try:
                # Update device heartbeat
                self.firebase.update(f"devices/{self.hwid}", {
                    "last_heartbeat": get_timestamp(),
                    "status": "online",
                    "active_accounts": len(self.active_accounts)
                })
                
                # Update local status
                self._save_local_status()
                
            except Exception as e:
                print(f"⚠️ Heartbeat error: {e}")
            
            # Wait for interval or stop signal
            self._stop_heartbeat.wait(self._heartbeat_interval)
    
    def _save_local_status(self):
        """Save current status to local file"""
        status = {
            "hwid": self.hwid,
            "machine_info": self.machine_info,
            "accounts": self.active_accounts,
            "last_update": get_timestamp(),
            "status": "online"
        }
        safe_json_save(self.local_status_file, status)
    
    # ===========================
    # ACCOUNT STATUS METHODS
    # ===========================
    
    def update_account_login(self, username):
        """Update account status when logging in"""
        self.active_accounts[username] = {
            "status": "logging_in",
            "pid": None,
            "start_time": get_timestamp(),
            "hwid": self.hwid
        }
        
        self.firebase.update_account_status(username, {
            "status": "logging_in",
            "hwid": self.hwid,
            "hostname": self.machine_info.get("hostname", "unknown")
        })
        
        self.firebase.log_event("account_login", {
            "username": username,
            "hwid": self.hwid
        })
    
    def update_account_verification(self, username):
        """Update account status when waiting for verification"""
        if username in self.active_accounts:
            self.active_accounts[username]["status"] = "verification"
        
        self.firebase.update_account_status(username, {
            "status": "verification",
            "verification_start": get_timestamp()
        })
    
    def update_account_joining(self, username):
        """Update account status when joining server"""
        if username in self.active_accounts:
            self.active_accounts[username]["status"] = "joining"
        
        self.firebase.update_account_status(username, {
            "status": "joining_server"
        })
    
    def update_account_running(self, username, pid):
        """Update account status when Roblox is running"""
        self.active_accounts[username] = {
            "status": "running",
            "pid": pid,
            "start_time": self.active_accounts.get(username, {}).get("start_time", get_timestamp()),
            "hwid": self.hwid
        }
        
        self.firebase.update_account_status(username, {
            "status": "running",
            "pid": pid,
            "pid_alive": True,
            "hwid": self.hwid
        })
        
        self.firebase.log_event("account_running", {
            "username": username,
            "pid": pid,
            "hwid": self.hwid
        })
    
    def update_account_stopped(self, username, reason="stopped"):
        """Update account status when stopped"""
        pid = self.active_accounts.get(username, {}).get("pid")
        
        if username in self.active_accounts:
            del self.active_accounts[username]
        
        self.firebase.update_account_status(username, {
            "status": reason,
            "pid_alive": False,
            "stopped_at": get_timestamp()
        })
        
        self.firebase.log_event("account_stopped", {
            "username": username,
            "pid": pid,
            "reason": reason,
            "hwid": self.hwid
        })
    
    def update_pid_heartbeat(self, username, pid, alive=True):
        """Update PID heartbeat status"""
        if username in self.active_accounts:
            self.active_accounts[username]["pid"] = pid
            self.active_accounts[username]["pid_alive"] = alive
        
        self.firebase.update_pid_status(username, pid, alive, self.hwid)
    
    def get_status_summary(self):
        """Get current status summary"""
        return {
            "hwid": self.hwid,
            "hostname": self.machine_info.get("hostname", "unknown"),
            "status": "online",
            "active_accounts": len(self.active_accounts),
            "accounts": dict(self.active_accounts),
            "last_update": get_timestamp()
        }


# Singleton instance
_status_manager = None


def get_status_manager():
    """Get global StatusManager instance"""
    global _status_manager
    if _status_manager is None:
        _status_manager = StatusManager()
    return _status_manager


if __name__ == "__main__":
    # Test StatusManager
    manager = StatusManager()
    manager.start()
    
    print("\nStatus Summary:")
    print(manager.get_status_summary())
    
    time.sleep(5)
    manager.stop()
