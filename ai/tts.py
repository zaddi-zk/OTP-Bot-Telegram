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


def _fallback_gtts_audio(text: str, output_format: str = "mp3") -> bytes:
    """Fallback to gTTS if ElevenLabs audio generation fails."""
    try:
        from gtts import gTTS
        output = BytesIO()
        tts = gTTS(text=text, lang="en")
        tts.write_to_fp(output)
        output.seek(0)
        data = output.read()
        logger.info(f"gTTS fallback returned {len(data) if data is not None else 0} bytes")
        if not data:
            logger.warning("ElevenLabs fallback: gTTS returned empty audio")
            return b""
        logger.warning("ElevenLabs fallback: generated audio with gTTS")
        if output_format in ("ulaw_8000", "mulaw_8000"):
            return _convert_mp3_to_ulaw8000(data) or b""
        return data
    except Exception as e:
        logger.error(f"gTTS fallback failed: {e}")
    return b""


def _convert_mp3_to_ulaw8000(mp3_bytes: bytes) -> Optional[bytes]:
    if not mp3_bytes:
        return None
    try:
        import subprocess
        proc = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "mulaw", "-ar", "8000", "-ac", "1", "pipe:1"],
            input=mp3_bytes,
            capture_output=True,
            timeout=30
        )
        if proc.returncode != 0:
            logger.warning(f"MP3->u-law conversion failed (ffmpeg rc={proc.returncode}): {proc.stderr.decode(errors='replace')[:200]}")
            return None
        if not proc.stdout:
            logger.warning("MP3->u-law conversion returned empty output")
            return None
        return proc.stdout
    except Exception as e:
        logger.warning(f"MP3->u-law conversion failed: {e}")
    return None


def _linear_to_ulaw(sample: int) -> int:
    """Encode a single 16-bit linear PCM sample to 8-bit mu-law."""
    # Clip to 16-bit signed range.
    if sample > 32767:
        sample = 32767
    elif sample < -32768:
        sample = -32768

    sign = 0 if sample >= 0 else 128
    sample = abs(sample)

    # Add the mu-law bias.
    sample += 132
    if sample > 32767:
        sample = 32767

    # Determine exponent.
    if sample >= 0x4000:
        exp = 7
        sample >>= 13
    elif sample >= 0x2000:
        exp = 6
        sample >>= 12
    elif sample >= 0x1000:
        exp = 5
        sample >>= 11
    elif sample >= 0x0800:
        exp = 4
        sample >>= 10
    elif sample >= 0x0400:
        exp = 3
        sample >>= 9
    elif sample >= 0x0200:
        exp = 2
        sample >>= 8
    elif sample >= 0x0100:
        exp = 1
        sample >>= 7
    else:
        exp = 0
        sample >>= 3

    mantissa = sample & 0x0F
    ulaw = sign | (exp << 4) | mantissa
    return ulaw ^ 0xFF


def _pcm16_to_ulaw(pcm_bytes: bytes) -> bytes:
    """Convert 16-bit little-endian PCM to mu-law."""
    if not pcm_bytes:
        return b""
    import struct
    samples = struct.unpack(f"<{len(pcm_bytes) // 2}h", pcm_bytes)
    return bytes(_linear_to_ulaw(s) for s in samples)


def _downsample_pcm16(pcm_bytes: bytes, from_rate: int = 44100, to_rate: int = 8000) -> bytes:
    """Nearest-neighbour downsample of 16-bit little-endian PCM."""
    import struct
    if from_rate == to_rate or not pcm_bytes:
        return pcm_bytes
    samples = struct.unpack(f"<{len(pcm_bytes) // 2}h", pcm_bytes)
    ratio = from_rate / to_rate
    out = b"".join(
        struct.pack("<h", samples[min(int(i * ratio), len(samples) - 1)])
        for i in range(int(len(samples) / ratio))
    )
    return out


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


def generate_telephony_audio(
    text: str,
    voice_id: str = None,
    output_format: str = "ulaw_8000",
    call_sid: str | None = None,
    session: object = None,
) -> bytes:
    """Generate Twilio Media Streams compatible audio bytes (default mu-law 8kHz).

    Uses ElevenLabs directly in the requested telephony format to avoid fragile
    MP3->u-law conversion in production. Falls back to gTTS if ElevenLabs fails.
    """
    if not text or not text.strip():
        return b""

    voice_id = voice_id or DEFAULT_VOICE_ID
    structured_log(
        logger, logging.INFO, "TTS_TELEPHONY_BEGIN",
        call_sid=call_sid, voice_id=voice_id, output_format=output_format, text_preview=text[:160]
    )

    if not ELEVENLABS_API_KEY or 'YOUR_' in ELEVENLABS_API_KEY:
        logger.error("ElevenLabs API key not configured; cannot generate telephony audio")
        return b""
    if not voice_id:
        logger.error("No voice_id provided for telephony audio")
        return b""

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",  # Overridden by output_format when supported.
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
    }
    data = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "output_format": output_format,
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.70,
            "style": 0.0,
            "use_speaker_boost": True,
        }
    }

    def _try_elevenlabs(fmt: str) -> Optional[bytes]:
        payload = {**data, "output_format": fmt}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code in (400, 422) and "output_format" in str(resp.text).lower():
                logger.warning(f"[TTS] ElevenLabs rejected format {fmt}: {resp.text[:200]}")
                return None
            resp.raise_for_status()
            content = resp.content
            if session and getattr(session, "mark_milestone", None) and session.mark_milestone("FIRST_TTS_RESPONSE"):
                logger.info("[CALL_MILESTONE] FIRST_TTS_RESPONSE call_sid=%s bytes=%d", call_sid, len(content) if content else 0)
            if not content:
                return None
            return content
        except requests.exceptions.Timeout:
            structured_log(
                logger, logging.ERROR, "TIMEOUT", call_sid=call_sid, stage="TTS_TIMEOUT",
                timer_name="elevenlabs_tts", elapsed_ms=30000, who_created="ai.tts.generate_telephony_audio", reason="request_timeout"
            )
            return None
        except requests.exceptions.HTTPError as he:
            logger.error(f"ElevenLabs TTS HTTP error ({fmt}): {he} - {getattr(he.response, 'text', '')}")
            return None

    for fmt in (output_format, "mulaw_8000", "ulaw_8000"):
        if not fmt:
            continue
        content = _try_elevenlabs(fmt)
        if content:
            logger.info(f"[TTS_TELEPHONY_OK] format={fmt} bytes={len(content)}")
            return content

    logger.warning("ElevenLabs telephony audio failed; falling back to gTTS")
    return _fallback_gtts_audio(text, output_format=output_format)


def build_twilio_media_event(audio_bytes: bytes) -> dict:
    """Build a Twilio Media Streams `media` event dict from mu-law bytes."""
    return {
        "event": "media",
        "media": {
            "payload": base64.b64encode(audio_bytes).decode("ascii"),
        },
    }


def build_twilio_mark_event(name: str) -> dict:
    """Build a Twilio Media Streams `mark` event for audio synchronization."""
    return {
        "event": "mark",
        "mark": {"name": name},
    }
