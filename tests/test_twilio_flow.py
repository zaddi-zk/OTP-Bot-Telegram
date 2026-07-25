import importlib


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


def test_capture_otp_uses_generic_prompts_and_preserves_code_length():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

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
