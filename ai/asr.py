"""
Real-time transcription using Groq Whisper API.
Converts Twilio µ-law audio stream to text via Groq's production-grade speech-to-text.
"""

import requests
import audioop
import logging
from io import BytesIO
from config import GROQ_API_KEY, WHISPER_MODEL

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


def transcribe_audio_buffer(audio_bytes: bytes, audio_format: str = "wav") -> str:
    """
    Transcribe audio buffer using Groq Whisper API.
    
    Args:
        audio_bytes: Raw audio data
        audio_format: Format hint (wav, mp3, etc)
        
    Returns:
        Transcribed text (empty string if no speech detected or API error)
    """
    if not audio_bytes or len(audio_bytes) < 512:
        return ""
    
    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        logger.error("[ASR] GROQ_API_KEY not configured. Set via Railway env or .env")
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
        
        response = session.post(
            GROQ_WHISPER_URL,
            files=files,
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            text = result.get("text", "").strip()
            if text:
                logger.debug(f"[ASR] Transcribed: {text[:100]}...")
            return text
        else:
            logger.error(f"[ASR] Groq API error {response.status_code}: {response.text}")
            return ""
            
    except requests.Timeout:
        logger.error("[ASR] Groq API request timed out")
        return ""
    except Exception as e:
        logger.error(f"[ASR] Transcription error: {e}")
        return ""


def process_ulaw_buffer(ulaw_bytes: bytes) -> str:
    """
    Convert Twilio µ-law (8kHz) audio to 16kHz PCM and transcribe via Groq.
    
    Twilio sends audio as µ-law at 8kHz; Groq Whisper accepts WAV at various rates.
    
    Args:
        ulaw_bytes: µ-law encoded audio (8kHz)
        
    Returns:
        Transcribed text
    """
    if not ulaw_bytes:
        return ""
    
    try:
        # µ-law to 16-bit PCM (8kHz)
        pcm_8k = audioop.ulaw2lin(ulaw_bytes, 2)
        
        # Resample to 16kHz (better for Groq Whisper)
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        
        # Build minimal WAV header for 16kHz PCM
        # WAV format: 44 bytes header + audio data
        sample_rate = 16000
        num_channels = 1
        sample_width = 2
        
        import struct
        
        # WAV header
        num_samples = len(pcm_16k) // sample_width
        byte_rate = sample_rate * num_channels * sample_width
        block_align = num_channels * sample_width
        
        wav_header = (
            b'RIFF' +
            struct.pack('<I', 36 + len(pcm_16k)) +
            b'WAVE' +
            b'fmt ' +
            struct.pack('<I', 16) +  # fmt chunk size
            struct.pack('<HHIIHH', 1, num_channels, sample_rate, byte_rate, block_align, sample_width * 8) +
            b'data' +
            struct.pack('<I', len(pcm_16k)) +
            pcm_16k
        )
        
        # Transcribe via Groq
        return transcribe_audio_buffer(wav_header, audio_format="wav")
        
    except Exception as e:
        logger.error(f"[ASR] µ-law processing error: {e}")
        return ""


def initialize_asr():
    """Initialize Groq Whisper ASR - checks API connectivity."""
    if not GROQ_API_KEY or "YOUR_" in GROQ_API_KEY:
        logger.error("[ASR] GROQ_API_KEY not configured - ASR unavailable")
        return False
    
    logger.info(f"[ASR] Groq Whisper initialized (model={WHISPER_MODEL})")
    return True

