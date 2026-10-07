"""
Member Service for Koperasi Core.
Enforces object-level authorization, member-employee-user separation,
and audit logging.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime

from app.database import get_db
from app.security import log_audit, generate_secure_token, hash_password
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_BENDAHARA,
    TOKEN_EXPIRATION_HOURS,
)

class MemberAccessForbidden(Exception):
    pass

def can_access_member_data(current_user: Dict[str, Any], target_member_id: int) -> bool:
    """Object-level authorization check: Members can only access their own data."""
    roles = current_user.get("roles", [])
    privileged_roles = {ROLE_SUPER_ADMIN, ROLE_ADMIN_KOPERASI, ROLE_KETUA, ROLE_BENDAHARA}
    if any(r in privileged_roles for r in roles):
        return True
    # If member, only allowed if current_user's member_id matches target_member_id
    return current_user.get("member_id") == target_member_id

def get_member_by_id(member_id: int, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve member by ID with strict object-level authorization."""
    if not can_access_member_data(current_user, member_id):
        raise MemberAccessForbidden("Akses ditolak: Anda hanya dapat melihat data keanggotaan Anda sendiri.")

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT m.*, e.employee_id as emp_code, d.name as department_name, p.title as position_title,
                   u.status as user_account_status, u.last_login_at
            FROM members m
            LEFT JOIN employees e ON m.employee_id = e.id
            LEFT JOIN departments d ON e.department_id = d.id
            LEFT JOIN positions p ON e.position_id = p.id
            LEFT JOIN users u ON m.user_id = u.id
            WHERE m.id = ?
            """,
            (member_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"Anggota dengan ID {member_id} tidak ditemukan.")

        return dict(row)

def get_member_by_number(member_number: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve member by member_number with object-level authorization."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM members WHERE member_number = ?", (member_number,)).fetchone()
        if not row:
            raise ValueError(f"Anggota dengan nomor {member_number} tidak ditemukan.")
        return get_member_by_id(row["id"], current_user)

def list_members(
    current_user: Dict[str, Any],
    query: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List members. Normal members can only view their own record."""
    roles = current_user.get("roles", [])
    privileged_roles = {ROLE_SUPER_ADMIN, ROLE_ADMIN_KOPERASI, ROLE_KETUA, ROLE_BENDAHARA}
    is_privileged = any(r in privileged_roles for r in roles)

    with get_db() as conn:
        if not is_privileged:
            # Strictly member self-view
            user_member_id = current_user.get("member_id")
            if not user_member_id:
                return {"items": [], "total": 0}
            row = conn.execute(
                """
                SELECT m.*, e.employee_id as emp_code, d.name as department_name, p.title as position_title,
                       u.status as user_account_status
                FROM members m
                LEFT JOIN employees e ON m.employee_id = e.id
                LEFT JOIN departments d ON e.department_id = d.id
                LEFT JOIN positions p ON e.position_id = p.id
                LEFT JOIN users u ON m.user_id = u.id
                WHERE m.id = ?
                """,
                (user_member_id,),
            ).fetchone()
            items = [dict(row)] if row else []
            return {"items": items, "total": len(items)}

        # Privileged admin listing
        sql = """
            SELECT m.*, e.employee_id as emp_code, d.name as department_name, p.title as position_title,
                   u.status as user_account_status, u.id as user_id_val
            FROM members m
            LEFT JOIN employees e ON m.employee_id = e.id
            LEFT JOIN departments d ON e.department_id = d.id
            LEFT JOIN positions p ON e.position_id = p.id
            LEFT JOIN users u ON m.user_id = u.id
            WHERE 1=1
        """
        params = []
        if query:
            q_like = f"%{query.strip()}%"
            sql += " AND (m.member_number LIKE ? OR m.name LIKE ? OR m.nik LIKE ? OR m.email LIKE ?)"
            params.extend([q_like, q_like, q_like, q_like])
        if status:
            sql += " AND m.membership_status = ?"
            params.append(status)

        count_sql = f"SELECT COUNT(*) as total FROM ({sql})"
        total = conn.execute(count_sql, params).fetchone()["total"]

        sql += " ORDER BY m.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()

        return {"items": [dict(r) for r in rows], "total": total}

def create_member_manual(data: Dict[str, Any], current_user: Dict[str, Any]) -> int:
    """Admin creates member manually with initial savings accounts."""
    roles = current_user.get("roles", [])
    if ROLE_SUPER_ADMIN not in roles and ROLE_ADMIN_KOPERASI not in roles:
        raise MemberAccessForbidden("Hanya Admin yang dapat mendaftarkan anggota baru.")

    member_number = data["member_number"].strip().upper()
    nik = data["nik"].strip()
    email = data["email"].strip().lower()
    name = data["name"].strip()
    phone = data.get("phone", "").strip()
    address = data.get("address", "").strip()
    bank_account = data.get("bank_account", "").strip()
    membership_date = data.get("membership_date", datetime.utcnow().strftime("%Y-%m-%d"))
    membership_status = data.get("membership_status", "ACTIVE")

    with get_db() as conn:
        # Check duplicate member_number
        if conn.execute("SELECT id FROM members WHERE member_number = ?", (member_number,)).fetchone():
            raise ValueError(f"Nomor anggota {member_number} sudah terdaftar.")
        if conn.execute("SELECT id FROM members WHERE nik = ?", (nik,)).fetchone():
            raise ValueError(f"NIK {nik} sudah terdaftar pada anggota lain.")

        cur = conn.execute(
            """
            INSERT INTO members (
                member_number, name, nik, email, phone, address, bank_account,
                membership_date, membership_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (member_number, name, nik, email, phone, address, bank_account, membership_date, membership_status),
        )
        member_id = cur.lastrowid

        # Automatically create the 3 savings accounts
        for acc_type in ["POKOK", "WAJIB", "SUKARELA"]:
            acc_num = f"SA-{acc_type[:3]}-{member_number}"
            conn.execute(
                "INSERT INTO savings_accounts (member_id, account_number, account_type, status) VALUES (?, ?, ?, 'ACTIVE')",
                (member_id, acc_num, acc_type),
            )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ADMIN",
            action="MEMBER_CREATED",
            entity="members",
            entity_id=str(member_id),
            after_state={"member_number": member_number, "name": name, "nik": nik, "email": email},
            result="SUCCESS",
        )
        return member_id

def create_user_for_member(member_id: int, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates login account in INVITED state for a member.
    Generates single-use invitation token. Admin does NOT see or set a default password.
    """
    roles = current_user.get("roles", [])
    if ROLE_SUPER_ADMIN not in roles and ROLE_ADMIN_KOPERASI not in roles:
        raise MemberAccessForbidden("Hanya Admin yang dapat membuat akun login untuk anggota.")

    with get_db() as conn:
        member = conn.execute("SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()
        if not member:
            raise ValueError("Anggota tidak ditemukan.")

        if member["user_id"]:
            # Check if user already exists
            user = conn.execute("SELECT id, email, status FROM users WHERE id = ?", (member["user_id"],)).fetchone()
            if user and user["status"] == "ACTIVE":
                raise ValueError("Anggota ini sudah memiliki akun aktif.")

        # Check if email is already taken
        user = conn.execute("SELECT id, status FROM users WHERE email = ?", (member["email"],)).fetchone()
        if not user:
            from app.security import hash_password
            dummy_pwd = generate_secure_token(32)
            cur = conn.execute(
                """
                INSERT INTO users (email, password_hash, full_name, status, created_at, updated_at)
                VALUES (?, ?, ?, 'INVITED', datetime('now'), datetime('now'))
                """,
                (member["email"], hash_password(dummy_pwd), member["name"]),
            )
            user_id = cur.lastrowid
            # Assign ANGGOTA role
            role_anggota = conn.execute("SELECT id FROM roles WHERE code = ?", (ROLE_ANGGOTA,)).fetchone()
            if role_anggota:
                conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_anggota["id"]))
        else:
            user_id = user["id"]

        # Link member to user_id
        conn.execute("UPDATE members SET user_id = ?, updated_at = datetime('now') WHERE id = ?", (user_id, member_id))

        # Generate invitation token
        token = generate_secure_token(32)
        from datetime import timedelta
        expires_at = (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT INTO invitation_tokens (user_id, email, token, expires_at, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (user_id, member["email"], token, expires_at, current_user["id"]),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ADMIN",
            action="USER_INVITED",
            entity="users",
            entity_id=str(user_id),
            after_state={"member_id": member_id, "email": member["email"], "token_created": True},
            result="SUCCESS",
        )

        return {
            "member_id": member_id,
            "user_id": user_id,
            "email": member["email"],
            "invitation_token": token,
            "expires_at": expires_at,
        }
