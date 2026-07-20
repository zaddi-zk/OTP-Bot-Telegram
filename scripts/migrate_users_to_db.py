"""Import legacy user identifiers from JSON files into PostgreSQL."""
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so `import config` works when running scripts directly
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from core.user_manager import add_user_if_not_exists, init_user_db

logger = logging.getLogger("migrate_users_to_db")

CONF_DIR = Path("conf")
PENDING_FILE = CONF_DIR / "pending_verifications.json"


def load_pending_users():
    """Load user IDs from legacy JSON files."""
    if not PENDING_FILE.exists():
        logger.info("No pending_verifications.json found; nothing to import.")
        return []

    try:
        payload = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return [str(key) for key in payload.keys() if str(key)]
        if isinstance(payload, list):
            return [str(item) for item in payload if str(item)]
        return []
    except Exception as exc:
        logger.error(f"Failed to read pending file: {exc}")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_user_db()

    users = load_pending_users()
    if not users:
        logger.info("No users found to import.")
        raise SystemExit(0)

    imported = 0
    for user_id in users:
        if add_user_if_not_exists(user_id):
            imported += 1

    logger.info(f"✅ Imported {imported} users into PostgreSQL")
