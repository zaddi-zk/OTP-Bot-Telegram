import pytest
import sys
import os

# Ensure repository root is on PYTHONPATH for imports like `bot`
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root not in sys.path:
    sys.path.insert(0, root)

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


def test_amd_hold_prefers_session(monkeypatch):
    # Ensure /amd_hold uses canonical session answered_by when present
    from bot import call_sessions

    sent = []

    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    call_sessions["CA_HOLD_1"] = {"chat_id": 55555, "user_id": "u1", "answered_by": "machine_end_other"}
    client = app.test_client()
    data = {"CallSid": "CA_HOLD_1"}
    resp = client.post("/amd_hold", data=data)
    assert resp.status_code == 200
    # Expect hangup TwiML contains Goodbye
    assert b"Goodbye" in resp.data
    assert any("machine" in t[1].lower() for t in sent)


def test_handle_greeting_prefers_session(monkeypatch):
    from bot import call_sessions

    sent = []
    def fake_send_message(chat_id, text, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot, "send_message", fake_send_message)

    call_sessions["CA_GREET_1"] = {"chat_id": 66666, "user_id": "u2", "answered_by": "human"}
    client = app.test_client()
    data = {"CallSid": "CA_GREET_1", "Digits": "1"}
    resp = client.post("/handle_greeting", data=data)
    assert resp.status_code == 200
    # Expect redirect to ai_start in TwiML
    assert b"ai_start" in resp.data
    assert any("human pressed 1" in t[1].lower() for t in sent)
