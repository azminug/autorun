"""
Account Sync Manager
====================
Synchronizes account status between Firebase and local accounts.json.
Handles case-insensitive matching and active flag updates.
"""

import json
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from firebase.firebase_client import get_firebase_client
from services.firebase_watcher import FirebaseWatcher
from utils.helpers import safe_json_load, safe_json_save
from utils.logger import get_logger
from config import ACCOUNTS_FILE


class AccountSyncManager:
    """
    Manages synchronization between Firebase account status and local accounts.json.
    
    Logic:
    - If account is OFFLINE in Firebase -> set active=True in accounts.json (needs autorun)
    - If account is ONLINE in Firebase -> set active=False in accounts.json (already running)
    """
    
    def __init__(self, accounts_file: str = None):
        self.accounts_file = accounts_file or ACCOUNTS_FILE
        self.firebase = get_firebase_client()
        self.watcher = FirebaseWatcher()
        self.logger = get_logger()
        
        # Lock for file operations
        self._file_lock = threading.Lock()
        
        # Track sync state
        self._last_sync_time: Optional[datetime] = None
        self._sync_count = 0
        
    def _normalize_username(self, username: str) -> str:
        """Normalize username to lowercase for consistent matching"""
        return username.lower().strip() if username else ""
    
    def _load_local_accounts(self) -> List[dict]:
        """Load accounts from local JSON file"""
        with self._file_lock:
            return safe_json_load(self.accounts_file, [])
    
    def _save_local_accounts(self, accounts: List[dict]) -> bool:
        """Save accounts to local JSON file"""
        with self._file_lock:
            return safe_json_save(self.accounts_file, accounts)
    
    def _build_username_map(self, accounts: List[dict]) -> Dict[str, int]:
        """
        Build map of normalized username -> list index.
        Used for case-insensitive matching.
        """
        return {
            self._normalize_username(acc.get("username", "")): idx
            for idx, acc in enumerate(accounts)
        }
    
    def sync_status_to_local(self) -> Tuple[int, int]:
        """
        Sync Firebase status to local accounts.json.
        
        Returns:
            Tuple of (accounts_set_active, accounts_set_inactive)
        """
        self.logger.info("🔄 Syncing Firebase status to local accounts.json...")
        
        # Load local accounts
        local_accounts = self._load_local_accounts()
        if not local_accounts:
            self.logger.warning("No local accounts found")
            return (0, 0)
        
        # Build username map for case-insensitive matching
        username_map = self._build_username_map(local_accounts)
        
        # Get Firebase status
        online_accounts = set(self.watcher.get_all_online_accounts())
        offline_accounts = set(self.watcher.get_all_offline_accounts())
        
        self.logger.info(f"   Firebase: {len(online_accounts)} online, {len(offline_accounts)} offline")
        
        set_active = 0
        set_inactive = 0
        
        # Update local accounts based on Firebase status
        for i, account in enumerate(local_accounts):
            username = self._normalize_username(account.get("username", ""))
            current_active = account.get("active", False)
            
            if username in online_accounts:
                # Account is online -> set active=False (don't need to run)
                if current_active:
                    local_accounts[i]["active"] = False
                    set_inactive += 1
                    self.logger.debug(f"   {username}: online -> active=False")
                    
            elif username in offline_accounts:
                # Account is offline -> set active=True (needs autorun)
                if not current_active:
                    local_accounts[i]["active"] = True
                    set_active += 1
                    self.logger.debug(f"   {username}: offline -> active=True")
            
            # If account not in Firebase at all, keep current state
        
        # Save changes
        if set_active > 0 or set_inactive > 0:
            self._save_local_accounts(local_accounts)
            self.logger.info(f"✅ Synced: {set_active} set active, {set_inactive} set inactive")
        else:
            self.logger.info("✅ No changes needed")
        
        self._last_sync_time = datetime.now()
        self._sync_count += 1
        
        return (set_active, set_inactive)
    
    def get_accounts_needing_autorun(self) -> List[dict]:
        """
        Get list of accounts that need autorun.
        These are accounts that are:
        1. In local accounts.json
        2. Offline in Firebase (or not in Firebase at all)
        """
        local_accounts = self._load_local_accounts()
        if not local_accounts:
            return []
        
        online_accounts = set(self.watcher.get_all_online_accounts())
        needs_autorun = []
        
        for account in local_accounts:
            username = self._normalize_username(account.get("username", ""))
            
            # If not online in Firebase, needs autorun
            if username not in online_accounts:
                needs_autorun.append(account)
        
        return needs_autorun
    
    def get_active_accounts(self) -> List[dict]:
        """Get accounts with active=True from local file"""
        local_accounts = self._load_local_accounts()
        return [acc for acc in local_accounts if acc.get("active", False)]
    
    def set_account_active(self, username: str, active: bool) -> bool:
        """
        Set active status for specific account in local file.
        Uses case-insensitive matching.
        """
        local_accounts = self._load_local_accounts()
        username_map = self._build_username_map(local_accounts)
        normalized = self._normalize_username(username)
        
        if normalized in username_map:
            idx = username_map[normalized]
            local_accounts[idx]["active"] = active
            return self._save_local_accounts(local_accounts)
        
        return False
    
    def mark_account_running(self, username: str) -> bool:
        """
        Mark account as currently being processed (active=False to prevent double-run).
        Call this when starting autorun for an account.
        """
        return self.set_account_active(username, False)
    
    def mark_account_needs_run(self, username: str) -> bool:
        """
        Mark account as needing run (active=True).
        Call this when account goes offline.
        """
        return self.set_account_active(username, True)
    
    def on_account_offline(self, username: str, data: dict):
        """
        Callback when account goes offline.
        Sets active=True so autorun will pick it up.
        """
        self.logger.info(f"📥 Account offline detected: {username}")
        self.mark_account_needs_run(username)
    
    def on_account_online(self, username: str, data: dict):
        """
        Callback when account comes online.
        Sets active=False so autorun won't process it.
        """
        self.logger.info(f"📤 Account online detected: {username}")
        self.mark_account_running(username)
    
    def start_auto_sync(self, interval: int = 30):
        """
        Start automatic sync in background thread.
        
        Args:
            interval: Sync interval in seconds
        """
        self.logger.info(f"🔄 Starting auto-sync (interval: {interval}s)")
        
        # Register callbacks with watcher
        self.watcher.on_offline(self.on_account_offline)
        self.watcher.on_online(self.on_account_online)
        
        # Start watcher
        self.watcher.start(blocking=False)
        
        # Do initial sync
        self.sync_status_to_local()
        
        return self
    
    def stop_auto_sync(self):
        """Stop automatic sync"""
        self.watcher.stop()
        self.logger.info("🔄 Auto-sync stopped")
        return self
    
    def get_sync_stats(self) -> dict:
        """Get sync statistics"""
        return {
            "last_sync": self._last_sync_time.isoformat() if self._last_sync_time else None,
            "sync_count": self._sync_count,
            "local_accounts": len(self._load_local_accounts()),
            "online_accounts": len(self.watcher.get_all_online_accounts()),
            "offline_accounts": len(self.watcher.get_all_offline_accounts()),
        }


# Singleton instance
_sync_manager_instance = None


def get_sync_manager() -> AccountSyncManager:
    """Get global account sync manager instance"""
    global _sync_manager_instance
    if _sync_manager_instance is None:
        _sync_manager_instance = AccountSyncManager()
    return _sync_manager_instance


if __name__ == "__main__":
    # Test the sync manager
    print("Testing Account Sync Manager...")
    
    manager = AccountSyncManager()
    
    # Do sync
    active, inactive = manager.sync_status_to_local()
    print(f"\nSync result: {active} set active, {inactive} set inactive")
    
    # Get accounts needing autorun
    needs_run = manager.get_accounts_needing_autorun()
    print(f"\nAccounts needing autorun ({len(needs_run)}):")
    for acc in needs_run:
        print(f"  - {acc.get('username')}")
    
    # Print stats
    stats = manager.get_sync_stats()
    print(f"\nStats: {json.dumps(stats, indent=2)}")
