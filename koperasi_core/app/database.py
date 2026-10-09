"""
Database management, multi-dialect abstraction (PostgreSQL / SQLite),
and idempotent schema migration runner for Koperasi Core.
"""
import os
import sqlite3
import re
from contextlib import contextmanager
from typing import Generator, Any, Optional

from app.config import APP_ENV, DATABASE_URL, DB_PATH

# Detect Database Dialect
IS_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")))

# Try loading PostgreSQL driver if configured
_psycopg2 = None
if IS_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        _psycopg2 = psycopg2
    except ImportError:
        if APP_ENV == "production":
            raise RuntimeError(
                "CRITICAL ERROR: psycopg2 is required in production for PostgreSQL connection. "
                "Ensure psycopg2-binary is in requirements.txt."
            )

class PostgresConnectionWrapper:
    """Wraps psycopg2 connection to provide uniform ? query placeholder support and dict rows."""
    def __init__(self, raw_conn):
        self.raw_conn = raw_conn

    def execute(self, query: str, params: tuple = None):
        cur = self.raw_conn.cursor(cursor_factory=_psycopg2.extras.DictCursor)
        # Adapt ? to %s for PostgreSQL
        adapted_query = query.replace("?", "%s")
        if params is None:
            cur.execute(adapted_query)
        else:
            cur.execute(adapted_query, params)
        return cur

    def executescript(self, sql_script: str):
        with self.raw_conn.cursor() as cur:
            cur.execute(sql_script)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()

    def cursor(self):
        return self.raw_conn.cursor(cursor_factory=_psycopg2.extras.DictCursor)


class SQLiteConnectionWrapper:
    """Wraps sqlite3.Connection to provide FOR UPDATE query compatibility and uniform interface."""
    def __init__(self, raw_conn):
        self.raw_conn = raw_conn

    def execute(self, query: str, params: tuple = None):
        # Strip FOR UPDATE in SQLite while keeping it in PostgreSQL
        clean_query = re.sub(r"\s+FOR\s+UPDATE\b", "", query, flags=re.I)
        if params is None:
            return self.raw_conn.execute(clean_query)
        return self.raw_conn.execute(clean_query, params)

    def executescript(self, sql_script: str):
        return self.raw_conn.executescript(sql_script)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def close(self):
        self.raw_conn.close()

    def cursor(self):
        return self.raw_conn.cursor()


def execute_insert(conn, query: str, params: tuple = ()) -> int:
    """
    Executes an INSERT statement with RETURNING id and returns the newly created record ID.
    Guarantees 100% compatibility across PostgreSQL and SQLite without relying on cursor attribute row ids.
    """
    clean_query = query.strip().rstrip(";")
    if not re.search(r"\bRETURNING\b", clean_query, re.I):
        clean_query = f"{clean_query} RETURNING id"
    cur = conn.execute(clean_query, params)
    row = cur.fetchone()
    if row is not None:
        if hasattr(row, "keys") and "id" in row.keys():
            return int(row["id"])
        return int(row[0])
    return None


def get_connection(db_path: str = None):
    """Obtain raw database connection based on active engine."""
    if IS_POSTGRES and _psycopg2:
        conn_url = DATABASE_URL
        # Ensure SSL is enforced for cloud PostgreSQL providers (Supabase, Render, Neon, etc.)
        if ("supabase" in conn_url or "render" in conn_url or APP_ENV == "production") and "sslmode=" not in conn_url:
            sep = "&" if "?" in conn_url else "?"
            conn_url = f"{conn_url}{sep}sslmode=require"
        conn = _psycopg2.connect(conn_url)
        return PostgresConnectionWrapper(conn)
    else:
        target_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        raw_conn = sqlite3.connect(target_path, timeout=30.0)
        raw_conn.row_factory = sqlite3.Row
        raw_conn.execute("PRAGMA foreign_keys = ON;")
        return SQLiteConnectionWrapper(raw_conn)


@contextmanager
def get_db(db_path: str = None) -> Generator[Any, None, None]:
    """Transactional context manager for database operations."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema_compatibility(conn):
    """Ensure newly introduced security columns exist on legacy or partially migrated databases."""
    if not IS_POSTGRES:
        schema_patches = [
            ("qr_verification_tokens", "token_hash", "TEXT"),
            ("qr_verification_tokens", "token_display", "TEXT"),
            ("password_reset_tokens", "token_hash", "TEXT"),
            ("invitation_tokens", "token_hash", "TEXT"),
            ("user_sessions", "csrf_token", "TEXT"),
        ]
        for table, col, col_type in schema_patches:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                if cols and col not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type};")
            except Exception:
                pass


def run_migrations(db_path: str = None):
    """
    Apply database schema migrations idempotently.
    Reads SQL migration files from migrations/ directory.
    """
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
    dialect = "postgresql" if IS_POSTGRES else "sqlite"
    migration_file = os.path.join(migrations_dir, f"001_initial_schema_{dialect}.sql")

    if not os.path.exists(migration_file):
        raise FileNotFoundError(f"Migration file not found: {migration_file}")

    with open(migration_file, "r", encoding="utf-8") as f:
        sql = f.read()

    with get_db(db_path) as conn:
        try:
            if hasattr(conn, "executescript"):
                conn.executescript(sql)
            else:
                conn.execute(sql)
            ensure_schema_compatibility(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES ('001_initial_schema', CURRENT_TIMESTAMP) ON CONFLICT (version) DO NOTHING"
            )
        except Exception:
            for statement in sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    try:
                        conn.execute(stmt)
                    except Exception:
                        pass
            ensure_schema_compatibility(conn)


def init_db(db_path: str = None):
    """Initialize database by running migrations."""
    run_migrations(db_path)
