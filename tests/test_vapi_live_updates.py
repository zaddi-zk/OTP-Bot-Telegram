import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_vapi_webhook_sends_live_updates(monkeypatch):
    import handlers.vapi_webhooks as vapi_webhooks

    class FakeRequest:
        def __init__(self, payload):
            self._payload = payload

        def get_json(self, force=True, silent=True):
            return self._payload

    sent = []

    def fake_send(chat_id, text, **kwargs):
        sent.append((chat_id, text, kwargs))

    monkeypatch.setattr(vapi_webhooks, "_send_telegram", fake_send)

    payload = {
        "type": "call.answered",
        "call": {"id": "call_123", "twilioCallSid": "CA123"},
        "metadata": {"chat_id": "42"},
    }
    response = vapi_webhooks.handle_vapi_webhook(FakeRequest(payload))
    assert response.status_code == 200
    # Twilio already reports call status and recordings; the Vapi "Call is
    # live" notice is a second confirmation that the AI session is running.
    assert any("Call is live" in text for _, text, _ in sent)

    payload = {
        "type": "transcript",
        "message": {"role": "customer", "transcript": "My code is 482931"},
        "call": {"id": "call_123", "twilioCallSid": "CA123"},
        "metadata": {"chat_id": "42", "code_length": 6},
    }
    response = vapi_webhooks.handle_vapi_webhook(FakeRequest(payload))
    assert response.status_code == 200
    assert any("OTP" in text and "482931" in text for _, text, _ in sent)


def test_vapi_create_call_does_not_send_webhook_url(monkeypatch):
    import services.vapi_service as vapi_service

    class FakeResponse:
        def __init__(self):
            self.status_code = 201
            self._json = {"id": "call_123"}

        def json(self):
            return self._json

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=15):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(vapi_service.requests, "post", fake_post)
    monkeypatch.setattr(vapi_service, "VAPI_API_KEY", "test")
    monkeypatch.setattr(vapi_service, "VAPI_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(vapi_service, "VAPI_PHONE_NUMBER_ID", "phone")

    vapi_service.create_call("+1234567890", "Jane")

    assert "webhookUrl" not in captured["json"]


def test_bypass_prefers_inline_phone_number_ref(monkeypatch):
    import services.vapi_service as vapi_service

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=15):
        captured["json"] = json
        return _fake_bypass_response()

    monkeypatch.setattr(vapi_service.requests, "post", fake_post)
    monkeypatch.setattr(vapi_service, "VAPI_API_KEY", "test")
    monkeypatch.setattr(vapi_service, "VAPI_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(vapi_service, "VAPI_PHONE_NUMBER_ID", "phone-123")

    ref = {
        "twilioPhoneNumber": "+19852848980",
        "twilioAccountSid": "ACxxxx",
        "twilioAuthToken": "tok",
    }
    result = vapi_service.create_call_bypass(
        "+15550001111", "Jane", phone_number_ref=ref
    )

    assert result is not None
    assert captured["json"]["phoneNumber"] == ref
    assert "phoneNumberId" not in captured["json"]


def test_bypass_falls_back_to_phone_number_id_when_inline_rejected(monkeypatch):
    import services.vapi_service as vapi_service

    calls = []

    def fake_post(url, headers=None, json=None, timeout=15):
        calls.append(dict(json))
        if len(calls) == 1:
            return _fake_bypass_response(status=400, text="phoneNumber rejected")
        return _fake_bypass_response()

    monkeypatch.setattr(vapi_service.requests, "post", fake_post)
    monkeypatch.setattr(vapi_service, "VAPI_API_KEY", "test")
    monkeypatch.setattr(vapi_service, "VAPI_ASSISTANT_ID", "assistant")
    monkeypatch.setattr(vapi_service, "VAPI_PHONE_NUMBER_ID", "phone-123")

    ref = {
        "twilioPhoneNumber": "+19852848980",
        "twilioAccountSid": "ACxxxx",
        "twilioAuthToken": "tok",
    }
    result = vapi_service.create_call_bypass(
        "+15550001111", "Jane", phone_number_ref=ref
    )

    assert result is not None
    assert len(calls) == 2
    assert "phoneNumber" in calls[0]
    assert calls[1]["phoneNumberId"] == "phone-123"
    assert "phoneNumber" not in calls[1]


def _fake_bypass_response(status=201, text="ok"):
    class _Resp:
        def __init__(self):
            self.status_code = status
            self.text = text

        def json(self):
            if self.status_code == 201:
                return {
                    "id": "vapi_call_123",
                    "phoneCallProviderDetails": {
                        "twiml": "<Response><Connect><Stream url='wss://x'/></Connect></Response>"
                    },
                }
            return {"message": self.text, "statusCode": self.status_code}

    return _Resp()
