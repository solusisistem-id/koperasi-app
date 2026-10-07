"""
Authentication, Session, RBAC, Invitation, and Password Reset Services.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import secrets

from app.database import get_db, DB_PATH
from app.security import (
    hash_password,
    verify_password,
    generate_secure_token,
    log_audit,
)
from app.config import (
    SESSION_LIFETIME_HOURS,
    TOKEN_EXPIRATION_HOURS,
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

def authenticate_user(email: str, password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Dict[str, Any]:
    """Authenticate user with email and password, enforce lifecycle state and rate limiting."""
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash, full_name, status, failed_login_attempts, locked_until FROM users WHERE email = ?",
            (email.strip(),),
        ).fetchone()

        if not user:
            log_audit(
                conn,
                actor_id=None,
                actor_name=email,
                actor_role="ANONYMOUS",
                action="LOGIN_FAILED",
                entity="users",
                entity_id=None,
                before_state={"email": email, "reason": "user_not_found"},
                result="FAILURE",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthenticationError("Email atau password tidak valid.")

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
            raise AuthenticationError(f"Akun Anda sedang {user['status'].lower()}. Silakan hubungi Administrator.")

        if user["status"] in ("INVITED", "PENDING_ACTIVATION"):
            raise AuthenticationError("Akun belum diaktivasi. Silakan periksa tautan aktivasi/undangan Anda.")

        if not verify_password(password, user["password_hash"]):
            failed_attempts = user["failed_login_attempts"] + 1
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
            raise AuthenticationError("Email atau password tidak valid.")

        # Reset failed login attempts and update last login
        conn.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = datetime('now') WHERE id = ?",
            (user["id"],),
        )

        # Create session token
        session_token = generate_secure_token(32)
        expires_at = (datetime.utcnow() + timedelta(hours=SESSION_LIFETIME_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT INTO user_sessions (user_id, session_token, expires_at, created_at, user_agent, ip_address)
            VALUES (?, ?, ?, datetime('now'), ?, ?)
            """,
            (user["id"], session_token, expires_at, user_agent, ip_address),
        )

        # Fetch roles
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
            "expires_at": expires_at,
        }

def get_user_from_session(session_token: str) -> Optional[Dict[str, Any]]:
    """Retrieve active user from valid session token."""
    if not session_token:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.full_name, u.status, s.expires_at, s.id as session_id
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_token = ? AND s.expires_at > datetime('now')
            """,
            (session_token,),
        ).fetchone()

        if not row:
            return None

        if row["status"] in ("SUSPENDED", "DEACTIVATED"):
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

        # Check if user has associated member or employee
        member = conn.execute("SELECT id, member_number FROM members WHERE user_id = ?", (row["id"],)).fetchone()
        employee = conn.execute("SELECT id, employee_id, manager_id FROM employees WHERE email = ?", (row["email"],)).fetchone()

        return {
            "id": row["id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "status": row["status"],
            "roles": role_codes,
            "member_id": member["id"] if member else None,
            "member_number": member["member_number"] if member else None,
            "employee_id": employee["id"] if employee else None,
            "manager_id": employee["manager_id"] if employee else None,
            "session_id": row["session_id"],
        }

def invalidate_session(session_token: str):
    """Log out user and invalidate session."""
    with get_db() as conn:
        conn.execute("DELETE FROM user_sessions WHERE session_token = ?", (session_token,))

def create_user_invitation(email: str, full_name: str, role_codes: List[str], creator_user_id: int) -> Dict[str, Any]:
    """Admin invites a user. User account is created in INVITED status without default password."""
    email_clean = email.strip().lower()
    with get_db() as conn:
        existing = conn.execute("SELECT id, email, status FROM users WHERE email = ?", (email_clean,)).fetchone()
        if existing:
            raise ValueError(f"Email {email_clean} sudah terdaftar dalam sistem.")

        # Create placeholder un-guessable password hash
        dummy_pwd = secrets.token_hex(32)
        pwd_hash = hash_password(dummy_pwd)

        cur = conn.execute(
            """
            INSERT INTO users (email, password_hash, full_name, status, created_at, updated_at)
            VALUES (?, ?, ?, 'INVITED', datetime('now'), datetime('now'))
            """,
            (email_clean, pwd_hash, full_name.strip()),
        )
        user_id = cur.lastrowid

        # Assign roles
        for r_code in role_codes:
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (r_code,)).fetchone()
            if role:
                conn.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
                    (user_id, role["id"]),
                )

        # Generate invitation token
        token = generate_secure_token(32)
        expires_at = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT INTO invitation_tokens (user_id, email, token, expires_at, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (user_id, email_clean, token, expires_at, creator_user_id),
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
            after_state={"email": email_clean, "roles": role_codes, "expires_at": expires_at},
            result="SUCCESS",
        )

        return {
            "user_id": user_id,
            "email": email_clean,
            "token": token,
            "expires_at": expires_at,
        }

def accept_invitation(token: str, new_password: str) -> Dict[str, Any]:
    """User activates invited account and sets their own private password."""
    if len(new_password) < 8:
        raise ValueError("Password harus memiliki panjang minimal 8 karakter.")

    with get_db() as conn:
        inv = conn.execute(
            """
            SELECT id, user_id, email, expires_at, used_at
            FROM invitation_tokens
            WHERE token = ?
            """,
            (token,),
        ).fetchone()

        if not inv:
            raise ValueError("Token undangan tidak valid.")

        if inv["used_at"] is not None:
            raise ValueError("Token undangan sudah pernah digunakan.")

        if datetime.strptime(inv["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.utcnow():
            raise ValueError("Token undangan telah kadaluarsa. Silakan minta undangan baru kepada Admin.")

        # Hash new password
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
    """Generate secure password reset token without revealing if email exists to the public caller."""
    email_clean = email.strip().lower()
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, full_name, status FROM users WHERE email = ?",
            (email_clean,),
        ).fetchone()

        # In both cases, we log internally but do not leak existence to outsider
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

        # Invalidate any old unused reset tokens for this user
        conn.execute("UPDATE password_reset_tokens SET used_at = datetime('now') WHERE user_id = ? AND used_at IS NULL", (user["id"],))

        token = generate_secure_token(32)
        expires_at = (datetime.utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, email, token, expires_at, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (user["id"], email_clean, token, expires_at),
        )

        log_audit(
            conn,
            actor_id=user["id"],
            actor_name=user["full_name"],
            actor_role="USER",
            action="PASSWORD_RESET_REQUESTED",
            entity="users",
            entity_id=str(user["id"]),
            after_state={"expires_at": expires_at},
            result="SUCCESS",
            ip_address=ip_address,
        )

        return token

def reset_password(token: str, new_password: str, ip_address: Optional[str] = None) -> bool:
    """Reset password using secure token and invalidate all active sessions."""
    if len(new_password) < 8:
        raise ValueError("Password baru harus minimal 8 karakter.")

    with get_db() as conn:
        res = conn.execute(
            """
            SELECT id, user_id, expires_at, used_at
            FROM password_reset_tokens
            WHERE token = ?
            """,
            (token,),
        ).fetchone()

        if not res or res["used_at"] is not None:
            raise ValueError("Token reset password tidak valid atau sudah digunakan.")

        if datetime.strptime(res["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.utcnow():
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

        # Invalidate all active user sessions for security
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
    """Suspend, deactivate, or reactivate user account."""
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
