"""Firebase Realtime Database Client for status tracking"""
import json
import threading
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FIREBASE_CONFIG


class FirebaseClient:
    """
    Firebase Realtime Database client using REST API.
    No external dependencies required.
    """
    
    def __init__(self, database_url=None):
        """Initialize Firebase client"""
        self.database_url = database_url or FIREBASE_CONFIG.get('databaseURL', '')
        if self.database_url.endswith('/'):
            self.database_url = self.database_url[:-1]
        self._connected = False
        self._heartbeat_thread = None
        self._stop_heartbeat = threading.Event()
    
    @property
    def is_connected(self):
        """Check if Firebase is configured and reachable"""
        return self._connected and self.database_url and 'YOUR_PROJECT' not in self.database_url
    
    def _make_request(self, path, method='GET', data=None):
        """Make HTTP request to Firebase"""
        if not self.database_url or 'YOUR_PROJECT' in self.database_url:
            return None
            
        url = f"{self.database_url}/{path}.json"
        
        try:
            if data is not None:
                data = json.dumps(data).encode('utf-8')
                
            request = Request(url, data=data, method=method)
            request.add_header('Content-Type', 'application/json')
            
            with urlopen(request, timeout=10) as response:
                result = response.read().decode('utf-8')
                self._connected = True
                return json.loads(result) if result else None
                
        except (URLError, HTTPError) as e:
            print(f"⚠️ Firebase request error: {e}")
            self._connected = False
            return None
        except Exception as e:
            print(f"⚠️ Firebase error: {e}")
            self._connected = False
            return None
    
    def get(self, path):
        """Get data from Firebase path"""
        return self._make_request(path, 'GET')
    
    def set(self, path, data):
        """Set data at Firebase path (overwrites)"""
        return self._make_request(path, 'PUT', data)
    
    def update(self, path, data):
        """Update data at Firebase path (merges)"""
        return self._make_request(path, 'PATCH', data)
    
    def delete(self, path):
        """Delete data at Firebase path"""
        return self._make_request(path, 'DELETE')
    
    def push(self, path, data):
        """Push new data to Firebase path (generates unique key)"""
        return self._make_request(path, 'POST', data)
    
    # ===========================
    # HIGH-LEVEL METHODS
    # ===========================
    
    def update_device_status(self, hwid, status_data):
        """
        Update device status in Firebase
        
        Args:
            hwid: Hardware ID of the device
            status_data: Dict with status information
        """
        status_data['last_update'] = datetime.now().isoformat()
        return self.update(f"devices/{hwid}", status_data)
    
    def set_device_online(self, hwid, machine_info=None):
        """Mark device as online"""
        data = {
            "status": "online",
            "online_since": datetime.now().isoformat(),
            "last_heartbeat": datetime.now().isoformat()
        }
        if machine_info:
            data["machine_info"] = machine_info
        return self.update(f"devices/{hwid}", data)
    
    def set_device_offline(self, hwid):
        """Mark device as offline"""
        return self.update(f"devices/{hwid}", {
            "status": "offline",
            "offline_since": datetime.now().isoformat()
        })
    
    def update_account_status(self, username, status_data):
        """
        Update account status in Firebase
        
        Args:
            username: Roblox username (will be normalized to lowercase)
            status_data: Dict with pid, status, hwid, etc.
        """
        # Normalize username to lowercase for consistency
        username_normalized = username.lower() if username else username
        status_data['last_update'] = datetime.now().isoformat()
        return self.update(f"accounts/{username_normalized}", status_data)
    
    def update_pid_status(self, username, pid, alive=True, hwid=None):
        """
        Update PID status for account
        
        Args:
            username: Roblox username
            pid: Process ID
            alive: Whether process is alive
            hwid: Hardware ID of running device
        """
        data = {
            "pid": pid,
            "pid_alive": alive,
            "pid_status": "running" if alive else "dead",
            "last_heartbeat": datetime.now().isoformat()
        }
        if hwid:
            data["hwid"] = hwid
        return self.update(f"accounts/{username}", data)
    
    def get_all_accounts(self):
        """Get all account statuses"""
        return self.get("accounts") or {}
    
    def get_all_devices(self):
        """Get all device statuses"""
        return self.get("devices") or {}
    
    def log_event(self, event_type, data):
        """Log an event to Firebase"""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        return self.push("logs", event)


# Singleton instance
_firebase_client = None


def get_firebase_client():
    """Get global Firebase client instance"""
    global _firebase_client
    if _firebase_client is None:
        _firebase_client = FirebaseClient()
    return _firebase_client


if __name__ == "__main__":
    # Test Firebase connection
    client = FirebaseClient()
    print(f"Database URL: {client.database_url}")
    print(f"Connected: {client.is_connected}")
    
    # Test write
    result = client.set("test", {"message": "Hello from Python!", "timestamp": datetime.now().isoformat()})
    print(f"Write result: {result}")
