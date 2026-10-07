"""
Reporting and Analytics Service for Koperasi Core.
Generates metrics for dashboards and operational reports across all domains.
"""
import os
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from decimal import Decimal

from app.database import get_db
from app.security import format_rupiah, to_decimal
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)

def get_role_dashboard_data(current_user: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve tailored metrics based on user's active role(s)."""
    roles = current_user.get("roles", [])
    data = {"roles": roles, "user": current_user}

    with get_db() as conn:
        # 1. ANGGOTA DASHBOARD METRICS
        if ROLE_ANGGOTA in roles or current_user.get("member_id"):
            member_id = current_user.get("member_id")
            if member_id:
                # Savings
                from app.savings.service import get_member_savings_summary
                savings_summary = get_member_savings_summary(member_id, current_user)

                # Active Loan
                loan = conn.execute(
                    """
                    SELECT * FROM loans
                    WHERE member_id = ? AND status = 'ACTIVE'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (member_id,),
                ).fetchone()

                # Next Installment
                next_inst = None
                if loan:
                    next_inst = conn.execute(
                        """
                        SELECT * FROM loan_installments
                        WHERE loan_id = ? AND status = 'PENDING'
                        ORDER BY installment_number ASC LIMIT 1
                        """,
                        (loan["id"],),
                    ).fetchone()

                # Recent Loan Applications
                apps = conn.execute(
                    """
                    SELECT * FROM loan_applications
                    WHERE member_id = ?
                    ORDER BY id DESC LIMIT 5
                    """,
                    (member_id,),
                ).fetchall()

                data["member_metrics"] = {
                    "savings_summary": savings_summary,
                    "active_loan": {
                        **dict(loan),
                        "formatted_principal": format_rupiah(loan["principal_amount"]),
                        "formatted_outstanding": format_rupiah(loan["outstanding_amount"]),
                    } if loan else None,
                    "next_installment": {
                        **dict(next_inst),
                        "formatted_amount": format_rupiah(next_inst["amount"]),
                    } if next_inst else None,
                    "recent_applications": [dict(a) for a in apps],
                }

        # 2. ATASAN / APPROVER METRICS
        if ROLE_ATASAN_APPROVER in roles or ROLE_SUPER_ADMIN in roles:
            # Subordinates pending loans
            pending_mgr = conn.execute(
                """
                SELECT la.*, m.name as member_name, m.member_number
                FROM loan_applications la
                JOIN members m ON la.member_id = m.id
                WHERE la.status = 'SUBMITTED' AND la.current_step = 'MANAGER'
                  AND (la.assigned_manager_id = ? OR ? = 1)
                ORDER BY la.id ASC
                """,
                (current_user["id"], 1 if ROLE_SUPER_ADMIN in roles else 0),
            ).fetchall()

            # Recent decisions made by this manager
            decisions = conn.execute(
                """
                SELECT la.*, app.application_number, app.amount, m.name as member_name
                FROM loan_approvals la
                JOIN loan_applications app ON la.application_id = app.id
                JOIN members m ON app.member_id = m.id
                WHERE la.approver_id = ?
                ORDER BY la.id DESC LIMIT 5
                """,
                (current_user["id"],),
            ).fetchall()

            data["approver_metrics"] = {
                "pending_subordinate_count": len(pending_mgr),
                "pending_subordinates": [dict(p) for p in pending_mgr],
                "recent_decisions": [dict(d) for d in decisions],
            }

        # 3. KETUA KOPERASI METRICS
        if ROLE_KETUA in roles or ROLE_SUPER_ADMIN in roles:
            # Pending Ketua approvals
            pending_ketua = conn.execute(
                """
                SELECT la.*, m.name as member_name, m.member_number
                FROM loan_applications la
                JOIN members m ON la.member_id = m.id
                WHERE la.current_step = 'KETUA' AND la.status = 'APPROVED_BY_MANAGER'
                ORDER BY la.id ASC
                """,
            ).fetchall()

            # Cooperative Summary Stats
            total_members = conn.execute("SELECT COUNT(*) as cnt FROM members WHERE membership_status = 'ACTIVE'").fetchone()["cnt"]
            total_active_loans = conn.execute("SELECT COUNT(*) as cnt FROM loans WHERE status = 'ACTIVE'").fetchone()["cnt"]

            total_savings_res = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
                FROM savings_transactions
                """,
            ).fetchone()
            total_savings = to_decimal(total_savings_res["balance"])

            total_outstanding_res = conn.execute(
                "SELECT COALESCE(SUM(CAST(outstanding_amount AS NUMERIC)), 0) as total FROM loans WHERE status = 'ACTIVE'"
            ).fetchone()
            total_outstanding = to_decimal(total_outstanding_res["total"])

            data["ketua_metrics"] = {
                "pending_approval_count": len(pending_ketua),
                "pending_applications": [dict(p) for p in pending_ketua],
                "total_members": total_members,
                "total_active_loans": total_active_loans,
                "total_savings": format_rupiah(total_savings),
                "total_outstanding": format_rupiah(total_outstanding),
            }

        # 4. BENDAHARA METRICS
        if ROLE_BENDAHARA in roles or ROLE_SUPER_ADMIN in roles:
            # Pending Disbursement
            waiting_disb = conn.execute(
                """
                SELECT la.*, m.name as member_name, m.member_number, m.bank_account
                FROM loan_applications la
                JOIN members m ON la.member_id = m.id
                WHERE la.status = 'WAITING_DISBURSEMENT'
                ORDER BY la.id ASC
                """,
            ).fetchall()

            # Cash Inflow & Outflow
            inflow_res = conn.execute(
                "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM financial_transactions WHERE transaction_type = 'INFLOW'"
            ).fetchone()["total"]
            outflow_res = conn.execute(
                "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM financial_transactions WHERE transaction_type = 'OUTFLOW'"
            ).fetchone()["total"]

            inflow = to_decimal(inflow_res)
            outflow = to_decimal(outflow_res)
            net_cash = inflow - outflow

            data["bendahara_metrics"] = {
                "waiting_disbursement_count": len(waiting_disb),
                "waiting_disbursements": [dict(w) for w in waiting_disb],
                "total_inflow": format_rupiah(inflow),
                "total_outflow": format_rupiah(outflow),
                "net_cash": format_rupiah(net_cash),
            }

        # 5. ADMIN KOPERASI METRICS
        if ROLE_ADMIN_KOPERASI in roles or ROLE_SUPER_ADMIN in roles:
            total_members = conn.execute("SELECT COUNT(*) as cnt FROM members").fetchone()["cnt"]
            pending_members = conn.execute("SELECT COUNT(*) as cnt FROM members WHERE membership_status = 'PENDING'").fetchone()["cnt"]
            recent_batches = conn.execute("SELECT COUNT(*) as cnt FROM import_batches").fetchone()["cnt"]
            all_apps = conn.execute("SELECT COUNT(*) as cnt FROM loan_applications WHERE status NOT IN ('DISBURSED', 'REJECTED')").fetchone()["cnt"]

            data["admin_metrics"] = {
                "total_members": total_members,
                "pending_members": pending_members,
                "import_batches_count": recent_batches,
                "in_flight_applications": all_apps,
            }

        # 6. SUPER ADMIN METRICS
        if ROLE_SUPER_ADMIN in roles:
            total_users = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
            active_users = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE status = 'ACTIVE'").fetchone()["cnt"]
            audit_events = conn.execute("SELECT COUNT(*) as cnt FROM audit_logs").fetchone()["cnt"]
            recent_audits = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 8").fetchall()

            data["superadmin_metrics"] = {
                "total_users": total_users,
                "active_users": active_users,
                "audit_events_count": audit_events,
                "recent_audits": [dict(a) for a in recent_audits],
            }

    return data

def get_members_report(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate member summary report with savings and loan status."""
    with get_db() as conn:
        sql = """
            SELECT m.id, m.member_number, m.name, m.nik, m.email, m.phone,
                   m.membership_date, m.membership_status,
                   e.employee_id as emp_code, d.name as department_name,
                   (
                       SELECT COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                              COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0)
                       FROM savings_transactions WHERE member_id = m.id
                   ) as total_savings,
                   (
                       SELECT COALESCE(SUM(CAST(outstanding_amount AS NUMERIC)), 0)
                       FROM loans WHERE member_id = m.id AND status = 'ACTIVE'
                   ) as active_loans_outstanding
            FROM members m
            LEFT JOIN employees e ON m.employee_id = e.id
            LEFT JOIN departments d ON e.department_id = d.id
            WHERE 1=1
        """
        params = []
        if status:
            sql += " AND m.membership_status = ?"
            params.append(status)
        sql += " ORDER BY m.id DESC"

        rows = conn.execute(sql, params).fetchall()
        return [
            {
                **dict(r),
                "formatted_savings": format_rupiah(r["total_savings"]),
                "formatted_loans": format_rupiah(r["active_loans_outstanding"]),
            }
            for r in rows
        ]

def get_savings_ledger_report() -> Dict[str, Any]:
    """Generate savings report with reconciliation totals across Pokok, Wajib, Sukarela."""
    with get_db() as conn:
        by_type = conn.execute(
            """
            SELECT sa.account_type,
                   COUNT(DISTINCT sa.id) as account_count,
                   COALESCE(SUM(CASE WHEN st.transaction_type = 'CREDIT' THEN CAST(st.amount AS NUMERIC) ELSE 0 END), 0) -
                   COALESCE(SUM(CASE WHEN st.transaction_type = 'DEBIT' THEN CAST(st.amount AS NUMERIC) ELSE 0 END), 0) as balance
            FROM savings_accounts sa
            LEFT JOIN savings_transactions st ON sa.id = st.account_id
            GROUP BY sa.account_type
            """,
        ).fetchall()

        recent_txs = conn.execute(
            """
            SELECT st.*, m.member_number, m.name as member_name, sa.account_type, u.full_name as created_by_name
            FROM savings_transactions st
            JOIN savings_accounts sa ON st.account_id = sa.id
            JOIN members m ON st.member_id = m.id
            LEFT JOIN users u ON st.created_by = u.id
            ORDER BY st.id DESC LIMIT 50
            """,
        ).fetchall()

        total_savings = sum(to_decimal(r["balance"]) for r in by_type)

        return {
            "by_type": [
                {
                    "account_type": r["account_type"],
                    "account_count": r["account_count"],
                    "balance": str(to_decimal(r["balance"])),
                    "formatted_balance": format_rupiah(r["balance"]),
                }
                for r in by_type
            ],
            "total_savings": format_rupiah(total_savings),
            "recent_transactions": [
                {
                    **dict(tx),
                    "formatted_amount": format_rupiah(tx["amount"]),
                    "formatted_balance_after": format_rupiah(tx["balance_after"]),
                }
                for tx in recent_txs
            ],
        }

def get_financial_transactions_report(limit: int = 100) -> Dict[str, Any]:
    """Report of all financial inflow/outflow transactions."""
    with get_db() as conn:
        inflow_res = conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM financial_transactions WHERE transaction_type = 'INFLOW'"
        ).fetchone()["total"]
        outflow_res = conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM financial_transactions WHERE transaction_type = 'OUTFLOW'"
        ).fetchone()["total"]

        txs = conn.execute(
            """
            SELECT ft.*, u.full_name as created_by_name
            FROM financial_transactions ft
            LEFT JOIN users u ON ft.created_by = u.id
            ORDER BY ft.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        inflow = to_decimal(inflow_res)
        outflow = to_decimal(outflow_res)

        return {
            "total_inflow": format_rupiah(inflow),
            "total_outflow": format_rupiah(outflow),
            "net_balance": format_rupiah(inflow - outflow),
            "transactions": [
                {
                    **dict(t),
                    "formatted_amount": format_rupiah(t["amount"]),
                }
                for t in txs
            ],
        }

def get_audit_trail_report(limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve audit logs for compliance review."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ==============================================================================
# Business Units (Toko & Fotocopy) Service & Global Consolidation
# ==============================================================================
class BusinessUnitError(Exception):
    pass

def init_default_units():
    """Ensure standard Toko and Fotocopy units exist in database."""
    with get_db() as conn:
        units = [
            ("TOKO", "Unit Toko / Minimarket Koperasi", "Pengurus Toko", "Penyedia sembako dan kebutuhan sehari-hari karyawan"),
            ("FOTOCOPY", "Unit Fotocopy & Percetakan", "Pengurus Fotocopy", "Layanan fotocopy, jilid, cetak dokumen, dan penjualan ATK"),
        ]
        for code, name, mgr, desc in units:
            conn.execute(
                """
                INSERT OR IGNORE INTO business_units (code, name, manager_name, description, is_active)
                VALUES (?, ?, ?, ?, 1)
                """,
                (code, name, mgr, desc),
            )

def get_all_units() -> List[Dict[str, Any]]:
    """Retrieve all business units."""
    init_default_units()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM business_units ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

def get_unit_by_id(unit_id: int) -> Dict[str, Any]:
    """Retrieve unit details."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM business_units WHERE id = ?", (unit_id,)).fetchone()
        if not row:
            raise BusinessUnitError("Unit usaha tidak ditemukan.")
        return dict(row)

def submit_unit_report(
    unit_id: int,
    period_type: str,
    period_year: int,
    period_month: Optional[int],
    cash_and_bank: str,
    inventory_value: str,
    receivables: str,
    fixed_assets: str,
    other_assets: str,
    payables: str,
    unit_capital: str,
    gross_revenue: str,
    cogs: str,
    operational_expenses: str,
    cash_deposit_to_parent: str,
    deposit_date: Optional[str],
    notes: Optional[str],
    current_user: Dict[str, Any],
) -> int:
    """Submit periodic financial summary (Neraca & Laba Rugi) for a unit."""
    from app.security import log_audit
    d_cash = to_decimal(cash_and_bank)
    d_inv = to_decimal(inventory_value)
    d_rec = to_decimal(receivables)
    d_fix = to_decimal(fixed_assets)
    d_oth = to_decimal(other_assets)
    d_tot_assets = d_cash + d_inv + d_rec + d_fix + d_oth

    d_pay = to_decimal(payables)
    d_cap = to_decimal(unit_capital)

    d_rev = to_decimal(gross_revenue)
    d_cogs = to_decimal(cogs)
    d_g_profit = d_rev - d_cogs
    d_opex = to_decimal(operational_expenses)
    d_n_profit = d_g_profit - d_opex

    d_dep = to_decimal(cash_deposit_to_parent)

    with get_db() as conn:
        existing = conn.execute(
            """
            SELECT id FROM unit_financial_reports
            WHERE unit_id = ? AND period_type = ? AND period_year = ? AND COALESCE(period_month, 0) = COALESCE(?, 0)
            """,
            (unit_id, period_type, period_year, period_month),
        ).fetchone()

        if existing:
            report_id = existing["id"]
            conn.execute(
                """
                UPDATE unit_financial_reports
                SET cash_and_bank = ?, inventory_value = ?, receivables = ?, fixed_assets = ?,
                    other_assets = ?, total_assets = ?, payables = ?, unit_capital = ?,
                    gross_revenue = ?, cogs = ?, gross_profit = ?, operational_expenses = ?,
                    net_profit = ?, cash_deposit_to_parent = ?, deposit_date = ?, notes = ?,
                    status = 'SUBMITTED', reported_by = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    str(d_cash), str(d_inv), str(d_rec), str(d_fix), str(d_oth), str(d_tot_assets),
                    str(d_pay), str(d_cap), str(d_rev), str(d_cogs), str(d_g_profit), str(d_opex),
                    str(d_n_profit), str(d_dep), deposit_date, notes or "", current_user["id"], report_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO unit_financial_reports (
                    unit_id, period_type, period_year, period_month,
                    cash_and_bank, inventory_value, receivables, fixed_assets, other_assets, total_assets,
                    payables, unit_capital, gross_revenue, cogs, gross_profit, operational_expenses,
                    net_profit, cash_deposit_to_parent, deposit_date, notes, status, reported_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED', ?, datetime('now'), datetime('now'))
                """,
                (
                    unit_id, period_type, period_year, period_month,
                    str(d_cash), str(d_inv), str(d_rec), str(d_fix), str(d_oth), str(d_tot_assets),
                    str(d_pay), str(d_cap), str(d_rev), str(d_cogs), str(d_g_profit), str(d_opex),
                    str(d_n_profit), str(d_dep), deposit_date, notes or "", current_user["id"],
                ),
            )
            report_id = cur.lastrowid

        unit = conn.execute("SELECT name FROM business_units WHERE id = ?", (unit_id,)).fetchone()
        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="STAFF",
            action="UNIT_REPORT_SUBMITTED",
            entity="unit_financial_reports",
            entity_id=str(report_id),
            after_state={"unit": unit["name"] if unit else unit_id, "year": period_year, "net_profit": str(d_n_profit)},
            result="SUCCESS",
        )

        return report_id

def verify_unit_report(report_id: int, current_user: Dict[str, Any]) -> bool:
    """Bendahara/Admin verifies report and logs cash deposit into cooperative financial transactions."""
    from app.security import log_audit, generate_reference_number
    with get_db() as conn:
        rep = conn.execute("SELECT * FROM unit_financial_reports WHERE id = ?", (report_id,)).fetchone()
        if not rep:
            raise BusinessUnitError("Laporan unit tidak ditemukan.")

        conn.execute(
            """
            UPDATE unit_financial_reports
            SET status = 'VERIFIED', verified_by = ?, verified_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (current_user["id"], report_id),
        )

        dep_amount = to_decimal(rep["cash_deposit_to_parent"])
        if dep_amount > Decimal("0.00"):
            tx_num = generate_reference_number("FT-UNIT")
            idemp_key = f"IDEMP-UNIT-DEP-{report_id}"
            unit = conn.execute("SELECT name, code FROM business_units WHERE id = ?", (rep["unit_id"],)).fetchone()
            unit_name = unit["name"] if unit else "Unit Usaha"

            conn.execute(
                """
                INSERT OR IGNORE INTO financial_transactions (
                    transaction_number, transaction_type, category, amount, idempotency_key,
                    reference_type, reference_id, description, created_by, created_at
                ) VALUES (?, 'INFLOW', 'UNIT_DEPOSIT', ?, ?, 'UNIT_REPORT', ?, ?, ?, datetime('now'))
                """,
                (
                    tx_num,
                    str(dep_amount),
                    idemp_key,
                    str(report_id),
                    f"Setoran Kas dari {unit_name} (Periode {rep['period_month'] or '-'}/{rep['period_year']})",
                    current_user["id"],
                ),
            )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="BENDAHARA",
            action="UNIT_REPORT_VERIFIED",
            entity="unit_financial_reports",
            entity_id=str(report_id),
            after_state={"status": "VERIFIED"},
            result="SUCCESS",
        )
        return True

def get_unit_reports_list(unit_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Retrieve historical unit financial reports."""
    init_default_units()
    with get_db() as conn:
        sql = """
            SELECT r.*, u.name as unit_name, u.code as unit_code,
                   usr.full_name as reported_by_name, v.full_name as verified_by_name
            FROM unit_financial_reports r
            JOIN business_units u ON r.unit_id = u.id
            LEFT JOIN users usr ON r.reported_by = usr.id
            LEFT JOIN users v ON r.verified_by = v.id
            WHERE 1=1
        """
        params = []
        if unit_id:
            sql += " AND r.unit_id = ?"
            params.append(unit_id)
        sql += " ORDER BY r.period_year DESC, r.period_month DESC, r.id DESC"

        rows = conn.execute(sql, params).fetchall()
        return [
            {
                **dict(r),
                "formatted_revenue": format_rupiah(r["gross_revenue"]),
                "formatted_profit": format_rupiah(r["net_profit"]),
                "formatted_assets": format_rupiah(r["total_assets"]),
                "formatted_deposit": format_rupiah(r["cash_deposit_to_parent"]),
            }
            for r in rows
        ]

def get_consolidated_financial_summary(year: int) -> Dict[str, Any]:
    """Generate Global Consolidated Financial Report for RAT."""
    init_default_units()
    with get_db() as conn:
        usp_rev_res = conn.execute(
            """
            SELECT COALESCE(SUM(CAST(interest_portion AS NUMERIC)), 0) as total_interest
            FROM loan_installments
            WHERE status = 'PAID' AND strftime('%Y', paid_at) = ?
            """,
            (str(year),),
        ).fetchone()["total_interest"]
        usp_revenue = to_decimal(usp_rev_res)

        usp_loans_res = conn.execute(
            "SELECT COALESCE(SUM(CAST(outstanding_amount AS NUMERIC)), 0) as total FROM loans WHERE status = 'ACTIVE'"
        ).fetchone()["total"]
        usp_loans_asset = to_decimal(usp_loans_res)

        usp_savings_res = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
            FROM savings_transactions
            """
        ).fetchone()["balance"]
        usp_cash_asset = to_decimal(usp_savings_res)
        usp_total_assets = usp_loans_asset + usp_cash_asset

        usp_opex = (usp_revenue * Decimal("0.15")).quantize(Decimal("0.01"))
        usp_net_profit = usp_revenue - usp_opex

        units = conn.execute("SELECT id, code, name FROM business_units").fetchall()
        unit_summaries = []

        combined_revenue = usp_revenue
        combined_cogs = Decimal("0.00")
        combined_opex = usp_opex
        combined_net_profit = usp_net_profit

        combined_cash = usp_cash_asset
        combined_inventory = Decimal("0.00")
        combined_receivables = usp_loans_asset
        combined_fixed_assets = Decimal("0.00")
        combined_total_assets = usp_total_assets

        for u in units:
            rep = conn.execute(
                """
                SELECT
                    COALESCE(SUM(CAST(gross_revenue AS NUMERIC)), 0) as total_rev,
                    COALESCE(SUM(CAST(cogs AS NUMERIC)), 0) as total_cogs,
                    COALESCE(SUM(CAST(operational_expenses AS NUMERIC)), 0) as total_opex,
                    COALESCE(SUM(CAST(net_profit AS NUMERIC)), 0) as total_profit,
                    COALESCE(SUM(CAST(cash_deposit_to_parent AS NUMERIC)), 0) as total_dep,
                    (SELECT cash_and_bank FROM unit_financial_reports WHERE unit_id = ? AND period_year = ? ORDER BY id DESC LIMIT 1) as latest_cash,
                    (SELECT inventory_value FROM unit_financial_reports WHERE unit_id = ? AND period_year = ? ORDER BY id DESC LIMIT 1) as latest_inv,
                    (SELECT receivables FROM unit_financial_reports WHERE unit_id = ? AND period_year = ? ORDER BY id DESC LIMIT 1) as latest_rec,
                    (SELECT fixed_assets FROM unit_financial_reports WHERE unit_id = ? AND period_year = ? ORDER BY id DESC LIMIT 1) as latest_fix,
                    (SELECT total_assets FROM unit_financial_reports WHERE unit_id = ? AND period_year = ? ORDER BY id DESC LIMIT 1) as latest_tot
                FROM unit_financial_reports
                WHERE unit_id = ? AND period_year = ?
                """,
                (u["id"], year, u["id"], year, u["id"], year, u["id"], year, u["id"], year, u["id"], year),
            ).fetchone()

            u_rev = to_decimal(rep["total_rev"])
            u_cogs = to_decimal(rep["total_cogs"])
            u_opex = to_decimal(rep["total_opex"])
            u_profit = to_decimal(rep["total_profit"])
            u_dep = to_decimal(rep["total_dep"])

            u_cash = to_decimal(rep["latest_cash"])
            u_inv = to_decimal(rep["latest_inv"])
            u_rec = to_decimal(rep["latest_rec"])
            u_fix = to_decimal(rep["latest_fix"])
            u_tot_asset = to_decimal(rep["latest_tot"]) if rep["latest_tot"] else (u_cash + u_inv + u_rec + u_fix)

            combined_revenue += u_rev
            combined_cogs += u_cogs
            combined_opex += u_opex
            combined_net_profit += u_profit

            combined_cash += u_cash
            combined_inventory += u_inv
            combined_receivables += u_rec
            combined_fixed_assets += u_fix
            combined_total_assets += u_tot_asset

            unit_summaries.append({
                "unit_id": u["id"],
                "code": u["code"],
                "name": u["name"],
                "revenue": format_rupiah(u_rev),
                "cogs": format_rupiah(u_cogs),
                "opex": format_rupiah(u_opex),
                "net_profit": format_rupiah(u_profit),
                "deposit_to_parent": format_rupiah(u_dep),
                "assets": format_rupiah(u_tot_asset),
            })

        cadangan = (combined_net_profit * Decimal("0.40")).quantize(Decimal("0.01"))
        jasa_modal = (combined_net_profit * Decimal("0.20")).quantize(Decimal("0.01"))
        jasa_usaha = (combined_net_profit * Decimal("0.20")).quantize(Decimal("0.01"))
        pengurus = (combined_net_profit * Decimal("0.10")).quantize(Decimal("0.01"))
        pendidikan = (combined_net_profit * Decimal("0.05")).quantize(Decimal("0.01"))
        sosial = (combined_net_profit * Decimal("0.05")).quantize(Decimal("0.01"))

        return {
            "year": year,
            "units": unit_summaries,
            "usp": {
                "name": "Unit Simpan Pinjam (USP)",
                "revenue": format_rupiah(usp_revenue),
                "cogs": "Rp 0",
                "opex": format_rupiah(usp_opex),
                "net_profit": format_rupiah(usp_net_profit),
                "assets": format_rupiah(usp_total_assets),
            },
            "consolidated": {
                "total_revenue": format_rupiah(combined_revenue),
                "total_cogs": format_rupiah(combined_cogs),
                "gross_profit": format_rupiah(combined_revenue - combined_cogs),
                "total_opex": format_rupiah(combined_opex),
                "net_profit": format_rupiah(combined_net_profit),
                "raw_net_profit": str(combined_net_profit),
                "cash": format_rupiah(combined_cash),
                "inventory": format_rupiah(combined_inventory),
                "receivables": format_rupiah(combined_receivables),
                "fixed_assets": format_rupiah(combined_fixed_assets),
                "total_assets": format_rupiah(combined_total_assets),
            },
            "shu": {
                "total_shu": format_rupiah(combined_net_profit),
                "dana_cadangan": format_rupiah(cadangan),
                "jasa_modal": format_rupiah(jasa_modal),
                "jasa_usaha": format_rupiah(jasa_usaha),
                "pengurus_pengawas": format_rupiah(pengurus),
                "dana_pendidikan": format_rupiah(pendidikan),
                "dana_sosial": format_rupiah(sosial),
            },
        }


def get_member_shu_breakdown(year: int) -> Dict[str, Any]:
    """
    Calculate exact SHU allocation per individual member based on:
    1. Jasa Modal (Simpanan Anggota / Total Simpanan * Alokasi Jasa Modal)
    2. Jasa Usaha / Pinjaman (Kontribusi Jasa Pinjaman / Total Jasa Pinjaman * Alokasi Jasa Usaha)
    """
    summary = get_consolidated_financial_summary(year)
    raw_total_shu = Decimal(summary["consolidated"]["raw_net_profit"])

    # Standard: 20% Jasa Modal, 20% Jasa Usaha
    pool_jasa_modal = (raw_total_shu * Decimal("0.20")).quantize(Decimal("0.01"))
    pool_jasa_usaha = (raw_total_shu * Decimal("0.20")).quantize(Decimal("0.01"))

    with get_db() as conn:
        members = conn.execute("SELECT id, member_number, name, nik FROM members WHERE membership_status = 'ACTIVE' ORDER BY member_number ASC").fetchall()

        # Total savings of all active members
        tot_savings_row = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                   COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
            FROM savings_transactions
            """
        ).fetchone()
        total_all_savings = to_decimal(tot_savings_row["balance"])

        # Total loan interest paid by all members in that year
        tot_int_row = conn.execute(
            """
            SELECT COALESCE(SUM(CAST(interest_portion AS NUMERIC)), 0) as total_int
            FROM loan_installments
            WHERE status = 'PAID' AND strftime('%Y', paid_at) = ?
            """,
            (str(year),),
        ).fetchone()
        total_all_interest = to_decimal(tot_int_row["total_int"])

        member_breakdowns = []
        tot_distributed = Decimal("0.00")

        for m in members:
            # Member total savings
            m_sav_row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) -
                       COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN CAST(amount AS NUMERIC) ELSE 0 END), 0) as balance
                FROM savings_transactions WHERE member_id = ?
                """,
                (m["id"],),
            ).fetchone()
            m_savings = to_decimal(m_sav_row["balance"])

            # Member loan interest paid in that year
            m_int_row = conn.execute(
                """
                SELECT COALESCE(SUM(CAST(li.interest_portion AS NUMERIC)), 0) as m_int
                FROM loan_installments li
                JOIN loans l ON li.loan_id = l.id
                WHERE l.member_id = ? AND li.status = 'PAID' AND strftime('%Y', li.paid_at) = ?
                """,
                (m["id"], str(year)),
            ).fetchone()
            m_interest = to_decimal(m_int_row["m_int"])

            # Jasa modal calculation
            if total_all_savings > Decimal("0.00"):
                m_jasa_modal = ((m_savings / total_all_savings) * pool_jasa_modal).quantize(Decimal("0.01"))
            else:
                m_jasa_modal = Decimal("0.00")

            # Jasa usaha calculation
            if total_all_interest > Decimal("0.00"):
                m_jasa_usaha = ((m_interest / total_all_interest) * pool_jasa_usaha).quantize(Decimal("0.01"))
            else:
                m_jasa_usaha = Decimal("0.00")

            m_total_shu = m_jasa_modal + m_jasa_usaha
            tot_distributed += m_total_shu

            member_breakdowns.append({
                "member_id": m["id"],
                "member_number": m["member_number"],
                "name": m["name"],
                "nik": m["nik"],
                "savings": format_rupiah(m_savings),
                "interest_paid": format_rupiah(m_interest),
                "jasa_modal": format_rupiah(m_jasa_modal),
                "jasa_usaha": format_rupiah(m_jasa_usaha),
                "total_shu": format_rupiah(m_total_shu),
            })

        return {
            "year": year,
            "summary": summary,
            "pool_jasa_modal": format_rupiah(pool_jasa_modal),
            "pool_jasa_usaha": format_rupiah(pool_jasa_usaha),
            "total_distributed": format_rupiah(tot_distributed),
            "members": member_breakdowns,
        }


# ==============================================================================
# System & Product Settings & Database Backup Service
# ==============================================================================
DEFAULT_SETTINGS = [
    # 1. Profile & Legalitas Koperasi
    ("cooperative_name", "Koperasi Karyawan Sejahtera Mandiri", "PROFILE", "Nama resmi koperasi"),
    ("legal_number", "AHU-0012345.AH.01.26.TAHUN 2024", "PROFILE", "Nomor Badan Hukum / SK Kemenkumham"),
    ("cooperative_nik", "3374010010001", "PROFILE", "Nomor Induk Koperasi (NIK Kemenkop)"),
    ("office_address", "Jl. Pemuda No. 88, Semarang, Jawa Tengah", "PROFILE", "Alamat lengkap kantor sekretariat"),
    ("office_phone", "(024) 8765432", "PROFILE", "Nomor telepon resmi"),
    ("office_email", "sekretariat@koperasi-karyawan.com", "PROFILE", "Email resmi koperasi"),
    ("chief_name", "Drs. Hendro Wibowo", "PROFILE", "Nama Ketua Koperasi penandatangan"),
    ("secretary_name", "Agus Hartono, S.E.", "PROFILE", "Nama Sekretaris"),
    ("treasurer_name", "Siti Rahmawati, S.Ak.", "PROFILE", "Nama Bendahara"),

    # 2. Produk Simpanan
    ("savings_pokok_amount", "500000", "SAVINGS", "Nominal simpanan pokok anggota baru (Rp)"),
    ("savings_wajib_amount", "100000", "SAVINGS", "Iuran simpanan wajib bulanan (Rp)"),
    ("savings_sukarela_min", "10000", "SAVINGS", "Minimal setoran simpanan sukarela (Rp)"),

    # 3. Produk Pinjaman
    ("loan_interest_rate_monthly", "1.0", "LOANS", "Suku bunga pinjaman flat per bulan (%)"),
    ("loan_admin_fee_percent", "1.0", "LOANS", "Biaya administrasi pencairan (%)"),
    ("loan_max_tenor_months", "36", "LOANS", "Tenor maksimal pinjaman (Bulan)"),
    ("loan_max_amount", "25000000", "LOANS", "Plafon maksimal pinjaman reguler (Rp)"),
    ("loan_require_manager", "1", "LOANS", "Wajib persetujuan atasan langsung (1=Ya, 0=Tidak)"),

    # 4. Alokasi SHU RAT
    ("shu_cadangan_percent", "40", "SHU", "Alokasi Dana Cadangan (%)"),
    ("shu_jasa_modal_percent", "20", "SHU", "Alokasi Jasa Modal Anggota (%)"),
    ("shu_jasa_usaha_percent", "20", "SHU", "Alokasi Jasa Usaha Anggota (%)"),
    ("shu_pengurus_percent", "10", "SHU", "Alokasi Jasa Pengurus & Pengawas (%)"),
    ("shu_pendidikan_percent", "5", "SHU", "Alokasi Dana Pendidikan Koperasi (%)"),
    ("shu_sosial_percent", "5", "SHU", "Alokasi Dana Sosial & Pembangunan (%)"),

    # 5. Unit Usaha (Toko & Fotocopy)
    ("store_credit_limit", "500000", "UNITS", "Plafon maksimal bon belanja potong gaji per anggota (Rp)"),
    ("cutoff_day", "25", "UNITS", "Tanggal tutup buku bulanan toko/fotocopy"),
]

def init_default_settings():
    """Ensure all default settings exist in database."""
    with get_db() as conn:
        for key, val, cat, desc in DEFAULT_SETTINGS:
            conn.execute(
                """
                INSERT OR IGNORE INTO system_settings (setting_key, setting_value, category, description)
                VALUES (?, ?, ?, ?)
                """,
                (key, val, cat, desc),
            )

def get_all_settings() -> Dict[str, str]:
    """Retrieve key-value dictionary of all settings."""
    init_default_settings()
    with get_db() as conn:
        rows = conn.execute("SELECT setting_key, setting_value FROM system_settings").fetchall()
        return {r["setting_key"]: r["setting_value"] for r in rows}

def update_settings_dict(new_settings: Dict[str, str], current_user: Dict[str, Any]):
    """Update settings in database with audit trail."""
    init_default_settings()
    with get_db() as conn:
        for k, v in new_settings.items():
            conn.execute(
                "UPDATE system_settings SET setting_value = ?, updated_at = datetime('now') WHERE setting_key = ?",
                (str(v).strip(), k),
            )

        from app.security import log_audit
        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ADMIN",
            action="SETTINGS_UPDATED",
            entity="system_settings",
            entity_id="ALL",
            after_state={"updated_keys": list(new_settings.keys())},
            result="SUCCESS",
        )

def backup_database() -> Tuple[bytes, str]:
    """Read the current SQLite database file and return bytes for download."""
    from app.config import DB_PATH
    db_file = DB_PATH
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Database file not found at {db_file}")

    with open(db_file, "rb") as f:
        content = f.read()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_koperasi_{timestamp}.db"
    return content, filename
