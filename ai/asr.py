"""
Real-time transcription using faster-whisper.
Converts Twilio µ-law audio stream to text.
"""

from faster_whisper import WhisperModel
import numpy as np
import audioop
import logging

logger = logging.getLogger(__name__)

_model = None


def get_whisper_model(model_size: str = "base"):
    """Load Whisper model (base for speed, small for accuracy)."""
    global _model
    if _model is None:
        # "int8" on CPU is faster; use "float16" on GPU if available
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


def transcribe_pcm16(pcm_16k_bytes: bytes) -> str:
    """
    Transcribe 16kHz PCM (int16) audio to text.
    
    Args:
        pcm_16k_bytes: Raw 16-bit PCM audio at 16kHz
        
    Returns:
        Transcribed text (empty string if no speech detected)
    """
    if not pcm_16k_bytes or len(pcm_16k_bytes) < 1024:
        return ""
    
    try:
        model = get_whisper_model()
        audio_array = np.frombuffer(pcm_16k_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            audio_array,
            language="en",
            beam_size=3,
            vad_filter=True  # Voice Activity Detection to skip silence
        )
        text = " ".join([seg.text for seg in segments])
        return text.strip()
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return ""


def process_ulaw_buffer(ulaw_bytes: bytes) -> str:
    """
    Convert Twilio µ-law (8kHz) audio to 16kHz PCM and transcribe.
    
    Twilio sends audio as µ-law at 8kHz; Whisper expects 16kHz PCM.
    
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
        
        # Resample to 16kHz (Whisper requirement)
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        
        # Transcribe
        return transcribe_pcm16(pcm_16k)
    except Exception as e:
        logger.error(f"µ-law processing error: {e}")
        return ""
