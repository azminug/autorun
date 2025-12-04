"""Local Dashboard Server (for development/testing only)"""
import http.server
import socketserver
import os
import sys
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DASHBOARD_PORT, DASHBOARD_HOST


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler for dashboard"""
    
    def __init__(self, *args, directory=None, **kwargs):
        # Use website folder instead of dashboard folder
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dashboard_dir = directory or os.path.join(base_dir, 'website')
        super().__init__(*args, directory=self.dashboard_dir, **kwargs)
    
    def do_GET(self):
        # Serve index.html for root path
        if self.path == '/':
            self.path = '/index.html'
        
        # Add CORS headers for local development
        return super().do_GET()
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()
    
    def log_message(self, format, *args):
        # Suppress logs or customize
        print(f"📡 Dashboard: {args[0]}")


class DashboardServer:
    """Local dashboard server manager"""
    
    def __init__(self, host=None, port=None):
        self.host = host or DASHBOARD_HOST
        self.port = port or DASHBOARD_PORT
        self.server = None
        self.thread = None
        self.running = False
    
    def start(self, open_browser=True):
        """Start the dashboard server"""
        if self.running:
            print("⚠️ Dashboard server already running")
            return
        
        dashboard_dir = os.path.dirname(os.path.abspath(__file__))
        
        handler = lambda *args, **kwargs: DashboardHandler(*args, directory=dashboard_dir, **kwargs)
        
        try:
            self.server = socketserver.TCPServer((self.host, self.port), handler)
            self.running = True
            
            url = f"http://{self.host}:{self.port}"
            print(f"🌐 Dashboard server started at {url}")
            
            # Start in background thread
            self.thread = threading.Thread(target=self._serve, daemon=True)
            self.thread.start()
            
            # Open browser
            if open_browser:
                print(f"🔗 Opening browser...")
                webbrowser.open(url)
            
            return url
            
        except OSError as e:
            print(f"❌ Failed to start dashboard: {e}")
            if "Address already in use" in str(e):
                print(f"💡 Try a different port or close existing server on port {self.port}")
            return None
    
    def _serve(self):
        """Internal serve loop"""
        try:
            self.server.serve_forever()
        except Exception as e:
            if self.running:
                print(f"⚠️ Dashboard server error: {e}")
    
    def stop(self):
        """Stop the dashboard server"""
        if not self.running:
            return
        
        print("🌐 Stopping dashboard server...")
        self.running = False
        
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        
        print("🌐 Dashboard server stopped")
    
    def is_running(self):
        """Check if server is running"""
        return self.running


# Global server instance
_dashboard_server = None


def get_dashboard_server():
    """Get global dashboard server instance"""
    global _dashboard_server
    if _dashboard_server is None:
        _dashboard_server = DashboardServer()
    return _dashboard_server


def start_dashboard(open_browser=True):
    """Quick start dashboard server"""
    server = get_dashboard_server()
    return server.start(open_browser)


def stop_dashboard():
    """Quick stop dashboard server"""
    server = get_dashboard_server()
    server.stop()


if __name__ == "__main__":
    import time
    
    print("Starting Dashboard Server...")
    server = DashboardServer()
    url = server.start(open_browser=True)
    
    if url:
        print(f"\n✅ Dashboard running at: {url}")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nStopping server...")
            server.stop()
