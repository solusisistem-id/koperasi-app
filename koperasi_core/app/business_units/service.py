"""
Business Units (Toko & Fotocopy) Service and Financial Consolidation.
Allows independent unit managers to submit periodic balance sheet & P&L summaries,
and compiles global consolidated financial statements and SHU allocations for RAT.
"""
from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime

from app.database import get_db
from app.security import to_decimal, format_rupiah, log_audit, generate_reference_number

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
