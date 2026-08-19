# services/sms_gateway.py
"""
SMS gateway service for OTP-Bot-Telegram.
Sends OTP codes to target numbers via generic HTTP API.
"""
import logging
import random
import requests
from typing import Optional

from config import (
    SMS_PROVIDER,
    SMS_API_URL,
    SMS_API_KEY,
)

logger = logging.getLogger("OTP-Bot.sms_gateway")

class SMSGateway:
    def __init__(self):
        self.provider = SMS_PROVIDER or 'generic'

    def generate_otp(self, digits: int = 6) -> str:
        """Generate a random OTP code."""
        return ''.join([str(random.randint(0, 9)) for _ in range(digits)])

    def send_otp(self, to_number: str, otp: str = None, digits: int = 6) -> bool:
        """
        Send OTP to target number.

        Args:
            to_number: Target phone number (E.164 format)
            otp: Optional OTP code (if None, generates one)
            digits: Length of OTP to generate if not provided

        Returns:
            True if sent successfully, False otherwise
        """
        if otp is None:
            otp = self.generate_otp(digits)

        return self._send_generic(to_number, otp)

    def _send_generic(self, to_number: str, otp: str) -> bool:
        """Send OTP via generic HTTP API."""
        if not SMS_API_URL:
            logger.error("Generic SMS API URL not configured")
            return False
        try:
            payload = {
                "to": to_number,
                "otp": otp,
                "api_key": SMS_API_KEY,
            }
            resp = requests.post(SMS_API_URL, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info(f"OTP sent via generic API: {resp.text}")
                return True
            else:
                logger.error(f"Generic SMS API error: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Generic SMS request failed: {e}")
            return False