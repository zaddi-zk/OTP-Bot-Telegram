#!/usr/bin/env python3
"""Dispatch a live Twilio call via the service helper and wait for the SID.

Usage: python scripts/run_live_call.py
"""
import os
import sys
# Ensure repo root is on sys.path so imports from project work when running from scripts/
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import time
from config import TWILIO_PHONE_NUMBER, NGROK_URL
from services.twilio_service import make_call_and_store_async

user_id = "8366864444"
to = "+18336913224"
webhook = f"{NGROK_URL.rstrip('/')}/voice?user_id={user_id}&chat_id={user_id}"
async_cb = f"{NGROK_URL.rstrip('/')}/amd_callback?user_id={user_id}&chat_id={user_id}"

print("Dispatching call to:", to)
print("From number:", TWILIO_PHONE_NUMBER)
print("Webhook:", webhook)
print("AMD callback:", async_cb)

# AMD handling is disabled; dispatch the call without AMD params.
fut = make_call_and_store_async(
    user_id=user_id,
    to=to,
    from_number=TWILIO_PHONE_NUMBER,
    caller_id="",
    webhook_url=webhook,
    record=True,
    machine_detection=None,
    async_amd=False,
    async_amd_status_callback=async_cb,
)

if not fut:
    print("Failed to dispatch call (dispatch helper returned None). Check Twilio configuration.")
    sys.exit(1)

print("Dispatched, waiting up to 90s for call SID...")
try:
    sid = fut.result(timeout=90)
    print("Call SID:", sid)
    if sid:
        print("Call dispatched successfully.")
    else:
        print("Call creation returned no SID (failed). Check Twilio logs and credentials.")
except Exception as e:
    print("Error waiting for SID:", e)
    sys.exit(2)
