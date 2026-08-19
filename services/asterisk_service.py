"""
services/asterisk_service.py

Asterisk outbound bridge (Vapi SIP -> Asterisk -> SpoofGlobal trunk).

The bot never talks to Asterisk over AMI. Instead, before placing a Vapi SIP
call it drops a per-call JSON file keyed by the E.164 target number:

    {ASTERISK_CLI_DIR}/<E.164-without-plus>.json
    {"caller_id": "+15550123123", "display_name": "Bank of Example"}

Asterisk's dialplan runs an AGI (see asterisk/read_cli.py) that resolves the
custom caller ID/name: in multi-host deployments (bot on Render, Asterisk on a
VPS) it pulls the JSON over HTTP from the bot's /vapi/cli/<e164> endpoint, and
otherwise reads the file by ${EXTEN}, then dials the target out through the
SpoofGlobal trunk.
"""

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from config import ASTERISK_CLI_DIR

logger = logging.getLogger(__name__)

_PLUS_STRIP_RE = re.compile(r"[^\d]")


def cli_path(number: str) -> Path:
    """Filesystem path of the CLI file for an E.164 target number."""
    digits = _PLUS_STRIP_RE.sub("", str(number) or "")
    return Path(ASTERISK_CLI_DIR) / f"{digits}.json"


def write_asterisk_cli_file(
    number: str,
    caller_id: str = "",
    display_name: str = "",
) -> Path:
    """Atomically write the caller-ID file Asterisk's AGI will read.

    Written BEFORE the Vapi call is placed so the AGI always finds it. Uses a
    temp file + os.replace so a half-written file is never visible.
    """
    digits = _PLUS_STRIP_RE.sub("", str(number) or "")
    if not digits:
        logger.warning("[ASTERISK_CLI] no target number given; skipping CLI file")
        return Path()
    payload = {
        "caller_id": str(caller_id or "").strip(),
        "display_name": str(display_name or "").strip(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        target = Path(ASTERISK_CLI_DIR)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{digits}.json"
        fd, tmp_path = tempfile.mkstemp(prefix=f"{digits}.", suffix=".tmp", dir=str(target))
        tmp_path = Path(tmp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(str(tmp_path), str(path))
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        logger.info(
            "[ASTERISK_CLI] wrote caller-ID file %s caller_id=%r display_name=%r",
            path, payload["caller_id"], payload["display_name"],
        )
        return path
    except Exception as exc:
        logger.error("[ASTERISK_CLI] failed to write caller-ID file for %s: %s", digits, exc)
        return Path()


def remove_asterisk_cli_file(number: str) -> bool:
    """Best-effort cleanup of the CLI file after the call ends."""
    path = cli_path(number)
    try:
        if path.exists():
            path.unlink()
            logger.info("[ASTERISK_CLI] removed %s", path)
            return True
    except Exception as exc:
        logger.warning("[ASTERISK_CLI] failed to remove %s: %s", path, exc)
    return False