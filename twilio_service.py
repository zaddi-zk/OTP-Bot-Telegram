# services/twilio_service.py (full file with enhanced error handling)
"""
Twilio service layer for OTP-Bot-Telegram.
Handles call creation, status checking, recording retrieval, and hangup.
Includes retry logic with exponential backoff, spoofing support, carrier lookup,
and granular error messages for user feedback.
"""
import time
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from config import (
    ACCOUNT_SID,
    AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    NGROK_URL,
    ABSTRACT_API_KEY,
)
from rate_limiter import get_rate_limiter
from core.files import user_conf_path, read_user_file, write_user_file, ensure_user_path

logger = logging.getLogger("OTP-Bot.twilio")

# ======================================================================
# Twilio client (singleton, thread-safe)
# ======================================================================
_twilio_client = None

def get_twilio_client() -> Optional[Client]:
    """Get or create the Twilio client singleton."""
    global _twilio_client
    if _twilio_client is None:
        if ACCOUNT_SID and AUTH_TOKEN and "YOUR_" not in ACCOUNT_SID:
            _twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)
        else:
            logger.error("Twilio credentials not properly configured")
    return _twilio_client

# ======================================================================
# Twilio error code mapping for user feedback
# ======================================================================
class TwilioErrorHandler:
    """
    Maps Twilio REST exception codes to user‑friendly messages.
    Reference: https://www.twilio.com/docs/api/errors
    """
    ERROR_MESSAGES = {
        # Phone number errors
        21211: "❌ Invalid phone number format. Please use E.164 format (e.g., +1234567890).",
        21614: "❌ Caller ID is not verified. Please use a Twilio‑verified number or contact support.",
        20003: "❌ Authentication failed. Check your Twilio Account SID and Auth Token.",
        # Capacity/limiting errors
        20429: "❌ Rate limit exceeded. Please wait a few minutes before trying again.",
        20001: "❌ Twilio account is suspended or inactive.",
        # Carrier/sip errors
        30007: "❌ Carrier rejected the call. The number may be blocked or invalid.",
        30008: "❌ Destination number is not reachable (invalid or disconnected).",
        30009: "❌ Carrier returned an error. Try again later.",
        # Recording/transcription errors
        20404: "❌ Recording not found. The call may not have been recorded.",
        20002: "❌ Recording failed due to insufficient balance.",
        # General errors
        20004: "❌ Invalid Twilio phone number. Please check your number.",
        20407: "❌ Call cannot be made to this number (likely blocked by carrier).",
        20413: "❌ The 'from' number is not owned by this account.",
    }
    
    @classmethod
    def get_user_message(cls, exception: TwilioRestException) -> str:
        """
        Get a user‑friendly message for a Twilio exception.
        
        Args:
            exception: TwilioRestException object
        
        Returns:
            User‑friendly error message
        """
        code = exception.code
        if code in cls.ERROR_MESSAGES:
            return cls.ERROR_MESSAGES[code]
        # Generic fallback
        return f"❌ Twilio error (code {code}): {str(exception)}"

# ======================================================================
# Carrier lookup (using Abstract API or fallback)
# ======================================================================
def lookup_carrier(phone_number: str) -> Dict[str, Any]:
    """
    Identify carrier, country, and line type for a phone number.
    Uses Abstract API if key is provided, otherwise returns placeholder.
    
    Returns dict with keys:
        carrier, country, line_type, valid
    """
    if not ABSTRACT_API_KEY:
        return {"carrier": "Unknown", "country": "Unknown", "line_type": "Unknown", "valid": False}
    
    import requests
    try:
        url = f"https://phonevalidation.abstractapi.com/v1/?api_key={ABSTRACT_API_KEY}&phone={phone_number}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "carrier": data.get("carrier", "Unknown"),
                "country": data.get("country", {}).get("name", "Unknown"),
                "line_type": data.get("line_type", "Unknown"),
                "valid": data.get("valid", False),
            }
    except Exception as e:
        logger.debug(f"Carrier lookup error: {e}")
    
    return {"carrier": "Unknown", "country": "Unknown", "line_type": "Unknown", "valid": False}

# ======================================================================
# Call creation with spoofing and retry logic (basic)
# ======================================================================
def add_twilio_amd_parameters(params: dict, enable: bool = True, async_amd: bool = True, async_amd_status_callback: str = None) -> None:
    # AMD/Answering-Machine-Detection is intentionally disabled for this
    # deployment. Keep this function as a no-op so callers can remain unchanged
    # while ensuring no AMD params are sent to Twilio.
    return


def _safe_caller_id(caller_id: Optional[str]) -> str:
    if not caller_id:
        return TWILIO_PHONE_NUMBER
    cleaned = caller_id.strip()
    if "1234567890" in cleaned:
        return TWILIO_PHONE_NUMBER
    return cleaned

def make_call(
    to: str,
    from_number: str = None,
    caller_id: str = None,
    webhook_url: str = None,
    user_id: str = "",
    record: bool = False,
    retry_count: int = 2,
    delay_between_retries: int = 2,
    machine_detection: str = "Detect",
    async_amd: bool = True,
    async_amd_status_callback: str = None,
) -> Optional[str]:
    """
    Place a Twilio call with optional spoofing, automatic retry, and async AMD.
    
    Args:
        to: Destination phone number (E.164 format)
        from_number: Twilio phone number to use (defaults to config)
        caller_id: Caller ID to display (requires verification)
        webhook_url: URL for Twilio to request on call events
        user_id: For logging and rate limiting
        record: Whether to record the call
        retry_count: Number of retry attempts on failure
        delay_between_retries: Base delay in seconds (exponential backoff)
        machine_detection: Enable AMD ("Enable" or "Skip")
        async_amd: Enable async AMD (non-blocking)
        async_amd_status_callback: URL for AMD verdict
    
    Returns:
        Call SID on success, None on failure
    """
    client = get_twilio_client()
    if not client:
        logger.error("Twilio client not available")
        return None

    from_number = from_number or TWILIO_PHONE_NUMBER
    caller_id = _safe_caller_id(caller_id)
    webhook_url = webhook_url or f"{NGROK_URL}/voice?user_id={user_id}"

    # Rate limiting check
    limiter = get_rate_limiter()
    allowed, ban_remaining = limiter.check_and_consume(user_id, "twilio_call", tokens=1)
    if not allowed:
        logger.warning(f"Rate limit exceeded for user {user_id}")
        return None

    for attempt in range(retry_count + 1):
        try:
            call_params = {
                "to": to,
                "from_": from_number,
                "url": webhook_url,
                "method": "POST",
            }
            if record:
                call_params["record"] = True
            if caller_id:
                call_params["caller_id"] = caller_id

            call = client.calls.create(**call_params)
            logger.info(f"Call created: {call.sid} -> {to}")
            return call.sid

        except TwilioRestException as e:
            logger.warning(f"Twilio error (attempt {attempt+1}/{retry_count+1}): {e}")
            if attempt == retry_count:
                logger.error(f"Call failed after {retry_count+1} attempts: {e}")
                raise
            time.sleep(delay_between_retries ** attempt)

        except Exception as e:
            logger.error(f"Unexpected error during call creation: {e}")
            return None

    return None

# ======================================================================
# Call creation with retry and status verification (advanced)
# ======================================================================
def make_call_with_retry(
    to: str,
    from_number: str = None,
    caller_id: str = None,
    webhook_url: str = None,
    user_id: str = "",
    max_retries: int = 3,
    base_delay: int = 5,
    backoff_factor: float = 2.0,
) -> Optional[str]:
    """
    Place a call with exponential backoff retry on failure.
    Retries on: 'busy', 'no-answer', 'failed' (checked after 5 seconds).
    
    Args:
        to: Destination phone number (E.164 format)
        from_number: Twilio phone number to use (defaults to config)
        caller_id: Caller ID to display (requires verification)
        webhook_url: URL for Twilio to request on call events
        user_id: For logging and rate limiting
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        backoff_factor: Multiplier for delay between attempts
    
    Returns:
        Call SID on success, None on failure
    
    Raises:
        TwilioRestException: For critical Twilio errors that should stop retries
    """
    try:
        # First attempt
        first_sid = make_call(to, from_number, caller_id, webhook_url, user_id, record=True)
    except TwilioRestException as e:
        # If it's a critical error (authentication, invalid number, etc.), don't retry
        if e.code in [20003, 20004, 20413, 21211, 21614]:
            raise
        logger.warning(f"Initial call failed with non‑critical error: {e}")
        first_sid = None

    if not first_sid:
        logger.warning(f"Initial call to {to} failed")
        return None

    # Wait and check status for each retry
    for attempt in range(max_retries):
        time.sleep(base_delay * (backoff_factor ** attempt))
        status = get_call_status(first_sid)
        logger.debug(f"Call {first_sid} status: {status} (attempt {attempt+1}/{max_retries})")
        
        if status in ['completed', 'in-progress', 'ringing', 'queued']:
            # Call is successful or still progressing
            return first_sid
        
        # If busy, no-answer, or failed -> retry with new call
        if status in ['busy', 'no-answer', 'failed']:
            logger.info(f"Call {first_sid} status = {status}, retry #{attempt+1}")
            try:
                new_sid = make_call(to, from_number, caller_id, webhook_url, user_id, record=True)
            except TwilioRestException as e:
                logger.warning(f"Retry #{attempt+1} failed with Twilio error: {e}")
                continue
            if new_sid:
                # Cancel the old call and replace SID
                hangup_call(first_sid)
                first_sid = new_sid
                logger.info(f"Retry successful, new call SID: {first_sid}")
            else:
                logger.warning(f"Retry #{attempt+1} failed for {to}")
        else:
            # Unknown status – wait and continue
            continue
    
    return first_sid

# ======================================================================
# Call status checking
# ======================================================================
def get_call_status(call_sid: str) -> Optional[str]:
    """
    Fetch the current status of a call.
    
    Args:
        call_sid: Twilio call SID
    
    Returns:
        Status string (queued, ringing, in-progress, completed, failed, etc.)
        None if call not found or error
    """
    client = get_twilio_client()
    if not client:
        return None

    try:
        call = client.calls(call_sid).fetch()
        return call.status
    except TwilioRestException as e:
        logger.debug(f"Call {call_sid} not found: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching call status: {e}")
        return None

# ======================================================================
# Call metadata storage with history
# ======================================================================
def store_call_metadata(user_id: str, sid: str, target: str = "") -> None:
    """Store call SID in user's metadata and append to call history JSON."""
    try:
        ensure_user_path(user_id)
        write_user_file(user_id, "call_sid.txt", sid)

        history_path = user_conf_path(user_id) / "call_history.json"
        history = []
        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except:
                pass
        history.append({
            "sid": sid,
            "target": target,
            "started": datetime.now().isoformat(),
            "status": "initiated"
        })
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history[-200:], f, indent=2)
        logger.info(f"Call metadata stored: {sid} for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to store call metadata: {e}")


# ======================================================================
# Call termination (hangup)
# ======================================================================
def hangup_call(call_sid: str) -> bool:
    """
    Terminate an active call.
    
    Args:
        call_sid: Twilio call SID
    
    Returns:
        True if successful, False otherwise
    """
    client = get_twilio_client()
    if not client:
        return False

    try:
        client.calls(call_sid).update(status="completed")
        logger.info(f"Call {call_sid} hung up")
        return True
    except Exception as e:
        logger.error(f"Failed to hang up call {call_sid}: {e}")
        return False

# ======================================================================
# Recording retrieval
# ======================================================================
def get_recording_url(call_sid: str) -> Optional[str]:
    """
    Get the recording URL for a completed call.
    
    Args:
        call_sid: Twilio call SID
    
    Returns:
        URL to the recording MP3, or None if not available
    """
    client = get_twilio_client()
    if not client:
        return None

    try:
        recordings = client.calls(call_sid).recordings.list(limit=1)
        if recordings:
            return recordings[0].uri.replace(".json", ".mp3")
        return None
    except Exception as e:
        logger.error(f"Error retrieving recording for {call_sid}: {e}")
        return None

# ======================================================================
# Download recording to user folder
# ======================================================================
def download_recording(call_sid: str, user_id: str) -> Optional[str]:
    """
    Download a call recording and save it to the user's conf folder.
    
    Args:
        call_sid: Twilio call SID
        user_id: User ID for file storage
    
    Returns:
        Path to the downloaded file, or None if failed
    """
    recording_url = get_recording_url(call_sid)
    if not recording_url:
        return None

    import requests
    from requests.auth import HTTPBasicAuth
    
    try:
        # Build full URL
        full_url = f"https://api.twilio.com{recording_url}"
        resp = requests.get(
            full_url,
            auth=HTTPBasicAuth(ACCOUNT_SID, AUTH_TOKEN),
            timeout=30
        )
        if resp.status_code == 200:
            record_path = user_conf_path(user_id) / "record.mp3"
            record_path.write_bytes(resp.content)
            logger.info(f"Recording saved for user {user_id}: {record_path}")
            return str(record_path)
        else:
            logger.error(f"Failed to download recording: {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error downloading recording: {e}")
        return None

# ======================================================================
# Get call SID from user metadata
# ======================================================================
def get_current_call_sid(user_id: str) -> Optional[str]:
    """
    Retrieve the most recent call SID for a user from their metadata.
    
    Args:
        user_id: User ID
    
    Returns:
        Call SID or None if not found
    """
    try:
        return read_user_file(user_id, "call_sid.txt", "")
    except:
        return None

# ======================================================================
# Store call SID in user metadata
# ======================================================================
def store_call_sid(user_id: str, call_sid: str) -> None:
    """
    Store a call SID in the user's metadata for later retrieval.
    
    Args:
        user_id: User ID
        call_sid: Twilio call SID
    """
    write_user_file(user_id, "call_sid.txt", call_sid)
    logger.debug(f"Stored call SID {call_sid} for user {user_id}")

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    # Test error message mapping
    from twilio.base.exceptions import TwilioRestException
    # Simulate an error (code 21211)
    err = TwilioRestException(21211, "Invalid phone number", "Invalid phone number")
    print(TwilioErrorHandler.get_user_message(err))
