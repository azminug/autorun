"""Notification Service for Discord, Telegram, and WhatsApp webhooks"""
import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    DISCORD_WEBHOOK_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    WHATSAPP_API_URL,
    WHATSAPP_API_KEY
)


class NotificationService:
    """
    Unified notification service for sending alerts via multiple channels.
    Supports Discord, Telegram, and WhatsApp.
    """
    
    def __init__(self, 
                 discord_webhook=None,
                 telegram_token=None,
                 telegram_chat_id=None,
                 whatsapp_url=None,
                 whatsapp_key=None):
        """
        Initialize Notification Service
        
        Args:
            discord_webhook: Discord webhook URL
            telegram_token: Telegram bot token
            telegram_chat_id: Telegram chat ID
            whatsapp_url: WhatsApp API URL
            whatsapp_key: WhatsApp API key
        """
        self.discord_webhook = discord_webhook or DISCORD_WEBHOOK_URL
        self.telegram_token = telegram_token or TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = telegram_chat_id or TELEGRAM_CHAT_ID
        self.whatsapp_url = whatsapp_url or WHATSAPP_API_URL
        self.whatsapp_key = whatsapp_key or WHATSAPP_API_KEY
        
        # Track enabled services
        self.discord_enabled = bool(self.discord_webhook and 'discord' in self.discord_webhook)
        self.telegram_enabled = bool(self.telegram_token and self.telegram_chat_id)
        self.whatsapp_enabled = bool(self.whatsapp_url and self.whatsapp_key)
    
    def _make_request(self, url, data, headers=None):
        """Make HTTP POST request"""
        try:
            if headers is None:
                headers = {'Content-Type': 'application/json'}
            
            request = Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
            
            with urlopen(request, timeout=10) as response:
                return True, response.read().decode('utf-8')
        except (URLError, HTTPError) as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)
    
    # ===========================
    # DISCORD
    # ===========================
    
    def send_discord(self, content=None, embed=None, username="Roblox Bot"):
        """
        Send message to Discord webhook
        
        Args:
            content: Plain text message
            embed: Embed object (dict)
            username: Bot username to display
        
        Returns:
            bool: Success status
        """
        if not self.discord_enabled:
            return False
        
        data = {"username": username}
        
        if content:
            data["content"] = content
        
        if embed:
            data["embeds"] = [embed] if isinstance(embed, dict) else embed
        
        success, result = self._make_request(self.discord_webhook, data)
        
        if not success:
            print(f"⚠️ Discord notification failed: {result}")
        
        return success
    
    def send_discord_embed(self, title, description, color=0x00ff00, fields=None, footer=None):
        """
        Send Discord embed message
        
        Args:
            title: Embed title
            description: Embed description
            color: Embed color (hex)
            fields: List of field dicts [{name, value, inline}]
            footer: Footer text
        
        Returns:
            bool: Success status
        """
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if fields:
            embed["fields"] = fields
        
        if footer:
            embed["footer"] = {"text": footer}
        
        return self.send_discord(embed=embed)
    
    # ===========================
    # TELEGRAM
    # ===========================
    
    def send_telegram(self, message, parse_mode="HTML"):
        """
        Send message to Telegram
        
        Args:
            message: Message text
            parse_mode: Parse mode (HTML, Markdown)
        
        Returns:
            bool: Success status
        """
        if not self.telegram_enabled:
            return False
        
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        data = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        success, result = self._make_request(url, data)
        
        if not success:
            print(f"⚠️ Telegram notification failed: {result}")
        
        return success
    
    def send_telegram_formatted(self, title, content, emoji="🤖"):
        """
        Send formatted Telegram message
        
        Args:
            title: Message title
            content: Message content (can be multiline)
            emoji: Emoji prefix
        
        Returns:
            bool: Success status
        """
        message = f"{emoji} <b>{title}</b>\n\n{content}"
        return self.send_telegram(message)
    
    # ===========================
    # WHATSAPP
    # ===========================
    
    def send_whatsapp(self, message, phone_number=None):
        """
        Send message via WhatsApp API
        
        Args:
            message: Message text
            phone_number: Target phone number (optional)
        
        Returns:
            bool: Success status
        """
        if not self.whatsapp_enabled:
            return False
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.whatsapp_key}'
        }
        
        data = {
            "message": message
        }
        
        if phone_number:
            data["phone"] = phone_number
        
        success, result = self._make_request(self.whatsapp_url, data, headers)
        
        if not success:
            print(f"⚠️ WhatsApp notification failed: {result}")
        
        return success
    
    # ===========================
    # UNIFIED METHODS
    # ===========================
    
    def notify_all(self, title, message, level="info"):
        """
        Send notification to all enabled channels
        
        Args:
            title: Notification title
            message: Notification message
            level: Level (info, warning, error, success)
        
        Returns:
            dict: Results for each channel
        """
        results = {}
        
        # Color mapping for Discord
        colors = {
            "info": 0x3498db,
            "warning": 0xf39c12,
            "error": 0xe74c3c,
            "success": 0x2ecc71
        }
        
        # Emoji mapping
        emojis = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅"
        }
        
        emoji = emojis.get(level, "🤖")
        color = colors.get(level, 0x3498db)
        
        # Discord
        if self.discord_enabled:
            results["discord"] = self.send_discord_embed(
                title=f"{emoji} {title}",
                description=message,
                color=color
            )
        
        # Telegram
        if self.telegram_enabled:
            results["telegram"] = self.send_telegram_formatted(title, message, emoji)
        
        # WhatsApp
        if self.whatsapp_enabled:
            results["whatsapp"] = self.send_whatsapp(f"{emoji} {title}\n\n{message}")
        
        return results
    
    # ===========================
    # PRESET NOTIFICATIONS
    # ===========================
    
    def notify_account_login(self, username, hwid=None):
        """Notify when account starts login"""
        message = f"Account <b>{username}</b> is logging in"
        if hwid:
            message += f"\nDevice: {hwid[:16]}..."
        return self.notify_all("Account Login", message, "info")
    
    def notify_verification_needed(self, username):
        """Notify when verification is needed"""
        return self.notify_all(
            "Verification Required",
            f"Account <b>{username}</b> requires manual verification!",
            "warning"
        )
    
    def notify_account_running(self, username, pid):
        """Notify when account starts running"""
        return self.notify_all(
            "Account Running",
            f"Account <b>{username}</b> is now running\nPID: {pid}",
            "success"
        )
    
    def notify_account_stopped(self, username, reason="unknown"):
        """Notify when account stops"""
        return self.notify_all(
            "Account Stopped",
            f"Account <b>{username}</b> has stopped\nReason: {reason}",
            "error"
        )
    
    def notify_device_status(self, hwid, hostname, status="online", account_count=0):
        """Notify device status change"""
        emoji = "🟢" if status == "online" else "🔴"
        return self.notify_all(
            f"Device {status.upper()}",
            f"{emoji} <b>{hostname}</b>\nHWID: {hwid[:16]}...\nActive accounts: {account_count}",
            "success" if status == "online" else "warning"
        )
    
    def get_status(self):
        """Get notification service status"""
        return {
            "discord": self.discord_enabled,
            "telegram": self.telegram_enabled,
            "whatsapp": self.whatsapp_enabled
        }


# Singleton instance
_notification_service = None


def get_notification_service():
    """Get global NotificationService instance"""
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service


if __name__ == "__main__":
    # Test notification service
    service = NotificationService()
    
    print("Notification Service Status:")
    status = service.get_status()
    for channel, enabled in status.items():
        print(f"  {channel}: {'✅ Enabled' if enabled else '❌ Disabled'}")
    
    # Test if any service is enabled
    if any(status.values()):
        print("\nSending test notification...")
        results = service.notify_all("Test Notification", "This is a test message from Roblox Bot", "info")
        print(f"Results: {results}")
    else:
        print("\n⚠️ No notification services configured!")
        print("Configure webhooks in config.py")
