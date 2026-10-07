"""
Bulk Import Engine for Koperasi Core.
Manages Excel/CSV parsing, staging, validation, dry-run, preview, commit, and error export.
"""
import os
import csv
import io
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
import openpyxl

from app.database import get_db
from app.config import DATA_DIR, UPLOADS_DIR, TEMPLATES_DIR, ROLE_SUPER_ADMIN, ROLE_ADMIN_KOPERASI
from app.security import log_audit, sanitize_for_spreadsheet
from app.bulk_import.validator import (
    REQUIRED_HEADERS,
    ALL_HEADERS,
    normalize_row_data,
    validate_member_row,
)

def generate_member_import_template(file_format: str = "xlsx") -> Tuple[bytes, str, str]:
    """
    Generate downloadable template for member bulk import.
    Returns: (file_bytes, filename, mime_type)
    """
    sample_rows = [
        {
            "member_number": "MEM-101",
            "employee_id": "EMP-101",
            "name": "Bambang Sudirman",
            "nik": "3171011503850001",
            "email": "bambang.sudirman@koperasi.local",
            "phone": "081234567801",
            "department": "IT",
            "position": "Software Engineer",
            "membership_date": "2024-01-01",
            "membership_status": "ACTIVE",
            "address": "Jl. Melati No. 5, Jakarta Barat",
            "bank_account": "BCA 8820192831",
        },
        {
            "member_number": "MEM-102",
            "employee_id": "EMP-102",
            "name": "Citra Lestari",
            "nik": "3171012008920002",
            "email": "citra.lestari@koperasi.local",
            "phone": "081234567802",
            "department": "HR",
            "position": "HR Specialist",
            "membership_date": "2024-02-01",
            "membership_status": "ACTIVE",
            "address": "Jl. Kenanga No. 12, Jakarta Selatan",
            "bank_account": "Mandiri 137001928374",
        },
    ]

    if file_format.lower() == "csv":
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=ALL_HEADERS)
        writer.writeheader()
        for r in sample_rows:
            writer.writerow(r)
        content = out.getvalue().encode("utf-8")
        filename = "template_import_anggota.csv"
        mime_type = "text/csv"
        return content, filename, mime_type

    # Excel format (.xlsx)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data_Anggota"
    ws.append(ALL_HEADERS)
    for r in sample_rows:
        ws.append([r.get(h, "") for h in ALL_HEADERS])

    ws_guide = wb.create_sheet(title="Petunjuk_Pengisian")
    guide_headers = ["Nama Kolom", "Wajib / Opsional", "Tipe Data / Format", "Keterangan & Nilai yang Diizinkan"]
    ws_guide.append(guide_headers)
    guide_rows = [
        ("member_number", "WAJIB", "Teks (Uppercase)", "Nomor unik anggota koperasi, cth: MEM-001"),
        ("employee_id", "OPSIONAL", "Teks", "Nomor induk karyawan (jika karyawan internal), cth: EMP-001"),
        ("name", "WAJIB", "Teks", "Nama lengkap sesuai KTP"),
        ("nik", "WAJIB", "16 Digit Angka", "Nomor Induk Kependudukan (unik)"),
        ("email", "WAJIB", "Email Valid", "Alamat email unik untuk korespondensi/aktivasi akun"),
        ("phone", "OPSIONAL", "Nomor Telepon", "Nomor HP / WhatsApp aktif"),
        ("department", "OPSIONAL", "Kode / Nama", "Departemen kerja karyawan: IT, HR, FIN, OPS"),
        ("position", "OPSIONAL", "Nama Jabatan", "Nama posisi / jabatan"),
        ("membership_date", "OPSIONAL", "YYYY-MM-DD", "Tanggal bergabung, cth: 2024-01-15 (default: hari ini)"),
        ("membership_status", "OPSIONAL", "ACTIVE / INACTIVE / PENDING", "Status keanggotaan (default: ACTIVE)"),
        ("address", "OPSIONAL", "Teks", "Alamat domisili lengkap"),
        ("bank_account", "OPSIONAL", "Teks", "Nama Bank dan Nomor Rekening pencairan pinjaman"),
    ]
    for g in guide_rows:
        ws_guide.append(list(g))

    buf = io.BytesIO()
    wb.save(buf)
    content = buf.getvalue()
    filename = "template_import_anggota.xlsx"
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return content, filename, mime_type

def parse_file(file_bytes: bytes, filename: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Parse CSV or Excel file bytes into headers and row dictionaries."""
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        text = file_bytes.decode("utf-8-sig", errors="replace")
        f = io.StringIO(text)
        reader = csv.reader(f)
        try:
            raw_headers = next(reader)
        except StopIteration:
            raise ValueError("File CSV kosong.")
        headers = [h.strip().lower() for h in raw_headers if h.strip()]
        rows = []
        for r_idx, row_vals in enumerate(reader, start=2):
            if not any(row_vals):
                continue
            row_dict = {}
            for col_idx, h in enumerate(headers):
                row_dict[h] = row_vals[col_idx] if col_idx < len(row_vals) else ""
            rows.append(row_dict)
        return headers, rows

    elif lower_name.endswith((".xlsx", ".xls")):
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            raise ValueError("File Excel kosong.")
        raw_headers = [str(h).strip().lower() for h in all_rows[0] if h is not None]
        headers = raw_headers
        rows = []
        for row_vals in all_rows[1:]:
            if not any(row_vals):
                continue
            row_dict = {}
            for col_idx, h in enumerate(headers):
                val = row_vals[col_idx] if col_idx < len(row_vals) else ""
                row_dict[h] = "" if val is None else val
            rows.append(row_dict)
        return headers, rows

    else:
        raise ValueError(f"Ekstensi file tidak didukung: {filename}. Harap gunakan format .xlsx atau .csv.")

def stage_and_preview_import(
    file_bytes: bytes,
    filename: str,
    mode: str,
    current_user: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Parse uploaded file, validate all rows, store in staging tables,
    and return preview summary. Does NOT commit to production tables!
    """
    if mode not in ("ADD_ONLY", "UPDATE_EXISTING", "UPSERT"):
        raise ValueError(f"Mode import '{mode}' tidak valid.")

    headers, raw_rows = parse_file(file_bytes, filename)

    # 1. Header validation
    missing_headers = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing_headers:
        raise ValueError(f"Header wajib tidak ditemukan pada file: {', '.join(missing_headers)}")

    with get_db() as conn:
        mem_rows = conn.execute("SELECT id, member_number, nik, email FROM members").fetchall()
        db_members = {
            "numbers": {r["member_number"] for r in mem_rows},
            "niks": {r["nik"] for r in mem_rows},
            "emails": {r["email"] for r in mem_rows},
            "records": {r["member_number"]: dict(r) for r in mem_rows},
        }

        dept_rows = conn.execute("SELECT id, code, name FROM departments").fetchall()
        dept_map = {r["code"].upper(): r["id"] for r in dept_rows}
        dept_map.update({r["name"].upper(): r["id"] for r in dept_rows})

        pos_rows = conn.execute("SELECT id, code, title FROM positions").fetchall()
        pos_map = {r["code"].upper(): r["id"] for r in pos_rows}
        pos_map.update({r["title"].upper(): r["id"] for r in pos_rows})

        batch_number = f"IMP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets_hex(3)}"
        file_ext = filename.split(".")[-1].upper()

        cur_batch = conn.execute(
            """
            INSERT INTO import_batches (
                batch_number, file_name, file_type, import_type, mode,
                status, imported_by, started_at
            ) VALUES (?, ?, ?, 'MEMBER', ?, 'PENDING_PREVIEW', ?, datetime('now'))
            """,
            (batch_number, filename, file_ext, mode, current_user["id"]),
        )
        batch_id = cur_batch.lastrowid

        file_seen_numbers = set()
        file_seen_niks = set()
        file_seen_emails = set()

        total_rows = len(raw_rows)
        valid_count = 0
        invalid_count = 0
        warning_count = 0
        new_count = 0
        update_count = 0
        dup_count = 0

        staged_rows = []
        all_errors_summary = []

        for idx, r in enumerate(raw_rows, start=2):
            norm = normalize_row_data(r)
            status, action_type, errors, warnings = validate_member_row(
                row_num=idx,
                norm_data=norm,
                file_seen_numbers=file_seen_numbers,
                file_seen_niks=file_seen_niks,
                file_seen_emails=file_seen_emails,
                db_existing_members=db_members,
                dept_map=dept_map,
                pos_map=pos_map,
                mode=mode,
            )

            if status == "INVALID":
                invalid_count += 1
                for err in errors:
                    all_errors_summary.append({"row": idx, "field": err["field"], "reason": err["reason"]})
            else:
                valid_count += 1
                if status == "WARNING":
                    warning_count += 1

            if action_type == "NEW":
                new_count += 1
            elif action_type == "UPDATE":
                update_count += 1
            elif action_type == "DUPLICATE":
                dup_count += 1

            conn.execute(
                """
                INSERT INTO import_rows (
                    batch_id, row_number, raw_data_json, normalized_data_json,
                    status, action_type, errors_json, warnings_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    batch_id,
                    idx,
                    json.dumps(r, default=str),
                    json.dumps(norm, default=str),
                    status,
                    action_type,
                    json.dumps(errors),
                    json.dumps(warnings),
                ),
            )

            staged_rows.append({
                "row_number": idx,
                "status": status,
                "action_type": action_type,
                "data": norm,
                "errors": errors,
                "warnings": warnings,
            })

        batch_status = "VALIDATED" if invalid_count == 0 else "PENDING_PREVIEW"
        conn.execute(
            """
            UPDATE import_batches
            SET total_rows = ?, valid_rows = ?, invalid_rows = ?, warning_count = ?,
                status = ?, error_summary = ?
            WHERE id = ?
            """,
            (
                total_rows,
                valid_count,
                invalid_count,
                warning_count,
                batch_status,
                json.dumps(all_errors_summary[:20]),
                batch_id,
            ),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ADMIN",
            action="IMPORT_STARTED",
            entity="import_batches",
            entity_id=str(batch_id),
            after_state={
                "batch_number": batch_number,
                "total": total_rows,
                "valid": valid_count,
                "invalid": invalid_count,
                "mode": mode,
                "dry_run": dry_run,
            },
            result="SUCCESS",
        )

        return {
            "batch_id": batch_id,
            "batch_number": batch_number,
            "filename": filename,
            "mode": mode,
            "dry_run": dry_run,
            "summary": {
                "total_rows": total_rows,
                "valid_rows": valid_count,
                "invalid_rows": invalid_count,
                "warning_rows": warning_count,
                "new_rows": new_count,
                "update_rows": update_count,
                "duplicate_rows": dup_count,
            },
            "preview_rows": staged_rows[:50],
            "all_errors": all_errors_summary,
            "can_commit": invalid_count == 0,
        }

def secrets_hex(n: int) -> str:
    import secrets
    return secrets.token_hex(n).upper()

def commit_import_batch(batch_id: int, current_user: Dict[str, Any], ignore_warnings: bool = True) -> Dict[str, Any]:
    """
    Commit staged rows from import_batches to production tables (members, employees, savings_accounts).
    Ensures transactional integrity and audit logging.
    """
    with get_db() as conn:
        batch = conn.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
        if not batch:
            raise ValueError(f"Batch import dengan ID {batch_id} tidak ditemukan.")

        if batch["status"] == "COMMITTED":
            raise ValueError(f"Batch import {batch['batch_number']} sudah pernah di-commit sebelumnya.")

        invalid_rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM import_rows WHERE batch_id = ? AND status = 'INVALID'",
            (batch_id,),
        ).fetchone()["cnt"]

        if invalid_rows > 0:
            raise ValueError(f"Batch memiliki {invalid_rows} baris dengan error blocking. Perbaiki file sebelum commit.")

        rows_to_commit = conn.execute(
            "SELECT * FROM import_rows WHERE batch_id = ? AND status IN ('VALID', 'WARNING') ORDER BY row_number ASC",
            (batch_id,),
        ).fetchall()

        created_count = 0
        updated_count = 0
        failed_count = 0

        dept_rows = conn.execute("SELECT id, code, name FROM departments").fetchall()
        dept_map = {r["code"].upper(): r["id"] for r in dept_rows}
        dept_map.update({r["name"].upper(): r["id"] for r in dept_rows})

        pos_rows = conn.execute("SELECT id, code, title FROM positions").fetchall()
        pos_map = {r["title"].upper(): r["id"] for r in pos_rows}
        pos_map.update({r["code"].upper(): r["id"] for r in pos_rows})

        for r_row in rows_to_commit:
            try:
                norm = json.loads(r_row["normalized_data_json"])
                action = r_row["action_type"]

                dept_code = norm.get("department", "")
                dept_id = None
                if dept_code:
                    if dept_code.upper() in dept_map:
                        dept_id = dept_map[dept_code.upper()]
                    else:
                        cur_d = conn.execute("INSERT INTO departments (code, name) VALUES (?, ?)", (dept_code.upper(), dept_code))
                        dept_id = cur_d.lastrowid
                        dept_map[dept_code.upper()] = dept_id

                pos_title = norm.get("position", "")
                pos_id = None
                if pos_title:
                    if pos_title.upper() in pos_map:
                        pos_id = pos_map[pos_title.upper()]
                    else:
                        cur_p = conn.execute(
                            "INSERT INTO positions (department_id, code, title) VALUES (?, ?, ?)",
                            (dept_id or 1, pos_title[:10].upper(), pos_title),
                        )
                        pos_id = cur_p.lastrowid
                        pos_map[pos_title.upper()] = pos_id

                emp_id = None
                emp_code = norm.get("employee_id", "")
                if emp_code:
                    existing_emp = conn.execute("SELECT id FROM employees WHERE employee_id = ?", (emp_code,)).fetchone()
                    if existing_emp:
                        emp_id = existing_emp["id"]
                        conn.execute(
                            """
                            UPDATE employees
                            SET name = ?, nik = ?, email = ?, phone = ?, department_id = COALESCE(?, department_id),
                                position_id = COALESCE(?, position_id), updated_at = datetime('now')
                            WHERE id = ?
                            """,
                            (norm["name"], norm["nik"], norm["email"], norm.get("phone", ""), dept_id, pos_id, emp_id),
                        )
                    else:
                        cur_emp = conn.execute(
                            """
                            INSERT INTO employees (
                                employee_id, name, nik, email, phone, department_id, position_id, status, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', datetime('now'), datetime('now'))
                            """,
                            (emp_code, norm["name"], norm["nik"], norm["email"], norm.get("phone", ""), dept_id, pos_id),
                        )
                        emp_id = cur_emp.lastrowid

                if action == "NEW":
                    cur_m = conn.execute(
                        """
                        INSERT INTO members (
                            member_number, employee_id, name, nik, email, phone, address,
                            bank_account, membership_date, membership_status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                        """,
                        (
                            norm["member_number"],
                            emp_id,
                            norm["name"],
                            norm["nik"],
                            norm["email"],
                            norm.get("phone", ""),
                            norm.get("address", ""),
                            norm.get("bank_account", ""),
                            norm.get("membership_date"),
                            norm.get("membership_status", "ACTIVE"),
                        ),
                    )
                    member_id = cur_m.lastrowid

                    for acc_type in ["POKOK", "WAJIB", "SUKARELA"]:
                        acc_num = f"SA-{acc_type[:3]}-{norm['member_number']}"
                        conn.execute(
                            "INSERT OR IGNORE INTO savings_accounts (member_id, account_number, account_type, status) VALUES (?, ?, ?, 'ACTIVE')",
                            (member_id, acc_num, acc_type),
                        )

                    created_count += 1
                    conn.execute("UPDATE import_rows SET status = 'COMMITTED' WHERE id = ?", (r_row["id"],))

                elif action == "UPDATE":
                    existing_m = conn.execute("SELECT id FROM members WHERE member_number = ?", (norm["member_number"],)).fetchone()
                    if existing_m:
                        member_id = existing_m["id"]
                        conn.execute(
                            """
                            UPDATE members
                            SET employee_id = COALESCE(?, employee_id), name = ?, nik = ?, email = ?,
                                phone = ?, address = ?, bank_account = ?, membership_date = ?,
                                membership_status = ?, updated_at = datetime('now')
                            WHERE id = ?
                            """,
                            (
                                emp_id,
                                norm["name"],
                                norm["nik"],
                                norm["email"],
                                norm.get("phone", ""),
                                norm.get("address", ""),
                                norm.get("bank_account", ""),
                                norm.get("membership_date"),
                                norm.get("membership_status", "ACTIVE"),
                                member_id,
                            ),
                        )
                        updated_count += 1
                        conn.execute("UPDATE import_rows SET status = 'COMMITTED' WHERE id = ?", (r_row["id"],))
                    else:
                        failed_count += 1
                        conn.execute("UPDATE import_rows SET status = 'FAILED' WHERE id = ?", (r_row["id"],))

            except Exception as e:
                failed_count += 1
                conn.execute(
                    "UPDATE import_rows SET status = 'FAILED', errors_json = ? WHERE id = ?",
                    (json.dumps([{"field": "general", "reason": str(e)}]), r_row["id"]),
                )

        final_status = "COMMITTED" if failed_count == 0 else "PARTIALLY_COMMITTED"
        conn.execute(
            """
            UPDATE import_batches
            SET created_rows = ?, updated_rows = ?, failed_rows = ?, status = ?, completed_at = datetime('now')
            WHERE id = ?
            """,
            (created_count, updated_count, failed_count, final_status, batch_id),
        )

        log_audit(
            conn,
            actor_id=current_user["id"],
            actor_name=current_user["full_name"],
            actor_role="ADMIN",
            action="IMPORT_COMPLETED",
            entity="import_batches",
            entity_id=str(batch_id),
            after_state={
                "batch_id": batch_id,
                "created": created_count,
                "updated": updated_count,
                "failed": failed_count,
                "status": final_status,
            },
            result="SUCCESS",
        )

        return {
            "batch_id": batch_id,
            "status": final_status,
            "created_rows": created_count,
            "updated_rows": updated_count,
            "failed_rows": failed_count,
            "total_processed": len(rows_to_commit),
        }

def generate_error_report_csv(batch_id: int) -> Tuple[bytes, str]:
    """Generate CSV error report for a specific import batch."""
    with get_db() as conn:
        batch = conn.execute("SELECT batch_number FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
        batch_num = batch["batch_number"] if batch else f"BATCH-{batch_id}"

        rows = conn.execute(
            "SELECT row_number, errors_json, raw_data_json FROM import_rows WHERE batch_id = ? AND status = 'INVALID' ORDER BY row_number ASC",
            (batch_id,),
        ).fetchall()

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["Row Number", "Field", "Error Reason", "Raw Input Data"])

        for r in rows:
            errors = json.loads(r["errors_json"] or "[]")
            for err in errors:
                writer.writerow([
                    r["row_number"],
                    sanitize_for_spreadsheet(err.get("field", "")),
                    sanitize_for_spreadsheet(err.get("reason", "")),
                    sanitize_for_spreadsheet(r["raw_data_json"]),
                ])

        content = out.getvalue().encode("utf-8")
        filename = f"error_report_{batch_num}.csv"
        return content, filename

def list_import_batches(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """List historical import batches."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT b.*, u.full_name as imported_by_name
            FROM import_batches b
            LEFT JOIN users u ON b.imported_by = u.id
            ORDER BY b.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

def get_import_batch_detail(batch_id: int) -> Dict[str, Any]:
    """Get full details of a specific batch including rows."""
    with get_db() as conn:
        batch = conn.execute(
            """
            SELECT b.*, u.full_name as imported_by_name
            FROM import_batches b
            LEFT JOIN users u ON b.imported_by = u.id
            WHERE b.id = ?
            """,
            (batch_id,),
        ).fetchone()

        if not batch:
            raise ValueError("Batch import tidak ditemukan.")

        rows = conn.execute(
            "SELECT * FROM import_rows WHERE batch_id = ? ORDER BY row_number ASC",
            (batch_id,),
        ).fetchall()

        return {
            "batch": dict(batch),
            "rows": [dict(r) for r in rows],
        }
