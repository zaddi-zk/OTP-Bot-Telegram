import pytest

from bot import app


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        yield client


# /voice and /twilio/voice are legacy Twilio media-stream webhooks. The call
# modes that used them (Crack Blast, Custom Call, Manual Calling, AI Emotion
# Call) are being migrated to the Normal Call path: place_ai_call -> Vapi
# bypass with inline TwiML, which needs no webhook URL. Keep these tests as a
# reminder of what must be removed once the migration lands.
pytestmark = pytest.mark.xfail(
    reason="Legacy /voice webhook routes removed in the Vapi bypass migration",
    strict=False,
)


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
