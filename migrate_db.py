#!/usr/bin/env python3
"""Migrate a PostgreSQL database from a source connection string to a target connection string.

This script uses pg_dump / pg_restore for a full database migration including schema,
sequences, tables, and data. It is designed for remote PostgreSQL services such as
Railway and Render where SSL is required.

Usage:
    python migrate_db.py "postgresql://source_user:source_pass@host:5432/source_db" "postgresql://target_user:target_pass@host:5432/target_db"

Environment variables can also be used:
    export SOURCE_DATABASE_URL="..."
    export TARGET_DATABASE_URL="..."
    python migrate_db.py
"""

import os
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
from typing import Optional


def log(message: str) -> None:
    print(f"[migrate_db] {message}", flush=True)


def parse_conn_string(conn_str: str) -> dict:
    parsed = urlparse(conn_str)
    if parsed.scheme != "postgresql" and parsed.scheme != "postgres":
        raise ValueError(f"Unsupported connection string scheme: {parsed.scheme}")

    if not parsed.hostname:
        raise ValueError("Connection string is missing hostname")

    if not parsed.path or parsed.path == "/":
        raise ValueError("Connection string is missing database name")

    db_name = parsed.path.lstrip("/")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": db_name,
        "sslmode": "require",
    }


def build_pg_dump_command(source_conn: str, dump_file: str) -> list[str]:
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--dbname={source_conn}",
        "--file",
        dump_file,
    ]


def build_pg_restore_command(target_conn: str, dump_file: str) -> list[str]:
    return [
        "pg_restore",
        "--verbose",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        f"--dbname={target_conn}",
        dump_file,
    ]


def run_command(cmd: list[str], description: str) -> None:
    log(f"Running: {' '.join(shlex.quote(part) for part in cmd)}")
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, end="", flush=True)
    if completed.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {completed.returncode}")


def ensure_tools() -> None:
    for tool in ("pg_dump", "pg_restore"):
        result = subprocess.run([tool, "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Required tool not found: {tool}. Install PostgreSQL client tools first.")
    log("Verified pg_dump and pg_restore are available")


def migrate(source_url: str, target_url: str) -> None:
    ensure_tools()

    log("Parsing source and target connection strings")
    source_conn = source_url
    target_conn = target_url

    if "sslmode=" not in source_conn:
        source_conn = source_conn + "?sslmode=require"
    if "sslmode=" not in target_conn:
        target_conn = target_conn + "?sslmode=require"

    log("Creating temporary dump file")
    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as temp:
        dump_file = temp.name

    try:
        log("Starting schema and data export from source database")
        run_command(build_pg_dump_command(source_conn, dump_file), "pg_dump export")
        log("Export completed successfully")

        log("Starting import into target database")
        run_command(build_pg_restore_command(target_conn, dump_file), "pg_restore import")
        log("Import completed successfully")
    finally:
        try:
            os.remove(dump_file)
            log("Removed temporary dump file")
        except FileNotFoundError:
            pass


def main() -> int:
    source_url = os.environ.get("SOURCE_DATABASE_URL") or os.environ.get("RAILWAY_DATABASE_URL")
    target_url = os.environ.get("TARGET_DATABASE_URL") or os.environ.get("RENDER_DATABASE_URL")

    if len(sys.argv) >= 3:
        source_url = sys.argv[1]
        target_url = sys.argv[2]

    if not source_url or not target_url:
        print("Usage:")
        print("  python migrate_db.py <source_postgres_url> <target_postgres_url>")
        print("Or set environment variables:")
        print("  SOURCE_DATABASE_URL=... TARGET_DATABASE_URL=...")
        return 2

    log("Source database URL: " + source_url)
    log("Target database URL: " + target_url)

    try:
        migrate(source_url, target_url)
    except Exception as exc:
        log(f"Migration failed: {exc}")
        return 1

    log("Migration completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
