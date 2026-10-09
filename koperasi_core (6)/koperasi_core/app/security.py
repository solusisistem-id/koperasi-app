"""
Security, Cryptography, Password Hashing, Session Management, CSRF, and Audit Services.
Hardened for Production & Render Readiness.
"""
import os
import hmac
import hashlib
import secrets
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_HALF_UP

# Password Hashing with PBKDF2-HMAC-SHA256 (NIST SP 800-63B compliant)
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

def hash_token(raw_token: str) -> str:
    """Compute SHA-256 hash of a token for secure database storage and lookup."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

def verify_token_hash(raw_token: str, stored_hash: str) -> bool:
    """Verify a raw token against its stored SHA-256 hash in constant time."""
    if not raw_token or not stored_hash:
        return False
    computed_hash = hash_token(raw_token)
    return secrets.compare_digest(computed_hash, stored_hash)

# CSRF Protection Helpers
def generate_csrf_token() -> str:
    """Generate cryptographically random CSRF token."""
    return secrets.token_hex(32)

def verify_csrf_token(stored_csrf: Optional[str], submitted_csrf: Optional[str]) -> bool:
    """Verify CSRF token in constant time."""
    if not stored_csrf or not submitted_csrf:
        return False
    return secrets.compare_digest(stored_csrf, submitted_csrf)

def generate_reference_number(prefix: str) -> str:
    """Generate a unique reference number with prefix and timestamp/random digits."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
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

def mask_sensitive_data(val: Any, mask_type: str = "general") -> str:
    """Mask sensitive identifiers like NIK, bank accounts, or tokens for audit and logging."""
    if not val:
        return ""
    s = str(val).strip()
    if mask_type == "nik" and len(s) == 16:
        return f"{s[:4]}********{s[-4:]}"
    elif mask_type == "bank" and len(s) > 4:
        return f"{'*' * (len(s) - 4)}{s[-4:]}"
    elif len(s) > 8:
        return f"{s[:4]}...{s[-4:]}"
    return "****"

def to_decimal(value: Any) -> Decimal:
    """Safely convert any numeric value or string to Decimal with 2 decimal places."""
    if value is None or str(value).strip() == "":
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cleaned = str(value).replace("Rp", "").replace(" ", "").replace(".", "").replace(",", ".")
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
    int_part = int(dec)
    formatted_int = f"{int_part:,}".replace(",", ".")
    return f"Rp {formatted_int}"

def sanitize_audit_state(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Ensure sensitive attributes like raw tokens or passwords are never logged into audit trail."""
    if not state:
        return None
    sanitized = {}
    sensitive_keys = {"password", "password_hash", "token", "raw_token", "secret", "session_token"}
    for k, v in state.items():
        if k in sensitive_keys:
            sanitized[k] = "[REDACTED]"
        elif k == "nik" and v:
            sanitized[k] = mask_sensitive_data(v, "nik")
        elif k == "token_hash":
            sanitized[k] = str(v)[:8] + "..."
        else:
            sanitized[k] = v
    return sanitized

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
    """Insert immutable record into audit_logs table with sensitive data redaction."""
    safe_before = sanitize_audit_state(before_state)
    safe_after = sanitize_audit_state(after_state)

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
            json.dumps(safe_before, default=str) if safe_before else None,
            json.dumps(safe_after, default=str) if safe_after else None,
            result,
            ip_address,
            user_agent,
            correlation_id or secrets.token_hex(8),
        ),
    )
