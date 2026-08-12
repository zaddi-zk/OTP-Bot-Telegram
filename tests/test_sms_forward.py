"""
tests/test_sms_forward.py — network-free tests for the /sms inbound forwarder.

The route reads Twilio's Messaging webhook form params and forwards the text to
every admin ID via safe_bot_send_message (monkeypatched here).
"""

import pytest

import bot as bot_module


@pytest.fixture
def client():
    bot_module.app.config.update(TESTING=True)
    with bot_module.app.test_client() as client:
        yield client


@pytest.fixture
def admin_ids(monkeypatch):
    ids = [111111111, 222222222, 333333333]
    monkeypatch.setattr(bot_module, "OWNER_ID", ids[0])
    monkeypatch.setattr(bot_module, "ADMIN_ID", ids[1])
    monkeypatch.setattr(bot_module, "DEVELOPER_IDS", [ids[2]])
    return ids


@pytest.fixture
def sent_messages(monkeypatch):
    sent = []

    def fake_send(chat_id, text, *args, **kwargs):
        sent.append((chat_id, text))

    monkeypatch.setattr(bot_module, "safe_bot_send_message", fake_send)
    return sent


def test_sms_forward_sends_to_all_admins(client, admin_ids, sent_messages):
    response = client.post(
        "/sms",
        data={"From": "+15551234567", "To": "+15074012012", "Body": "Your code is 123456"},
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "OK"
    assert sorted(chat_id for chat_id, _ in sent_messages) == sorted(admin_ids)
    text = sent_messages[0][1]
    assert "+15551234567" in text
    assert "Your code is 123456" in text


def test_sms_forward_appends_media(client, admin_ids, sent_messages):
    response = client.post(
        "/sms",
        data={
            "From": "+15551112222",
            "To": "+15074012012",
            "Body": "photo",
            "NumMedia": "1",
            "MediaUrl0": "https://api.twilio.com/2010-04-01/media/ME123",
        },
    )

    assert response.status_code == 200
    text = sent_messages[0][1]
    assert "ME123" in text


def test_sms_forward_handles_missing_fields(client, admin_ids, sent_messages):
    response = client.post("/sms", data={})

    assert response.status_code == 200
    assert len(sent_messages) == len(admin_ids)
