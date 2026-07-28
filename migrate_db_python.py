#!/usr/bin/env python3
"""Direct Python-based PostgreSQL database migration.

Works without pg_dump/pg_restore. Copies schema and data directly using SQLAlchemy.
Handles version mismatches automatically.

Usage:
    python migrate_db_python.py "postgresql://source_user:pass@host:5432/db" "postgresql://target_user:pass@host:5432/db"
"""

import sys
from sqlalchemy import create_engine, inspect, text, MetaData, Table, Column, select, insert, Integer, String, TIMESTAMP
from sqlalchemy.pool import NullPool


def log(message: str) -> None:
    print(f"[migrate] {message}", flush=True)


def migrate(source_url: str, target_url: str) -> None:
    """Migrate database from source to target."""
    
    # Add SSL requirement if not present
    if "sslmode=" not in source_url:
        source_url = source_url + ("&" if "?" in source_url else "?") + "sslmode=require"
    if "sslmode=" not in target_url:
        target_url = target_url + ("&" if "?" in target_url else "?") + "sslmode=require"
    
    log("Connecting to source database...")
    source_engine = create_engine(source_url, poolclass=NullPool, echo=False)
    
    log("Connecting to target database...")
    target_engine = create_engine(target_url, poolclass=NullPool, echo=False)
    
    try:
        # Test connections
        with source_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            log(f"Source: {result.scalar()}")
        
        with target_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            log(f"Target: {result.scalar()}")
        
        # Get source metadata
        log("Inspecting source database schema...")
        source_inspector = inspect(source_engine)
        source_metadata = MetaData()
        source_metadata.reflect(bind=source_engine)
        
        # Drop existing tables in target
        log("Dropping existing tables in target database...")
        with target_engine.connect() as conn:
            for table_name in reversed(source_inspector.get_table_names()):
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
                    log(f"  Dropped table: {table_name}")
                except Exception as e:
                    log(f"  Failed to drop {table_name}: {e}")
            conn.commit()
        
        # Create tables in target
        log("Creating tables in target database...")
        source_metadata.create_all(target_engine)
        
        # Copy data for each table
        log("Copying data from source to target...")
        for table_name in source_inspector.get_table_names():
            log(f"  Copying table: {table_name}")
            
            source_table = Table(table_name, source_metadata, autoload_with=source_engine)
            
            with source_engine.connect() as source_conn:
                # Get all rows from source
                rows = source_conn.execute(select(source_table)).fetchall()
                
                if rows:
                    log(f"    Found {len(rows)} rows")
                    
                    # Insert into target
                    with target_engine.connect() as target_conn:
                        for row in rows:
                            stmt = insert(source_table).values(row._mapping)
                            target_conn.execute(stmt)
                        target_conn.commit()
                    
                    log(f"    Inserted {len(rows)} rows into {table_name}")
                else:
                    log(f"    No rows to copy")
        
        log("Migration completed successfully!")
        
    except Exception as e:
        log(f"Migration failed: {e}")
        raise
    finally:
        source_engine.dispose()
        target_engine.dispose()


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
