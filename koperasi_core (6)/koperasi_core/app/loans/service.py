"""
Loans, Multi-level Approval Engine, Disbursement, and Installments Service.
Enforces maker-checker guardrails, automatic manager routing, exact Decimal math,
idempotent installment processing, and audit logging.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import secrets

from app.database import get_db, execute_insert
from app.security import (
    to_decimal,
    format_rupiah,
    log_audit,
    generate_reference_number,
    generate_secure_token,
    hash_token,
)
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)

class LoanError(Exception):
    pass

class MakerCheckerViolation(LoanError):
    pass

def calculate_loan_schedule(amount: Decimal, tenor_months: int, monthly_interest_rate: Decimal = Decimal("0.01")) -> Dict[str, Any]:
    """Calculate principal, total interest, total obligation, and monthly installment."""
    total_interest = (amount * monthly_interest_rate * Decimal(tenor_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_amount = amount + total_interest
    monthly_installment = (total_amount / Decimal(tenor_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    principal_per_month = (amount / Decimal(tenor_months)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    interest_per_month = monthly_installment - principal_per_month

    return {
        "principal": amount,
        "total_interest": total_interest,
        "total_amount": total_amount,
        "monthly_installment": monthly_installment,
        "principal_per_month": principal_per_month,
        "interest_per_month": interest_per_month,
    }

def apply_for_loan(
    member_id: int,
    amount_str: str,
    tenor_months: int,
    purpose: str,
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Member applies for a loan.
    Automatically resolves applicant's manager from employee organization structure.
    """
    from app.members.service import can_access_member_data
    if not can_access_member_data(current_user, member_id):
        raise LoanError("Akses ditolak: Anda hanya dapat mengajukan pinjaman untuk akun Anda sendiri.")

    amount = to_decimal(amount_str)
    if amount <= Decimal("0.00"):
        raise LoanError("Nominal pinjaman harus lebih besar dari 0.")
    if tenor_months not in (3, 6, 12, 18, 24, 36):
        raise LoanError("Tenor harus salah satu dari: 3, 6, 12, 18, 24, atau 36 bulan.")
    if not purpose or len(purpose.strip()) < 5:
        raise LoanError("Keperluan pinjaman harus diisi secara jelas.")

    sched = calculate_loan_schedule(amount, tenor_months)
    app_number = generate_reference_number("LAPP")

    with get_db() as conn:
        # Check if member has existing active loan with unpaid balance
        existing_loan = conn.execute(
            """
            SELECT l.id, l.loan_number, l.outstanding_amount
            FROM loans l
            WHERE l.member_id = ? AND l.status = 'ACTIVE' AND CAST(l.outstanding_amount AS NUMERIC) > 0
            """,
            (member_id,),
        ).fetchone()
        if existing_loan:
            raise LoanError(f"Anda masih memiliki pinjaman aktif ({existing_loan['loan_number']}) dengan sisa pinjaman {format_rupiah(existing_loan['outstanding_amount'])}.")

        # Determine manager via employee hierarchy
        member = conn.execute("SELECT m.*, e.manager_id, e.name as emp_name FROM members m LEFT JOIN employees e ON m.employee_id = e.id WHERE m.id = ?", (member_id,)).fetchone()
        if not member:
            raise LoanError("Data anggota tidak ditemukan.")

        assigned_manager_user_id = None
        current_step = "MANAGER"

        if member["manager_id"]:
            # Find user account linked to the manager employee
            mgr_emp = conn.execute("SELECT email FROM employees WHERE id = ?", (member["manager_id"],)).fetchone()
            if mgr_emp:
                mgr_user = conn.execute("SELECT id FROM users WHERE email = ?", (mgr_emp["email"],)).fetchone()
                if mgr_user:
                    assigned_manager_user_id = mgr_user["id"]

        # If no specific manager found, fallback step to KETUA directly
        if not assigned_manager_user_id:
            current_step = "KETUA"

        app_id = execute_insert(
            conn,
            """
            INSERT INTO loan_applications (
                application_number, member_id, amount, tenor_months, interest_rate,
                monthly_installment, purpose, status, current_step, assigned_manager_id,
                submitted_at, updated_at
            ) VALUES (?, ?, ?, ?, '0.01', ?, ?, 'SUBMITTED', ?, ?, datetime('now'), datetime('now'))
            """,
            (
                app_number,
                member_id,
                str(amount),
                tenor_months,
                str(sched["monthly_installment"]),
                purpose.strip(),
                current_step,
                assigned_manager_user_id,
            ),
        )

        # Insert initial approval steps
        if assigned_manager_user_id:
            conn.execute(
                """
                INSERT INTO loan_approval_steps (application_id, step_order, approver_role, approver_user_id, status)
                VALUES (?, 1, 'MANAGER', ?, 'PENDING')
                """,
                (app_id, assigned_manager_user_id),
            )
            conn.execute(
                """
                INSERT INTO loan_approval_steps (application_id, step_order, approver_role, approver_user_id, status)
                VALUES (?, 2, 'KETUA', NULL, 'PENDING')
                """,
                (app_id,),
            )
        else:
            conn.execute(
                """
                INSERT INTO loan_approval_steps (application_id, step_order, approver_role, approver_user_id, status)
                VALUES (?, 1, 'KETUA', NULL, 'PENDING')
                """,
                (app_id,),
            )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ANGGOTA",
            action="LOAN_SUBMITTED",
            entity="loan_applications",
            entity_id=str(app_id),
            after_state={
                "application_number": app_number,
                "amount": str(amount),
                "tenor_months": tenor_months,
                "assigned_manager_id": assigned_manager_user_id,
                "current_step": current_step,
            },
            result="SUCCESS",
        )

        return {
            "application_id": app_id,
            "application_number": app_number,
            "amount": str(amount),
            "tenor_months": tenor_months,
            "monthly_installment": str(sched["monthly_installment"]),
            "current_step": current_step,
        }

def process_approval(
    application_id: int,
    decision: str, # APPROVE, REJECT, REQUEST_REVISION
    comment: str,
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute approval step with strict maker-checker validation:
    1. Approver cannot approve own application.
    2. Approver must hold the requisite role for current step.
    3. Transition status accordingly.
    """
    if decision not in ("APPROVE", "REJECT", "REQUEST_REVISION"):
        raise LoanError(f"Keputusan '{decision}' tidak valid.")

    with get_db() as conn:
        app = conn.execute(
            """
            SELECT la.*, m.user_id as member_user_id, m.name as member_name, m.member_number
            FROM loan_applications la
            JOIN members m ON la.member_id = m.id
            WHERE la.id = ? FOR UPDATE
            """,
            (application_id,),
        ).fetchone()

        if not app:
            raise LoanError(f"Pengajuan pinjaman ID {application_id} tidak ditemukan.")

        if app["status"] in ("REJECTED", "DISBURSED", "CANCELLED"):
            raise LoanError(f"Pengajuan pinjaman sudah berstatus {app['status']} dan tidak dapat diproses lagi.")

        # Guardrail: MAKER-CHECKER (Approver cannot approve own application)
        if app["member_user_id"] == current_user["id"]:
            raise MakerCheckerViolation("Pelanggaran Maker-Checker: Anda tidak dapat menyetujui pengajuan pinjaman Anda sendiri.")

        user_roles = current_user.get("roles", [])
        current_step = app["current_step"]
        before_status = app["status"]
        after_status = before_status
        next_step = current_step

        # Step 1: MANAGER Approval
        if current_step == "MANAGER":
            is_assigned_mgr = (app["assigned_manager_id"] == current_user["id"])
            has_approver_role = ROLE_ATASAN_APPROVER in user_roles or ROLE_SUPER_ADMIN in user_roles
            if not (is_assigned_mgr or has_approver_role):
                raise LoanError("Akses ditolak: Anda bukan atasan yang ditugaskan untuk pengajuan ini.")

            if decision == "APPROVE":
                after_status = "APPROVED_BY_MANAGER"
                next_step = "KETUA"
                conn.execute(
                    "UPDATE loan_approval_steps SET status = 'APPROVED', updated_at = datetime('now') WHERE application_id = ? AND step_order = 1",
                    (application_id,),
                )
            elif decision == "REJECT":
                after_status = "REJECTED"
                next_step = "COMPLETED"
                conn.execute(
                    "UPDATE loan_approval_steps SET status = 'REJECTED', updated_at = datetime('now') WHERE application_id = ? AND step_order = 1",
                    (application_id,),
                )
            elif decision == "REQUEST_REVISION":
                after_status = "REVISION_REQUESTED"
                next_step = "MEMBER"

        # Step 2: KETUA Approval
        elif current_step == "KETUA":
            if ROLE_KETUA not in user_roles and ROLE_SUPER_ADMIN not in user_roles:
                raise LoanError("Akses ditolak: Hanya Ketua Koperasi yang dapat melakukan persetujuan pada tahap ini.")

            if decision == "APPROVE":
                after_status = "WAITING_DISBURSEMENT"
                next_step = "BENDAHARA"
                conn.execute(
                    "UPDATE loan_approval_steps SET status = 'APPROVED', approver_user_id = ?, updated_at = datetime('now') WHERE application_id = ? AND approver_role = 'KETUA'",
                    (current_user["id"], application_id),
                )
            elif decision == "REJECT":
                after_status = "REJECTED"
                next_step = "COMPLETED"
                conn.execute(
                    "UPDATE loan_approval_steps SET status = 'REJECTED', approver_user_id = ?, updated_at = datetime('now') WHERE application_id = ? AND approver_role = 'KETUA'",
                    (current_user["id"], application_id),
                )
            elif decision == "REQUEST_REVISION":
                after_status = "REVISION_REQUESTED"
                next_step = "MEMBER"

        else:
            raise LoanError(f"Tahap saat ini '{current_step}' tidak menerima review approval biasa.")

        # Update loan application state
        conn.execute(
            """
            UPDATE loan_applications
            SET status = ?, current_step = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (after_status, next_step, application_id),
        )

        audit_ref = generate_reference_number("APPR-LOG")
        acting_role = "KETUA" if current_step == "KETUA" else "MANAGER"
        conn.execute(
            """
            INSERT INTO loan_approvals (
                application_id, approver_id, role, decision, comment,
                before_status, after_status, audit_reference, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                application_id,
                current_user["id"],
                acting_role,
                decision,
                comment.strip() if comment else "",
                before_status,
                after_status,
                audit_ref,
            ),
        )

        action_name = "APPROVAL_APPROVED" if decision == "APPROVE" else ("APPROVAL_REJECTED" if decision == "REJECT" else "REVISION_REQUESTED")
        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role=acting_role,
            action=action_name,
            entity="loan_applications",
            entity_id=str(application_id),
            before_state={"status": before_status, "step": current_step},
            after_state={"status": after_status, "step": next_step, "decision": decision, "comment": comment},
            result="SUCCESS",
        )

        return {
            "application_id": application_id,
            "decision": decision,
            "before_status": before_status,
            "after_status": after_status,
            "current_step": next_step,
        }

def disburse_loan(
    application_id: int,
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Bendahara performs loan disbursement:
    1. Creates active loan record.
    2. Generates installment schedule.
    3. Records financial transaction (OUTFLOW).
    4. Generates SK Pinjaman document with QR verification token.
    5. Sets application status to DISBURSED.
    """
    user_roles = current_user.get("roles", [])
    if ROLE_BENDAHARA not in user_roles and ROLE_SUPER_ADMIN not in user_roles:
        raise LoanError("Akses ditolak: Hanya Bendahara yang dapat melakukan pencairan pinjaman.")

    with get_db() as conn:
        app = conn.execute(
            """
            SELECT la.*, m.member_number, m.name as member_name, m.bank_account
            FROM loan_applications la
            JOIN members m ON la.member_id = m.id
            WHERE la.id = ? FOR UPDATE
            """,
            (application_id,),
        ).fetchone()

        if not app:
            raise LoanError("Pengajuan pinjaman tidak ditemukan.")

        if app["status"] == "DISBURSED":
            existing_l = conn.execute("SELECT * FROM loans WHERE application_id = ?", (application_id,)).fetchone()
            if existing_l:
                return {
                    "loan_id": existing_l["id"],
                    "loan_number": existing_l["loan_number"],
                    "disbursed_amount": str(existing_l["principal_amount"]),
                    "document_id": None,
                    "qr_token": None,
                    "status": "DISBURSED",
                    "already_processed": True,
                }
        if app["status"] != "WAITING_DISBURSEMENT":
            raise LoanError(f"Pinjaman tidak dapat dicairkan. Status saat ini: {app['status']} (harus WAITING_DISBURSEMENT).")

        principal = to_decimal(app["amount"])
        tenor_months = app["tenor_months"]
        sched = calculate_loan_schedule(principal, tenor_months)
        loan_number = generate_reference_number("LOAN")

        start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Due date: end of tenor
        due_date = (datetime.now(timezone.utc) + timedelta(days=30 * tenor_months)).strftime("%Y-%m-%d")

        # 1. Create active loan
        loan_id = execute_insert(
            conn,
            """
            INSERT INTO loans (
                loan_number, application_id, member_id, principal_amount, total_amount,
                outstanding_amount, tenor_months, monthly_installment, start_date, due_date,
                status, disbursed_by, disbursed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, datetime('now'), datetime('now'))
            """,
            (
                loan_number,
                application_id,
                app["member_id"],
                str(principal),
                str(sched["total_amount"]),
                str(sched["total_amount"]),
                tenor_months,
                str(sched["monthly_installment"]),
                start_date,
                due_date,
                current_user["id"],
            ),
        )

        # 2. Generate installment schedule
        for inst_num in range(1, tenor_months + 1):
            inst_due = (datetime.now(timezone.utc) + timedelta(days=30 * inst_num)).strftime("%Y-%m-%d")
            inst_idemp = f"IDEMP-{loan_number}-INST-{inst_num}"
            conn.execute(
                """
                INSERT INTO loan_installments (
                    loan_id, installment_number, due_date, amount, principal_portion,
                    interest_portion, paid_amount, status, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, '0', 'PENDING', ?, datetime('now'))
                """,
                (
                    loan_id,
                    inst_num,
                    inst_due,
                    str(sched["monthly_installment"]),
                    str(sched["principal_per_month"]),
                    str(sched["interest_per_month"]),
                    inst_idemp,
                ),
            )

        # 3. Financial Transaction Outflow
        tx_num = generate_reference_number("FT-DISB")
        conn.execute(
            """
            INSERT INTO financial_transactions (
                transaction_number, transaction_type, category, amount, idempotency_key,
                reference_type, reference_id, description, created_by, created_at
            ) VALUES (?, 'OUTFLOW', 'LOAN_DISBURSEMENT', ?, ?, 'LOAN', ?, ?, ?, datetime('now'))
            """,
            (
                tx_num,
                str(principal),
                f"IDEMP-{tx_num}",
                str(loan_id),
                f"Pencairan Pinjaman {loan_number} Anggota {app['member_number']} ({app['member_name']})",
                current_user["id"],
            ),
        )

        # 4. Generate SK Pinjaman Document & QR Token
        doc_num = generate_reference_number("DOC-SKP")
        doc_id = execute_insert(
            conn,
            """
            INSERT INTO documents (
                document_number, title, document_type, owner_user_id, reference_type,
                reference_id, storage_key, verification_status, verified_by, verified_at, created_at
            ) VALUES (?, ?, 'SK_PINJAMAN', ?, 'LOAN', ?, ?, 'VERIFIED', ?, datetime('now'), datetime('now'))
            """,
            (
                doc_num,
                f"Surat Keputusan Pinjaman {loan_number}",
                app["member_id"],
                str(loan_id),
                secrets.token_hex(16),
                current_user["id"],
            ),
        )

        qr_token = generate_secure_token(24)
        qr_digest = hash_token(qr_token)
        qr_display = f"{qr_token[:4]}...{qr_token[-4:]}"
        conn.execute(
            """
            INSERT INTO qr_verification_tokens (token_hash, token_display, document_id, is_revoked, created_at)
            VALUES (?, ?, ?, 0, datetime('now'))
            """,
            (qr_digest, qr_display, doc_id),
        )

        # 5. Update loan application status to DISBURSED
        conn.execute(
            "UPDATE loan_applications SET status = 'DISBURSED', current_step = 'COMPLETED', updated_at = datetime('now') WHERE id = ?",
            (application_id,),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="BENDAHARA",
            action="DISBURSED",
            entity="loans",
            entity_id=str(loan_id),
            after_state={
                "loan_number": loan_number,
                "principal": str(principal),
                "total_amount": str(sched["total_amount"]),
                "document_id": doc_id,
                "qr_token": qr_token,
            },
            result="SUCCESS",
        )

        return {
            "loan_id": loan_id,
            "loan_number": loan_number,
            "disbursed_amount": str(principal),
            "document_id": doc_id,
            "qr_token": qr_token,
            "status": "DISBURSED",
        }

def pay_loan_installment(
    installment_id: int,
    paid_amount_str: str,
    idempotency_key: str,
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Process installment payment with strict atomic transaction and idempotency.
    Prevents double payment on double-click/retry.
    """
    with get_db() as conn:
        # Check idempotency first
        if idempotency_key:
            existing = conn.execute(
                "SELECT id, amount, reference_id FROM financial_transactions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return {
                    "already_processed": True,
                    "message": "Pembayaran sudah diproses sebelumnya (Idempotent).",
                    "transaction_id": existing["id"],
                }

        inst = conn.execute(
            """
            SELECT li.*, l.member_id, l.loan_number, l.outstanding_amount, l.id as l_id, m.user_id as member_user_id
            FROM loan_installments li
            JOIN loans l ON li.loan_id = l.id
            JOIN members m ON l.member_id = m.id
            WHERE li.id = ? FOR UPDATE
            """,
            (installment_id,),
        ).fetchone()

        if not inst:
            raise LoanError("Angsuran tidak ditemukan.")

        if inst["status"] == "PAID":
            raise LoanError(f"Angsuran ke-{inst['installment_number']} sudah berstatus LUNAS.")

        from app.members.service import can_access_member_data
        # Either member self-payment or staff/bendahara
        if not can_access_member_data(current_user, inst["member_id"]):
            raise LoanError("Akses ditolak.")

        payment_amount = to_decimal(paid_amount_str)
        required_amount = to_decimal(inst["amount"])
        if payment_amount < required_amount:
            raise LoanError(f"Nominal pembayaran kurang. Tagihan angsuran: {format_rupiah(required_amount)}.")

        # Update installment record
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE loan_installments
            SET paid_amount = ?, paid_at = ?, status = 'PAID', payment_reference = ?
            WHERE id = ?
            """,
            (str(payment_amount), today, idempotency_key, installment_id),
        )

        # Update loan outstanding balance
        current_outstanding = to_decimal(inst["outstanding_amount"])
        new_outstanding = max(Decimal("0.00"), current_outstanding - required_amount)
        new_loan_status = "PAID_OFF" if new_outstanding == Decimal("0.00") else "ACTIVE"

        conn.execute(
            "UPDATE loans SET outstanding_amount = ?, status = ? WHERE id = ?",
            (str(new_outstanding), new_loan_status, inst["l_id"]),
        )

        # Record financial transaction (INFLOW)
        tx_num = generate_reference_number("FT-INST")
        conn.execute(
            """
            INSERT INTO financial_transactions (
                transaction_number, transaction_type, category, amount, idempotency_key,
                reference_type, reference_id, description, created_by, created_at
            ) VALUES (?, 'INFLOW', 'LOAN_INSTALLMENT', ?, ?, 'LOAN_INSTALLMENT', ?, ?, ?, datetime('now'))
            """,
            (
                tx_num,
                str(payment_amount),
                idempotency_key,
                str(installment_id),
                f"Pembayaran Angsuran ke-{inst['installment_number']} Pinjaman {inst['loan_number']}",
                current_user["id"],
            ),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ANGGOTA" if ROLE_ANGGOTA in current_user.get("roles", []) else "BENDAHARA",
            action="INSTALLMENT_RECORDED",
            entity="loan_installments",
            entity_id=str(installment_id),
            after_state={
                "paid_amount": str(payment_amount),
                "remaining_outstanding": str(new_outstanding),
                "loan_status": new_loan_status,
            },
            result="SUCCESS",
        )

        return {
            "installment_id": installment_id,
            "status": "PAID",
            "paid_amount": str(payment_amount),
            "remaining_outstanding": str(new_outstanding),
            "loan_status": new_loan_status,
        }

def get_loan_details(loan_id: int, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """Get active loan details with complete installment schedule."""
    with get_db() as conn:
        loan = conn.execute(
            """
            SELECT l.*, m.member_number, m.name as member_name, m.email as member_email
            FROM loans l
            JOIN members m ON l.member_id = m.id
            WHERE l.id = ?
            """,
            (loan_id,),
        ).fetchone()

        if not loan:
            raise LoanError("Pinjaman tidak ditemukan.")

        from app.members.service import can_access_member_data
        if not can_access_member_data(current_user, loan["member_id"]):
            raise LoanError("Akses ditolak.")

        installments = conn.execute(
            "SELECT * FROM loan_installments WHERE loan_id = ? ORDER BY installment_number ASC",
            (loan_id,),
        ).fetchall()

        # Associated document & QR
        doc = conn.execute(
            """
            SELECT d.id, d.document_number, d.title, qr.token_hash, qr.token_display, qr.is_revoked
            FROM documents d
            LEFT JOIN qr_verification_tokens qr ON d.id = qr.document_id
            WHERE d.reference_type = 'LOAN' AND d.reference_id = ?
            """,
            (str(loan_id),),
        ).fetchone()

        return {
            "loan": {
                **dict(loan),
                "formatted_principal": format_rupiah(loan["principal_amount"]),
                "formatted_total": format_rupiah(loan["total_amount"]),
                "formatted_outstanding": format_rupiah(loan["outstanding_amount"]),
                "formatted_monthly": format_rupiah(loan["monthly_installment"]),
            },
            "installments": [
                {
                    **dict(i),
                    "formatted_amount": format_rupiah(i["amount"]),
                    "formatted_paid": format_rupiah(i["paid_amount"]),
                }
                for i in installments
            ],
            "document": dict(doc) if doc else None,
        }
