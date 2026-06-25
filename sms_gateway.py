# services/sms_gateway.py
"""
SMS gateway service for OTP-Bot-Telegram.
Sends OTP codes to target numbers via various providers.
Supports Twilio SMS as primary, with fallback to generic HTTP API.
"""
import logging
import random
import requests
from typing import Optional, Dict

from config import (
    ACCOUNT_SID,
    AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    SMS_PROVIDER,  # Add this to config.py: 'twilio' or 'generic'
    SMS_API_URL,   # For generic provider
    SMS_API_KEY,
)

logger = logging.getLogger("OTP-Bot.sms_gateway")

class SMSGateway:
    def __init__(self):
        self.provider = SMS_PROVIDER or 'twilio'

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
        
        if self.provider == 'twilio':
            return self._send_twilio(to_number, otp)
        else:
            return self._send_generic(to_number, otp)

    def _send_twilio(self, to_number: str, otp: str) -> bool:
        """Send OTP via Twilio SMS."""
        if not ACCOUNT_SID or not AUTH_TOKEN:
            logger.error("Twilio credentials missing")
            return False
        try:
            from twilio.rest import Client
            client = Client(ACCOUNT_SID, AUTH_TOKEN)
            message = client.messages.create(
                body=f"Your verification code is: {otp}",
                from_=TWILIO_PHONE_NUMBER,
                to=to_number,
            )
            logger.info(f"OTP sent via Twilio: {message.sid}")
            return True
        except Exception as e:
            logger.error(f"Twilio SMS failed: {e}")
            return False

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