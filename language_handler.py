# handlers/language_handler.py
"""
Language selection handler for OTP-Bot-Telegram.
Provides inline keyboard for language selection and updates user's language preference.
Integrates with call flow to generate scripts in the selected language.
"""
import logging
from typing import Optional

from telebot import types

from core.files import write_user_file, read_user_file
from language_service import (
    SUPPORTED_LANGUAGES,
    get_supported_languages_list,
    set_user_language,
    get_user_language,
    get_language_selection_keyboard,
    CALL_TEMPLATES,
)
from menu import send_main_menu

logger = logging.getLogger("OTP-Bot.language_handler")

# ======================================================================
# Language selection menu
# ======================================================================
def send_language_menu(chat_id: int, message_id: Optional[int] = None, user_id_str: Optional[str] = None) -> None:
    """
    Send language selection menu with available languages.
    
    Args:
        chat_id: Telegram chat ID
        message_id: If provided, edit existing message
        user_id_str: User ID (to show current selection)
    """
    if not user_id_str:
        user_id_str = str(chat_id)
    
    current_lang = get_user_language(user_id_str)
    current_flag = SUPPORTED_LANGUAGES.get(current_lang, {}).get("flag", "🇺🇸")
    current_name = SUPPORTED_LANGUAGES.get(current_lang, {}).get("name", "English")
    
    text = (
        "🌍 <b>Language Selection</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Current language: {current_flag} <b>{current_name}</b> ({current_lang.upper()})\n\n"
        "Select your preferred language for call scripts:\n\n"
        f"{get_supported_languages_list()}\n\n"
        "Tap a button to switch languages.\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    keyboard = get_language_selection_keyboard(current_lang, callback_prefix="lang_select_")
    
    # Add back button
    keyboard.row(types.InlineKeyboardButton("↩ Back to Menu", callback_data="back_to_menu"))
    
    if message_id:
        try:
            bot.edit_message_text(
                text,
                chat_id,
                message_id,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"Edit failed, sending new message: {e}")
            bot.send_message(
                chat_id,
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
    else:
        bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

# ======================================================================
# Callback handler for language selection
# ======================================================================
def handle_language_selection_callback(call, user_id_str: str, lang_code: str) -> None:
    """
    Handle language selection callback.
    
    Args:
        call: Callback query object
        user_id_str: User ID
        lang_code: Selected language code
    """
    if lang_code not in SUPPORTED_LANGUAGES:
        bot.answer_callback_query(call.id, "❌ Language not supported.", show_alert=True)
        return
    
    # Set user language
    if set_user_language(user_id_str, lang_code):
        lang_info = SUPPORTED_LANGUAGES[lang_code]
        bot.answer_callback_query(
            call.id,
            f"✅ Language set to {lang_info['flag']} {lang_info['name']}",
            show_alert=False,
        )
        # Refresh the language menu to show updated selection
        send_language_menu(call.message.chat.id, call.message.message_id, user_id_str)
    else:
        bot.answer_callback_query(call.id, "❌ Failed to set language.", show_alert=True)

# ======================================================================
# Register callback handler (to be called from callback_router)
# ======================================================================
def register_language_handlers():
    """Register language-related callbacks with the bot."""
    @bot.callback_query_handler(func=lambda call: call.data.startswith("lang_select_"))
    def language_callback(call):
        user_id_str = str(call.from_user.id)
        lang_code = call.data.replace("lang_select_", "")
        handle_language_selection_callback(call, user_id_str, lang_code)

# ======================================================================
# Add language button to main menu
# ======================================================================
def add_language_button_to_menu(buttons: types.InlineKeyboardMarkup) -> types.InlineKeyboardMarkup:
    """
    Add a language selection button to an existing menu.
    
    Args:
        buttons: Existing InlineKeyboardMarkup
    
    Returns:
        Updated InlineKeyboardMarkup with language button
    """
    # Create a copy of the keyboard and add a new row
    new_buttons = types.InlineKeyboardMarkup(row_width=3)
    
    # Copy existing rows
    for row in buttons.keyboard:
        new_buttons.row(*row)
    
    # Add language button as a new row
    new_buttons.row(types.InlineKeyboardButton("🌍 Language", callback_data="language_menu"))
    
    return new_buttons

# ======================================================================
# Example: Updated send_main_menu with language button
# ======================================================================
# To integrate, replace the existing send_main_menu function in handlers/menu.py with this version:
"""
def send_main_menu(chat_id: int, user, message_id: Optional[int] = None) -> None:
    status_text = get_panel_status_text(str(user.id))
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔱 <b>HOTTBOIIHITZZ PREMIUM PANEL v4.0</b> 🔱\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
        f"{status_text}\n\n"
        "🔥 <b>Premium Controls</b> — Fast access to calls, AI mode, and account tools.\n"
    )
    
    buttons = types.InlineKeyboardMarkup(row_width=3)
    buttons.row(
        types.InlineKeyboardButton("📞 START CALL", callback_data="start_call"),
        types.InlineKeyboardButton("⚡ BULK CALL", callback_data="bulk_call"),
        types.InlineKeyboardButton("🧠 AI MODE", callback_data="ai_mode"),
    )
    buttons.row(
        types.InlineKeyboardButton("👑 ACCOUNT", callback_data="account"),
        types.InlineKeyboardButton("💥 CRACK BLAST", callback_data="crack_blast"),
        types.InlineKeyboardButton("📊 ANALYTICS", callback_data="analytics"),
    )
    buttons.row(
        types.InlineKeyboardButton("🛠 SUPPORT", callback_data="support"),
        types.InlineKeyboardButton("📡 CHANNEL", callback_data="channel"),
        types.InlineKeyboardButton("🎧 LIVE LISTEN", callback_data="live_listen"),
    )
    buttons.row(
        types.InlineKeyboardButton("🤝 VOUCHES", callback_data="vouches"),
        types.InlineKeyboardButton("📅 SCHEDULE", callback_data="schedule_menu"),
        types.InlineKeyboardButton("🌍 LANGUAGE", callback_data="language_menu"),
    )
    buttons.row(
        types.InlineKeyboardButton("💎 SHOP", callback_data="open_shop"),
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
"""

# ======================================================================
# Integration with call flow: use language-aware scripts
# ======================================================================
def get_call_script_with_language(user_id: str, page: str) -> str:
    """
    Get call script in user's selected language.
    This replaces the hardcoded English scripts in prepare_call_audio.
    
    Args:
        user_id: User ID
        page: Page name ('checkifhuman', 'explain', 'askdigits')
    
    Returns:
        Script string in user's language
    """
    from services.language_service import get_call_script
    return get_call_script(user_id, page)

# ======================================================================
# Example: Updated prepare_call_audio in tts_service.py
# ======================================================================
"""
def prepare_call_audio(
    user_id: str,
    mode: str = "normal",
    emotion: str = "neutral",
    voice_id: Optional[str] = None,
) -> None:
    ensure_user_path(user_id)
    if not voice_id:
        voice_id = read_user_file(user_id, "Voice.txt", "")
    
    if mode == "normal":
        name = read_user_file(user_id, "Name.txt", "Customer")
        company = read_user_file(user_id, "Company Name.txt", "your company")
        digits = read_user_file(user_id, "Digits.txt", "6")
        
        # Get scripts in user's language
        from handlers.language_handler import get_call_script_with_language
        texts = {
            "checkifhuman": get_call_script_with_language(user_id, "checkifhuman"),
            "explain": get_call_script_with_language(user_id, "explain"),
            "askdigits": get_call_script_with_language(user_id, "askdigits"),
        }
        # Fallback if language service fails
        if not texts["checkifhuman"]:
            texts = {
                "checkifhuman": f"Hello, I am calling from {company}. Please press 1 to confirm you are {name}.",
                "explain": f"Thank you for confirming, {name}. We have detected suspicious activity and need to verify some details.",
                "askdigits": f"Please enter the {digits} digit code sent to you using your keypad.",
            }
        
        for page, text in texts.items():
            generate_ai(user_id, text, page, voice_id, emotion)
    
    elif mode == "custom":
        script = read_user_file(user_id, "custom_script.txt", "")
        if script:
            generate_ai(user_id, script, "custom_script", voice_id, emotion)
    
    logger.info(f"Audio preparation complete for user {user_id} (mode={mode}, emotion={emotion})")
"""

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    print("Language handler loaded")