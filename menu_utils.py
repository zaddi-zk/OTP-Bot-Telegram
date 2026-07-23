# menu_utils.py
"""
Utilities for building consistent, styled Telegram menus with icons,
voice selection keyboards, and rich text formatting.
"""
import html
import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from telebot import types

# ======================================================================
# Icon assets
# ======================================================================
class MenuIcons(Dict[str, str]):
    """Typed dictionary for menu icon assets."""
    pass

ICON_ASSETS: MenuIcons = {
    "system": "🏛️",
    "settings": "⚙️",
    "terminal": "💻",
    "success": "✅",
    "warning": "⚠️",
    "info": "ℹ️",
    "back": "↩",
    "forward": "➡️",
    "section": "📚",
    "action": "🔧",
    "node": "🧩",
    "link": "🔗",
    "phone": "📞",
    "star": "⭐",
    "crown": "👑",
    "fire": "🔥",
    "shield": "🛡️",
    "bolt": "⚡",
    "brain": "🧠",
    "bomb": "💣",
    "chart": "📊",
    "headphones": "🎧",
    "calendar": "📅",
    "handshake": "🤝",
    "shop": "💎",
    "account": "👤",
    "support": "🛠️",
    "channel": "📡",
    "vouch": "🤝",
    "live": "🎙️",
}

LIVE_STATE_ICONS: MenuIcons = {
    "active": "🟢",
    "inactive": "🔴",
    "selected": "🔘",
    "unselected": "⚪",
    "processing": "⚡",
    "idle": "💤",
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
}

# ======================================================================
# String utilities
# ======================================================================
def safe_text(value: Optional[str]) -> str:
    """Convert optional value to HTML‑escaped string."""
    return html.escape(str(value or ""))

def escape_markdown_v2(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in escape_chars else c for c in text)

# ======================================================================
# Menu rendering
# ======================================================================
@dataclass
class MenuLine:
    label: str
    value: Optional[str] = None
    icon: Optional[str] = None

    def render(self) -> str:
        label_safe = safe_text(self.label)
        value_safe = safe_text(self.value or "")
        icon_prefix = f"{self.icon} " if self.icon else ""
        return f"{icon_prefix}<b>{label_safe}</b>: <code>{value_safe}</code>"

def render_system_message(
    title: str,
    subtitle: Optional[str] = None,
    lines: Optional[Sequence[MenuLine]] = None,
    icons: Optional[Mapping[str, str]] = None,
) -> str:
    """Render a responsive HTML menu card with clear visual hierarchy."""
    icons = {**ICON_ASSETS, **(icons or {})}
    title_text = f"{icons.get('system')} <b>{safe_text(title)}</b>"
    subtitle_text = f"\n<em>{safe_text(subtitle)}</em>" if subtitle else ""
    body_lines: List[str] = [title_text + subtitle_text, "\n"]

    if lines:
        for line in lines:
            body_lines.append(line.render())

    body_lines.append("\n<code>Tip:</code> Use the buttons below or type your selection.")
    return "\n".join(body_lines)

def render_status_block(
    status_name: str,
    state: str,
    details: Optional[str] = None,
    icons: Optional[Mapping[str, str]] = None,
) -> str:
    """Render a compact operational status block."""
    icons = {**ICON_ASSETS, **(icons or {})}
    state_icon = icons.get(state.lower(), icons.get("info", "ℹ️"))
    header = f"{state_icon} <b>{safe_text(status_name)}</b>"
    footer = f"<code>{safe_text(details)}</code>" if details else ""
    return f"{header}\n{footer}"

def get_selection_emoji(is_selected: bool, icons: Optional[Mapping[str, str]] = None) -> str:
    """Return selected/unselected emoji."""
    icons = {**LIVE_STATE_ICONS, **(icons or {})}
    return icons["selected"] if is_selected else icons["unselected"]

# ======================================================================
# Voice selection keyboard builder
# ======================================================================
def build_voice_selection_keyboard(
    voice_mapping: Mapping[str, Mapping[str, str]],
    selected_voice_id: Optional[str] = None,
    callback_prefix: str = "voice_select_",
    row_width: int = 2,
    icons: Optional[Mapping[str, str]] = None,
) -> types.InlineKeyboardMarkup:
    """
    Build a voice selection keyboard using PREMIUM_VOICES.
    """
    icons = {**LIVE_STATE_ICONS, **(icons or {})}
    keyboard = types.InlineKeyboardMarkup(row_width=row_width)
    if not voice_mapping:
        return keyboard

    sorted_items = sorted(
        voice_mapping.items(),
        key=lambda item: item[1].get("name", "").lower()
    )
    buttons: List[types.InlineKeyboardButton] = []

    for voice_id, metadata in sorted_items:
        name = metadata.get("name", f"Voice {voice_id}")
        voice_key = metadata.get("id", voice_id)
        is_selected = selected_voice_id is not None and selected_voice_id == voice_key
        marker = icons["selected"] if is_selected else icons["unselected"]
        label = f"{marker} {html.escape(name)}"
        callback_data = f"{callback_prefix}{html.escape(voice_key)}"
        buttons.append(types.InlineKeyboardButton(label, callback_data=callback_data))

    for i in range(0, len(buttons), row_width):
        keyboard.row(*buttons[i : i + row_width])

    return keyboard

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    # Test voice keyboard
    test_mapping = {
        "1": {"name": "Hannah", "id": "TEST_VOICE_ID_1"},
        "2": {"name": "Joyce", "id": "TEST_VOICE_ID_2"},
    }
    kb = build_voice_selection_keyboard(test_mapping, test_mapping["1"]["id"])
    print(kb)