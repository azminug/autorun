"""Logging utility for the automation bot"""
import logging
import os
from datetime import datetime


class Logger:
    """Custom logger with file and console output"""
    
    def __init__(self, name="autorun", log_file="autorun.log", log_level=logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)
        
        # Prevent duplicate handlers
        if not self.logger.handlers:
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(log_level)
            console_format = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
            console_handler.setFormatter(console_format)
            self.logger.addHandler(console_handler)
            
            # File handler
            try:
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
                file_handler.setLevel(log_level)
                file_format = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
                file_handler.setFormatter(file_format)
                self.logger.addHandler(file_handler)
            except Exception as e:
                print(f"Could not create log file: {e}")
    
    def info(self, message):
        self.logger.info(message)
    
    def debug(self, message):
        self.logger.debug(message)
    
    def warning(self, message):
        self.logger.warning(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def critical(self, message):
        self.logger.critical(message)
    
    def success(self, message):
        """Log success message (info level with emoji)"""
        self.logger.info(f"✅ {message}")
    
    def fail(self, message):
        """Log failure message (error level with emoji)"""
        self.logger.error(f"❌ {message}")


# Global logger instance
_logger = None


def get_logger():
    """Get global logger instance"""
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger
