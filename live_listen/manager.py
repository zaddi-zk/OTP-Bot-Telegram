"""
live_listen.manager
Session manager for live-call streaming and websocket broadcasting.

Core responsibilities:
- Track active call sessions (call_id / call_sid)
- Store connected websocket clients for each session
- Relay media frames from Twilio Media Streams to connected clients
- Manage state transitions and cleanup timers
"""
import asyncio
import json
import logging
import time
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


class LiveListenSession:
    def __init__(self, call_id: str, call_sid: str = None, chat_id: Optional[int] = None):
        self.call_id = call_id
        self.call_sid = call_sid
        self.chat_id = chat_id
        self.clients = set()  # set of websocket objects
        self.state = 'disconnected'  # disconnected|ringing|in-progress|completed
        self.created_at = time.time()
        self.lock = asyncio.Lock()
        self.cleanup_task = None
        self.first_audio_frame_sent = False

    def to_dict(self):
        return {
            'call_id': self.call_id,
            'call_sid': self.call_sid,
            'chat_id': self.chat_id,
            'state': self.state,
            'clients': len(self.clients)
        }


class SessionManager:
    def __init__(self):
        # mapping call_id -> LiveListenSession
        self.sessions: Dict[str, LiveListenSession] = {}
        self._lock = asyncio.Lock()

    async def ensure_session(self, call_id: str, call_sid: str = None, chat_id: Optional[int] = None) -> LiveListenSession:
        async with self._lock:
            s = self.sessions.get(call_id)
            if not s:
                s = LiveListenSession(call_id=call_id, call_sid=call_sid, chat_id=chat_id)
                self.sessions[call_id] = s
            else:
                if call_sid and not s.call_sid:
                    s.call_sid = call_sid
                if chat_id is not None and s.chat_id is None:
                    s.chat_id = chat_id
            return s

    async def remove_session(self, call_id: str):
        async with self._lock:
            s = self.sessions.pop(call_id, None)
            if s and s.cleanup_task:
                s.cleanup_task.cancel()
            # Close websockets handled by server code; this just removes state

    async def set_state(self, call_id: str, state: str):
        s = await self.ensure_session(call_id)
        async with s.lock:
            s.state = state
            # schedule auto-cleanup after terminal states
            if state in ('completed', 'failed', 'no-answer', 'canceled'):
                if s.cleanup_task is None:
                    s.cleanup_task = asyncio.create_task(self._delayed_cleanup(call_id, delay=10))
        await self.broadcast_state(call_id)

    async def _delayed_cleanup(self, call_id: str, delay: int = 10):
        await asyncio.sleep(delay)
        await self.remove_session(call_id)

    async def add_client(self, call_id: str, ws):
        s = await self.ensure_session(call_id)
        async with s.lock:
            s.clients.add(ws)

    async def remove_client(self, call_id: str, ws):
        s = self.sessions.get(call_id)
        if not s:
            return
        async with s.lock:
            s.clients.discard(ws)
            if not s.clients and s.state in ('completed', 'failed', 'no-answer', 'canceled'):
                # schedule immediate cleanup
                if s.cleanup_task is None:
                    s.cleanup_task = asyncio.create_task(self._delayed_cleanup(call_id, delay=1))

    async def broadcast_media(self, call_id: str, payload: bytes, sequence: Optional[str] = None):
        """Relay binary payload to all connected clients for a session."""
        s = self.sessions.get(call_id)
        if not s:
            return
        to_remove = []
        async with s.lock:
            if not s.first_audio_frame_sent:
                s.first_audio_frame_sent = True
                logger.info(
                    "[CALL_MILESTONE] FIRST_AUDIO_FRAME_SENT_TO_TWILIO bytes=%d call_sid=%s sequence=%s",
                    len(payload),
                    s.call_sid or call_id,
                    sequence or "unknown",
                )
            for ws in list(s.clients):
                try:
                    await ws.send_bytes(payload)
                except Exception as e:
                    logger.error(
                        "[WS_SEND_ERROR] call_id=%s client=%s sequence=%s error=%s",
                        call_id,
                        getattr(ws, 'client', None),
                        sequence or "unknown",
                        e,
                        exc_info=True,
                    )
                    to_remove.append(ws)
            for ws in to_remove:
                s.clients.discard(ws)

    async def broadcast_state(self, call_id: str):
        s = self.sessions.get(call_id)
        if not s:
            return
        payload = json.dumps({'type': 'session', 'data': s.to_dict()})
        to_remove = []
        async with s.lock:
            for ws in list(s.clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    to_remove.append(ws)
            for ws in to_remove:
                s.clients.discard(ws)


manager = SessionManager()
