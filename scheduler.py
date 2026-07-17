# services/scheduler.py
"""
Scheduled calls service for OTP-Bot-Telegram.
Runs a background thread that checks for due scheduled calls and executes them.
Supports persistent storage of schedules in user's conf directory.
Enhanced with recurrence: 'none' (one‑time), 'daily', 'weekly', 'monthly'.
"""
import json
import time
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from config import NGROK_URL, TWILIO_PHONE_NUMBER
from twilio_service import make_call_with_retry
from services.tts_service import prepare_call_audio
from core.files import (
    user_conf_path, ensure_user_path, read_user_file, write_user_file
)

logger = logging.getLogger("OTP-Bot.scheduler")

# ======================================================================
# Schedule storage and management
# ======================================================================
def load_schedules(user_id: str) -> List[Dict]:
    """
    Load all scheduled calls for a user.
    
    Args:
        user_id: User ID
    
    Returns:
        List of schedule dictionaries
    """
    schedule_path = user_conf_path(user_id) / "scheduled_calls.json"
    if not schedule_path.exists():
        return []
    try:
        with open(schedule_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load schedules for user {user_id}: {e}")
        return []

def save_schedules(user_id: str, schedules: List[Dict]) -> None:
    """
    Save scheduled calls for a user.
    
    Args:
        user_id: User ID
        schedules: List of schedule dictionaries
    """
    schedule_path = user_conf_path(user_id) / "scheduled_calls.json"
    with open(schedule_path, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2)

def add_schedule(
    user_id: str,
    phone: str,
    scheduled_time: datetime,
    emotion: str = "neutral",
    recurrence: str = "none",
) -> bool:
    """
    Add a new scheduled call.
    
    Args:
        user_id: User ID
        phone: Target phone number (E.164 format)
        scheduled_time: Datetime when call should be made
        emotion: Emotion for TTS
        recurrence: 'none', 'daily', 'weekly', 'monthly'
    
    Returns:
        True if added successfully, False otherwise
    """
    schedules = load_schedules(user_id)
    # Check for duplicate pending schedules
    for sched in schedules:
        if sched.get("status") == "pending":
            existing_time = datetime.fromisoformat(sched["time"])
            if existing_time == scheduled_time and sched.get("phone") == phone:
                logger.warning(f"Duplicate schedule for {phone} at {scheduled_time}")
                return False
    
    schedules.append({
        "phone": phone,
        "time": scheduled_time.isoformat(),
        "created": datetime.now().isoformat(),
        "user_id": user_id,
        "emotion": emotion,
        "recurrence": recurrence,
        "status": "pending",
        "sid": None,
    })
    save_schedules(user_id, schedules)
    logger.info(f"Scheduled call added for user {user_id}: {phone} at {scheduled_time} ({recurrence})")
    return True

def remove_schedule(user_id: str, index: int) -> bool:
    """
    Remove a scheduled call by index.
    
    Args:
        user_id: User ID
        index: Index in the schedules list
    
    Returns:
        True if removed, False if index invalid
    """
    schedules = load_schedules(user_id)
    if 0 <= index < len(schedules):
        removed = schedules.pop(index)
        save_schedules(user_id, schedules)
        logger.info(f"Removed schedule for user {user_id}: {removed.get('phone')}")
        return True
    return False

def clear_completed_schedules(user_id: str) -> int:
    """
    Remove all completed/failed schedules (non‑recurring only).
    Recurring schedules remain with status 'pending'.
    
    Args:
        user_id: User ID
    
    Returns:
        Number of schedules removed
    """
    schedules = load_schedules(user_id)
    before = len(schedules)
    schedules = [
        s for s in schedules
        if s.get("status") == "pending" or s.get("recurrence") != "none"
    ]
    after = len(schedules)
    if before != after:
        save_schedules(user_id, schedules)
        logger.info(f"Cleared {before - after} completed/failed non‑recurring schedules for user {user_id}")
    return before - after

# ======================================================================
# Recurrence helpers
# ======================================================================
def _next_occurrence(current_time: datetime, recurrence: str) -> Optional[datetime]:
    """
    Calculate the next occurrence time based on recurrence type.
    
    Args:
        current_time: The time of the current occurrence
        recurrence: 'daily', 'weekly', 'monthly', or 'none'
    
    Returns:
        Datetime of next occurrence, or None if no recurrence
    """
    if recurrence == "daily":
        return current_time + timedelta(days=1)
    elif recurrence == "weekly":
        return current_time + timedelta(days=7)
    elif recurrence == "monthly":
        # Add one month (approximate)
        year = current_time.year
        month = current_time.month + 1
        if month > 12:
            month = 1
            year += 1
        day = current_time.day
        # Handle month length
        max_day = {
            1: 31, 2: 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31
        }.get(month, 31)
        day = min(day, max_day)
        return datetime(year, month, day, current_time.hour, current_time.minute)
    else:
        return None

# ======================================================================
# Schedule executor (background thread)
# ======================================================================
def _execute_scheduled_call(user_id: str, sched: Dict) -> None:
    """
    Execute a single scheduled call.
    
    Args:
        user_id: User ID
        sched: Schedule dictionary
    """
    phone = sched.get("phone")
    emotion = sched.get("emotion", "neutral")
    
    if not phone:
        logger.error(f"Invalid schedule: no phone number for user {user_id}")
        sched["status"] = "failed"
        return
    
    # Prepare user data
    name = read_user_file(user_id, "Name.txt", "Customer")
    company = read_user_file(user_id, "Company Name.txt", "")
    digits = read_user_file(user_id, "Digits.txt", "6")
    
    # Write temporary files for this call
    write_user_file(user_id, "Name.txt", name)
    write_user_file(user_id, "Company Name.txt", company)
    write_user_file(user_id, "Digits.txt", digits)
    
    # Prepare audio
    prepare_call_audio(user_id, mode="normal", emotion=emotion)
    
    # Build webhook URL
    webhook_url = f"{NGROK_URL}/voice?user_id={user_id}&emotion={emotion}"
    caller_id = read_user_file(user_id, "Caller ID.txt", TWILIO_PHONE_NUMBER)
    
    # Make the call with retry
    sid = make_call_with_retry(
        to=phone,
        from_number=TWILIO_PHONE_NUMBER,
        caller_id=caller_id,
        webhook_url=webhook_url,
        user_id=user_id,
        max_retries=2,
        base_delay=5,
    )
    
    if sid:
        sched["status"] = "completed"
        sched["sid"] = sid
        logger.info(f"Scheduled call executed: {phone} -> {sid}")
    else:
        sched["status"] = "failed"
        logger.warning(f"Scheduled call failed: {phone}")

# ======================================================================
# Main scheduler loop
# ======================================================================
def _scheduler_loop() -> None:
    """
    Main scheduler loop that checks for due calls every 60 seconds.
    Handles recurrence by re‑adding the next occurrence after execution.
    """
    logger.info("Scheduler loop started")
    
    while True:
        try:
            # Scan all user folders
            conf_dir = Path("conf")
            if not conf_dir.exists():
                time.sleep(60)
                continue
            
            for user_folder in conf_dir.iterdir():
                if not user_folder.is_dir():
                    continue
                
                user_id = user_folder.name
                schedules = load_schedules(user_id)
                updated = False
                
                for sched in schedules:
                    if sched.get("status") != "pending":
                        continue
                    
                    target_time = datetime.fromisoformat(sched["time"])
                    if datetime.now() >= target_time:
                        # Execute the call
                        _execute_scheduled_call(user_id, sched)
                        updated = True
                        
                        # Handle recurrence
                        recurrence = sched.get("recurrence", "none")
                        if recurrence != "none":
                            # Calculate next occurrence
                            next_time = _next_occurrence(target_time, recurrence)
                            if next_time:
                                # Add a new schedule for the next occurrence
                                add_schedule(
                                    user_id,
                                    sched["phone"],
                                    next_time,
                                    sched.get("emotion", "neutral"),
                                    recurrence
                                )
                                logger.info(f"Recurring schedule: next call at {next_time}")
                        # The original schedule is now completed/failed (we keep it for history)
                
                if updated:
                    save_schedules(user_id, schedules)
            
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
        
        time.sleep(60)

# ======================================================================
# Start scheduler thread
# ======================================================================
_scheduler_thread = None

def start_scheduler() -> None:
    """
    Start the background scheduler thread.
    Should be called once at application startup.
    """
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        logger.warning("Scheduler already running")
        return
    
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="OTP-Bot-Scheduler"
    )
    _scheduler_thread.start()
    logger.info("Scheduler background thread started")

# ======================================================================
# Utility functions for Telegram handlers
# ======================================================================
def format_schedule_list(user_id: str) -> str:
    """
    Format list of pending schedules for display in Telegram.
    
    Args:
        user_id: User ID
    
    Returns:
        Formatted string with all pending schedules
    """
    schedules = load_schedules(user_id)
    pending = [s for s in schedules if s.get("status") == "pending"]
    
    if not pending:
        return "📅 No pending schedules."
    
    lines = ["📅 <b>Pending Schedules:</b>"]
    for idx, sched in enumerate(pending, 1):
        dt = datetime.fromisoformat(sched["time"])
        phone = sched.get("phone", "?")
        emotion = sched.get("emotion", "neutral")
        recurrence = sched.get("recurrence", "none")
        recurrence_icon = {
            "none": "🔁",
            "daily": "🔁",
            "weekly": "📆",
            "monthly": "🗓️"
        }.get(recurrence, "🔁")
        lines.append(f"{idx}. {phone} at {dt.strftime('%d/%m/%Y %H:%M')} ({emotion}) {recurrence_icon}")
    
    return "\n".join(lines)

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    # Test adding a recurring schedule
    from datetime import datetime, timedelta
    test_time = datetime.now() + timedelta(minutes=5)
    add_schedule("test_user", "+1234567890", test_time, "cheerful", "daily")
    print("Daily schedule added")
    
    # List schedules
    print(format_schedule_list("test_user"))