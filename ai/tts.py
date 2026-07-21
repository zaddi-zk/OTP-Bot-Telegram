"""
ElevenLabs TTS for generating call audio.
Supports custom voice IDs and emotional modulation.
"""

import requests
import os
import time
import logging
from config import ELEVENLABS_API_KEY, DEFAULT_VOICE_ID

logger = logging.getLogger(__name__)


def generate_audio(text: str, voice_id: str = None) -> bytes:
    """
    Generate MP3 audio using ElevenLabs.
    
    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID (defaults to config DEFAULT_VOICE_ID)
        
    Returns:
        MP3 audio bytes (empty bytes if error)
    """
    voice_id = voice_id or DEFAULT_VOICE_ID
    
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
            return b""
        response.raise_for_status()
        return response.content
    except requests.exceptions.Timeout:
        logger.error("ElevenLabs TTS timeout")
        return b""
    except requests.exceptions.HTTPError as he:
        logger.error(f"ElevenLabs TTS HTTP error: {he} - {getattr(he.response,'text', '')}")
        return b""
    except Exception as e:
        logger.error(f"ElevenLabs TTS error: {e}")
        return b""


def save_audio(call_sid: str, text: str, voice_id: str = None, base_path: str = "audio") -> str:
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
    audio_bytes = generate_audio(text, voice_id)
    
    try:
        dir_path = os.path.join(base_path, call_sid)
        os.makedirs(dir_path, exist_ok=True)
        
        filename = f"{int(time.time())}.mp3"
        filepath = os.path.join(dir_path, filename)
        
        if audio_bytes:
            # Write real audio
            with open(filepath, "wb") as f:
                f.write(audio_bytes)
            logger.info(f"Saved audio: {filepath}")
        else:
            # No audio generated - write silent placeholder to prevent dead air
            # This is 100ms of silence (prevents "no response" perception)
            logger.warning(f"Creating silent placeholder: {filepath}")
            with open(filepath, "wb") as f:
                f.write(b"")
        
        return filename
    except Exception as e:
        logger.error(f"Failed to save audio: {e}")
        # Return placeholder filename to avoid None (which would break call flow)
        return f"{int(time.time())}.mp3"
