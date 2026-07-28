#!/usr/bin/env python3
"""Direct psycopg2-based PostgreSQL database migration.

Simple and reliable. Copies schema and data directly.

Usage:
    python migrate_db_simple.py "postgresql://source_user:pass@host:port/db" "postgresql://target_user:pass@host:port/db"
"""

import sys
import psycopg2
from urllib.parse import urlparse


def log(message: str) -> None:
    print(f"[migrate] {message}", flush=True)


def parse_conn_string(conn_str: str) -> dict:
    """Parse PostgreSQL connection string."""
    parsed = urlparse(conn_str)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/"),
        "sslmode": "require",
    }


def get_all_tables(conn):
    """Get list of all table names."""
    cur = conn.cursor()
    cur.execute("""
        SELECT tablename FROM pg_tables 
        WHERE schemaname = 'public'
    """)
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    return tables


def migrate(source_url: str, target_url: str) -> None:
    """Migrate database from source to target."""
    
    source_config = parse_conn_string(source_url)
    target_config = parse_conn_string(target_url)
    
    log(f"Connecting to source: {source_config['host']}:{source_config['port']}/{source_config['database']}")
    source_conn = psycopg2.connect(**source_config)
    
    log(f"Connecting to target: {target_config['host']}:{target_config['port']}/{target_config['database']}")
    target_conn = psycopg2.connect(**target_config)
    
    try:
        # Get source version
        src_cur = source_conn.cursor()
        src_cur.execute("SELECT version()")
        log(f"Source: {src_cur.fetchone()[0][:60]}...")
        src_cur.close()
        
        # Get target version
        tgt_cur = target_conn.cursor()
        tgt_cur.execute("SELECT version()")
        log(f"Target: {tgt_cur.fetchone()[0][:60]}...")
        tgt_cur.close()
        
        # Get all tables
        tables = get_all_tables(source_conn)
        log(f"Found {len(tables)} tables to migrate: {', '.join(tables[:5])}{'...' if len(tables) > 5 else ''}")
        
        # Drop and recreate in target
        log("Clearing target database...")
        tgt_cur = target_conn.cursor()
        for table in tables:
            try:
                tgt_cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            except Exception as e:
                log(f"  Warning: Could not drop {table}: {e}")
        target_conn.commit()
        tgt_cur.close()
        
        # Copy each table
        log("Copying data...")
        src_cur = source_conn.cursor()
        tgt_cur = target_conn.cursor()
        
        for table in tables:
            # Get table structure
            src_cur.execute(f"SELECT * FROM {table} LIMIT 0")
            
            # Create table in target with same structure
            src_cur.execute(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table,))
            
            columns = src_cur.fetchall()
            if not columns:
                log(f"  {table}: No columns, skipping")
                continue
            
            col_defs = ", ".join([f'"{col[0]}" {col[1]} {"NOT NULL" if col[2] == "NO" else ""}' for col in columns])
            col_names = ", ".join([f'"{col[0]}"' for col in columns])
            
            try:
                tgt_cur.execute(f"CREATE TABLE {table} ({col_defs})")
            except Exception as e:
                log(f"  {table}: Create failed: {e}")
                continue
            
            # Copy data
            src_cur.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = src_cur.fetchone()[0]
            
            if row_count > 0:
                # Use COPY for efficiency
                copy_sql = f"COPY {table} ({col_names}) FROM STDIN"
                src_cur.copy_to(
                    tgt_cur.copy_expert(copy_sql),
                    f"({col_names}) FROM {table}"
                )
            
            log(f"  {table}: {row_count} rows copied")
        
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
        print("  python migrate_db_simple.py <source_url> <target_url>")
        return 2
    
    source_url = sys.argv[1]
    target_url = sys.argv[2]
    
    try:
        migrate(source_url, target_url)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
