"""
AI-powered call handling module.
Integrates Whisper (ASR), Ollama (LLM), and ElevenLabs (TTS).
"""

from .session import CallSession, get_session, remove_session
from .llm import generate_response, chat_with_ai
from .tts import generate_audio, save_audio
from .utils import extract_otp, send_otp_to_channel

# ASR is optional (only needed for live calls with transcription)
try:
    from .asr import transcribe_pcm16, process_ulaw_buffer
    ASR_AVAILABLE = True
except ImportError:
    ASR_AVAILABLE = False
    # Provide stub functions if ASR fails to import
    def transcribe_pcm16(pcm_16k_bytes: bytes) -> str:
        return ""
    def process_ulaw_buffer(ulaw_bytes: bytes) -> str:
        return ""

__all__ = [
    "CallSession", "get_session", "remove_session",
    "transcribe_pcm16", "process_ulaw_buffer",
    "generate_response", "chat_with_ai",
    "generate_audio", "save_audio",
    "extract_otp", "send_otp_to_channel",
    "ASR_AVAILABLE",
]
