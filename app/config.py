"""
Configuration and constants for Koperasi Core.
"""
import os

APP_NAME = "Koperasi Core"
APP_VERSION = "2.0.0"
SECRET_KEY = os.environ.get("SECRET_KEY", "koperasi_super_secure_secret_key_prod_v2_2026")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")

# On some virtual filesystems (e.g. 9p mounts in sandbox containers), SQLite file locking
# requires standard POSIX fs like /tmp or /var/data. Allow fallback to /tmp/koperasi.db.
DEFAULT_DB_PATH = os.environ.get("DB_PATH")
if not DEFAULT_DB_PATH:
    # Test if data dir is writable by sqlite
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

SESSION_COOKIE_NAME = "koperasi_session"
SESSION_LIFETIME_HOURS = 12
TOKEN_EXPIRATION_HOURS = 24

# Roles
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
