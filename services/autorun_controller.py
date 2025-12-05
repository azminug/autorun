"""
Autorun Controller
==================
Controls automated running of offline accounts.
Prevents double-run and manages run queue.
"""

import time
import threading
import queue
from datetime import datetime
from typing import Dict, Set, Optional, Callable
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.firebase_watcher import FirebaseWatcher
from services.account_sync import AccountSyncManager
from utils.logger import get_logger


class AutorunController:
    """
    Controls automated running of accounts when they go offline.
    
    Features:
    - Monitors Firebase for offline accounts
    - Prevents double-run of same account
    - Queue-based processing
    - Callback-based execution
    """
    
    # Minimum time between runs of same account (seconds)
    RUN_COOLDOWN = 60
    
    # Maximum accounts to queue
    MAX_QUEUE_SIZE = 50
    
    def __init__(self):
        self.watcher = FirebaseWatcher()
        self.sync_manager = AccountSyncManager()
        self.logger = get_logger()
        
        # Queue of accounts to process
        self._run_queue: queue.Queue = queue.Queue(maxsize=self.MAX_QUEUE_SIZE)
        
        # Track running/recently run accounts
        self._running: Set[str] = set()  # Currently being processed
        self._last_run: Dict[str, float] = {}  # username -> timestamp of last run
        
        # Locks
        self._running_lock = threading.Lock()
        
        # Run callback
        self._run_callback: Optional[Callable] = None
        
        # Control flags
        self._running_flag = False
        self._worker_thread: Optional[threading.Thread] = None
        
    def _normalize_username(self, username: str) -> str:
        """Normalize username for consistent matching"""
        return username.lower().strip() if username else ""
    
    def _can_run_account(self, username: str) -> bool:
        """
        Check if account can be run.
        Returns False if:
        - Currently running
        - Recently run (within cooldown)
        """
        normalized = self._normalize_username(username)
        
        with self._running_lock:
            # Check if currently running
            if normalized in self._running:
                return False
            
            # Check cooldown
            last_run = self._last_run.get(normalized, 0)
            if time.time() - last_run < self.RUN_COOLDOWN:
                return False
        
        return True
    
    def _mark_running(self, username: str):
        """Mark account as currently running"""
        normalized = self._normalize_username(username)
        with self._running_lock:
            self._running.add(normalized)
    
    def _mark_finished(self, username: str):
        """Mark account as finished running"""
        normalized = self._normalize_username(username)
        with self._running_lock:
            self._running.discard(normalized)
            self._last_run[normalized] = time.time()
    
    def _on_account_offline(self, username: str, data: dict):
        """
        Callback when account goes offline.
        Queues account for autorun.
        """
        normalized = self._normalize_username(username)
        
        if not self._can_run_account(normalized):
            self.logger.debug(f"⏭️ Skipping {username} (already running or cooldown)")
            return
        
        try:
            self._run_queue.put_nowait({
                "username": normalized,
                "data": data,
                "queued_at": datetime.now().isoformat()
            })
            self.logger.info(f"📥 Queued for autorun: {username}")
        except queue.Full:
            self.logger.warning(f"⚠️ Queue full, cannot add {username}")
    
    def _process_queue(self):
        """Process queued accounts"""
        while self._running_flag:
            try:
                # Get next account from queue (with timeout to check running flag)
                try:
                    item = self._run_queue.get(timeout=5)
                except queue.Empty:
                    continue
                
                username = item["username"]
                
                # Double-check can run
                if not self._can_run_account(username):
                    self.logger.debug(f"⏭️ Skipping {username} (state changed)")
                    continue
                
                # Mark as running
                self._mark_running(username)
                
                # Update local accounts.json (set active=False to prevent double-run)
                self.sync_manager.mark_account_running(username)
                
                self.logger.info(f"🚀 Starting autorun for: {username}")
                
                # Execute run callback
                if self._run_callback:
                    try:
                        self._run_callback(username, item.get("data", {}))
                    except Exception as e:
                        self.logger.error(f"❌ Autorun error for {username}: {e}")
                
                # Mark as finished
                self._mark_finished(username)
                self.logger.info(f"✅ Finished autorun for: {username}")
                
            except Exception as e:
                self.logger.error(f"Queue processing error: {e}")
    
    def set_run_callback(self, callback: Callable[[str, dict], None]):
        """
        Set the callback function for running accounts.
        
        The callback receives:
        - username: str - The account username
        - data: dict - Firebase account data
        """
        self._run_callback = callback
        return self
    
    def queue_account(self, username: str, data: dict = None):
        """
        Manually queue an account for autorun.
        """
        self._on_account_offline(username, data or {})
    
    def queue_all_offline(self):
        """
        Queue all currently offline accounts for autorun.
        """
        offline = self.watcher.get_all_offline_accounts()
        self.logger.info(f"📋 Queueing {len(offline)} offline accounts")
        
        for username in offline:
            self.queue_account(username)
        
        return len(offline)
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self._run_queue.qsize()
    
    def get_running_accounts(self) -> Set[str]:
        """Get currently running accounts"""
        with self._running_lock:
            return self._running.copy()
    
    def is_account_running(self, username: str) -> bool:
        """Check if specific account is currently running"""
        normalized = self._normalize_username(username)
        with self._running_lock:
            return normalized in self._running
    
    def start(self, blocking: bool = False):
        """
        Start the autorun controller.
        
        Args:
            blocking: If True, blocks current thread. Otherwise runs in background.
        """
        self.logger.info("🎮 Starting Autorun Controller")
        self._running_flag = True
        
        # Register callback with watcher
        self.watcher.on_offline(self._on_account_offline)
        
        # Start watcher
        self.watcher.start(blocking=False)
        
        # Do initial sync and queue offline accounts
        self.sync_manager.sync_status_to_local()
        self.queue_all_offline()
        
        # Start worker thread
        if blocking:
            self._process_queue()
        else:
            self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._worker_thread.start()
        
        return self
    
    def stop(self):
        """Stop the autorun controller"""
        self.logger.info("🛑 Stopping Autorun Controller")
        self._running_flag = False
        self.watcher.stop()
        
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)
        
        return self
    
    def run_idle(self, callback: Callable = None, check_interval: int = 30):
        """
        Run in idle mode - continuously watch and trigger autorun.
        Blocks until interrupted.
        
        Args:
            callback: Function to call for each account that needs running
            check_interval: How often to re-check for offline accounts (seconds)
        """
        if callback:
            self.set_run_callback(callback)
        
        self.start(blocking=False)
        
        print("\n" + "=" * 50)
        print("🔄 Autorun Controller - Idle Mode")
        print("=" * 50)
        print(f"   Queue check: {check_interval}s")
        print(f"   Run cooldown: {self.RUN_COOLDOWN}s")
        print("   Press Ctrl+C to stop")
        print("=" * 50 + "\n")
        
        try:
            while self._running_flag:
                # Periodic re-check for offline accounts
                offline_count = len(self.watcher.get_all_offline_accounts())
                online_count = len(self.watcher.get_all_online_accounts())
                queue_size = self.get_queue_size()
                running = len(self.get_running_accounts())
                
                self.logger.info(
                    f"📊 Status: {online_count} online, {offline_count} offline, "
                    f"{queue_size} queued, {running} running"
                )
                
                time.sleep(check_interval)
                
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user")
        finally:
            self.stop()


# Singleton instance
_controller_instance = None


def get_autorun_controller() -> AutorunController:
    """Get global autorun controller instance"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = AutorunController()
    return _controller_instance


if __name__ == "__main__":
    # Test the controller
    print("Testing Autorun Controller...")
    
    controller = AutorunController()
    
    # Set a dummy callback
    def dummy_run(username, data):
        print(f"[DUMMY RUN] Would run account: {username}")
        time.sleep(2)  # Simulate work
    
    controller.set_run_callback(dummy_run)
    
    # Start in idle mode
    controller.run_idle(check_interval=10)
