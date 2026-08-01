"""
Pro analytics for all call modes.

Stores enriched per-call records in conf/<user>/call_history.json and
computes aggregates: totals, per-mode breakdown, success / OTP capture
rates, average duration and a rolling 7-day activity window.
"""
import html
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from core.files import read_user_json, write_user_json

logger = logging.getLogger("OTP-Bot.analytics")

SUCCESS_STATUSES = {"completed", "ended"}
FAIL_STATUSES = {"failed", "busy", "no-answer", "canceled", "queued", "error"}
PENDING_STATUSES = {"initiated", "in-progress", "pending", "ringing"}

MODE_FALLBACKS = {
    "CRACK BLAST": "Crack Blast",
    "MANUAL CALL": "Manual Call",
    "CUSTOM CALL": "Custom Call",
    "FAST MODE": "Fast Mode",
    "AI MODE": "AI MASTER",
    "AI Mode": "AI MASTER",
    "AI MASTER": "AI MASTER",
}

STATUS_ICONS = {
    "completed": "✅",
    "ended": "✅",
    "failed": "❌",
    "busy": "ℹ️",
    "no-answer": "⏱️",
    "canceled": "ℹ️",
    "queued": "⏳",
    "initiated": "⏳",
    "in-progress": "⏳",
}


def _safe(value) -> str:
    return html.escape(str(value or ""))


def _pick(*values) -> str:
    for v in values:
        if v not in (None, ""):
            return str(v)
    return ""


def load_history(user_id: str) -> List[dict]:
    entries = read_user_json(user_id, "call_history.json", [])
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def save_history(user_id: str, entries: List[dict]) -> None:
    write_user_json(user_id, "call_history.json", entries)


def clear_history(user_id: str) -> None:
    save_history(user_id, [])


def resolve_mode(entry: dict) -> str:
    mode = _pick(entry.get("mode"), entry.get("campaign"))
    mode = MODE_FALLBACKS.get(mode, mode)
    return mode or "Normal Call"


def _now_iso() -> str:
    return datetime.now().isoformat()


def record_call(
    user_id: str,
    sid: str,
    target: str = "",
    campaign: str = "",
    status: str = "initiated",
    session: Optional[dict] = None,
) -> None:
    """Append a new call record (used at call initiation)."""
    session = session or {}
    entry = {
        "sid": sid,
        "vapi_call_id": session.get("vapi_call_id") or "",
        "target": target,
        "campaign": campaign,
        "mode": resolve_mode(
            {
                "mode": _pick(session.get("mode_label"), campaign),
                "campaign": campaign,
            }
        ),
        "voice_id": session.get("voice_id") or "",
        "voice_name": session.get("voice_name") or "",
        "language": session.get("language") or "",
        "emotion": session.get("emotion") or "",
        "started": _now_iso(),
        "status": status,
    }
    entries = load_history(user_id)
    entries.append(entry)
    save_history(user_id, entries)


def finalize_call_history(
    user_id: Optional[str],
    call_sid: Optional[str],
    *,
    vapi_call_id: Optional[str] = None,
    status: str = "ended",
    duration_s: int = 0,
    ended_reason: str = "",
    otp: str = "",
    recording: bool = False,
    session: Optional[dict] = None,
) -> None:
    """Update or append a call record with its final outcome."""
    if not user_id:
        return
    session = session or {}
    entries = load_history(user_id)
    idx = None
    for i, e in enumerate(entries):
        if (call_sid and e.get("sid") == call_sid) or (
            vapi_call_id and e.get("vapi_call_id") == vapi_call_id
        ):
            idx = i
            break
    if idx is None:
        if not call_sid:
            return
        entries.append(
            {
                "sid": call_sid,
                "vapi_call_id": vapi_call_id or "",
                "target": _pick(session.get("name")),
                "campaign": session.get("campaign") or "",
                "started": _now_iso(),
            }
        )
        idx = len(entries) - 1

    entry = entries[idx]
    entry["status"] = status
    if ended_reason:
        entry["ended_reason"] = ended_reason
    if duration_s:
        entry["duration_s"] = int(duration_s)
    if otp:
        entry["otp"] = otp
    if recording:
        entry["recording"] = True
    entry["ended"] = _now_iso()
    session_mode = session.get("mode_label") or session.get("mode")
    if session_mode:
        entry["mode"] = resolve_mode(
            {"mode": session_mode, "campaign": entry.get("campaign") or ""}
        )
    elif not entry.get("mode"):
        entry["mode"] = resolve_mode(entry)
    for key in ("voice_id", "voice_name", "language", "emotion"):
        val = session.get(key)
        if val and not entry.get(key):
            entry[key] = val
    save_history(user_id, entries)


def mark_call_recording(
    user_id: Optional[str],
    call_sid: Optional[str],
    vapi_call_id: Optional[str] = None,
) -> None:
    if not user_id:
        return
    entries = load_history(user_id)
    changed = False
    for e in entries:
        if (call_sid and e.get("sid") == call_sid) or (
            vapi_call_id and e.get("vapi_call_id") == vapi_call_id
        ):
            if not e.get("recording"):
                e["recording"] = True
                changed = True
    if changed:
        save_history(user_id, entries)


def compute_summary(user_id: str) -> dict:
    entries = load_history(user_id)
    total = len(entries)
    success = sum(1 for e in entries if e.get("status") in SUCCESS_STATUSES)
    failed = sum(1 for e in entries if e.get("status") in FAIL_STATUSES)
    pending = total - success - failed
    success_rate = round(success / total * 100, 1) if total else 0.0

    durations = [
        int(e.get("duration_s") or 0)
        for e in entries
        if e.get("status") in SUCCESS_STATUSES and e.get("duration_s")
    ]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    otp_captured = sum(1 for e in entries if e.get("otp"))
    otp_rate = round(otp_captured / success * 100, 1) if success else 0.0

    modes: Dict[str, dict] = {}
    for e in entries:
        mode = resolve_mode(e)
        m = modes.setdefault(mode, {"total": 0, "success": 0, "otp": 0, "duration_s": 0})
        m["total"] += 1
        if e.get("status") in SUCCESS_STATUSES:
            m["success"] += 1
        if e.get("otp"):
            m["otp"] += 1
        if e.get("duration_s"):
            m["duration_s"] += int(e["duration_s"])

    today = datetime.now().date()
    days = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        count = sum(1 for e in entries if str(e.get("started") or "").startswith(day.isoformat()))
        days.append((day.strftime("%a"), count))

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "success_rate": success_rate,
        "avg_duration": avg_duration,
        "otp_captured": otp_captured,
        "otp_rate": otp_rate,
        "modes": modes,
        "days": days,
    }


def sorted_modes(user_id: str) -> List[str]:
    return sorted({resolve_mode(e) for e in load_history(user_id)})


def format_overview(user_id: str) -> str:
    s = compute_summary(user_id)
    total = s["total"]
    if total == 0:
        return (
            "📊 <b>ANALYTICS — OVERVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No calls recorded yet.\n"
            "Launch your first call to see analytics here."
        )
    week = "  ".join(f"{_safe(label)}:{count}" for label, count in s["days"])
    return "\n".join(
        [
            "📊 <b>ANALYTICS — OVERVIEW</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📞 <b>Total Calls:</b> {total}",
            f"✅ <b>Successful:</b> {s['success']}",
            f"❌ <b>Failed:</b> {s['failed']}",
            f"⏳ <b>Pending:</b> {s['pending']}",
            f"🎯 <b>Success Rate:</b> {s['success_rate']}%",
            f"⏱ <b>Avg Duration:</b> {s['avg_duration']}s",
            f"🔑 <b>OTP Captured:</b> {s['otp_captured']} ({s['otp_rate']}% of successful)",
            "",
            f"📈 <b>Last 7 Days:</b> {week}",
            "",
            f"🗂 <b>Modes Used:</b> {len(s['modes'])}",
        ]
    )


def format_modes(user_id: str) -> str:
    s = compute_summary(user_id)
    if not s["modes"]:
        return "🗂 <b>ANALYTICS — BY MODE</b>\n\nNo call data yet."
    lines = [
        "🗂 <b>ANALYTICS — BY MODE</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for mode, m in sorted(s["modes"].items(), key=lambda kv: -kv[1]["total"]):
        rate = round(m["success"] / m["total"] * 100, 1) if m["total"] else 0.0
        avg = round(m["duration_s"] / m["success"], 1) if m["success"] else 0.0
        lines.append(
            f"▫️ <b>{_safe(mode)}</b>\n"
            f"   📞 {m['total']} · ✅ {m['success']} · 🔑 {m['otp']} · 🎯 {rate}%"
            + (f" · ⏱ {avg}s" if avg else "")
        )
    lines.append("")
    lines.append("💡 Tap a mode below for full details.")
    return "\n".join(lines)


def format_recent(user_id: str, limit: int = 10) -> str:
    entries = load_history(user_id)
    if not entries:
        return "🕐 <b>ANALYTICS — RECENT CALLS</b>\n\nNo calls yet."
    lines = [
        "🕐 <b>ANALYTICS — RECENT CALLS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for e in reversed(entries[-limit:]):
        st = e.get("status", "")
        icon = STATUS_ICONS.get(st, "•")
        mode = resolve_mode(e)
        dur = e.get("duration_s")
        dur_txt = f" · ⏱{dur}s" if dur else ""
        otp_txt = " · 🔑" if e.get("otp") else ""
        rec_txt = " · 🎙" if e.get("recording") else ""
        target = _safe(e.get("target") or "")
        target_txt = f" → {target}" if target else ""
        started = (e.get("started") or "")[:16].replace("T", " ")
        lines.append(
            f"{icon} <b>{_safe(mode)}</b>{target_txt}{dur_txt}{otp_txt}{rec_txt}\n   {started}"
        )
    return "\n".join(lines)


def format_mode_detail(user_id: str, mode: str) -> str:
    entries = [e for e in load_history(user_id) if resolve_mode(e) == mode]
    if not entries:
        return f"🗂 <b>{_safe(mode)}</b>\n\nNo calls in this mode yet."
    total = len(entries)
    success = sum(1 for e in entries if e.get("status") in SUCCESS_STATUSES)
    otp = sum(1 for e in entries if e.get("otp"))
    durations = [int(e.get("duration_s") or 0) for e in entries if e.get("duration_s")]
    avg = round(sum(durations) / len(durations), 1) if durations else 0.0
    rate = round(success / total * 100, 1) if total else 0.0
    lines = [
        f"🗂 <b>ANALYTICS — {_safe(mode)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📞 <b>Total:</b> {total}",
        f"✅ <b>Successful:</b> {success}",
        f"🎯 <b>Success Rate:</b> {rate}%",
        f"⏱ <b>Avg Duration:</b> {avg}s",
        f"🔑 <b>OTP Captured:</b> {otp}",
        "",
        "🕐 <b>Recent:</b>",
    ]
    for e in reversed(entries[-5:]):
        st = e.get("status", "")
        icon = STATUS_ICONS.get(st, "•")
        otp_txt = " 🔑" if e.get("otp") else ""
        rec_txt = " 🎙" if e.get("recording") else ""
        target = _safe(e.get("target") or e.get("sid") or "")
        started = (e.get("started") or "")[:16].replace("T", " ")
        lines.append(f"{icon} {target} · {started}{otp_txt}{rec_txt}")
    return "\n".join(lines)
