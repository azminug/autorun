# Configuration for Roblox Auto Login Bot
# Copy this file to config.py and fill in your values
import os
import json

# ===========================
# FIREBASE CONFIGURATION
# ===========================
FIREBASE_CONFIG = {
    "databaseURL": "https://YOUR-PROJECT-ID.firebaseio.com"
}

# Firebase Admin SDK (for Python backend)
FIREBASE_CREDENTIALS_PATH = "firebase_credentials.json"

# ===========================
# NOTIFICATION WEBHOOKS
# ===========================
DISCORD_WEBHOOK_URL = ""  # Optional: Discord webhook for notifications
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
WHATSAPP_API_URL = ""
WHATSAPP_API_KEY = ""

# ===========================
# ROBLOX CONFIGURATION
# ===========================
ROBLOX_LOGIN_URL = "https://www.roblox.com/login"
DEFAULT_SERVER_LINK = "https://www.roblox.com/games/YOUR_GAME_ID"

# ===========================
# PID MONITORING
# ===========================
PID_HEARTBEAT_INTERVAL = 5  # seconds
PID_CHECK_TIMEOUT = 60  # seconds to wait for Roblox to start
ROBLOX_PROCESS_NAME = "RobloxPlayerBeta"

# ===========================
# VERIFICATION
# ===========================
VERIFICATION_WAIT_TIMEOUT = 300  # 5 minutes max wait for verification
VERIFICATION_CHECK_INTERVAL = 2  # seconds between checks

# ===========================
# BROWSER SETTINGS
# ===========================
BROWSER_ALERT_TIMEOUT = 10  # seconds to wait for browser alert
MAX_LOGIN_ATTEMPTS = 5

# ===========================
# DASHBOARD
# ===========================
DASHBOARD_PORT = 8080
DASHBOARD_HOST = "127.0.0.1"

# ===========================
# FILE PATHS
# ===========================
ACCOUNTS_FILE = "accounts.json"
STATUS_FILE = "status.json"
LOG_FILE = "autorun.log"


def load_config_from_file(config_file="config.json"):
    """Load configuration from external JSON file if exists"""
    if os.path.exists(config_file):
        with open(config_file, "r") as f:
            return json.load(f)
    return {}


def save_config_to_file(config_dict, config_file="config.json"):
    """Save configuration to JSON file"""
    with open(config_file, "w") as f:
        json.dump(config_dict, f, indent=4)
