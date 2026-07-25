import pytest
import sys
import os

# Ensure repository root is on PYTHONPATH for imports like `bot`
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)

import bot as bot_module
from bot import app, bot


def test_machine_detection_sends_message(monkeypatch):
    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    # Replace bot.send_message with our fake
    monkeypatch.setattr(bot, "send_message", fake_send_message)

    client = app.test_client()
    data = {
        "CallSid": "CA_TEST_MACHINE",
        "CallStatus": "completed",
        "AnsweredBy": "machine_end_other",
        "chat_id": "12345",
    }
    resp = client.post("/twilio/status", data=data)
    assert resp.status_code == 200
    # Ensure we attempted to notify the Telegram chat about a machine answer
    assert any("A machine answered the call." in item[1] for item in sent)


def test_human_detection_sends_message(monkeypatch):
    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    client = app.test_client()
    data = {
        "CallSid": "CA_TEST_HUMAN",
        "CallStatus": "completed",
        "AnsweredBy": "human",
        "chat_id": "54321",
    }
    resp = client.post("/twilio/status", data=data)
    assert resp.status_code == 200
    # Ensure we attempted to notify the Telegram chat about a human answer
    assert any("A human answered the call." in item[1] for item in sent)


def test_amd_callback_notifies(monkeypatch):
    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    client = app.test_client()
    data = {
        "CallSid": "CA_AMD_1",
        "AnsweredBy": "machine_end_other",
        "chat_id": "77777",
        "user_id": "testuser",
    }
    resp = client.post("/amd_callback", data=data)
    assert resp.status_code == 200
    assert any("machine or voicemail" in item[1].lower() for item in sent)


def test_amd_callback_human(monkeypatch):
    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    client = app.test_client()
    data = {
        "CallSid": "CA_AMD_2",
        "AnsweredBy": "human",
        "chat_id": "88888",
        "user_id": "testuser",
    }
    resp = client.post("/amd_callback", data=data)
    assert resp.status_code == 200
    assert any("a human answered" in item[1].lower() for item in sent)


def test_amd_callback_unknown_alerts_owner(monkeypatch):
    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(bot, "send_message", fake_send_message)
    monkeypatch.setattr(bot_module, "OWNER_ID", 99999)

    client = app.test_client()
    data = {
        "CallSid": "CA_AMD_3",
        "AnsweredBy": "unknown",
        "chat_id": "77777",
        "user_id": "testuser",
    }
    resp = client.post("/amd_callback", data=data)
    assert resp.status_code == 200
    assert any("amd coverage gap" in item[1].lower() for item in sent)
    assert any(item[0] == 99999 for item in sent)


def test_amd_hold_prefers_session(monkeypatch):
    # Ensure /amd_hold uses canonical session answered_by when present
    from bot import get_call_session, register_call_session

    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    register_call_session("CA_HOLD_1", user_id="u1", chat_id=55555)
    session = get_call_session("CA_HOLD_1")
    session["answered_by"] = "machine_end_other"
    client = app.test_client()
    data = {"CallSid": "CA_HOLD_1"}
    resp = client.post("/amd_hold", data=data)
    assert resp.status_code == 200
    # Expect hangup TwiML contains Goodbye
    assert b"Goodbye" in resp.data
    assert any("machine" in t[1].lower() for t in sent)


def test_handle_greeting_prefers_session(monkeypatch):
    from bot import get_call_session, register_call_session

    sent = []
    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    register_call_session("CA_GREET_1", user_id="u2", chat_id=66666)
    session = get_call_session("CA_GREET_1")
    session["answered_by"] = "human"
    client = app.test_client()
    data = {"CallSid": "CA_GREET_1", "Digits": "1"}
    resp = client.post("/handle_greeting", data=data)
    assert resp.status_code == 200
    # Expect legacy greeting endpoint to route into AI flow
    assert b"ai_start" in resp.data
    assert any("human pressed 1" in t[1].lower() for t in sent)


def test_amd_hold_routes_unknown_to_secondary_verification():
    client = app.test_client()
    response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "unknown", "CallSid": "CA_UNKNOWN_1"},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/handle_acknowledgment" in body


def test_amd_confidence_scores_human_speech_highly():
    from bot import evaluate_amd_confidence, get_call_session, register_call_session

    register_call_session("CA_CONF_1", user_id="u3", chat_id=44444)
    session = get_call_session("CA_CONF_1")
    confidence = evaluate_amd_confidence(session, answered_by="unknown", speech_result="Hello yes I can hear you")
    assert confidence["human_confidence"] >= confidence["unknown_confidence"]
    assert confidence["human_confidence"] > 0.5


def test_make_spoofed_call_sends_extended_amd_parameters(monkeypatch):
    import bot

    captured = {}

    def fake_make_call_and_store_async(**kwargs):
        captured.update(kwargs)
        return "CA_EXT"

    monkeypatch.setattr(bot, "is_twilio_configured", lambda: True)
    monkeypatch.setattr(bot, "make_call_and_store_async", fake_make_call_and_store_async)

    sid = bot.make_spoofed_call(
        to="+15551234567",
        from_number="+15557654321",
        caller_id="+15557654321",
        webhook_url="https://example.test/amd_hold",
        user_id="u4",
        chat_id=123,
        machine_detection=True,
    )

    assert sid == "CA_EXT"
    assert captured["machine_detection"] == "Enable"
    assert captured["async_amd"] is True
    assert captured["machine_detection_timeout"] == 8
    assert captured["machine_detection_speech_threshold"] == 1800
