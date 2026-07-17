# handlers/scripts_manager.py
"""
Scripts CRUD manager for OTP-Bot-Telegram.
Provides full SQLite-based script management with create, view, edit, delete,
export, import, undo, and pagination. All operations are per-user.
"""
import json
import time
import threading
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from telebot import types
import os
import requests

from core.files import (
    user_conf_path,
    ensure_user_path,
    read_user_file,
    write_user_file,
    set_user_state,
    get_user_state,
    clear_user_state,
)
from menu_utils import MenuLine, render_system_message

logger = logging.getLogger("OTP-Bot.scripts_manager")

# ======================================================================
# Database helpers
# ======================================================================
def get_db_path(user_id_str: str) -> Path:
    """Return path to user's scripts database."""
    return user_conf_path(user_id_str) / "scripts.db"

def init_user_db(user_id_str: str) -> None:
    """Initialize user's scripts database with schema."""
    ensure_user_path(user_id_str)
    db_path = get_db_path(user_id_str)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        logger.debug(f"Initialized scripts DB for user {user_id_str}")
    except Exception as e:
        logger.error(f"DB init error for {user_id_str}: {e}")

def db_add_script(user_id_str: str, content: str) -> bool:
    """Add a new script to database."""
    init_user_db(user_id_str)
    db_path = get_db_path(user_id_str)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO scripts (user_id, content) VALUES (?, ?)",
            (user_id_str, content)
        )
        conn.commit()
        conn.close()
        logger.debug(f"Added script for user {user_id_str}: {content[:50]}...")
        return True
    except Exception as e:
        logger.error(f"DB add error: {e}")
        return False

def db_get_scripts(user_id_str: str) -> List[str]:
    """Get all scripts for user ordered by creation date."""
    db_path = get_db_path(user_id_str)
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT content FROM scripts WHERE user_id = ? ORDER BY created_at ASC",
            (user_id_str,)
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"DB get error: {e}")
        return []

def db_get_script_by_index(user_id_str: str, idx: int) -> Optional[str]:
    """Get script at given index (1-based)."""
    scripts = db_get_scripts(user_id_str)
    if 1 <= idx <= len(scripts):
        return scripts[idx - 1]
    return None

def db_update_script_by_index(user_id_str: str, idx: int, new_content: str) -> bool:
    """Update script at given index (1-based)."""
    db_path = get_db_path(user_id_str)
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT id FROM scripts WHERE user_id = ? ORDER BY created_at ASC LIMIT 1 OFFSET ?",
            (user_id_str, idx - 1)
        ).fetchone()
        if not row:
            conn.close()
            return False
        script_id = row[0]
        conn.execute(
            "UPDATE scripts SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_content, script_id)
        )
        conn.commit()
        conn.close()
        logger.debug(f"Updated script #{idx} for user {user_id_str}")
        return True
    except Exception as e:
        logger.error(f"DB update error: {e}")
        return False

def db_delete_script_by_index(user_id_str: str, idx: int) -> Optional[str]:
    """Delete script at given index (1-based) and return its content for undo."""
    db_path = get_db_path(user_id_str)
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT id, content FROM scripts WHERE user_id = ? ORDER BY created_at ASC LIMIT 1 OFFSET ?",
            (user_id_str, idx - 1)
        ).fetchone()
        if not row:
            conn.close()
            return None
        script_id, content = row
        conn.execute("DELETE FROM scripts WHERE id = ?", (script_id,))
        conn.commit()
        conn.close()
        logger.debug(f"Deleted script #{idx} for user {user_id_str}")
        return content
    except Exception as e:
        logger.error(f"DB delete error: {e}")
        return None

def db_replace_scripts(user_id_str: str, scripts_list: List[str]) -> bool:
    """Replace all scripts with provided list."""
    db_path = get_db_path(user_id_str)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM scripts WHERE user_id = ?", (user_id_str,))
        for content in scripts_list:
            conn.execute(
                "INSERT INTO scripts (user_id, content) VALUES (?, ?)",
                (user_id_str, content)
            )
        conn.commit()
        conn.close()
        logger.debug(f"Replaced all scripts for user {user_id_str} with {len(scripts_list)} scripts")
        return True
    except Exception as e:
        logger.error(f"DB replace error: {e}")
        return False

def db_merge_scripts(user_id_str: str, scripts_list: List[str]) -> int:
    """Merge scripts_list with existing scripts (duplicates skipped)."""
    existing = db_get_scripts(user_id_str)
    existing_set = set(existing)
    new_count = 0
    for script in scripts_list:
        if script not in existing_set:
            if db_add_script(user_id_str, script):
                new_count += 1
    return new_count

# ======================================================================
# Undo functionality (60-second window)
# ======================================================================
def store_deleted_script(user_id_str: str, idx: int, content: str) -> None:
    """Store deleted script for 60-second undo window."""
    user_dir = user_conf_path(user_id_str)
    undo_file = user_dir / "last_deleted_script.txt"
    try:
        with open(undo_file, "w", encoding="utf-8") as f:
            f.write(f"{int(time.time())}\n{idx}\n{content}")
        # Auto-clear after 60 seconds
        def _clear():
            try:
                if undo_file.exists():
                    undo_file.unlink()
            except:
                pass
        timer = threading.Timer(60.0, _clear)
        timer.daemon = True
        timer.start()
        logger.debug(f"Stored deleted script #{idx} for undo (60s window)")
    except Exception as e:
        logger.error(f"Failed to store undo data: {e}")

def get_deleted_script(user_id_str: str) -> Optional[tuple]:
    """Get deleted script data for undo."""
    undo_file = user_conf_path(user_id_str) / "last_deleted_script.txt"
    if not undo_file.exists():
        return None
    try:
        lines = undo_file.read_text(encoding="utf-8").splitlines()
        if len(lines) < 3:
            return None
        ts = int(lines[0]) if lines[0].isdigit() else 0
        if time.time() - ts > 60:
            undo_file.unlink()
            return None
        idx = int(lines[1]) if lines[1].isdigit() else 0
        content = "\n".join(lines[2:])
        return idx, content
    except Exception as e:
        logger.error(f"Error reading undo data: {e}")
        return None

def clear_undo_data(user_id_str: str) -> None:
    """Clear undo data."""
    undo_file = user_conf_path(user_id_str) / "last_deleted_script.txt"
    try:
        if undo_file.exists():
            undo_file.unlink()
    except:
        pass

# ======================================================================
# Menu rendering functions
# ======================================================================
def open_scripts_menu(chat_id: int, message_id: Optional[int] = None, user_id_str: Optional[str] = None) -> None:
    """Show scripts manager main menu."""
    if not user_id_str:
        user_id_str = str(chat_id)
    script_count = len(db_get_scripts(user_id_str))
    text = (
        "⚜️ <b>HOTTBOIIHITZZ · SCRIPTS MANAGER</b> ⚜️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Your Scripts:</b> <code>{script_count}</code>\n\n"
        "<b>⚡ Premium Features:</b>\n"
        "✓ SQLite Powered\n"
        "✓ Real-time Sync\n"
        "✓ Instant Export/Import\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    buttons.row(
        types.InlineKeyboardButton("✨ CREATE NEW", callback_data="create_script"),
        types.InlineKeyboardButton("📚 MY LIBRARY", callback_data="my_scripts")
    )
    buttons.row(
        types.InlineKeyboardButton("📥 IMPORT", callback_data="scripts_import_start"),
        types.InlineKeyboardButton("💾 EXPORT", callback_data="scripts_export")
    )
    buttons.row(types.InlineKeyboardButton("⬅️ BACK TO ACCOUNT", callback_data="account"))
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=buttons, parse_mode="HTML")

def create_script(call, user_id_str: str) -> None:
    """Start script creation flow."""
    set_user_state(user_id_str, "creating_script")
    init_user_db(user_id_str)
    write_user_file(user_id_str, "last_panel_msg.txt", str(call.message.message_id))
    text = (
        "✨ <b>CREATE NEW SCRIPT</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📝 <b>Script Creation Mode</b>\n\n"
        "Send your script text below:\n"
        "• Max 1000 characters\n"
        "• Clear & concise format\n"
        "• Supports voice prompts\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    buttons.row(types.InlineKeyboardButton("❌ CANCEL", callback_data="open_scripts"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")

def my_scripts(call, user_id_str: str) -> None:
    """Show user's script library with pagination."""
    page = 1
    if call.data.startswith("my_scripts_page_"):
        try:
            page = int(call.data.split("_")[-1])
        except:
            page = 1
    set_user_state(user_id_str, '')
    write_user_file(user_id_str, 'last_panel_msg.txt', str(call.message.message_id))
    scripts = db_get_scripts(user_id_str)
    if not scripts:
        text = (
            "📚 <b>MY SCRIPT LIBRARY</b> 📚\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ <b>No Scripts Yet</b>\n\n"
            "Your library is empty. Create your first script now!\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        buttons = types.InlineKeyboardMarkup()
        buttons.row(types.InlineKeyboardButton("✨ CREATE FIRST SCRIPT", callback_data="create_script"))
        buttons.row(types.InlineKeyboardButton("⬅️ BACK", callback_data="open_scripts"))
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")
        return
    page_size = 3
    total_pages = (len(scripts) + page_size - 1) // page_size
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_scripts = scripts[start_idx:end_idx]
    script_items = []
    for i, script in enumerate(page_scripts):
        idx = start_idx + i + 1
        preview = script[:45] + "..." if len(script) > 45 else script
        script_items.append(f"#{idx} <code>{preview}</code>")
    script_list = "\n".join(script_items)
    text = (
        "📚 <b>MY SCRIPT LIBRARY</b> 📚\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>Total:</b> <code>{len(scripts)}</code> | "
        f"<b>Page:</b> <code>{page}/{total_pages}</code>\n\n"
        f"<b>Scripts:</b>\n{script_list}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    for i, script in enumerate(page_scripts):
        idx = start_idx + i + 1
        buttons.row(
            types.InlineKeyboardButton(f"👁️ #{idx}", callback_data=f"script_view_{idx}"),
            types.InlineKeyboardButton(f"✏️ #{idx}", callback_data=f"script_edit_{idx}"),
            types.InlineKeyboardButton(f"🗑️ #{idx}", callback_data=f"script_delete_{idx}")
        )
    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(types.InlineKeyboardButton("⬅️ PREV", callback_data=f"my_scripts_page_{page-1}"))
        if page < total_pages:
            nav_buttons.append(types.InlineKeyboardButton("NEXT ➡️", callback_data=f"my_scripts_page_{page+1}"))
        if nav_buttons:
            buttons.row(*nav_buttons)
    buttons.row(types.InlineKeyboardButton("✨ NEW SCRIPT", callback_data="create_script"))
    buttons.row(types.InlineKeyboardButton("⬅️ BACK", callback_data="open_scripts"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")

def script_view(call, user_id_str: str) -> None:
    """View a single script."""
    try:
        idx = int(call.data.split("_")[-1])
    except:
        bot.answer_callback_query(call.id, "❌ Invalid script", show_alert=True)
        return
    script = db_get_script_by_index(user_id_str, idx)
    if not script:
        bot.answer_callback_query(call.id, "❌ Script not found", show_alert=True)
        return
    text = (
        f"👁️ <b>VIEW SCRIPT #{idx}</b> 👁️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Content:</b>\n<code>{script}</code>\n\n"
        f"<b>Length:</b> <code>{len(script)}</code> chars\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    buttons.row(
        types.InlineKeyboardButton("✏️ EDIT", callback_data=f"script_edit_{idx}"),
        types.InlineKeyboardButton("🗑️ DELETE", callback_data=f"script_delete_{idx}")
    )
    buttons.row(types.InlineKeyboardButton("⬅️ BACK TO LIBRARY", callback_data="my_scripts"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")

def script_edit(call, user_id_str: str) -> None:
    """Start script editing flow."""
    try:
        idx = int(call.data.split("_")[-1])
    except:
        bot.answer_callback_query(call.id, "❌ Invalid script", show_alert=True)
        return
    script = db_get_script_by_index(user_id_str, idx)
    if not script:
        bot.answer_callback_query(call.id, "❌ Script not found", show_alert=True)
        return
    write_user_file(user_id_str, "editing_script_idx.txt", str(idx))
    set_user_state(user_id_str, "editing_script")
    write_user_file(user_id_str, "last_panel_msg.txt", str(call.message.message_id))
    text = (
        f"✏️ <b>EDIT SCRIPT #{idx}</b> ✏️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>Current Content:</b>\n<code>{script[:100]}{'...' if len(script) > 100 else ''}</code>\n\n"
        "<b>Instructions:</b>\n"
        "Send the new script text:\n"
        "• Max 1000 characters\n"
        "• Press Cancel to discard\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    buttons.row(types.InlineKeyboardButton("❌ CANCEL", callback_data=f"script_view_{idx}"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")

def script_delete(call, user_id_str: str) -> None:
    """Delete script (confirmation or execution)."""
    try:
        idx = int(call.data.split("_")[-1])
    except:
        bot.answer_callback_query(call.id, "❌ Invalid script", show_alert=True)
        return
    if "confirm" in call.data:
        # Execute deletion
        removed = db_delete_script_by_index(user_id_str, idx)
        if removed is None:
            bot.answer_callback_query(call.id, "❌ Script not found", show_alert=True)
            return
        store_deleted_script(user_id_str, idx, removed)
        text = (
            "✅ <b>SCRIPT DELETED</b> ✅\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Deleted Script #{idx}</b>\n\n"
            "⏱️ <b>UNDO AVAILABLE FOR 60 SECONDS</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        buttons = types.InlineKeyboardMarkup()
        buttons.row(
            types.InlineKeyboardButton("↩️ UNDO NOW", callback_data="script_undo"),
            types.InlineKeyboardButton("📚 LIBRARY", callback_data="my_scripts")
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")
        bot.answer_callback_query(call.id, "Script deleted. Undo available for 60 seconds.")
    else:
        # Show confirmation
        script = db_get_script_by_index(user_id_str, idx)
        if not script:
            bot.answer_callback_query(call.id, "❌ Script not found", show_alert=True)
            return
        preview = script[:70] + "..." if len(script) > 70 else script
        text = (
            f"🗑️ <b>DELETE SCRIPT #{idx}</b> 🗑️\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚠️ <b>CONFIRMATION REQUIRED</b> ⚠️\n\n"
            f"<b>Script:</b>\n<code>{preview}</code>\n\n"
            "💡 <b>UNDO available for 60 seconds</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        buttons = types.InlineKeyboardMarkup()
        buttons.row(
            types.InlineKeyboardButton("✅ CONFIRM DELETE", callback_data=f"script_confirm_delete_{idx}"),
            types.InlineKeyboardButton("❌ CANCEL", callback_data=f"script_view_{idx}")
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
        except:
            bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")
        bot.answer_callback_query(call.id)

def script_undo(call, user_id_str: str) -> None:
    """Undo last deletion (60s window)."""
    undo_data = get_deleted_script(user_id_str)
    if not undo_data:
        bot.send_message(call.message.chat.id, "⏱️ <b>UNDO WINDOW EXPIRED</b>\n\nThe 60-second undo window has closed.")
        bot.answer_callback_query(call.id)
        return
    idx, content = undo_data
    db_add_script(user_id_str, content)
    clear_undo_data(user_id_str)
    text = (
        "↩️ <b>SCRIPT RESTORED</b> ↩️\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Script successfully restored to your library\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    buttons.row(types.InlineKeyboardButton("📚 BACK TO LIBRARY", callback_data="my_scripts"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")
    bot.answer_callback_query(call.id, "Script restored.")

# ======================================================================
# Export scripts (JSON)
# ======================================================================
def scripts_export(call, user_id_str: str) -> None:
    """Export all scripts as JSON file."""
    scripts = db_get_scripts(user_id_str)
    if not scripts:
        bot.send_message(call.message.chat.id, "❌ No scripts to export.")
        bot.answer_callback_query(call.id)
        return
    try:
        export_data = json.dumps({
            "scripts": scripts,
            "exported_at": datetime.now().isoformat()
        }, indent=2)
        user_dir = user_conf_path(user_id_str)
        export_file = user_dir / f"scripts_export_{int(time.time())}.json"
        export_file.write_text(export_data, encoding="utf-8")
        with open(export_file, "rb") as f:
            bot.send_document(
                call.message.chat.id,
                f,
                caption=(
                    f"💾 <b>EXPORT SUCCESSFUL</b> 💾\n\n"
                    f"✅ Exported <code>{len(scripts)}</code> scripts\n"
                    f"📦 File: <code>scripts_export.json</code>"
                ),
                parse_mode="HTML"
            )
        export_file.unlink()
        bot.answer_callback_query(call.id, "Export successful.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Export failed: {e}")
        bot.answer_callback_query(call.id, "Export failed.")

# ======================================================================
# Import scripts (JSON)
# ======================================================================
def scripts_import_start(call, user_id_str: str) -> None:
    """Start import flow (file upload)."""
    set_user_state(user_id_str, "importing_scripts")
    write_user_file(user_id_str, "last_panel_msg.txt", str(call.message.message_id))
    text = (
        "📥 <b>IMPORT SCRIPTS</b> 📥\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📤 <b>Upload JSON File</b>\n\n"
        "Send a JSON file exported from this bot:\n"
        "• Max 100 scripts per import\n"
        "• .json format required\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    buttons = types.InlineKeyboardMarkup()
    buttons.row(types.InlineKeyboardButton("❌ CANCEL", callback_data="open_scripts"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=buttons, parse_mode="HTML")
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=buttons, parse_mode="HTML")
    bot.answer_callback_query(call.id)

def scripts_import_file(message, user_id_str: str) -> None:
    """Process uploaded JSON file."""
    if not message.document or not message.document.file_name.endswith('.json'):
        bot.send_message(message.chat.id, "❌ Please send a .json file.")
        return
    try:
        file_info = bot.get_file(message.document.file_id)
        data = requests.get(
            f"https://tg-api-proxy.zaddocklangat8.workers.dev/bot{BOT_TOKEN}/{file_info.file_path}"
        ).json()
        if 'scripts' not in data or not isinstance(data['scripts'], list):
            bot.send_message(message.chat.id, "❌ Invalid JSON format. 'scripts' array missing.")
            return
        scripts_to_import = data['scripts']
        if len(scripts_to_import) > 100:
            bot.send_message(message.chat.id, f"⚠️ Too many scripts ({len(scripts_to_import)}). Max 100.")
            return
        user_dir = user_conf_path(user_id_str)
        import_file = user_dir / "import_pending.json"
        import_file.write_text(json.dumps(scripts_to_import), encoding="utf-8")
        text = (
            "✅ <b>FILE LOADED SUCCESSFULLY</b> ✅\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Found <code>{len(scripts_to_import)}</code> scripts\n\n"
            "🔄 <b>Import Mode:</b>\n\n"
            "• <b>MERGE:</b> Add new scripts, keep existing\n"
            "• <b>REPLACE:</b> Clear all, import these\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        buttons = types.InlineKeyboardMarkup()
        buttons.row(
            types.InlineKeyboardButton("🔄 MERGE", callback_data="scripts_import_merge"),
            types.InlineKeyboardButton("✏️ REPLACE", callback_data="scripts_import_replace")
        )
        buttons.row(types.InlineKeyboardButton("❌ CANCEL", callback_data="open_scripts"))
        bot.send_message(message.chat.id, text, reply_markup=buttons, parse_mode="HTML")
        clear_user_state(user_id_str)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Import error: {e}")

def scripts_import_confirm(call, user_id_str: str, mode: str) -> None:
    """Confirm import (merge or replace)."""
    user_dir = user_conf_path(user_id_str)
    import_file = user_dir / "import_pending.json"
    if not import_file.exists():
        bot.answer_callback_query(call.id, "❌ No import file found.", show_alert=True)
        return
    try:
        scripts_to_import = json.loads(import_file.read_text())
        if mode == "merge":
            count = db_merge_scripts(user_id_str, scripts_to_import)
            bot.send_message(call.message.chat.id, f"✅ Merged {count} new scripts.")
        else:  # replace
            db_replace_scripts(user_id_str, scripts_to_import)
            bot.send_message(call.message.chat.id, f"✅ Replaced with {len(scripts_to_import)} scripts.")
        import_file.unlink()
        bot.answer_callback_query(call.id, "Import successful.")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Import failed: {e}")
        bot.answer_callback_query(call.id, "Import failed.")

# ======================================================================
# Message handler for script creation/editing
# ======================================================================
def handle_script_text(message, user_id_str: str) -> None:
    """Handle text input during script creation or editing."""
    state = get_user_state(user_id_str)
    text = message.text.strip()
    
    if state == "creating_script":
        if not text:
            bot.send_message(message.chat.id, "❌ Script cannot be empty.")
            return
        if len(text) > 1000:
            bot.send_message(message.chat.id, "❌ Script too long (max 1000 chars).")
            return
        if db_add_script(user_id_str, text):
            clear_user_state(user_id_str)
            bot.send_message(
                message.chat.id,
                "✅ Script created successfully!",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("📚 My Scripts", callback_data="my_scripts")
                )
            )
        else:
            bot.send_message(message.chat.id, "❌ Failed to create script.")
    
    elif state == "editing_script":
        idx_str = read_user_file(user_id_str, "editing_script_idx.txt", "")
        if not idx_str or not idx_str.isdigit():
            clear_user_state(user_id_str)
            bot.send_message(message.chat.id, "❌ Editing session lost.")
            return
        idx = int(idx_str)
        if not text:
            bot.send_message(message.chat.id, "❌ Script cannot be empty.")
            return
        if len(text) > 1000:
            bot.send_message(message.chat.id, "❌ Script too long (max 1000 chars).")
            return
        if db_update_script_by_index(user_id_str, idx, text):
            clear_user_state(user_id_str)
            bot.send_message(
                message.chat.id,
                f"✅ Script #{idx} updated!",
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("📚 My Scripts", callback_data="my_scripts")
                )
            )
        else:
            bot.send_message(message.chat.id, "❌ Update failed.")
    
    elif state == "importing_scripts":
        bot.send_message(message.chat.id, "📤 Please upload a JSON file, not text.")

# ======================================================================
# Register handlers with bot (called from main)
# ======================================================================
def register_scripts_handlers():
    """Register all scripts-related handlers with the bot."""
    @bot.callback_query_handler(func=lambda call: call.data in ["open_scripts", "create_script", "my_scripts", "scripts_export", "scripts_import_start", "scripts_import_merge", "scripts_import_replace"])
    def scripts_callback(call):
        user_id_str = str(call.from_user.id)
        if call.data == "open_scripts":
            open_scripts_menu(call.message.chat.id, call.message.message_id, user_id_str)
        elif call.data == "create_script":
            create_script(call, user_id_str)
        elif call.data == "my_scripts":
            my_scripts(call, user_id_str)
        elif call.data == "scripts_export":
            scripts_export(call, user_id_str)
        elif call.data == "scripts_import_start":
            scripts_import_start(call, user_id_str)
        elif call.data == "scripts_import_merge":
            scripts_import_confirm(call, user_id_str, "merge")
        elif call.data == "scripts_import_replace":
            scripts_import_confirm(call, user_id_str, "replace")
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("script_view_") or call.data.startswith("script_edit_") or call.data.startswith("script_delete_") or call.data.startswith("script_confirm_delete_"))
    def script_crud_callback(call):
        user_id_str = str(call.from_user.id)
        if call.data.startswith("script_view_"):
            script_view(call, user_id_str)
        elif call.data.startswith("script_edit_"):
            script_edit(call, user_id_str)
        elif call.data.startswith("script_delete_"):
            script_delete(call, user_id_str)
        elif call.data.startswith("script_confirm_delete_"):
            script_delete(call, user_id_str)
    
    @bot.callback_query_handler(func=lambda call: call.data == "script_undo")
    def undo_callback(call):
        user_id_str = str(call.from_user.id)
        script_undo(call, user_id_str)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("my_scripts_page_"))
    def pagination_callback(call):
        user_id_str = str(call.from_user.id)
        my_scripts(call, user_id_str)

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    print("Scripts manager loaded")