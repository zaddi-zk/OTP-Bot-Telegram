import sys
import os
import time

# Ensure repo root on path
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)

from bot import app, bot, call_sessions


def test_e2e_normal_call_human_flow(monkeypatch):
    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    client = app.test_client()
    call_sid = "CA_E2E_1"
    user_id = "testuser"
    chat_id = "99999"

    # 1) Twilio voice webhook (entry) -> should redirect to /amd_hold
    resp = client.post("/voice", data={"CallSid": call_sid, "user_id": user_id, "chat_id": chat_id})
    assert resp.status_code == 200

    # 2) Twilio async AMD callback: human answered
    resp = client.post("/amd_callback", data={"CallSid": call_sid, "AnsweredBy": "human", "chat_id": chat_id, "user_id": user_id})
    assert resp.status_code == 200
    assert any("human" in (t[1] or "").lower() for t in sent)

    # 3) amd_hold (Twilio follows redirect) -> should continue (not hangup)
    resp = client.post("/amd_hold", data={"CallSid": call_sid, "user_id": user_id})
    assert resp.status_code == 200

    # 4) handle_greeting: with session answered_by=human, emulate DTMF '1'
    resp = client.post("/handle_greeting", data={"CallSid": call_sid, "user_id": user_id, "Digits": "1"})
    assert resp.status_code == 200
    # Should redirect into ai_start
    assert b"ai_start" in resp.data
    assert any("human pressed 1" in (t[1] or "").lower() for t in sent)

    # 5) Simulate AI flow capturing OTP via live_capture_otp endpoint
    otp = "123456"
    resp = client.post("/live_capture_otp", data={"chat_id": chat_id, "call_sid": call_sid, "digits": otp})
    assert resp.status_code == 200
    # OTP message should have been sent
    assert any("otp captured" in (t[1] or "").lower() or (otp in (t[1] or "")) for t in sent)
