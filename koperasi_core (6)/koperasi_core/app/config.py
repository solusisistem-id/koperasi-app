"""
Configuration and constants for Koperasi Core.
Production Hardened & Render Ready.
"""
import os
import sys

APP_NAME = "Koperasi Core"
APP_VERSION = "2.1.0"
APP_ENV = os.environ.get("APP_ENV", "development").lower()

# Secret Key Management
SECRET_KEY = os.environ.get("SECRET_KEY")
INSECURE_SECRETS = (
    "koperasi_super_secure_secret_key_prod_v2_2026",
    "secret",
    "change_me",
    "secret_key",
    "default",
)

if APP_ENV == "production":
    if not SECRET_KEY or SECRET_KEY.strip() in INSECURE_SECRETS:
        raise RuntimeError(
            "FATAL SECURITY ERROR: In production environment, a secure, non-default SECRET_KEY "
            "must be provided via environment variable. Please set SECRET_KEY in your Render Dashboard."
        )
else:
    # Safe fallback for local development and testing only
    if not SECRET_KEY:
        SECRET_KEY = "koperasi_dev_secret_key_change_in_production_environment"

# Database Configuration
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # Normalize Render's legacy postgres:// to postgresql://
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if APP_ENV == "production":
    if not DATABASE_URL or not DATABASE_URL.startswith("postgresql://"):
        raise RuntimeError(
            "FATAL DATABASE ERROR: Production environment strictly requires PostgreSQL. "
            "Please provide a valid PostgreSQL connection string via DATABASE_URL."
        )

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")

# SQLite fallback path for local development and test suites
DEFAULT_DB_PATH = os.environ.get("DB_PATH")
if not DEFAULT_DB_PATH:
    test_path = os.path.join(DATA_DIR, ".sqlite_test.db")
    try:
        import sqlite3
        _c = sqlite3.connect(test_path)
        _c.execute("CREATE TABLE _t (x INT)")
        _c.close()
        os.remove(test_path)
        DEFAULT_DB_PATH = os.path.join(DATA_DIR, "koperasi.db")
    except Exception:
        DEFAULT_DB_PATH = "/tmp/koperasi.db"

DB_PATH = DEFAULT_DB_PATH

# Server & Network Configuration
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")

# Security, Cookie & Session Settings
SESSION_COOKIE_NAME = "koperasi_session"
CSRF_COOKIE_NAME = "koperasi_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_LIFETIME_HOURS = 12
TOKEN_EXPIRATION_HOURS = 24
RESET_TOKEN_EXPIRATION_HOURS = 1

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

# Storage Configuration
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()
STORAGE_BUCKET = os.environ.get("S3_BUCKET") or os.environ.get("STORAGE_BUCKET") or "koperasi-documents"
STORAGE_ENDPOINT = os.environ.get("S3_ENDPOINT_URL") or os.environ.get("STORAGE_ENDPOINT") or ""
STORAGE_REGION = os.environ.get("S3_REGION") or "auto"
STORAGE_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY_ID") or os.environ.get("STORAGE_ACCESS_KEY") or ""
STORAGE_SECRET_KEY = os.environ.get("S3_SECRET_ACCESS_KEY") or os.environ.get("STORAGE_SECRET_KEY") or ""

# Email / SMTP Configuration
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", "noreply@koperasi.local")

# RBAC Roles
ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_ADMIN_KOPERASI = "ADMIN_KOPERASI"
ROLE_ANGGOTA = "ANGGOTA"
ROLE_KETUA = "KETUA"
ROLE_ATASAN_APPROVER = "ATASAN_APPROVER"
ROLE_BENDAHARA = "BENDAHARA"

ALL_ROLES = [
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
]

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
