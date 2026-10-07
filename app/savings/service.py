"""
Savings Service and Opening Balance Ledger for Koperasi Core.
Enforces ledger-based transaction accounting, exact Decimal math,
opening balance batch traceability, and balance reconstruction.
"""
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import csv
import io
import openpyxl

from app.database import get_db
from app.security import to_decimal, format_rupiah, log_audit, sanitize_for_spreadsheet
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_BENDAHARA,
    ROLE_ANGGOTA,
    ROLE_KETUA,
)

class SavingsError(Exception):
    pass

def get_member_savings_summary(member_id: int, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieve savings summary for a member.
    Enforces object-level authorization and ledger-based balance reconstruction.
    """
    from app.members.service import can_access_member_data
    if not can_access_member_data(current_user, member_id):
        raise SavingsError("Akses ditolak: Anda hanya dapat melihat data simpanan Anda sendiri.")

    with get_db() as conn:
        accounts = conn.execute(
            """
            SELECT * FROM savings_accounts
            WHERE member_id = ? AND status = 'ACTIVE'
            ORDER BY account_type ASC
            """,
            (member_id,),
        ).fetchall()

        acc_list = []
        total_balance = Decimal("0.00")

        for acc in accounts:
            # Reconstruct balance dynamically from transactions ledger
            recon = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
                FROM savings_transactions
                WHERE account_id = ?
                """,
                (acc["id"],),
            ).fetchone()

            bal = to_decimal(recon["balance"])
            total_balance += bal

            acc_list.append({
                "id": acc["id"],
                "account_number": acc["account_number"],
                "account_type": acc["account_type"],
                "status": acc["status"],
                "balance": str(bal),
                "formatted_balance": format_rupiah(bal),
            })

        return {
            "member_id": member_id,
            "accounts": acc_list,
            "total_balance": str(total_balance),
            "formatted_total_balance": format_rupiah(total_balance),
        }

def get_account_transactions(account_id: int, current_user: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve transaction ledger for a specific savings account."""
    with get_db() as conn:
        acc = conn.execute("SELECT member_id FROM savings_accounts WHERE id = ?", (account_id,)).fetchone()
        if not acc:
            raise SavingsError("Rekening simpanan tidak ditemukan.")

        from app.members.service import can_access_member_data
        if not can_access_member_data(current_user, acc["member_id"]):
            raise SavingsError("Akses ditolak.")

        rows = conn.execute(
            """
            SELECT st.*, u.full_name as creator_name
            FROM savings_transactions st
            LEFT JOIN users u ON st.created_by = u.id
            WHERE st.account_id = ?
            ORDER BY st.id DESC
            LIMIT ?
            """,
            (account_id, limit),
        ).fetchall()

        return [
            {
                **dict(r),
                "formatted_amount": format_rupiah(r["amount"]),
                "formatted_balance_after": format_rupiah(r["balance_after"]),
            }
            for r in rows
        ]

def record_opening_balance(
    member_id: int,
    account_type: str,
    amount_str: str,
    effective_date: str,
    reference: str,
    notes: str,
    current_user: Dict[str, Any],
    source_batch_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Record an opening balance into the ledger as a CREDIT transaction.
    Does not blindly overwrite a balance column; reconstructible via ledger.
    """
    amount = to_decimal(amount_str)
    if amount <= Decimal("0.00"):
        raise SavingsError("Nominal saldo awal harus lebih besar dari 0.")

    if account_type not in ("POKOK", "WAJIB", "SUKARELA"):
        raise SavingsError(f"Tipe simpanan '{account_type}' tidak valid.")

    with get_db() as conn:
        # Find or create account
        acc = conn.execute(
            "SELECT id FROM savings_accounts WHERE member_id = ? AND account_type = ?",
            (member_id, account_type),
        ).fetchone()

        if not acc:
            mem = conn.execute("SELECT member_number FROM members WHERE id = ?", (member_id,)).fetchone()
            if not mem:
                raise SavingsError(f"Anggota dengan ID {member_id} tidak ditemukan.")
            acc_num = f"SA-{account_type[:3]}-{mem['member_number']}"
            cur_acc = conn.execute(
                "INSERT INTO savings_accounts (member_id, account_number, account_type, status) VALUES (?, ?, ?, 'ACTIVE')",
                (member_id, acc_num, account_type),
            )
            account_id = cur_acc.lastrowid
        else:
            account_id = acc["id"]

        # Calculate previous balance from ledger
        prev_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
            FROM savings_transactions WHERE account_id = ?
            """,
            (account_id,),
        ).fetchone()
        prev_balance = to_decimal(prev_row["balance"])
        new_balance = prev_balance + amount

        # Insert Opening Balance record
        conn.execute(
            """
            INSERT INTO savings_opening_balances (
                account_id, member_id, account_type, amount, effective_date,
                source_batch_id, reference, notes, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                account_id,
                member_id,
                account_type,
                str(amount),
                effective_date,
                source_batch_id,
                reference or "OB-MANUAL",
                notes,
                current_user["id"],
            ),
        )

        # Insert into savings_transactions (Ledger)
        cur_tx = conn.execute(
            """
            INSERT INTO savings_transactions (
                account_id, member_id, transaction_type, amount, balance_after,
                reference_type, reference_id, description, transaction_date, created_by, created_at
            ) VALUES (?, ?, 'CREDIT', ?, ?, 'OPENING_BALANCE', ?, ?, ?, ?, datetime('now'))
            """,
            (
                account_id,
                member_id,
                str(amount),
                str(new_balance),
                reference or "OB-MANUAL",
                f"Saldo Awal Simpanan {account_type} (Ref: {reference})",
                effective_date,
                current_user["id"],
            ),
        )
        tx_id = cur_tx.lastrowid

        # Insert into financial_transactions
        from app.security import generate_reference_number
        tx_num = generate_reference_number("FT-OB")
        conn.execute(
            """
            INSERT INTO financial_transactions (
                transaction_number, transaction_type, category, amount, idempotency_key,
                reference_type, reference_id, description, created_by, created_at
            ) VALUES (?, 'INFLOW', 'OPENING_BALANCE', ?, ?, 'SAVINGS_TRANSACTION', ?, ?, ?, datetime('now'))
            """,
            (
                tx_num,
                str(amount),
                f"IDEMP-{tx_num}",
                str(tx_id),
                f"Saldo Awal {account_type} Anggota ID {member_id}",
                current_user["id"],
            ),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ADMIN",
            action="SAVINGS_OPENING_BALANCE_IMPORTED",
            entity="savings_transactions",
            entity_id=str(tx_id),
            after_state={
                "member_id": member_id,
                "account_type": account_type,
                "amount": str(amount),
                "effective_date": effective_date,
                "source_batch_id": source_batch_id,
            },
            result="SUCCESS",
        )

        return {
            "transaction_id": tx_id,
            "account_id": account_id,
            "amount": str(amount),
            "new_balance": str(new_balance),
        }

def record_deposit(
    account_id: int,
    amount_str: str,
    description: str,
    idempotency_key: str,
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    """Process deposit with idempotency protection and atomic transaction."""
    amount = to_decimal(amount_str)
    if amount <= Decimal("0.00"):
        raise SavingsError("Nominal setoran harus lebih besar dari 0.")

    with get_db() as conn:
        # Check idempotency
        if idempotency_key:
            existing = conn.execute(
                "SELECT id, amount, reference_id FROM financial_transactions WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return {
                    "already_processed": True,
                    "transaction_id": existing["reference_id"],
                    "amount": existing["amount"],
                }

        acc = conn.execute("SELECT id, member_id, account_type FROM savings_accounts WHERE id = ?", (account_id,)).fetchone()
        if not acc:
            raise SavingsError("Rekening simpanan tidak ditemukan.")

        prev_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
            FROM savings_transactions WHERE account_id = ?
            """,
            (account_id,),
        ).fetchone()
        prev_balance = to_decimal(prev_row["balance"])
        new_balance = prev_balance + amount

        today = datetime.utcnow().strftime("%Y-%m-%d")
        cur_tx = conn.execute(
            """
            INSERT INTO savings_transactions (
                account_id, member_id, transaction_type, amount, balance_after,
                reference_type, reference_id, description, transaction_date, created_by
            ) VALUES (?, ?, 'CREDIT', ?, ?, 'DEPOSIT', ?, ?, ?, ?)
            """,
            (
                account_id,
                acc["member_id"],
                str(amount),
                str(new_balance),
                idempotency_key,
                description or f"Setoran Simpanan {acc['account_type']}",
                today,
                current_user["id"],
            ),
        )
        tx_id = cur_tx.lastrowid

        from app.security import generate_reference_number
        tx_num = generate_reference_number("FT-DEP")
        conn.execute(
            """
            INSERT INTO financial_transactions (
                transaction_number, transaction_type, category, amount, idempotency_key,
                reference_type, reference_id, description, created_by
            ) VALUES (?, 'INFLOW', 'SAVINGS_DEPOSIT', ?, ?, 'SAVINGS_TRANSACTION', ?, ?, ?)
            """,
            (
                tx_num,
                str(amount),
                idempotency_key,
                str(tx_id),
                description or f"Setoran Simpanan {acc['account_type']}",
                current_user["id"],
            ),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="BENDAHARA" if ROLE_BENDAHARA in current_user.get("roles", []) else "STAFF",
            action="TRANSACTION_CREATED",
            entity="savings_transactions",
            entity_id=str(tx_id),
            after_state={"amount": str(amount), "new_balance": str(new_balance)},
            result="SUCCESS",
        )

        return {
            "transaction_id": tx_id,
            "account_id": account_id,
            "amount": str(amount),
            "new_balance": str(new_balance),
        }

def generate_savings_opening_balance_template(file_format: str = "xlsx") -> Tuple[bytes, str, str]:
    """Generate template for bulk importing opening balances."""
    headers = ["member_number", "account_type", "amount", "effective_date", "reference", "notes"]
    sample_rows = [
        ["MEM-001", "POKOK", "500000", "2024-01-01", "OB-MIG-001", "Saldo Pokok Awal Migrasi"],
        ["MEM-001", "WAJIB", "200000", "2024-01-01", "OB-MIG-002", "Saldo Wajib Awal Migrasi"],
        ["MEM-001", "SUKARELA", "1500000", "2024-01-01", "OB-MIG-003", "Saldo Sukarela Awal Migrasi"],
    ]

    if file_format.lower() == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(headers)
        for r in sample_rows:
            writer.writerow(r)
        return out.getvalue().encode("utf-8"), "template_opening_balance_simpanan.csv", "text/csv"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Opening_Balance"
    ws.append(headers)
    for r in sample_rows:
        ws.append(r)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), "template_opening_balance_simpanan.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
