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


def test_amd_hold_routes_human_calls_to_greeting():
    bot_module = importlib.import_module("bot")
    client = bot_module.app.test_client()

    response = client.post(
        "/amd_hold",
        data={"user_id": "u1", "chat_id": "123", "AnsweredBy": "human"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/handle_greeting" in body


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
