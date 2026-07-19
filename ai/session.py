"""
Per-call session management: conversation history, audio buffer, context.
Stores call-specific data for AI personalization.
"""


class CallSession:
    """Represents a single Twilio call session."""
    
    def __init__(self, call_sid: str):
        self.call_sid = call_sid
        self.history = []              # list of {"role": "user"/"agent", "text": ...}
        self.audio_buffer = bytearray()
        self.last_response = None
        self.company = "your bank"
        self.name = "Customer"
        self.voice_id = None           # ElevenLabs voice ID
        self.chat_id = None            # Telegram chat_id for notifications
        self.custom_script = None      # Custom script from user
        self.code_length = 6           # OTP code length (from user)
        self.emotion = "neutral"       # Voice emotion
        self.otp_captured = False
        self.otp_value = None

    def add_user_message(self, text: str):
        """Add user input to conversation history."""
        self.history.append({"role": "user", "text": text})

    def add_agent_message(self, text: str):
        """Add AI response to conversation history."""
        self.history.append({"role": "agent", "text": text})

    def get_context(self, limit: int = 6) -> str:
        """Get recent conversation context for AI prompt."""
        recent = self.history[-limit:]
        lines = []
        for msg in recent:
            role = "Customer" if msg["role"] == "user" else "Agent"
            lines.append(f"{role}: {msg['text']}")
        return "\n".join(lines)


# In-memory session store
_sessions = {}


def get_session(call_sid: str) -> CallSession:
    """Retrieve or create a session for a call SID."""
    if call_sid not in _sessions:
        _sessions[call_sid] = CallSession(call_sid)
    return _sessions[call_sid]


def remove_session(call_sid: str):
    """Clean up session after call ends."""
    _sessions.pop(call_sid, None)
