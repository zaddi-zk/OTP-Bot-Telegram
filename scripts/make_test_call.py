#!/usr/bin/env python3
"""
Place a test outbound call through Vapi SIP -> Asterisk -> SpoofGlobal.

Usage:
  python scripts/make_test_call.py +1234567890 +15550123123 "Display Name" [user_id]

The caller ID (spoofed CLI) is mandatory and must be supplied by the operator.
The call is tracked and terminated using the Vapi call UUID only.
"""
import sys
import time
import logging
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config import VAPI_SIP_PHONE_NUMBER_ID, ASTERISK_CLI_DIR  # noqa: E402
from services import asterisk_service  # noqa: E402
from services import call_service  # noqa: E402
from services import vapi_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/make_test_call.py +TARGET_NUMBER +CALLER_ID [display_name] [user_id]")
        return 1

    to = sys.argv[1].strip()
    caller_id = sys.argv[2].strip()
    display_name = sys.argv[3].strip() if len(sys.argv) > 3 else "OTP Bot"
    user_id = sys.argv[4] if len(sys.argv) > 4 else "test_user"

    if not VAPI_SIP_PHONE_NUMBER_ID:
        logger.error("VAPI_SIP_PHONE_NUMBER_ID is not configured — create the Vapi SIP phone number first.")
        return 1

    logger.info("Target: %s  CallerID: %s  DisplayName: %s", to, caller_id, display_name)
    logger.info("CLI dir: %s", ASTERISK_CLI_DIR)
    asterisk_service.write_asterisk_cli_file(to, caller_id, display_name)

    call_id = vapi_service.create_call(
        customer_number=to,
        customer_name=display_name,
        phone_number_id=VAPI_SIP_PHONE_NUMBER_ID or None,
    )
    if not call_id:
        logger.error("Vapi create_call failed — no call UUID returned.")
        return 1

    logger.info("Call placed. Vapi call UUID: %s", call_id)

    # Poll status via Vapi REST API.
    for i in range(20):
        status = call_service.get_call_status(call_id)
        logger.info("[%d] status=%s", i, status)
        if status in ("completed", "failed", "ended", "no-answer", "busy", "canceled"):
            break
        time.sleep(3)

    logger.info("Final status: %s", call_service.get_call_status(call_id))

    # Terminate via Vapi end_call using the same UUID.
    ok = vapi_service.end_call(call_id)
    logger.info("end_call via Vapi: ok=%s uuid=%s", ok, call_id)
    asterisk_service.remove_asterisk_cli_file(to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
