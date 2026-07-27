import importlib
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ai.session import CallSession
import ai.llm as llm_module


def test_twilio_status_notifies_telegram_when_human_answers(monkeypatch):
    bot_module = importlib.import_module("bot")
    sent_messages = []

    def fake_send_message(chat_id, text, **kwargs):
        sent_messages.append((chat_id, text))

    monkeypatch.setattr(bot_module.bot, "send_message", fake_send_message)
    monkeypatch.setattr(bot_module, "validate_twilio_request", lambda: True)
    monkeypatch.setattr(bot_module, "update_call_status_message", lambda *args, **kwargs: False)

    client = bot_module.app.test_client()
    response = client.post(
        "/twilio/status",
        data={
            "CallSid": "CA123",
            "CallStatus": "completed",
            "AnsweredBy": "human",
            "chat_id": "987654",
            "user_id": "u1",
        },
    )

    assert response.status_code == 200
    assert any("human answered the call" in text.lower() for _, text in sent_messages)


def test_amd_hold_routes_human_calls_to_ai_start():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "human"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ai_start" in body


def test_amd_hold_hangs_up_when_machine_detected():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "machine_start"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Hangup" in body or "Goodbye" in body


def test_amd_hold_routes_unknown_to_acknowledgment():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "unknown"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/handle_acknowledgment" in body


def test_handle_acknowledgment_redirects_directly_to_ai_flow():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/handle_acknowledgment",
        data={"user_id": "u1", "chat_id": "123", "CallSid": "CA999"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ai_start" in body
    assert "Hello? Can you hear me" not in body
    assert "Press 1" not in body


def test_handle_greeting_redirects_directly_to_ai_flow():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/handle_greeting",
        data={"user_id": "u1", "chat_id": "123", "CallSid": "CA998"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ai_start" in body
    assert "Please say yes" not in body


def test_twilio_status_uses_session_chat_id(monkeypatch):
    bot_module = importlib.import_module("bot")
    sent_messages = []

    def fake_send_message(chat_id, text, **kwargs):
        sent_messages.append((chat_id, text))

    monkeypatch.setattr(bot_module.bot, "send_message", fake_send_message)
    monkeypatch.setattr(bot_module, "validate_twilio_request", lambda: True)
    monkeypatch.setattr(bot_module, "update_call_status_message", lambda *args, **kwargs: False)

    bot_module.register_call_session("CA456", user_id="u1", chat_id=777777)

    client = bot_module.app.test_client()
    response = client.post(
        "/twilio/status",
        data={
            "CallSid": "CA456",
            "CallStatus": "completed",
            "AnsweredBy": "human",
            "user_id": "u1",
        },
    )

    assert response.status_code == 200
    assert any(chat_id == 777777 for chat_id, _ in sent_messages)


def test_handle_acknowledgment_hangs_up_for_voicemail_speech():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/handle_acknowledgment",
        data={
            "user_id": "u1",
            "chat_id": "123",
            "CallSid": "CA789",
            "SpeechResult": "Calling gpen. This call is being recorded.",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Hangup" in body or "Goodbye" in body


def test_get_call_code_length_prefers_code_length_file(monkeypatch):
    bot_module = importlib.import_module("bot")

    def fake_read_user_file(user_id, file_name, default=""):
        if file_name == "CodeLength.txt":
            return "8"
        if file_name == "Digits.txt":
            return "6"
        return default

    monkeypatch.setattr(bot_module, "read_user_file", fake_read_user_file)

    assert bot_module.get_call_code_length("CA888", "u1") == 8


def test_handle_acknowledgment_redirect_contains_code_length():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/handle_acknowledgment",
        data={
            "user_id": "u1",
            "chat_id": "123",
            "CallSid": "CA555",
            "Digits": "1",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "code_length=" in body


def test_normal_call_human_path_reaches_otp_capture_and_acceptance_flow():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    amd_response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "human", "CallSid": "CA_NORMAL_1"},
    )
    assert amd_response.status_code == 200
    amd_body = amd_response.get_data(as_text=True)
    assert "/ai_start" in amd_body

    ack_response = client.post(
        "/handle_acknowledgment",
        data={"user_id": "u1", "chat_id": "123", "CallSid": "CA_NORMAL_1", "Digits": "1"},
    )
    assert ack_response.status_code == 200
    ack_body = ack_response.get_data(as_text=True)
    assert "/ai_start" in ack_body
    assert "code_length=" in ack_body

    otp_response = client.post(
        "/capture_otp",
        data={"user_id": "u1", "chat_id": "123", "CallSid": "CA_NORMAL_1", "stage": "otp", "Digits": "123456"},
    )
    assert otp_response.status_code == 200
    otp_body = otp_response.get_data(as_text=True)
    assert "OTP Captured" in otp_body or "Please wait" in otp_body or "pause" in otp_body.lower()


def test_fast_mode_uses_same_normal_call_human_path():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    amd_response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "human", "CallSid": "CA_FAST_1"},
    )
    assert amd_response.status_code == 200
    assert "/ai_start" in amd_response.get_data(as_text=True)

    ack_response = client.post(
        "/handle_acknowledgment",
        data={"user_id": "u1", "chat_id": "123", "CallSid": "CA_FAST_1", "Digits": "1"},
    )
    assert ack_response.status_code == 200
    assert "code_length=" in ack_response.get_data(as_text=True)


def test_capture_otp_uses_generic_prompts_and_preserves_code_length(monkeypatch):
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    monkeypatch.setattr(bot_module, "generate_call_audio", lambda **kwargs: None)

    response = client.post(
        "/capture_otp",
        data={
            "user_id": "u1",
            "chat_id": "123",
            "CallSid": "CA_PROMPT_1",
            "stage": "confirm1",
            "after_gather": "0",
            "code_length": "6",
        },
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True).lower()
    assert "please press 1" in body
    assert "hello. this is" not in body
    assert "one-time passcode" not in body
    assert "code_length=6" in body


def test_call_groq_retries_with_fallback_model(monkeypatch):
    import config as config_module

    attempted_models = []

    class FakeResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    class FakeSession:
        def post(self, url, json, timeout, headers):
            attempted_models.append(json["model"])
            if json["model"] == "primary-model":
                return FakeResponse(429, text="rate limited")
            return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm_module, "get_groq_session", lambda: FakeSession())
    monkeypatch.setattr(config_module, "GROQ_API_KEY", "test_key_12345")
    monkeypatch.setattr(config_module, "GROQ_MODEL", "primary-model")
    monkeypatch.setattr(config_module, "GROQ_FALLBACK_MODEL", "fallback-model")

    result = llm_module._call_groq([{"role": "user", "content": "hi"}], max_retries=1)

    assert result == "ok"
    assert attempted_models == ["primary-model", "fallback-model"]


def test_get_system_prompt_uses_builtin_fallback_when_env_missing(monkeypatch):
    import config as config_module

    monkeypatch.setattr(config_module, "SYSTEM_PROMPT", None)

    prompt = config_module.get_system_prompt()

    assert isinstance(prompt, str)
    assert len(prompt) > 80
    assert "verification" in prompt.lower() or "customer" in prompt.lower()


def test_chat_with_ai_uses_single_canonical_system_prompt(monkeypatch):
    import config as config_module

    captured = {}

    def fake_call_groq(messages, max_retries=2, call_sid=None):
        captured["messages"] = messages
        return "ok"

    monkeypatch.setattr(llm_module, "_call_groq", fake_call_groq)
    monkeypatch.setattr(config_module, "SYSTEM_PROMPT", "CANONICAL_PROMPT")
    monkeypatch.setattr(config_module, "GROQ_API_KEY", "test_key_12345")

    session = CallSession("CA_PROMPT_OVERRIDE")
    result = llm_module.generate_response("hello", "", system_prompt="SHOULD_BE_IGNORED")

    assert result == "ok"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][0]["content"].startswith("CANONICAL_PROMPT")


def test_fast_mode_writes_normal_call_setup_without_custom_script(monkeypatch):
    bot_module = importlib.import_module("bot")
    from core.files import read_user_file, user_conf_path

    user_id = "123456789"
    conf_dir = user_conf_path(user_id)
    for name in [
        "Name.txt",
        "Company Name.txt",
        "phonenum.txt",
        "Caller ID.txt",
        "From Name.txt",
        "Language.txt",
        "Delivery.txt",
        "Digits.txt",
        "call_mode_label.txt",
        "custom_script.txt",
    ]:
        path = conf_dir / name
        if path.exists():
            path.unlink()

    monkeypatch.setattr(bot_module, "is_premium_user", lambda uid: True)
    sent_messages = []
    monkeypatch.setattr(bot_module.bot, "send_message", lambda chat_id, text, **kwargs: sent_messages.append((chat_id, text)))

    bot_module.set_user_state(user_id, "fast_mode_awaiting")
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123456789),
        chat=SimpleNamespace(id=12345),
        text="Alice, Acme Bank, +15551234567, +15557654321, Support Team, en, sms, 6",
    )

    bot_module.handle_stateful_text(message)

    assert read_user_file(user_id, "Name.txt", "") == "Alice"
    assert read_user_file(user_id, "Company Name.txt", "") == "Acme Bank"
    assert read_user_file(user_id, "phonenum.txt", "") == "+15551234567"
    assert read_user_file(user_id, "Caller ID.txt", "") == "+15557654321"
    assert read_user_file(user_id, "From Name.txt", "") == "Support Team"
    assert read_user_file(user_id, "Language.txt", "") == "en"
    assert read_user_file(user_id, "Delivery.txt", "") == "sms"
    assert read_user_file(user_id, "Digits.txt", "") == "6"
    assert read_user_file(user_id, "CodeLength.txt", "") == "6"
    assert read_user_file(user_id, "call_mode_label.txt", "") == "Fast Mode"
    assert not (conf_dir / "custom_script.txt").exists()
    assert bot_module.get_user_state(user_id) == "normal_call_step_9_voice"


def test_manual_calls_use_custom_script_as_system_prompt(monkeypatch):
    import config as config_module

    captured = {}

    def fake_call_groq(messages, max_retries=2, call_sid=None):
        captured["messages"] = messages
        return "ok"

    monkeypatch.setattr(llm_module, "_call_groq", fake_call_groq)
    monkeypatch.setattr(config_module, "SYSTEM_PROMPT", "CANONICAL_PROMPT")
    monkeypatch.setattr(config_module, "GROQ_API_KEY", "test_key_12345")

    session = CallSession("CA_PROMPT_CUSTOM")
    session.call_type = "manual"
    session.custom_script = "CUSTOM_SCRIPT_INSTRUCTIONS"

    result = llm_module.generate_response("hello", "", session=session)

    assert result == "ok"
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][0]["content"].startswith("CUSTOM_SCRIPT_INSTRUCTIONS")
    assert "CANONICAL_PROMPT" not in captured["messages"][0]["content"]
