"""Test script to simulate Twilio async AMD callback.

Usage:
    python scripts/test_amd_callback.py --url http://localhost:5000/amd_callback --sid CA1234567890 --answered_by machine_start

Sends a simple form-encoded POST similar to Twilio's callback.
"""

import argparse
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=False, default="http://localhost:5000/amd_callback")
    p.add_argument("--sid", required=False, default="CA_TESTSID123456")
    p.add_argument("--answered_by", required=False, default="machine_start")
    args = p.parse_args()

    data = {
        "CallSid": args.sid,
        "AnsweredBy": args.answered_by,
    }

    # AMD handling is disabled in this project; do not send test callbacks.
    print("AMD handling is disabled; test callback skipped.")


if __name__ == '__main__':
    main()
