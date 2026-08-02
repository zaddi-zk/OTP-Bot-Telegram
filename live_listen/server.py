"""
live_listen.server

FastAPI server that mounts the Flask bot app and provides the Live Listen
streaming endpoints on a single public port:

- WebSocket for browser clients:      `/ws/live?call_id=...`
- WebSocket for Twilio Media Streams: `/twilio/media`
- Browser UI:                         `/live?call_id=...`
- Bootstrap endpoint:                 `/conversation/start`
- Health checks:                      `/health`, `/`

The Flask bot app (webhooks, Telegram, status/recording callbacks) is mounted
at the root via a WSGI middleware, so all existing bot routes keep working on
the same port (e.g. 5000 behind ngrok). The media stream for live listen is
forked by an extra unidirectional ``<Start><Stream>`` injected into the Vapi
bridge TwiML (see services/vapi_service.py).
"""
import asyncio
import base64
import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from live_listen.manager import manager

logger = logging.getLogger(__name__)

app = FastAPI(title="Live Listen + Bot Bridge", docs_url=None, redoc_url=None)


# ======================================================================
# µ-law (8-bit, 8000 Hz) -> linear PCM16 conversion
# Twilio Media Streams deliver audio as `audio/x-mulaw`; the browser UI
# (live.html) renders raw PCM16 (16-bit little-endian, 8000 Hz mono), so we
# decode here before relaying to clients.
# ======================================================================
_ULAW_BIAS = 0x84
_ULAW_MAX = 32635


def _ulaw2lin(ulaw_byte: int) -> int:
    ulaw_byte = ~ulaw_byte & 0xFF
    sign = ulaw_byte & 0x80
    exponent = (ulaw_byte >> 4) & 0x07
    mantissa = ulaw_byte & 0x0F
    sample = ((mantissa << 3) + _ULAW_BIAS) << exponent
    sample -= _ULAW_BIAS
    sample = max(-_ULAW_MAX, min(_ULAW_MAX, sample))
    return -sample if sign else sample


def ulaw_to_pcm16(payload: bytes) -> bytes:
    """Convert a block of µ-law audio bytes to 16-bit little-endian PCM."""
    import struct
    out = bytearray(len(payload) * 2)
    for i, b in enumerate(payload):
        s = _ulaw2lin(b)
        out[i * 2] = s & 0xFF
        out[i * 2 + 1] = (s >> 8) & 0xFF
    return bytes(out)


# ======================================================================
# Health
# ======================================================================
@app.get("/")
async def root():
    return {"status": "ok", "service": "live-listen-bridge"}


@app.get("/health")
async def health():
    return {"status": "healthy", "sessions": len(manager.sessions)}


# ======================================================================
# Browser Live Listen UI
# ======================================================================
@app.get("/live")
async def live_ui(request: Request):
    html_path = os.path.join(os.path.dirname(__file__), "static", "live.html")
    if not os.path.exists(html_path):
        return HTMLResponse("<h1>Live UI not found</h1>", status_code=404)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ======================================================================
# Browser client WebSocket: /ws/live?call_id=...
# ======================================================================
@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket, call_id: Optional[str] = None):
    if not call_id:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await manager.add_client(call_id, websocket)
    try:
        s = await manager.ensure_session(call_id)
        await websocket.send_text(json.dumps({"type": "session", "data": s.to_dict()}))
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        await manager.remove_client(call_id, websocket)
    except Exception:
        await manager.remove_client(call_id, websocket)


# ======================================================================
# Bootstrap endpoint used by bot notifications
# ======================================================================
@app.post("/conversation/start")
async def conversation_start(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}

    call_sid = body.get("call_sid") or body.get("CallSid")
    chat_id = body.get("chat_id")
    if chat_id is not None:
        try:
            chat_id = int(chat_id)
        except (ValueError, TypeError):
            chat_id = None
    if not call_sid:
        return JSONResponse({"ok": False, "error": "call_sid required"}, status_code=400)

    await manager.ensure_session(call_sid, call_sid=call_sid, chat_id=chat_id)
    await manager.set_state(call_sid, "ringing")
    logger.info("[CONVERSATION_START] live listen session for call_sid=%s chat_id=%s", call_sid, chat_id)
    return {"ok": True}


# ======================================================================
# Twilio Media Stream WebSocket: /twilio/media
#
# This endpoint receives the call audio that Twilio forks via the
# unidirectional `<Start><Stream>` injected into the bridge TwiML. It relays
# the decoded audio to any browser client connected on /ws/live.
# ======================================================================
@app.websocket("/twilio/media")
async def twilio_media(ws: WebSocket):
    subprotocol = None
    try:
        subprotocol_header = ws.headers.get("sec-websocket-protocol")
        if subprotocol_header:
            subprotocols = [t.strip() for t in subprotocol_header.split(",") if t.strip()]
            if subprotocols:
                subprotocol = subprotocols[0]
                await ws.accept(subprotocol=subprotocol)
            else:
                await ws.accept()
        else:
            await ws.accept()
    except Exception as e:
        logger.error("[TWILIO_MEDIA_ACCEPT_ERROR] %s", e)
        return

    logger.info("[TWILIO_MEDIA_CONNECT] client=%s subprotocol=%s", ws.client, subprotocol)
    call_sid = None
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception as e:
                logger.error("[TWILIO_MEDIA_JSON_ERROR] %s", e)
                continue

            event = data.get("event")

            if event == "start":
                start = data.get("start", {})
                call_sid = start.get("callSid")
                logger.info("[TWILIO_MEDIA_START] call_sid=%s stream_sid=%s", call_sid, start.get("streamSid"))
                await manager.ensure_session(call_sid or "unknown", call_sid=call_sid)
                if call_sid:
                    await manager.set_state(call_sid, "in-progress")

            elif event == "media":
                media = data.get("media", {})
                payload_b64 = media.get("payload")
                if payload_b64 and call_sid:
                    try:
                        audio_bytes = base64.b64decode(payload_b64)
                        pcm16 = ulaw_to_pcm16(audio_bytes)
                        await manager.broadcast_media(call_sid, pcm16, sequence=media.get("sequence"))
                    except Exception as e:
                        logger.error("[TWILIO_MEDIA_RELAY_ERROR] %s", e)

            elif event == "stop":
                logger.info("[TWILIO_MEDIA_STOP] call_sid=%s", call_sid)
                if call_sid:
                    await manager.set_state(call_sid, "completed")
                break
    except WebSocketDisconnect:
        logger.info("[TWILIO_MEDIA_DISCONNECT] call_sid=%s", call_sid)
    except Exception as e:
        logger.error("[TWILIO_MEDIA_ERROR] call_sid=%s error=%s", call_sid, e)
    finally:
        if call_sid:
            await manager.set_state(call_sid, "completed")


# ======================================================================
# Mount the Flask bot app so all existing routes run on the same port.
# ======================================================================
def build_app(flask_app) -> FastAPI:
    """Return the FastAPI app with the given Flask app mounted at the root.

    The same FastAPI app instance is reused, so calling this more than once
    (e.g. after module reload) is safe: it only mounts if not already mounted.
    """
    global app
    mounted = any(
        getattr(route, "path", None) == "/"
        for route in app.routes
        if route.__class__.__name__ == "Mount"
    )
    if not mounted:
        app.mount("", WSGIMiddleware(flask_app))
        logger.info("[FLASK_MOUNT] Flask bot app mounted to FastAPI")
    return app

