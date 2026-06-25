"""
File and user configuration management for OTP-Bot-Telegram.
Handles atomic reads/writes, user directory management, and state tracking.
"""
import json
import logging
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("OTP-Bot.files")

BASE_DIR = Path(__file__).resolve().parent.parent
CONF_DIR = BASE_DIR / "conf"
TMP_DIR = CONF_DIR / "tmp"
BACKUP_DIR = CONF_DIR / "backups"

for directory in (CONF_DIR, TMP_DIR, BACKUP_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically using a temporary file and rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"tmp_{path.name}_{uuid.uuid4().hex}")
    attempts = 4
    for attempt in range(attempts):
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(str(tmp_path), str(path))
            return
        except PermissionError as e:
            logger.warning(f"Permission error writing {path}, retrying: {e}")
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
        except Exception as e:
            logger.error(f"Atomic write failed for {path}: {e}")
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, str(text or "").encode("utf-8"))


def _atomic_write_json(path: Path, obj: Any, **kwargs) -> None:
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("indent", 2)
    json_bytes = json.dumps(obj, **kwargs).encode("utf-8")
    _atomic_write_bytes(path, json_bytes)


def _safe_read_text(path: Path, default: str = "") -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.error(f"Failed to read file {path}: {e}")
        return default


def _safe_read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.error(f"Failed to read JSON file {path}: {e}")
        return default


def user_conf_path(user_id: Union[str, int]) -> Path:
    """Return the path to a user's configuration directory."""
    return CONF_DIR / str(user_id)


def ensure_user_path(user_id: Union[str, int]) -> Path:
    """Ensure the user configuration directory exists."""
    path = user_conf_path(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_user_file(user_id: Union[str, int], filename: str, default: str = "") -> str:
    """Read a user file safely and return a default if it does not exist."""
    path = user_conf_path(user_id) / filename
    return _safe_read_text(path, default)


def write_user_file(user_id: Union[str, int], filename: str, value: str) -> None:
    """Write a user file atomically."""
    path = ensure_user_path(user_id) / filename
    _atomic_write_text(path, value)


def read_user_json(user_id: Union[str, int], filename: str, default: Any = None) -> Any:
    """Read a JSON file from a user's directory."""
    path = user_conf_path(user_id) / filename
    return _safe_read_json(path, default)


def write_user_json(user_id: Union[str, int], filename: str, value: Any, **kwargs) -> None:
    """Write a JSON file atomically in a user's directory."""
    path = ensure_user_path(user_id) / filename
    _atomic_write_json(path, value, **kwargs)


def write_user_bytes(user_id: Union[str, int], filename: str, data: bytes) -> None:
    """Write binary data atomically in a user's directory."""
    path = ensure_user_path(user_id) / filename
    _atomic_write_bytes(path, data)


def list_user_files(user_id: Union[str, int]) -> List[Path]:
    """List all files in a user's configuration directory."""
    path = user_conf_path(user_id)
    if not path.exists():
        return []
    return [p for p in path.iterdir() if p.is_file()]


def user_has_file(user_id: Union[str, int], filename: str) -> bool:
    return (user_conf_path(user_id) / filename).exists()


def delete_user_file(user_id: Union[str, int], filename: str) -> None:
    path = user_conf_path(user_id) / filename
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.error(f"Error deleting file {path}: {e}")


def set_user_state(user_id: Union[str, int], state: str) -> None:
    write_user_file(user_id, "state.txt", state)


def get_user_state(user_id: Union[str, int]) -> str:
    return read_user_file(user_id, "state.txt", "")


def clear_user_state(user_id: Union[str, int]) -> None:
    delete_user_file(user_id, "state.txt")


def delete_user_conf(user_id: Union[str, int]) -> None:
    """Remove a user's conf directory and all contained files."""
    path = user_conf_path(user_id)
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def normalize_user_filename(filename: str) -> str:
    """Normalize legacy filenames into safer canonical forms."""
    return filename.strip().replace(" ", "_").lower()


def normalize_legacy_user_filename(filename: str) -> str:
    """Convert common legacy user filenames into canonical keys."""
    mapping = {
        "name.txt": "name.txt",
        "company name.txt": "company_name.txt",
        "phonenum.txt": "phone_number.txt",
        "caller id.txt": "caller_id.txt",
        "from name.txt": "from_name.txt",
        "voice.txt": "voice_id.txt",
        "voicename.txt": "voice_name.txt",
        "digits.txt": "otp_digits.txt",
        "delivery.txt": "delivery.txt",
        "language.txt": "language.txt",
        "subs.txt": "subs.txt",
        "free_calls.txt": "free_calls.txt",
    }
    return mapping.get(filename.strip().lower(), normalize_user_filename(filename))


def get_user_conf_size(user_id: Union[str, int]) -> int:
    """Return approximate total size in bytes of a user's conf directory."""
    total = 0
    path = user_conf_path(user_id)
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except Exception:
                pass
    return total


def archive_user_conf(user_id: Union[str, int], tag: Optional[str] = None) -> Optional[Path]:
    """Create a timestamped ZIP archive backup of the user's conf directory."""
    user_path = user_conf_path(user_id)
    if not user_path.exists():
        return None
    backup_dir = BACKUP_DIR / str(user_id)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    archive_name = backup_dir / f"{timestamp}{suffix}"
    try:
        archive_file = shutil.make_archive(str(archive_name), "zip", root_dir=user_path)
        return Path(archive_file)
    except Exception as e:
        logger.error(f"Failed to archive user conf {user_id}: {e}")
        return None


def list_user_conf_backups(user_id: Union[str, int]) -> List[Path]:
    """List available backup archives for a user."""
    backup_dir = BACKUP_DIR / str(user_id)
    if not backup_dir.exists():
        return []
    return sorted([p for p in backup_dir.iterdir() if p.suffix == ".zip"], reverse=True)


def restore_user_conf_from_archive(user_id: Union[str, int], archive_name: str) -> bool:
    """Restore a user conf backup archive into the user directory."""
    archive_path = BACKUP_DIR / str(user_id) / archive_name
    if not archive_path.exists():
        return False
    target_dir = user_conf_path(user_id)
    try:
        delete_user_conf(user_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(archive_path), str(target_dir), format="zip")
        return True
    except Exception as e:
        logger.error(f"Failed to restore backup {archive_name} for user {user_id}: {e}")
        return False
