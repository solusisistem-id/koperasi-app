"""
Authentication, Session, RBAC, Invitation, and Password Reset Services.
Production Hardened with Account Lockout, Rate Limiting, CSRF Token Generation,
Token Hashing, Centralized Permission Engine, and Session Invalidation.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import secrets

from app.database import get_db, DB_PATH, execute_insert
from app.security import (
    hash_password,
    verify_password,
    generate_secure_token,
    hash_token,
    verify_token_hash,
    generate_csrf_token,
    log_audit,
)
from app.config import (
    APP_ENV,
    SESSION_LIFETIME_HOURS,
    TOKEN_EXPIRATION_HOURS,
    RESET_TOKEN_EXPIRATION_HOURS,
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_DURATION_MINUTES,
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)

class AuthenticationError(Exception):
    pass

class AuthorizationError(Exception):
    pass

def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)

def parse_utc_dt(dt_val: Any) -> datetime:
    """Safely parse datetime string or object into timezone-aware UTC datetime."""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    if not dt_val:
        return utc_now()
    dt_str = str(dt_val).strip()
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        clean_str = dt_str.split(".")[0].split("+")[0]
        dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)

# Canonical Role Permissions Mapping
ROLE_PERMISSIONS_MAP = {
    ROLE_SUPER_ADMIN: ["*"],
    ROLE_ADMIN_KOPERASI: [
        "member.read_all", "member.create", "member.update", "member.import",
        "savings.read_all", "savings.create", "savings.opening_balance",
        "loan.read_all", "loan.create", "transaction.read", "transaction.create",
        "document.read_all", "document.verify", "document.revoke",
        "report.read", "settings.manage", "audit.read", "user.manage",
    ],
    ROLE_KETUA: [
        "member.read_all", "savings.read_all", "loan.read_all",
        "loan.approve_chairman", "loan.approve", "report.read", "audit.read",
    ],
    ROLE_BENDAHARA: [
        "member.read_all", "savings.read_all", "loan.read_all",
        "loan.disburse", "installment.create", "savings.create",
        "transaction.create", "transaction.read", "report.read",
    ],
    ROLE_ATASAN_APPROVER: [
        "loan.approve_manager", "loan.approve", "member.read_subordinates", "loan.read_subordinates",
    ],
    ROLE_ANGGOTA: [
        "member.read_own", "savings.read_own", "loan.read_own", "loan.apply",
        "document.read_own", "statement.read_own",
    ],
}

def get_effective_permissions(roles: List[str], db_perms: List[str]) -> List[str]:
    """Computes effective union of permissions for multi-role users."""
    all_perms = set(db_perms)
    for r in roles:
        if r == ROLE_SUPER_ADMIN:
            all_perms.add("*")
        for p in ROLE_PERMISSIONS_MAP.get(r, []):
            all_perms.add(p)
    return sorted(all_perms)

def has_permission(user: Optional[Dict[str, Any]], permission_code: str) -> bool:
    """Check if user holds specific permission or superadmin wildcard."""
    if not user:
        return False
    perms = user.get("permissions") or []
    if "*" in perms or ROLE_SUPER_ADMIN in user.get("roles", []):
        return True
    return permission_code in perms

def require_permission(user: Optional[Dict[str, Any]], permission_code: str) -> None:
    """Raise AuthorizationError if user lacks requested permission."""
    if not user:
        raise AuthenticationError("Sesi Anda telah berakhir. Silakan masuk kembali.")
    if not has_permission(user, permission_code):
        raise AuthorizationError(f"Akses ditolak: Anda tidak memiliki izin '{permission_code}'.")


def authenticate_user(email: str, password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Dict[str, Any]:
    """Authenticate user with email and password, enforce lifecycle state, rate limiting, and account lockout."""
    email_clean = email.strip().lower()
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash, full_name, status, failed_login_attempts, locked_until FROM users WHERE email = ?",
            (email_clean,),
        ).fetchone()

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if not user:
            log_audit(
                conn,
                actor_id=None,
                actor_name=email_clean,
                actor_role="ANONYMOUS",
                action="LOGIN_FAILED",
                entity="users",
                entity_id=None,
                before_state={"email": email_clean, "reason": "user_not_found"},
                result="FAILURE",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            conn.commit()
            raise AuthenticationError("Email atau password tidak valid.")

        # Check account lockout before password check to prevent DoS timing leaks
        if user["locked_until"] and user["locked_until"] > now_str:
            log_audit(
                conn,
                actor_id=user["id"],
                actor_name=user["full_name"],
                actor_role=None,
                action="LOGIN_FAILED",
                entity="users",
                entity_id=str(user["id"]),
                before_state={"reason": "account_locked", "locked_until": user["locked_until"]},
                result="FAILURE",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            conn.commit()
            raise AuthenticationError(f"Akun sementara terkunci hingga {user['locked_until']} WIB karena terlalu banyak percobaan gagal.")

        if user["status"] in ("SUSPENDED", "DEACTIVATED"):
            log_audit(
                conn,
                actor_id=user["id"],
                actor_name=user["full_name"],
                actor_role=None,
                action="LOGIN_FAILED",
                entity="users",
                entity_id=str(user["id"]),
                before_state={"reason": f"account_{user['status'].lower()}"},
                result="FAILURE",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            conn.commit()
            raise AuthenticationError(f"Akun Anda sedang {user['status'].lower()}. Silakan hubungi Administrator.")

        if user["status"] in ("INVITED", "PENDING_ACTIVATION"):
            raise AuthenticationError("Akun belum diaktivasi. Silakan periksa tautan aktivasi/undangan Anda.")

        if not verify_password(password, user["password_hash"]):
            failed_attempts = user["failed_login_attempts"] + 1
            if failed_attempts >= MAX_LOGIN_ATTEMPTS:
                lockout_until = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
                    (failed_attempts, lockout_until, user["id"]),
                )
            else:
                conn.execute(
                    "UPDATE users SET failed_login_attempts = ? WHERE id = ?",
                    (failed_attempts, user["id"]),
                )

            log_audit(
                conn,
                actor_id=user["id"],
                actor_name=user["full_name"],
                actor_role=None,
                action="LOGIN_FAILED",
                entity="users",
                entity_id=str(user["id"]),
                before_state={"reason": "invalid_password", "failed_attempts": failed_attempts},
                result="FAILURE",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            conn.commit()
            raise AuthenticationError("Email atau password tidak valid.")

        # Successful login: reset failed attempts & lockout
        conn.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = datetime('now') WHERE id = ?",
            (user["id"],),
        )

        # Rotate Session ID and issue fresh CSRF Token
        session_token = generate_secure_token(32)
        csrf_token = generate_csrf_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_LIFETIME_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            INSERT INTO user_sessions (user_id, session_token, csrf_token, expires_at, created_at, user_agent, ip_address)
            VALUES (?, ?, ?, ?, datetime('now'), ?, ?)
            """,
            (user["id"], session_token, csrf_token, expires_at, user_agent, ip_address),
        )

        roles_cur = conn.execute(
            """
            SELECT r.code, r.name FROM roles r
            JOIN user_roles ur ON r.id = ur.role_id
            WHERE ur.user_id = ?
            """,
            (user["id"],),
        ).fetchall()
        role_codes = [r["code"] for r in roles_cur]

        log_audit(
            conn,
            actor_id=user["id"],
            actor_name=user["full_name"],
            actor_role=",".join(role_codes),
            action="LOGIN_SUCCESS",
            entity="users",
            entity_id=str(user["id"]),
            after_state={"roles": role_codes},
            result="SUCCESS",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "status": user["status"],
            "roles": role_codes,
            "session_token": session_token,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
        }

def get_user_from_session(session_token: str) -> Optional[Dict[str, Any]]:
    """Retrieve active user from valid session token with CSRF token and unified permissions."""
    if not session_token:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.full_name, u.status, s.expires_at, s.id as session_id, s.csrf_token
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_token = ? AND s.expires_at > datetime('now')
            """,
            (session_token,),
        ).fetchone()

        if not row or row["status"] in ("SUSPENDED", "DEACTIVATED"):
            return None

        roles_cur = conn.execute(
            """
            SELECT r.code, r.name FROM roles r
            JOIN user_roles ur ON r.id = ur.role_id
            WHERE ur.user_id = ?
            """,
            (row["id"],),
        ).fetchall()
        role_codes = [r["code"] for r in roles_cur]

        # Permissions mapping from DB union with role map
        perm_cur = conn.execute(
            """
            SELECT DISTINCT p.code FROM permissions p
            JOIN role_permissions rp ON p.id = rp.permission_id
            JOIN user_roles ur ON rp.role_id = ur.role_id
            WHERE ur.user_id = ?
            """,
            (row["id"],),
        ).fetchall()
        db_permissions = [p["code"] for p in perm_cur]
        permissions = get_effective_permissions(role_codes, db_permissions)

        member = conn.execute("SELECT id, member_number FROM members WHERE user_id = ?", (row["id"],)).fetchone()
        employee = conn.execute("SELECT id, employee_id, manager_id FROM employees WHERE email = ?", (row["email"],)).fetchone()

        return {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "status": row["status"],
            "roles": role_codes,
            "permissions": permissions,
            "member_id": member["id"] if member else None,
            "member_number": member["member_number"] if member else None,
            "employee_id": employee["id"] if employee else None,
            "manager_id": employee["manager_id"] if employee else None,
            "session_id": row["session_id"],
            "csrf_token": row["csrf_token"] or "",
        }

def invalidate_session(session_token: str):
    """Log out user and invalidate specific session."""
    with get_db() as conn:
        conn.execute("DELETE FROM user_sessions WHERE session_token = ?", (session_token,))

def invalidate_all_user_sessions(user_id: int):
    """Invalidate all active sessions for a user (used on password change or account deactivation)."""
    with get_db() as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

def create_user_invitation(email: str, full_name: str, role_codes: List[str], creator_user_id: int) -> Dict[str, Any]:
    """Admin invites a user. Token is hashed before database storage. Raw token never stored in DB."""
    email_clean = email.strip().lower()
    with get_db() as conn:
        existing = conn.execute("SELECT id, email, status FROM users WHERE email = ?", (email_clean,)).fetchone()
        if existing:
            raise ValueError(f"Email {email_clean} sudah terdaftar dalam sistem.")

        dummy_pwd = secrets.token_hex(32)
        pwd_hash = hash_password(dummy_pwd)

        user_id = execute_insert(
            conn,
            """
            INSERT INTO users (email, password_hash, full_name, status, created_at, updated_at)
            VALUES (?, ?, ?, 'INVITED', datetime('now'), datetime('now'))
            """,
            (email_clean, pwd_hash, full_name.strip()),
        )

        for r_code in role_codes:
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (r_code,)).fetchone()
            if role:
                conn.execute(
                    "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?) ON CONFLICT (user_id, role_id) DO NOTHING",
                    (user_id, role["id"]),
                )

        raw_token = generate_secure_token(32)
        token_digest = hash_token(raw_token)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRATION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            INSERT INTO invitation_tokens (user_id, email, token_hash, expires_at, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (user_id, email_clean, token_digest, expires_at, creator_user_id),
        )

        creator = conn.execute("SELECT full_name FROM users WHERE id = ?", (creator_user_id,)).fetchone()
        log_audit(
            conn,
            actor_id=creator_user_id,
            actor_name=creator["full_name"] if creator else "ADMIN",
            actor_role="ADMIN",
            action="USER_INVITED",
            entity="users",
            entity_id=str(user_id),
            after_state={"email": email_clean, "roles": role_codes, "expires_at": expires_at, "token_hash": token_digest},
            result="SUCCESS",
        )

        res = {
            "user_id": user_id,
            "email": email_clean,
            "token": raw_token,
            "token_hash": token_digest,
            "expires_at": expires_at,
        }
        return res

def accept_invitation(token: str, new_password: str) -> Dict[str, Any]:
    """User activates invited account and sets private password using secure token hash matching."""
    if len(new_password) < 8:
        raise ValueError("Password harus memiliki panjang minimal 8 karakter.")

    token_digest = hash_token(token)

    with get_db() as conn:
        inv = conn.execute(
            """
            SELECT id, user_id, email, expires_at, used_at
            FROM invitation_tokens
            WHERE token_hash = ?
            """,
            (token_digest,),
        ).fetchone()

        if not inv or inv["used_at"] is not None:
            raise ValueError("Token undangan tidak valid atau sudah digunakan.")

        if parse_utc_dt(inv["expires_at"]) < utc_now():
            raise ValueError("Token undangan telah kadaluarsa. Silakan minta undangan baru kepada Admin.")

        pwd_hash = hash_password(new_password)

        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, status = 'ACTIVE', updated_at = datetime('now')
            WHERE id = ?
            """,
            (pwd_hash, inv["user_id"]),
        )

        conn.execute(
            "UPDATE invitation_tokens SET used_at = datetime('now') WHERE id = ?",
            (inv["id"],),
        )

        user = conn.execute("SELECT id, full_name, email FROM users WHERE id = ?", (inv["user_id"],)).fetchone()

        log_audit(
            conn,
            actor_id=inv["user_id"],
            actor_name=user["full_name"],
            actor_role="USER",
            action="USER_ACTIVATED",
            entity="users",
            entity_id=str(inv["user_id"]),
            after_state={"status": "ACTIVE"},
            result="SUCCESS",
        )

        return {"user_id": inv["user_id"], "email": inv["email"], "status": "ACTIVE"}

def create_password_reset_token(email: str, ip_address: Optional[str] = None) -> Optional[str]:
    """
    Generate secure password reset token without revealing if email exists (prevent account enumeration).
    Stores token_hash in database. Raw token never stored in DB.
    """
    email_clean = email.strip().lower()
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, full_name, status FROM users WHERE email = ?",
            (email_clean,),
        ).fetchone()

        if not user or user["status"] in ("SUSPENDED", "DEACTIVATED"):
            log_audit(
                conn,
                actor_id=None,
                actor_name=email_clean,
                actor_role="ANONYMOUS",
                action="PASSWORD_RESET_REQUESTED",
                entity="users",
                entity_id=None,
                before_state={"email": email_clean, "found": bool(user)},
                result="FAILURE",
                ip_address=ip_address,
            )
            return None

        # Check rate limit: maximum 3 requests within 15 minutes
        recent_reqs = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM password_reset_tokens
            WHERE user_id = ? AND created_at > datetime('now', '-15 minutes')
            """,
            (user["id"],),
        ).fetchone()["cnt"]

        if recent_reqs >= 3:
            log_audit(
                conn,
                actor_id=user["id"],
                actor_name=user["full_name"],
                actor_role="USER",
                action="PASSWORD_RESET_REQUESTED",
                entity="users",
                entity_id=str(user["id"]),
                before_state={"reason": "rate_limited"},
                result="FAILURE",
                ip_address=ip_address,
            )
            return None

        # Invalidate any old unused reset tokens for this user
        conn.execute("UPDATE password_reset_tokens SET used_at = datetime('now') WHERE user_id = ? AND used_at IS NULL", (user["id"],))

        raw_token = generate_secure_token(32)
        token_digest = hash_token(raw_token)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRATION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, email, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (user["id"], email_clean, token_digest, expires_at),
        )

        log_audit(
            conn,
            actor_id=user["id"],
            actor_name=user["full_name"],
            actor_role="USER",
            action="PASSWORD_RESET_REQUESTED",
            entity="users",
            entity_id=str(user["id"]),
            after_state={"expires_at": expires_at, "token_hash": token_digest},
            result="SUCCESS",
            ip_address=ip_address,
        )

        return raw_token

def reset_password(token: str, new_password: str, ip_address: Optional[str] = None) -> bool:
    """Reset password using secure token hash matching and invalidate all active user sessions."""
    if len(new_password) < 8:
        raise ValueError("Password baru harus minimal 8 karakter.")

    token_digest = hash_token(token)

    with get_db() as conn:
        res = conn.execute(
            """
            SELECT id, user_id, expires_at, used_at
            FROM password_reset_tokens
            WHERE token_hash = ?
            """,
            (token_digest,),
        ).fetchone()

        if not res or res["used_at"] is not None:
            raise ValueError("Token reset password tidak valid atau sudah digunakan.")

        if parse_utc_dt(res["expires_at"]) < utc_now():
            raise ValueError("Token reset password telah kadaluarsa.")

        pwd_hash = hash_password(new_password)

        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, failed_login_attempts = 0, locked_until = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (pwd_hash, res["user_id"]),
        )

        conn.execute("UPDATE password_reset_tokens SET used_at = datetime('now') WHERE id = ?", (res["id"],))

        # Security requirement: Invalidate ALL active user sessions
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (res["user_id"],))

        user = conn.execute("SELECT id, full_name, email FROM users WHERE id = ?", (res["user_id"],)).fetchone()

        log_audit(
            conn,
            actor_id=res["user_id"],
            actor_name=user["full_name"],
            actor_role="USER",
            action="PASSWORD_CHANGED",
            entity="users",
            entity_id=str(res["user_id"]),
            after_state={"action": "password_reset_completed"},
            result="SUCCESS",
            ip_address=ip_address,
        )

        return True

def change_user_status(user_id: int, new_status: str, actor_user_id: int) -> bool:
    """Suspend, deactivate, or reactivate user account and revoke active sessions on deactivation."""
    if new_status not in ('ACTIVE', 'SUSPENDED', 'DEACTIVATED'):
        raise ValueError(f"Status {new_status} tidak valid.")

    with get_db() as conn:
        user = conn.execute("SELECT id, full_name, status FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise ValueError("User tidak ditemukan.")

        actor = conn.execute("SELECT full_name FROM users WHERE id = ?", (actor_user_id,)).fetchone()

        conn.execute(
            "UPDATE users SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (new_status, user_id),
        )

        # Force session invalidation if account is suspended or deactivated
        if new_status in ('SUSPENDED', 'DEACTIVATED'):
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))

        action_name = "USER_SUSPENDED" if new_status == 'SUSPENDED' else ("USER_DEACTIVATED" if new_status == 'DEACTIVATED' else "USER_ACTIVATED")
        log_audit(
            conn,
            actor_id=actor_user_id,
            actor_name=actor["full_name"] if actor else "ADMIN",
            actor_role="ADMIN",
            action=action_name,
            entity="users",
            entity_id=str(user_id),
            before_state={"status": user["status"]},
            after_state={"status": new_status},
            result="SUCCESS",
        )
        return True
