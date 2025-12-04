# Roblox Auto Login Bot v6

Automated Roblox account management and monitoring system with Firebase integration.

## 🌟 Features

- **Multi-Account Management**: Handle multiple Roblox accounts simultaneously
- **Automatic Login**: Selenium-based browser automation for account login
- **Firebase Monitoring**: Real-time status tracking via Firebase RTDB
- **Verification Handling**: Automatic detection and handling of verification prompts
- **Alert Handler**: Auto-click browser alerts (Bloxstrap, protocol handlers)
- **Device Tracking**: HWID-based device identification
- **Discord Notifications**: Webhook integration for status alerts
- **Web Dashboard**: Real-time monitoring dashboard (separate repo)

## 📁 Project Structure

```
autorun/
├── run.py                  # Main entry point
├── config.example.py       # Configuration template
├── accounts.example.json   # Accounts template
├── requirements.txt        # Python dependencies
├── firebase/
│   ├── firebase_client.py  # Firebase REST API client
│   └── status_manager.py   # Status management
├── utils/
│   ├── hwid.py            # Hardware ID generation
│   ├── helpers.py         # Utility functions
│   └── logger.py          # Logging setup
├── verification/
│   ├── verification_handler.py   # Captcha/verification detection
│   └── browser_alert_handler.py  # Browser alert automation
├── services/
│   └── notification_service.py   # Discord/Telegram notifications
└── dashboard/
    └── server.py          # Local dashboard server
```

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Chrome browser
- ChromeDriver (auto-managed by Selenium)
- Bloxstrap (recommended for Roblox launching)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/azminug/autorun.git
cd autorun
```

2. Create virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure the bot:
```bash
# Copy example files
copy config.example.py config.py
copy accounts.example.json accounts.json

# Edit config.py with your Firebase URL
# Edit accounts.json with your Roblox accounts
```

### Configuration

Edit `config.py`:
```python
FIREBASE_CONFIG = {
    "databaseURL": "https://your-project.firebaseio.com"
}

DEFAULT_SERVER_LINK = "https://www.roblox.com/games/YOUR_GAME_ID"

# Optional: Discord webhook for notifications
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
```

Edit `accounts.json`:
```json
[
    {"username": "account1", "password": "password1", "active": true},
    {"username": "account2", "password": "password2", "active": true}
]
```

### Usage

```bash
# Run with default settings (persistent mode)
python run.py

# Run once and exit
python run.py --no-persistent

# Show help
python run.py --help
```

## 🔧 Architecture

### Components

1. **run.py** - Main orchestrator
   - Handles Selenium browser automation
   - Manages account login flow
   - Coordinates with Firebase for status updates

2. **Firebase Client** - Real-time database
   - REST API wrapper for Firebase RTDB
   - Status updates, device tracking, logging

3. **Verification Handler** - Anti-bot detection
   - Detects captcha/verification prompts
   - Pauses automation when verification needed

4. **Browser Alert Handler** - Protocol handling
   - Auto-accepts Bloxstrap/Roblox protocol dialogs
   - Windows API integration for native dialogs

5. **Heartbeat Module** (Lua) - In-game monitoring
   - Runs inside Roblox via executor
   - Updates Firebase with player status
   - Scans inventory/backpack data

### Data Flow

```
run.py → Login → Launch Game
            ↓
    Firebase (accounts/{username})
            ↓
  heartbeat.lua → Firebase (status updates)
            ↓
    Web Dashboard (real-time display)
```

## 📊 Firebase Structure

```
/accounts/{username}
  ├── hostname      # Device name
  ├── last_update   # ISO timestamp
  ├── roblox/
  │   ├── inGame    # boolean
  │   ├── status    # "online" | "idle" | "offline"
  │   ├── gameName  # Current game
  │   ├── serverId  # Job ID
  │   └── timestamp # Unix timestamp
  └── backpack/
      ├── items[]
      ├── secretItems[]
      ├── rarityCount{}
      └── totalValue

/devices/{hwid}
  ├── hostname
  ├── status        # "online" | "offline"
  ├── last_heartbeat
  └── active_accounts

/logs/{id}
  ├── type          # "login" | "launch" | "error"
  ├── message
  ├── username
  ├── hostname
  └── timestamp
```

## 🔐 Security Notes

- **Never commit** `config.py` or `accounts.json`
- Use `.gitignore` to exclude sensitive files
- Firebase rules should restrict access by device HWID
- Webhook URLs should be kept private

## 📝 Related Projects

- **Web Dashboard**: [azminug/autofarm](https://github.com/azminug/autofarm) - Real-time monitoring UI
- **Lua Heartbeat**: [azminug/autotrade](https://github.com/azminug/autotrade) - In-game status module

## 📄 License

This project is for educational purposes only. Use responsibly and in accordance with Roblox's Terms of Service.

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---

Made with ❤️ for the Roblox automation community
