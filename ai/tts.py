"""
ElevenLabs TTS for generating call audio.
Supports custom voice IDs and emotional modulation.
"""

import requests
import os
import time
import logging
import traceback
from io import BytesIO
from typing import Optional
from config import ELEVENLABS_API_KEY, DEFAULT_VOICE_ID
from core.logging_utils import structured_log

logger = logging.getLogger(__name__)


def _fallback_gtts_audio(text: str) -> bytes:
    """Fallback to gTTS if ElevenLabs audio generation fails."""
    try:
        from gtts import gTTS
        output = BytesIO()
        tts = gTTS(text=text, lang="en")
        tts.write_to_fp(output)
        output.seek(0)
        data = output.read()
        logger.info(f"gTTS fallback returned {len(data) if data is not None else 0} bytes")
        if data:
            logger.warning("ElevenLabs fallback: generated audio with gTTS")
            return data
        logger.warning("ElevenLabs fallback: gTTS returned empty audio")
    except Exception as e:
        logger.error(f"gTTS fallback failed: {e}")
    return b""


def generate_audio(text: str, voice_id: str = None, call_sid: str | None = None, session: object = None) -> bytes:
    """
    Generate MP3 audio using ElevenLabs.
    
    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID (defaults to config DEFAULT_VOICE_ID)
        
    Returns:
        MP3 audio bytes (empty bytes if error)
    """
    voice_id = voice_id or DEFAULT_VOICE_ID
    structured_log(logger, logging.INFO, "TTS_BEGIN", call_sid=call_sid, stage="TTS_BEGIN", voice_id=voice_id, text_preview=text[:160])

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    
    data = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.70,
            "style": 0.0,
            "use_speaker_boost": True,
        }
    }
    
    # Basic validation
    if not ELEVENLABS_API_KEY or 'YOUR_' in ELEVENLABS_API_KEY:
        logger.error("ElevenLabs API key not configured. Set ELEVENLABS_API_KEY in env or conf/settings.txt")
        return b""
    if not voice_id:
        logger.error("ElevenLabs voice_id not set. Set DEFAULT_VOICE_ID in config or pass voice_id")
        return b""

    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 404:
            logger.error(f"ElevenLabs voice not found (voice_id={voice_id}). Check DEFAULT_VOICE_ID.")
            return _fallback_gtts_audio(text)
        response.raise_for_status()
        content = response.content
        if session and getattr(session, "mark_milestone", None) and session.mark_milestone("FIRST_TTS_RESPONSE"):
            logger.info("[CALL_MILESTONE] FIRST_TTS_RESPONSE call_sid=%s bytes=%d", call_sid, len(content) if content else 0)
        logger.info(f"ElevenLabs TTS returned {len(content) if content is not None else 0} bytes")
        if not content:
            structured_log(logger, logging.WARNING, "TTS_SKIPPED", call_sid=call_sid, stage="TTS_COMPLETE", reason="empty_content")
            logger.error("ElevenLabs TTS returned empty content")
            return _fallback_gtts_audio(text)
        structured_log(logger, logging.INFO, "TTS_STREAMING", call_sid=call_sid, stage="TTS_STREAMING", bytes=len(content))
        structured_log(logger, logging.INFO, "TTS_COMPLETE", call_sid=call_sid, stage="TTS_COMPLETE", bytes=len(content))
        return content
    except requests.exceptions.Timeout:
        structured_log(logger, logging.ERROR, "TIMEOUT", call_sid=call_sid, stage="TTS_TIMEOUT", timer_name="elevenlabs_tts", elapsed_ms=30000, who_created="ai.tts.generate_audio", reason="request_timeout")
        logger.error("ElevenLabs TTS timeout")
        return _fallback_gtts_audio(text)
    except requests.exceptions.HTTPError as he:
        structured_log(logger, logging.ERROR, "EXCEPTION", call_sid=call_sid, stage="TTS_EXCEPTION", reason="elevenlabs_http_error", error=str(he), traceback=traceback.format_exc())
        logger.error(f"ElevenLabs TTS HTTP error: {he} - {getattr(he.response,'text', '')}")
        return _fallback_gtts_audio(text)
    except Exception as e:
        structured_log(logger, logging.ERROR, "EXCEPTION", call_sid=call_sid, stage="TTS_EXCEPTION", reason="tts_generation_exception", error=str(e), traceback=traceback.format_exc())
        logger.error(f"ElevenLabs TTS error: {e}")
        return _fallback_gtts_audio(text)


def save_audio(call_sid: str, text: str, voice_id: str = None, base_path: str = "audio", session: object = None) -> str:
    """
    Generate audio, save to disk, return filename.
    If ElevenLabs fails, returns a silent placeholder to prevent dead air.
    
    Args:
        call_sid: Twilio call SID (used as directory)
        text: Text to convert
        voice_id: Voice ID (optional)
        base_path: Base directory for audio files
        
    Returns:
        Filename (e.g., "1234567890.mp3") or placeholder filename if failed
    """
    audio_bytes = generate_audio(text, voice_id, call_sid=call_sid, session=session)
    
    try:
        dir_path = os.path.join(base_path, call_sid)
        os.makedirs(dir_path, exist_ok=True)
        
        filename = f"{int(time.time())}.mp3"
        filepath = os.path.join(dir_path, filename)
        
        if not audio_bytes:
            structured_log(logger, logging.WARNING, "TTS_SKIPPED", call_sid=call_sid, stage="TTS_COMPLETE", reason="no_audio_bytes")
            logger.warning(f"No audio generated for call_sid={call_sid}; returning None for fallback handling")
            return None

        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        logger.info(
            "[AUDIO_WRITE] call_sid=%s filename=%s cwd=%s abs_path=%s exists_after_write=%s",
            call_sid,
            filename,
            os.getcwd(),
            os.path.abspath(filepath),
            os.path.exists(filepath),
        )
        return filename
    except Exception as e:
        logger.error(f"Failed to save audio: {e}")
        # Return placeholder filename to avoid None (which would break call flow)
        return f"{int(time.time())}.mp3"
