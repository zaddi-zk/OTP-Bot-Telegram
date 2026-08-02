import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bot
import services.vapi_service as vapi_service


def test_normal_call_does_not_consume_free_calls_when_it_cannot_start(monkeypatch):
    monkeypatch.setattr(bot, "run_callback_async", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(bot, "is_premium_user", lambda uid: False)

    decremented = []
    monkeypatch.setattr(bot, "decrement_free_call", lambda uid: decremented.append(uid) or -1)

    monkeypatch.setattr(bot, "USE_AI_FLOW", False)
    monkeypatch.setattr(bot, "ensure_user_path", lambda uid: None)
    monkeypatch.setattr(bot, "_compute_setup_hash", lambda uid: "hash")
    monkeypatch.setattr(bot, "_has_completed_call", lambda uid: False)
    monkeypatch.setattr(bot, "_write_last_setup_hash", lambda uid, value: None)
    monkeypatch.setattr(bot, "clear_user_call_setup", lambda uid: None)
    monkeypatch.setattr(bot, "register_call_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot, "store_call_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(vapi_service, "create_call", lambda **kwargs: "call-123")

    class DummyBot:
        def send_message(self, *args, **kwargs):
            return type("Msg", (), {"message_id": 1})()

    monkeypatch.setattr(bot, "bot", DummyBot())

    def fake_read_user_file(user_id, filename, default=""):
        values = {
            "phonenum.txt": "bad-phone",
            "Name.txt": "John",
            "Company Name.txt": "Bank",
            "From Name.txt": "Support",
            "Language.txt": "en",
            "Delivery.txt": "sms",
            "CodeLength.txt": "6",
            "Voice.txt": "voice-1",
            "VoiceName.txt": "Test Voice",
            "emotion.txt": "neutral",
            "Caller ID.txt": "",
        }
        return values.get(filename, default)

    monkeypatch.setattr(bot, "read_user_file", fake_read_user_file)

    bot.initiate_normal_call(123, "user-1", None)

    assert decremented == []


def test_normal_call_consumes_free_call_only_after_real_vapi_call(monkeypatch):
    monkeypatch.setattr(bot, "run_callback_async", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(bot, "is_premium_user", lambda uid: False)

    decremented = []
    monkeypatch.setattr(bot, "decrement_free_call", lambda uid: decremented.append(uid) or 1)

    monkeypatch.setattr(bot, "USE_AI_FLOW", True)
    monkeypatch.setattr(bot, "ensure_user_path", lambda uid: None)
    monkeypatch.setattr(bot, "_compute_setup_hash", lambda uid: "hash")
    monkeypatch.setattr(bot, "_has_completed_call", lambda uid: False)
    monkeypatch.setattr(bot, "_write_last_setup_hash", lambda uid, value: None)
    monkeypatch.setattr(bot, "clear_user_call_setup", lambda uid: None)
    monkeypatch.setattr(bot, "register_call_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot, "store_call_metadata", lambda *args, **kwargs: None)
    monkeypatch.setattr(vapi_service, "create_call", lambda **kwargs: "call-123")
    monkeypatch.setattr(vapi_service, "end_call", lambda call_id: True)

    class DummyBot:
        def send_message(self, *args, **kwargs):
            return type("Msg", (), {"message_id": 1})()

    monkeypatch.setattr(bot, "bot", DummyBot())

    def fake_read_user_file(user_id, filename, default=""):
        values = {
            "phonenum.txt": "+1234567890",
            "Name.txt": "John",
            "Company Name.txt": "Bank",
            "From Name.txt": "Support",
            "Language.txt": "en",
            "Delivery.txt": "sms",
            "CodeLength.txt": "6",
            "Voice.txt": "voice-1",
            "VoiceName.txt": "Test Voice",
            "emotion.txt": "neutral",
            "Caller ID.txt": "",
        }
        return values.get(filename, default)

    monkeypatch.setattr(bot, "read_user_file", fake_read_user_file)

    bot.initiate_normal_call(123, "user-2", None)

    assert decremented == ["user-2"]
