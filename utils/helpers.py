"""General helper utilities"""
import json
import os
from datetime import datetime


def get_timestamp():
    """Get current timestamp in ISO format"""
    return datetime.now().isoformat()


def get_timestamp_unix():
    """Get current Unix timestamp"""
    return int(datetime.now().timestamp())


def format_duration(seconds):
    """Format duration in human readable format"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:.0f}m {secs:.0f}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:.0f}h {minutes:.0f}m"


def safe_json_load(file_path, default=None):
    """Safely load JSON file, return default if error"""
    if default is None:
        default = {}
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ Error loading {file_path}: {e}")
        return default


def safe_json_save(file_path, data):
    """Safely save data to JSON file"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except IOError as e:
        print(f"⚠️ Error saving {file_path}: {e}")
        return False


def ensure_directory(path):
    """Ensure directory exists, create if not"""
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def truncate_string(s, max_length=50):
    """Truncate string with ellipsis if too long"""
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + "..."
