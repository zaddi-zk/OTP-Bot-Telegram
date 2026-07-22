#!/usr/bin/env python3
"""
Place a test Twilio call using credentials from config.
Usage:
  python scripts/make_test_call.py +1234567890 [user_id]
"""
import sys
import time
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import ACCOUNT_SID, AUTH_TOKEN, TWILIO_PHONE_NUMBER, NGROK_URL
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/make_test_call.py +1234567890 [user_id]")
        return 1

    to = sys.argv[1].strip()
    user_id = sys.argv[2] if len(sys.argv) > 2 else "test_user"
    url = f"{NGROK_URL}/ai_start?user_id={user_id}&call_type=normal&mode_label=Normal%20Call"
    
    logger.info(f"From: {TWILIO_PHONE_NUMBER} To: {to}")
    logger.info(f"Webhook URL: {url}")

    if not ACCOUNT_SID or "YOUR_" in ACCOUNT_SID:
        logger.error("Twilio credentials not configured properly")
        return 1

    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    try:
        # AMD disabled: do not pass machine_detection parameters
        call = client.calls.create(
            to=to,
            from_=TWILIO_PHONE_NUMBER,
            url=url,
            method="POST",
            record=True,
        )
        logger.info(f"Call placed. SID: {call.sid}")
    except TwilioRestException as e:
        logger.error(f"Twilio error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1

    # Poll status
    sid = call.sid
    for i in range(20):
        try:
            c = client.calls(sid).fetch()
            logger.info(f"[{i}] status={c.status}")
            if c.status in ("completed", "failed", "busy", "no-answer", "canceled"):
                break
        except Exception as e:
            logger.error(f"Error fetching status: {e}")
            break
        time.sleep(3)

    logger.info(f"Final status: {c.status}")
    return 0

if __name__ == "__main__":
    sys.exit(main())