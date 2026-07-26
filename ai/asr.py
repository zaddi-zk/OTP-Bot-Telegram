"""
Speech-to-text using Groq Whisper API.
Converts Twilio µ-law audio to text via Groq's production-grade transcription.
No local ML models - pure API calls for production reliability.
"""

import requests
import struct
import logging
from io import BytesIO
from config import GROQ_API_KEY, WHISPER_MODEL
from core.logging_utils import structured_log, build_prefix

logger = logging.getLogger(__name__)

# Groq API endpoint for Whisper
GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Session for connection pooling
_groq_session = None


def get_groq_session():
    """Lazy-load and reuse a single requests.Session for Groq API."""
    global _groq_session
    if _groq_session is None:
        _groq_session = requests.Session()
        _groq_session.headers.update({"Authorization": f"Bearer {GROQ_API_KEY}"})
    return _groq_session


def _build_wav_header(audio_bytes: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """
    Build minimal WAV header for audio bytes.
    No external dependencies - pure struct packing.
    
    Args:
        audio_bytes: Raw PCM audio data
        sample_rate: Sample rate in Hz (default 16000)
        channels: Number of channels (default 1 = mono)
        sample_width: Bytes per sample (default 2 = 16-bit)
        
    Returns:
        Complete WAV file with header + audio data
    """
    num_samples = len(audio_bytes) // sample_width
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    
    # WAV header (44 bytes)
    header = (
        b'RIFF' +
        struct.pack('<I', 36 + len(audio_bytes)) +
        b'WAVE' +
        b'fmt ' +
        struct.pack('<I', 16) +  # fmt chunk size
        struct.pack('<HHIIHH', 1, channels, sample_rate, byte_rate, block_align, sample_width * 8) +
        b'data' +
        struct.pack('<I', len(audio_bytes))
    )
    
    return header + audio_bytes


def _ulaw_to_linear(ulaw_byte: int) -> int:
    """
    Convert single µ-law byte to 16-bit linear PCM.
    No external dependencies - pure bit manipulation.
    
    Reference: ITU-T G.711
    """
    ulaw_byte = ulaw_byte ^ 0xFF
    exponent = (ulaw_byte >> 4) & 0x07
    mantissa = ulaw_byte & 0x0F
    
    sample = mantissa << (exponent + 3)
    if exponent > 0:
        sample |= 0x80 << exponent
    
    if ulaw_byte & 0x80:
        sample = -sample
    else:
        sample = sample - 0x84
    
    return sample


def _ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """
    Convert µ-law bytes (8kHz Twilio) to 16-bit PCM (16kHz).
    Pure Python - no external audio libraries needed.
    
    Args:
        ulaw_bytes: µ-law encoded audio from Twilio (8kHz, 8-bit)
        
    Returns:
        16-bit PCM bytes at 16kHz
    """
    if not ulaw_bytes:
        return b""
    
    try:
        # Decode µ-law to 16-bit linear (8kHz)
        pcm_samples = []
        for byte in ulaw_bytes:
            sample = _ulaw_to_linear(byte)
            pcm_samples.append(struct.pack('<h', sample))
        
        pcm_8k = b''.join(pcm_samples)
        
        # Simple resampling: 8kHz → 16kHz (duplicate each sample)
        pcm_16k = b''
        for i in range(0, len(pcm_8k), 2):
            sample = pcm_8k[i:i+2]
            # Duplicate each 16-bit sample (simple linear interpolation)
            pcm_16k += sample + sample
        
        return pcm_16k
    except Exception as e:
        logger.error(f"[ASR] µ-law to PCM conversion error: {e}")
        return b""


def transcribe_audio_buffer(audio_bytes: bytes, audio_format: str = "wav") -> str:
    """
    Transcribe audio buffer using Groq Whisper API.
    
    Args:
        audio_bytes: Audio data (WAV, µ-law, or other supported format)
        audio_format: Audio format hint (wav, ulaw, etc)
        
    Returns:
        Transcribed text (empty string if no speech or API error)
    """
    if not audio_bytes or len(audio_bytes) < 512:
        structured_log(logger, logging.WARNING, "EMPTY_PAYLOAD or too small for transcription", call_sid=None, stage="ASR_PRECHECK", payload_len=len(audio_bytes) if audio_bytes else 0)
        return ""
    
    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        logger.error("[ASR] GROQ_API_KEY not configured - transcription unavailable")
        return ""
    
    try:
        session = get_groq_session()

        # Prepare audio file
        audio_file = BytesIO(audio_bytes)
        audio_file.name = f"audio.{audio_format}"

        files = {
            "file": (f"audio.{audio_format}", audio_file),
        }

        data = {
            "model": WHISPER_MODEL,
            "language": "en",
        }

        structured_log(logger, logging.DEBUG, "ASR_REQUEST", stage="ASR_REQUEST", payload_len=len(audio_bytes), audio_format=audio_format)

        response = session.post(
            GROQ_WHISPER_URL,
            files=files,
            data=data,
            timeout=30
        )

        structured_log(logger, logging.DEBUG, "ASR_RESPONSE", stage="ASR_RESPONSE", status_code=response.status_code)

        if response.status_code == 200:
            result = response.json()
            text = result.get("text", "").strip()
            if text:
                structured_log(logger, logging.INFO, "ASR_FINAL_TRANSCRIPT", stage="ASR_RESULT", transcript=text[:100])
            else:
                structured_log(logger, logging.WARNING, "EMPTY_TRANSCRIPT", stage="ASR_RESULT")
            return text
        else:
            structured_log(logger, logging.ERROR, "GROQ_API_ERROR", stage="ASR_ERROR", status=response.status_code, response=response.text[:200])
            return ""

    except requests.Timeout:
        structured_log(logger, logging.ERROR, "ASR_TIMEOUT", stage="ASR_ERROR")
        return ""
    except Exception as e:
        structured_log(logger, logging.ERROR, "ASR_EXCEPTION", stage="ASR_ERROR", error=str(e))
        return ""


def process_ulaw_buffer(ulaw_bytes: bytes, context: dict | None = None) -> str:
    """
    Convert Twilio µ-law (8kHz) audio to text via Groq Whisper.
    
    Twilio sends audio as µ-law at 8kHz; we convert to 16kHz WAV and transcribe.
    Pure Python conversion - no external audio library dependencies.
    
    Args:
        ulaw_bytes: µ-law encoded audio from Twilio (8kHz, 8-bit)
        
    Returns:
        Transcribed text (empty string if error)
    """
    ctx = context or {}
    call_sid = ctx.get("call_sid") if isinstance(ctx, dict) else None
    stage = "ULAW_PROCESS"

    if not ulaw_bytes:
        structured_log(logger, logging.WARNING, "NO_MEDIA_RECEIVED", call_sid=call_sid, stage=stage)
        return ""

    try:
        payload_len = len(ulaw_bytes)
        structured_log(logger, logging.DEBUG, "ULAW_BUFFER_RECEIVED", call_sid=call_sid, stage=stage, payload_len=payload_len)

        # Convert µ-law (8kHz) to PCM16 (16kHz)
        pcm_16k = _ulaw_to_pcm16(ulaw_bytes)
        if not pcm_16k:
            structured_log(logger, logging.ERROR, "ULAW_DECODE_FAILED", call_sid=call_sid, stage=stage)
            return ""

        decoded_len = len(pcm_16k)
        if decoded_len < 320:  # arbitrary threshold for too-short audio (~20ms at 16kHz)
            structured_log(logger, logging.WARNING, "PCM_TOO_SHORT", call_sid=call_sid, stage=stage, pcm_len=decoded_len)

        structured_log(logger, logging.DEBUG, "PCM_READY", call_sid=call_sid, stage=stage, pcm_len=decoded_len)

        # Build WAV file with proper headers
        wav_data = _build_wav_header(pcm_16k, sample_rate=16000, channels=1, sample_width=2)
        structured_log(logger, logging.DEBUG, "WAV_BUILT", call_sid=call_sid, stage=stage, wav_len=len(wav_data))

        # Transcribe via Groq
        transcript = transcribe_audio_buffer(wav_data, audio_format="wav")
        if transcript:
            structured_log(logger, logging.INFO, "TRANSCRIBE_SUCCESS", call_sid=call_sid, stage=stage, transcript=transcript[:200])
        else:
            structured_log(logger, logging.WARNING, "TRANSCRIBE_EMPTY", call_sid=call_sid, stage=stage)

        return transcript

    except Exception as e:
        structured_log(logger, logging.ERROR, "ASR_PROCESSING_EXCEPTION", call_sid=call_sid, stage=stage, error=str(e))
        return ""


def initialize_asr() -> bool:
    """
    Initialize Groq Whisper ASR - validates API configuration.
    
    Returns:
        True if ASR is ready, False otherwise
    """
    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        logger.error("[ASR] GROQ_API_KEY not configured - ASR unavailable")
        return False
    
    logger.info(f"[OK] Groq Whisper ASR initialized successfully (model={WHISPER_MODEL})")
    return True


