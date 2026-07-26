import logging
import json
import traceback
from datetime import datetime


def build_prefix(call_sid: str | None = None, user_id: str | None = None, stage: str | None = None) -> str:
    parts = []
    if call_sid:
        parts.append(f"CALL {call_sid}")
    if user_id:
        parts.append(f"USER {user_id}")
    if stage:
        parts.append(stage)
    if parts:
        return f"[{ ' | '.join(parts) }]"
    return "[NO_CTX]"


def structured_log(logger: logging.Logger, level: int, msg: str, *, call_sid: str | None = None, user_id: str | None = None, stage: str | None = None, **kwargs) -> None:
    prefix = build_prefix(call_sid, user_id, stage)
    ts = datetime.utcnow().isoformat() + 'Z'
    extra = ''
    if kwargs:
        try:
            extra = ' ' + json.dumps(kwargs, default=str)
        except Exception:
            extra = f" {kwargs}"
    logger.log(level, f"{ts} {prefix} {msg}{extra}")


def log_exception(logger: logging.Logger, *, call_sid: str | None = None, session_id: str | None = None, stage: str | None = None, reason: str | None = None, **kwargs) -> None:
    structured_log(
        logger,
        logging.ERROR,
        "EXCEPTION",
        call_sid=call_sid,
        user_id=session_id,
        stage=stage,
        reason=reason,
        traceback=traceback.format_exc(),
        **kwargs,
    )
