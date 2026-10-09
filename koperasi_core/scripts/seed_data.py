"""
Database Seeding Script for Koperasi Core.
Initializes roles, permissions, departments, positions, initial privileged accounts,
sample employee hierarchy, member, savings accounts, and opening balance ledger.
"""
import os
import sys
from datetime import datetime

# Adjust path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, init_db, DB_PATH, execute_insert
from app.security import hash_password, log_audit, to_decimal
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)

def seed_all():
    print(f"Initializing database at: {DB_PATH}")
    init_db(DB_PATH)

    with get_db(DB_PATH) as conn:
        # 1. Seed Roles
        roles_data = [
            (ROLE_SUPER_ADMIN, "Super Admin", "Full system administration, security, audit, user management"),
            (ROLE_ADMIN_KOPERASI, "Admin Koperasi", "Member management, imports, verifications, operational transactions"),
            (ROLE_ANGGOTA, "Anggota", "Member self-service: personal profile, savings, loan applications"),
            (ROLE_KETUA, "Ketua Koperasi", "Final executive loan approvals, cooperative policy and reports"),
            (ROLE_ATASAN_APPROVER, "Atasan / Approver", "Direct manager line approval for subordinate loan applications"),
            (ROLE_BENDAHARA, "Bendahara", "Financial disbursement, collections, and cash flow control"),
        ]
        for code, name, desc in roles_data:
            conn.execute(
                "INSERT INTO roles (code, name, description) VALUES (?, ?, ?) ON CONFLICT (code) DO NOTHING",
                (code, name, desc),
            )

        # 2. Seed Departments & Positions
        depts = [
            ("IT", "Information Technology"),
            ("HR", "Human Resources"),
            ("FIN", "Finance & Accounting"),
            ("OPS", "Operations"),
        ]
        dept_ids = {}
        for code, name in depts:
            conn.execute("INSERT INTO departments (code, name) VALUES (?, ?) ON CONFLICT (code) DO NOTHING", (code, name))
            row = conn.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()
            dept_ids[code] = row["id"]

        positions = [
            ("IT", "ENG", "Software Engineer"),
            ("IT", "IT_HEAD", "IT Department Head"),
            ("HR", "HR_SPEC", "HR Specialist"),
            ("HR", "HR_HEAD", "HR Department Head"),
            ("FIN", "FIN_OFF", "Finance Officer"),
            ("OPS", "OPS_STAFF", "Operations Staff"),
        ]
        pos_ids = {}
        for d_code, p_code, title in positions:
            d_id = dept_ids[d_code]
            conn.execute(
                "INSERT INTO positions (department_id, code, title) VALUES (?, ?, ?) ON CONFLICT (code) DO NOTHING",
                (d_id, p_code, title),
            )
            row = conn.execute("SELECT id FROM positions WHERE code = ?", (p_code,)).fetchone()
            pos_ids[p_code] = row["id"]

        # Helper to create user and assign role
        def create_user_if_not_exists(email, password, full_name, role_codes, status="ACTIVE"):
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if not user:
                pwd_hash = hash_password(password)
                user_id = execute_insert(
                    conn,
                    """
                    INSERT INTO users (email, password_hash, full_name, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    (email, pwd_hash, full_name, status),
                )
                print(f"Created user: {email} (ID: {user_id})")
                log_audit(
                    conn,
                    actor_id=user_id,
                    actor_name="SYSTEM_SEED",
                    actor_role="SYSTEM",
                    action="USER_CREATED",
                    entity="users",
                    entity_id=str(user_id),
                    after_state={"email": email, "full_name": full_name, "status": status},
                )
            else:
                user_id = user["id"]

            for r_code in role_codes:
                role = conn.execute("SELECT id FROM roles WHERE code = ?", (r_code,)).fetchone()
                if role:
                    conn.execute(
                        "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?) ON CONFLICT (user_id, role_id) DO NOTHING",
                        (user_id, role["id"]),
                    )
            return user_id

        # 3. Privileged Users
        superadmin_id = create_user_if_not_exists("superadmin@koperasi.local", "SuperAdmin123!", "Super Administrator", [ROLE_SUPER_ADMIN])
        admin_id = create_user_if_not_exists("admin@koperasi.local", "Admin123!", "Admin Koperasi", [ROLE_ADMIN_KOPERASI])
        ketua_id = create_user_if_not_exists("ketua@koperasi.local", "Ketua123!", "Drs. Hendro Wibowo (Ketua)", [ROLE_KETUA, ROLE_ATASAN_APPROVER])
        bendahara_id = create_user_if_not_exists("bendahara@koperasi.local", "Bendahara123!", "Siti Rahmawati (Bendahara)", [ROLE_BENDAHARA])

        # 4. Organization Structure & Employees
        # Manager: Budi Santoso (Head of IT) -> approver
        budi_user_id = create_user_if_not_exists(
            "manager.budi@koperasi.local", "Manager123!", "Budi Santoso", [ROLE_ATASAN_APPROVER]
        )
        budi_emp = conn.execute("SELECT id FROM employees WHERE employee_id = 'EMP-001'").fetchone()
        if not budi_emp:
            budi_emp_id = execute_insert(
                conn,
                """
                INSERT INTO employees (employee_id, name, nik, email, phone, department_id, position_id, manager_id, status)
                VALUES ('EMP-001', 'Budi Santoso', '3171010101800001', 'manager.budi@koperasi.local', '081234567890', ?, ?, NULL, 'ACTIVE')
                """,
                (dept_ids["IT"], pos_ids["IT_HEAD"]),
            )
        else:
            budi_emp_id = budi_emp["id"]

        # Subordinate Employee & Member: Andi Pratama (Software Engineer, reports to Budi)
        andi_user_id = create_user_if_not_exists(
            "member.andi@koperasi.local", "Member123!", "Andi Pratama", [ROLE_ANGGOTA]
        )
        andi_emp = conn.execute("SELECT id FROM employees WHERE employee_id = 'EMP-002'").fetchone()
        if not andi_emp:
            andi_emp_id = execute_insert(
                conn,
                """
                INSERT INTO employees (employee_id, name, nik, email, phone, department_id, position_id, manager_id, status)
                VALUES ('EMP-002', 'Andi Pratama', '3171010202900002', 'member.andi@koperasi.local', '081234567891', ?, ?, ?, 'ACTIVE')
                """,
                (dept_ids["IT"], pos_ids["ENG"], budi_emp_id),
            )
        else:
            andi_emp_id = andi_emp["id"]

        # Andi Member Record
        andi_member = conn.execute("SELECT id FROM members WHERE member_number = 'MEM-001'").fetchone()
        if not andi_member:
            andi_member_id = execute_insert(
                conn,
                """
                INSERT INTO members (
                    member_number, employee_id, user_id, name, nik, email, phone,
                    address, bank_account, membership_date, membership_status
                ) VALUES (
                    'MEM-001', ?, ?, 'Andi Pratama', '3171010202900002', 'member.andi@koperasi.local',
                    '081234567891', 'Jl. Merdeka No. 10, Jakarta Pusat', 'BCA 1234567890', '2024-01-15', 'ACTIVE'
                )
                """,
                (andi_emp_id, andi_user_id),
            )
            print(f"Created initial member Andi Pratama (MEM-001, ID: {andi_member_id})")

            # Create savings accounts for Andi: POKOK, WAJIB, SUKARELA
            for acc_type in ["POKOK", "WAJIB", "SUKARELA"]:
                acc_num = f"SA-{acc_type[:3]}-MEM-001"
                acc_id = execute_insert(
                    conn,
                    "INSERT INTO savings_accounts (member_id, account_number, account_type, status) VALUES (?, ?, ?, 'ACTIVE') ON CONFLICT (account_number) DO NOTHING",
                    (andi_member_id, acc_num, acc_type),
                )

                # Add initial opening balance transaction
                initial_amount = "500000.00" if acc_type == "POKOK" else ("100000.00" if acc_type == "WAJIB" else "250000.00")
                conn.execute(
                    """
                    INSERT INTO savings_transactions (
                        account_id, member_id, transaction_type, amount, balance_after,
                        reference_type, reference_id, description, transaction_date, created_by
                    ) VALUES (?, ?, 'CREDIT', ?, ?, 'OPENING_BALANCE', 'INIT-SEED', ?, '2024-01-15', ?)
                    """,
                    (acc_id, andi_member_id, initial_amount, initial_amount, f"Saldo Awal Simpanan {acc_type}", admin_id),
                )
                conn.execute(
                    """
                    INSERT INTO savings_opening_balances (
                        account_id, member_id, account_type, amount, effective_date, reference, notes, created_by
                    ) VALUES (?, ?, ?, ?, '2024-01-15', 'INIT-SEED', 'Opening balance seed data', ?)
                    """,
                    (acc_id, andi_member_id, acc_type, initial_amount, admin_id),
                )
                # Financial transaction record
                conn.execute(
                    """
                    INSERT INTO financial_transactions (
                        transaction_number, transaction_type, category, amount, idempotency_key,
                        reference_type, reference_id, description, created_by
                    ) VALUES (?, 'INFLOW', 'OPENING_BALANCE', ?, ?, 'SAVINGS_ACCOUNT', ?, ?, ?)
                    """,
                    (
                        f"FT-INIT-{acc_type}-001",
                        initial_amount,
                        f"IDEMP-INIT-{acc_type}-001",
                        str(acc_id),
                        f"Setoran Awal Simpanan {acc_type} Anggota MEM-001",
                        admin_id,
                    ),
                )

        print("Seeding completed successfully!")

if __name__ == "__main__":
    seed_all()
