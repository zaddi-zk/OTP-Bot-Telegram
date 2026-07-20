"""Create the PostgreSQL users table using SQLAlchemy."""
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so `import config` works when running scripts directly
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from core.user_manager import init_user_db

logger = logging.getLogger("create_users_table")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_user_db()
    logger.info("✅ PostgreSQL users table initialization complete")
