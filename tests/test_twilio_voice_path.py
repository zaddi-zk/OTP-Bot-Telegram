import pytest

from bot import app


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


def test_voice_webhook_returns_connect_stream_twili(client):
    response = client.post(
        "/twilio/voice",
        data={"CallSid": "CA123", "user_id": "u1", "chat_id": "123", "AnsweredBy": "human"},
    )

    assert response.status_code == 200
    assert response.content_type.startswith("application/xml")
    body = response.get_data(as_text=True)
    assert "<Response>" in body
    assert "<Connect>" in body
    assert "<Stream" in body
    assert "wss://" in body or "ws://" in body


def test_voice_and_twilio_voice_share_the_same_handler(client):
    response = client.post(
        "/voice",
        data={"CallSid": "CA123", "user_id": "u1", "chat_id": "123", "AnsweredBy": "human"},
    )

    assert response.status_code == 200
    assert response.content_type.startswith("application/xml")
    body = response.get_data(as_text=True)
    assert "<Connect>" in body
    assert "<Stream" in body
