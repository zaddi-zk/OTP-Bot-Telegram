#!/usr/bin/env python3
"""Direct Python-based PostgreSQL migration without SQLAlchemy reflection.

Works without pg_dump/pg_restore. Connects to PostgreSQL via raw psycopg2,
queries public tables directly from information_schema, recreates tables on the
target, and copies rows using psycopg2.extras.execute_values.

Usage:
    python migrate_db_python.py "postgresql://source_user:pass@host:5432/db" "postgresql://target_user:pass@host:5432/db"
"""

import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values


def log(message: str) -> None:
    print(f"[migrate] {message}", flush=True)


def ensure_sslmode(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError(f"Unsupported database URL scheme: {parsed.scheme}")

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    return urlunparse(parsed._replace(query=urlencode(query)))


def parse_pg_url(url: str) -> Dict[str, Any]:
    parsed = urlparse(ensure_sslmode(url))
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": parsed.password,
        "sslmode": parse_qsl(parsed.query, keep_blank_values=True)
        and dict(parse_qsl(parsed.query, keep_blank_values=True)).get("sslmode", "require")
        or "require",
    }


def connect(url: str):
    conn = psycopg2.connect(**parse_pg_url(url))
    conn.autocommit = False
    return conn


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def fetch_public_tables(conn) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        return [row[0] for row in cur.fetchall()]


def fetch_table_columns(conn, table_name: str) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                column_name,
                data_type,
                udt_name,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        return [
            {
                "column_name": row[0],
                "data_type": row[1],
                "udt_name": row[2],
                "is_nullable": row[3],
                "column_default": row[4],
                "character_maximum_length": row[5],
                "numeric_precision": row[6],
                "numeric_scale": row[7],
            }
            for row in cur.fetchall()
        ]


def fetch_primary_key_columns(conn, table_name: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = 'public'
              AND tc.table_name = %s
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """,
            (table_name,),
        )
        return [row[0] for row in cur.fetchall()]


def build_create_table_sql(table_name: str, columns: Sequence[Dict[str, Any]]) -> str:
    column_statements: List[str] = []
    for column in columns:
        name = column["column_name"]
        data_type = (column["data_type"] or "").lower()
        udt_name = (column["udt_name"] or "").lower()
        is_nullable = column["is_nullable"]
        character_max_length = column["character_maximum_length"]
        numeric_precision = column["numeric_precision"]
        numeric_scale = column["numeric_scale"]

        if data_type in {"character varying", "varchar"}:
            if character_max_length:
                sql_type = f"varchar({character_max_length})"
            else:
                sql_type = "varchar"
        elif data_type in {"character", "char"}:
            sql_type = f"char({character_max_length})" if character_max_length else "char"
        elif data_type in {"numeric", "decimal", "number"}:
            if numeric_precision is not None and numeric_scale is not None:
                sql_type = f"numeric({numeric_precision},{numeric_scale})"
            elif numeric_precision is not None:
                sql_type = f"numeric({numeric_precision})"
            else:
                sql_type = "numeric"
        elif data_type in {"integer", "int", "int4"}:
            sql_type = "integer"
        elif data_type in {"bigint", "int8"}:
            sql_type = "bigint"
        elif data_type in {"smallint", "int2"}:
            sql_type = "smallint"
        elif data_type in {"boolean", "bool"}:
            sql_type = "boolean"
        elif data_type in {"timestamp without time zone", "timestamp with time zone", "timestamp"}:
            sql_type = "timestamp"
        elif data_type in {"bytea", "json", "jsonb", "text", "name"}:
            sql_type = data_type
        elif udt_name:
            sql_type = udt_name
        else:
            sql_type = data_type or "text"

        definition = f"{quote_identifier(name)} {sql_type}"
        if is_nullable and str(is_nullable).upper() == "NO":
            definition += " NOT NULL"
        column_statements.append(definition)

    return f"CREATE TABLE public.{quote_identifier(table_name)} (\n  " + ",\n  ".join(column_statements) + "\n);"


def create_table(target_conn, table_name: str, columns: Sequence[Dict[str, Any]]) -> None:
    with target_conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS public.{quote_identifier(table_name)} CASCADE")
        cur.execute(build_create_table_sql(table_name, columns))
    target_conn.commit()


def copy_table_data(source_conn, target_conn, table_name: str) -> None:
    with source_conn.cursor() as source_cur:
        source_cur.execute(sql.SQL("SELECT * FROM public.{}" ).format(sql.Identifier(table_name)))
        rows = source_cur.fetchall()
        column_names = [desc[0] for desc in source_cur.description] or []

    if not rows:
        return

    insert_sql = (
        f"INSERT INTO public.{quote_identifier(table_name)} "
        f"({', '.join(quote_identifier(name) for name in column_names)}) VALUES %s"
    )

    with target_conn.cursor() as target_cur:
        execute_values(target_cur, insert_sql, rows, page_size=1000)
    target_conn.commit()


def migrate(source_url: str, target_url: str) -> None:
    """Migrate schema and data from source to target using raw psycopg2."""
    source_url = ensure_sslmode(source_url)
    target_url = ensure_sslmode(target_url)

    log("Connecting to source database...")
    source_conn = connect(source_url)

    log("Connecting to target database...")
    target_conn = connect(target_url)

    try:
        with source_conn.cursor() as cur:
            cur.execute("SELECT version()")
            log(f"Source: {cur.fetchone()[0]}")

        with target_conn.cursor() as cur:
            cur.execute("SELECT version()")
            log(f"Target: {cur.fetchone()[0]}")

        table_names = fetch_public_tables(source_conn)
        if not table_names:
            log("No user tables found in source database")
            return

        log("Dropping and recreating tables in target database...")
        for table_name in table_names:
            columns = fetch_table_columns(source_conn, table_name)
            create_table(target_conn, table_name, columns)
            log(f"  Created table: {table_name}")

        log("Disabling foreign-key enforcement for data load...")
        with target_conn.cursor() as cur:
            cur.execute("SET session_replication_role = 'replica';")

        try:
            log("Copying data from source to target...")
            for table_name in table_names:
                log(f"  Copying table: {table_name}")
                copy_table_data(source_conn, target_conn, table_name)
                log(f"    Inserted rows into {table_name}")
        finally:
            with target_conn.cursor() as cur:
                cur.execute("SET session_replication_role = 'DEFAULT';")
            target_conn.commit()

        log("Migration completed successfully!")
    except Exception as e:
        log(f"Migration failed: {e}")
        raise
    finally:
        source_conn.close()
        target_conn.close()


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python migrate_db_python.py <source_url> <target_url>")
        print("")
        print("Example:")
        print('  python migrate_db_python.py "postgresql://user:pass@host:5432/db" "postgresql://user:pass@host:5432/db"')
        return 2

    source_url = sys.argv[1]
    target_url = sys.argv[2]

    log(f"Source: {source_url}")
    log(f"Target: {target_url}")

    try:
        migrate(source_url, target_url)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
