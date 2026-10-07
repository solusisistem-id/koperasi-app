"""
Security, Cryptography, Password Hashing, Session Management, and Audit Services.
"""
import os
import hmac
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_HALF_UP

# Password Hashing with PBKDF2-HMAC-SHA256
PBKDF2_ITERATIONS = 260_000
SALT_BYTES = 16

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with secure random salt."""
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against pbkdf2_sha256 hash using constant-time comparison."""
    try:
        parts = hashed.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_dk = bytes.fromhex(parts[3])
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(dk, expected_dk)
    except Exception:
        return False

def generate_secure_token(nbytes: int = 32) -> str:
    """Generate cryptographically secure URL-safe random token."""
    return secrets.token_urlsafe(nbytes)

def generate_reference_number(prefix: str) -> str:
    """Generate a unique reference number with prefix and timestamp/random digits."""
    date_str = datetime.utcnow().strftime("%Y%m%d")
    rand_str = secrets.token_hex(4).upper()
    return f"{prefix}-{date_str}-{rand_str}"

def sanitize_for_spreadsheet(value: Any) -> str:
    """Sanitize fields for CSV/Excel export to prevent CSV formula injection (CWE-1236)."""
    if value is None:
        return ""
    s = str(value)
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + s
    return s

def to_decimal(value: Any) -> Decimal:
    """Safely convert any numeric value or string to Decimal with 2 decimal places."""
    if value is None or str(value).strip() == "":
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Strip potential thousand separators and currency symbols if present
    cleaned = str(value).replace("Rp", "").replace(" ", "").replace(".", "").replace(",", ".")
    # If standard dot format was used: e.g. 1000000.00
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        pass
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def format_rupiah(value: Any) -> str:
    """Format decimal amount as Indonesian Rupiah string without float loss."""
    dec = to_decimal(value)
    # Format with dot as thousand separator
    int_part = int(dec)
    formatted_int = f"{int_part:,}".replace(",", ".")
    return f"Rp {formatted_int}"

# Audit Logging Helper
def log_audit(
    conn,
    actor_id: Optional[int],
    actor_name: Optional[str],
    actor_role: Optional[str],
    action: str,
    entity: str,
    entity_id: Optional[str] = None,
    before_state: Optional[Dict[str, Any]] = None,
    after_state: Optional[Dict[str, Any]] = None,
    result: str = "SUCCESS",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    correlation_id: Optional[str] = None,
):
    """Insert immutable record into audit_logs table."""
    conn.execute(
        """
        INSERT INTO audit_logs (
            actor_id, actor_name, actor_role, action, entity, entity_id,
            before_state_json, after_state_json, result, ip_address, user_agent, correlation_id, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            actor_id,
            actor_name,
            actor_role,
            action,
            entity,
            str(entity_id) if entity_id is not None else None,
            json.dumps(before_state, default=str) if before_state else None,
            json.dumps(after_state, default=str) if after_state else None,
            result,
            ip_address,
            user_agent,
            correlation_id or secrets.token_hex(8),
        ),
    )
