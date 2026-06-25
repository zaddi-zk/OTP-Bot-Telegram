"""
OTP-Bot-Telegram core package.
Provides centralized utilities for file storage, configuration, backup, migration, and monitoring.
"""

from .files import (
    user_conf_path,
    ensure_user_path,
    read_user_file,
    write_user_file,
    read_user_json,
    write_user_json,
    write_user_bytes,
    delete_user_file,
    delete_user_conf,
    user_has_file,
    list_user_files,
    set_user_state,
    get_user_state,
    clear_user_state,
)
from .config_manager import (
    load_settings,
    save_settings,
    get_setting,
    set_setting,
)
from .backup_manager import (
    backup_user_conf,
    list_user_backups,
    restore_user_conf_from_backup,
)
from .migration import (
    migrate_user_conf_dir,
    normalize_legacy_user_filename,
)
from .monitoring import (
    get_conf_usage_report,
    get_user_conf_metrics,
)
