#!/usr/bin/env python3
"""
asterisk/read_cli.py - Asterisk AGI that applies the per-call caller ID.

The bot writes conf/asterisk_cli/<E.164>.json (caller_id + display_name) BEFORE
placing the Vapi SIP call. This AGI runs when the inbound Vapi leg hits the
dialplan: it reads the JSON by ${EXTEN} and, when found, prints the SET CALLERID
command so the outbound SpoofGlobal leg presents the custom CLI.

Multi-host (bot on Render, Asterisk on a VPS):
  - The bot writes the CLI JSON on its own host, so this AGI first PULLS it over
    HTTP from the bot's endpoint:
        GET <ASTERISK_CLI_PUBLIC_URL>/vapi/cli/<digits>
        Header: X-CLI-Token: <ASTERISK_CLI_API_TOKEN>
    and only falls back to the local filesystem when that fails (single-host
    deployments with a shared directory).

Install:
  - Copy next to the bot or deploy as a shared script, then set the env vars
    below / in the Asterisk runtime environment (path Asterisk can read).
  - In extensions.conf:
      exten => _+X.,1,NoOp(Vapi inbound)
        same => n,AGI(/opt/otp-bot/asterisk/read_cli.py)
        same => n,Set(CALLERID(all)="SpoofGlobal Caller"<+12025550131>)  ; fallback
        same => n,Dial(PJSIP/${EXTEN}@spoofglobal-endpoint,,m)
        same => n,Hangup()
"""

import json
import os
import re
import sys
import urllib.request

AGI_ENV = "/opt/otp-bot/conf/asterisk_cli"  # change to your Asterisk-readable path
ASTERISK_CLI_DIR = os.environ.get("ASTERISK_CLI_DIR", AGI_ENV)
# Public base URL of the bot (Render). Empty disables the HTTP pull.
ASTERISK_CLI_PUBLIC_URL = os.environ.get("ASTERISK_CLI_PUBLIC_URL", "").strip().rstrip("/")
# Shared secret the bot's /vapi/cli/<e164> endpoint requires (X-CLI-Token).
ASTERISK_CLI_API_TOKEN = os.environ.get("ASTERISK_CLI_API_TOKEN", "").strip()
PLUS_STRIP_RE = re.compile(r"[^\d]")

# SpoofGlobal may be configured to accept/require the leading '+' (E.164) or a
# bare national format; try the exact dialed extension first, then normalized.
FALLBACK_CALLER_ID = os.environ.get(
    "ASTERISK_FALLBACK_CALLER_ID", "+12025550131"
)
FALLBACK_DISPLAY_NAME = os.environ.get("ASTERISK_FALLBACK_DISPLAY_NAME", "OTP Bot")


def _write(line: str) -> None:
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _read_variable(name: str) -> str:
    """Read an AGI channel variable via GET VARIABLE."""
    try:
        sys.stdout.write(f"GET VARIABLE {name}\n")
        sys.stdout.flush()
        reply = sys.stdin.readline()
        # AGI replies look like: 200 result=1 (value)
        if "(" in reply and ")" in reply:
            value = reply.split("(", 1)[1].rsplit(")", 1)[0]
            return value.strip()
    except Exception:
        pass
    return ""


def _fetch_cli_via_http(digits: str):
    """Pull the caller-ID JSON from the bot's /vapi/cli/<digits> endpoint.

    Returns (caller_id, display_name) on success, or None when the pull fails
    (network error, bad auth, 404, malformed payload) so the caller falls back
    to the local-file path. Uses only the stdlib so no extra deps are needed on
    the Asterisk host.
    """
    if not ASTERISK_CLI_PUBLIC_URL or not ASTERISK_CLI_API_TOKEN or not digits:
        return None
    url = f"{ASTERISK_CLI_PUBLIC_URL}/vapi/cli/{digits}"
    try:
        req = urllib.request.Request(
            url,
            headers={"X-CLI-Token": ASTERISK_CLI_API_TOKEN, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            return None
        caller_id = str(data.get("caller_id") or "").strip()
        display_name = str(data.get("display_name") or "").strip()
        if not caller_id:
            return None
        _write('VERBOSE "read_cli: http pull ok digits=%s caller_id=%s" 3' % (digits, caller_id))
        return caller_id, display_name
    except Exception as exc:
        _write('VERBOSE "read_cli: http pull failed (%s) for %s" 3' % (exc, digits))
        return None


def _read_cli_file(exten: str, digits: str):
    """Local-filesystem fallback for single-host deployments."""
    for candidate in (f"{digits}.json", f"+{digits}.json", exten):
        if not candidate:
            continue
        path = os.path.join(ASTERISK_CLI_DIR, candidate)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (
                (data.get("caller_id") or "").strip(),
                (data.get("display_name") or "").strip(),
            )
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return None


def main() -> None:
    exten = _read_variable("EXTEN") or ""
    digits = PLUS_STRIP_RE.sub("", exten)

    caller_id = FALLBACK_CALLER_ID
    display_name = FALLBACK_DISPLAY_NAME

    if digits:
        fetched = _fetch_cli_via_http(digits) or _read_cli_file(exten, digits)
        if fetched:
            caller_id = fetched[0] or caller_id
            display_name = fetched[1] or display_name

    # Publish the effective values as channel variables ALWAYS (fallback
    # included). The dialplan builds CALLERID(all) from these; the AGI's native
    # `SET CALLERID all "name" <num>` form is brittle in Asterisk 20 when the
    # display name contains spaces (res_agi space-splits the value), so the
    # dialplan Set() is the authoritative application.
    _write(f'SET VARIABLE AST_CUSTOM_CLI "{caller_id}"')
    _write(f'SET VARIABLE AST_CUSTOM_CNAM "{display_name}"')

    # Emit the caller id; kept for dialplans that don't re-apply it via Set().
    if caller_id:
        if display_name:
            _write(f'SET CALLERID all "{display_name}" <{caller_id}>')
        else:
            _write(f"SET CALLERID all <{caller_id}>")
    _write("VERBOSE \"read_cli: exten=%s caller_id=%s cnam=%s\" 3" % (exten, caller_id, display_name))


if __name__ == "__main__":
    main()