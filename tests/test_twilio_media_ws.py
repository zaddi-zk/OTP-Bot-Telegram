import json

import bot
from fastapi.testclient import TestClient
from live_listen.server import app


def test_twilio_media_websocket_accepts_twilio_subprotocol(monkeypatch):
    monkeypatch.setattr(bot, "USE_WEBHOOK", False)
    monkeypatch.setattr(bot, "get_runtime_mode", lambda _: "lite")

    with TestClient(app) as client:
        with client.websocket_connect(
            "/twilio/media",
            subprotocols=["twilio.media.v1"],
        ) as websocket:
            assert websocket.accepted_subprotocol == "twilio.media.v1"
            websocket.send_text(json.dumps({
                "event": "start",
                "start": {
                    "callSid": "CA_TEST_SUBPROTO",
                    "streamSid": "SM_TEST",
                    "accountSid": "AC_TEST",
                    "from": "+15551234567",
                    "to": "+15557654321",
                    "direction": "inbound",
                },
            }))
            websocket.close()


def test_twilio_media_websocket_route_exists():
    routes = [route.path for route in app.router.routes if hasattr(route, "path")]
    assert "/twilio/media" in routes
    assert any(
        getattr(route, "path", None) == "/twilio/media" and route.__class__.__name__ == "APIWebSocketRoute"
        for route in app.router.routes
    )
