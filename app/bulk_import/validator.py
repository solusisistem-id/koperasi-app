"""
Bulk Import Validation Logic for Koperasi Core.
Validates headers, data types, normalization, intra-file duplicates, and database duplicates.
"""
import re
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from decimal import Decimal

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_REGEX = re.compile(r"^[0-9+\-\s()]{8,20}$")

REQUIRED_HEADERS = [
    "member_number",
    "name",
    "nik",
    "email",
]

ALL_HEADERS = [
    "member_number",
    "employee_id",
    "name",
    "nik",
    "email",
    "phone",
    "department",
    "position",
    "membership_date",
    "membership_status",
    "address",
    "bank_account",
]

VALID_STATUSES = {"ACTIVE", "INACTIVE", "PENDING"}

def parse_date(date_val: Any) -> Optional[str]:
    """Parse various date formats into YYYY-MM-DD."""
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val.strftime("%Y-%m-%d")
    s = str(date_val).strip()
    # Try multiple standard formats
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def normalize_row_data(row: Dict[str, Any]) -> Dict[str, Any]:
    """Clean and normalize row fields."""
    normalized = {}
    for k, v in row.items():
        k_clean = str(k).strip().lower()
        if v is None:
            normalized[k_clean] = ""
        elif isinstance(v, datetime):
            normalized[k_clean] = v.strftime("%Y-%m-%d")
        else:
            normalized[k_clean] = str(v).strip()

    # Normalization specific to domain
    if "member_number" in normalized:
        normalized["member_number"] = normalized["member_number"].upper()
    if "employee_id" in normalized and normalized["employee_id"]:
        normalized["employee_id"] = normalized["employee_id"].upper()
    if "email" in normalized:
        normalized["email"] = normalized["email"].lower()
    if "nik" in normalized:
        normalized["nik"] = re.sub(r"\D", "", normalized["nik"])
    if "phone" in normalized:
        normalized["phone"] = re.sub(r"[^\d+]", "", normalized["phone"])
    if "membership_status" in normalized and normalized["membership_status"]:
        normalized["membership_status"] = normalized["membership_status"].upper()
    else:
        normalized["membership_status"] = "ACTIVE"
    if "department" in normalized:
        normalized["department"] = normalized["department"].upper()
    if "position" in normalized:
        normalized["position"] = normalized["position"].strip()

    return normalized

def validate_member_row(
    row_num: int,
    norm_data: Dict[str, Any],
    file_seen_numbers: set,
    file_seen_niks: set,
    file_seen_emails: set,
    db_existing_members: Dict[str, Any], # dict with 'numbers', 'niks', 'emails'
    dept_map: Dict[str, int],
    pos_map: Dict[str, int],
    mode: str, # ADD_ONLY, UPDATE_EXISTING, UPSERT
) -> Tuple[str, str, List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Validate a single row against business rules, data types, and duplicates.
    Returns: (status: VALID/INVALID/WARNING, action_type: NEW/UPDATE/DUPLICATE/NONE, errors, warnings)
    """
    errors = []
    warnings = []

    member_num = norm_data.get("member_number", "")
    name = norm_data.get("name", "")
    nik = norm_data.get("nik", "")
    email = norm_data.get("email", "")
    date_val = norm_data.get("membership_date", "")
    status_val = norm_data.get("membership_status", "ACTIVE")
    dept = norm_data.get("department", "")
    pos = norm_data.get("position", "")

    # 1. Required fields
    if not member_num:
        errors.append({"field": "member_number", "reason": "Nomor anggota (member_number) wajib diisi."})
    if not name:
        errors.append({"field": "name", "reason": "Nama lengkap wajib diisi."})
    if not nik:
        errors.append({"field": "nik", "reason": "NIK wajib diisi."})
    if not email:
        errors.append({"field": "email", "reason": "Email wajib diisi."})

    # 2. Email format validation
    if email and not EMAIL_REGEX.match(email):
        errors.append({"field": "email", "reason": f"Format email '{email}' tidak valid."})

    # 3. NIK validation
    if nik and (len(nik) != 16 or not nik.isdigit()):
        errors.append({"field": "nik", "reason": f"NIK harus berupa 16 digit angka, ditemukan: '{nik}'."})

    # 4. Date validation
    parsed_date = parse_date(date_val)
    if date_val and not parsed_date:
        errors.append({"field": "membership_date", "reason": f"Format tanggal '{date_val}' tidak dikenali. Gunakan YYYY-MM-DD atau DD/MM/YYYY."})
    elif parsed_date:
        norm_data["membership_date"] = parsed_date
    else:
        norm_data["membership_date"] = datetime.utcnow().strftime("%Y-%m-%d")

    # 5. Membership status validation
    if status_val not in VALID_STATUSES:
        errors.append({"field": "membership_status", "reason": f"Status '{status_val}' tidak valid. Pilihan: ACTIVE, INACTIVE, PENDING."})

    # 6. Department / Position validation
    if dept and dept not in dept_map and dept.upper() not in dept_map:
        warnings.append({"field": "department", "reason": f"Departemen '{dept}' belum terdaftar di sistem. Akan dibuat otomatis jika valid."})
    if pos and pos not in pos_map and pos.upper() not in pos_map:
        warnings.append({"field": "position", "reason": f"Posisi '{pos}' belum terdaftar di sistem. Akan dibuat otomatis jika valid."})

    # 7. Intra-file duplicate check
    if member_num:
        if member_num in file_seen_numbers:
            errors.append({"field": "member_number", "reason": f"Duplikat nomor anggota dalam file: '{member_num}'."})
        else:
            file_seen_numbers.add(member_num)

    if nik:
        if nik in file_seen_niks:
            errors.append({"field": "nik", "reason": f"Duplikat NIK dalam file: '{nik}'."})
        else:
            file_seen_niks.add(nik)

    if email:
        if email in file_seen_emails:
            errors.append({"field": "email", "reason": f"Duplikat email dalam file: '{email}'."})
        else:
            file_seen_emails.add(email)

    # 8. Database duplicate / existence check based on Import Mode
    exists_in_db = member_num in db_existing_members["numbers"]
    nik_in_db = nik in db_existing_members["niks"]
    email_in_db = email in db_existing_members["emails"]

    action_type = "NEW"

    if mode == "ADD_ONLY":
        if exists_in_db:
            errors.append({"field": "member_number", "reason": f"Nomor anggota '{member_num}' sudah ada di database (Mode: ADD_ONLY)."})
            action_type = "DUPLICATE"
        if nik_in_db:
            errors.append({"field": "nik", "reason": f"NIK '{nik}' sudah terdaftar pada anggota lain di database."})
            action_type = "DUPLICATE"
        if email_in_db:
            errors.append({"field": "email", "reason": f"Email '{email}' sudah terdaftar di database."})
            action_type = "DUPLICATE"

    elif mode == "UPDATE_EXISTING":
        if not exists_in_db:
            errors.append({"field": "member_number", "reason": f"Nomor anggota '{member_num}' tidak ditemukan di database (Mode: UPDATE_EXISTING)."})
            action_type = "NONE"
        else:
            action_type = "UPDATE"
            existing_row = db_existing_members["records"].get(member_num)
            if existing_row:
                if nik_in_db and existing_row["nik"] != nik:
                    errors.append({"field": "nik", "reason": f"NIK '{nik}' sudah dipakai anggota lain."})
                if email_in_db and existing_row["email"] != email:
                    errors.append({"field": "email", "reason": f"Email '{email}' sudah dipakai anggota lain."})

    elif mode == "UPSERT":
        if exists_in_db:
            action_type = "UPDATE"
            existing_row = db_existing_members["records"].get(member_num)
            if existing_row:
                if nik_in_db and existing_row["nik"] != nik:
                    errors.append({"field": "nik", "reason": f"NIK '{nik}' sudah dipakai anggota lain."})
                if email_in_db and existing_row["email"] != email:
                    errors.append({"field": "email", "reason": f"Email '{email}' sudah dipakai anggota lain."})
        else:
            action_type = "NEW"
            if nik_in_db:
                errors.append({"field": "nik", "reason": f"NIK '{nik}' sudah terdaftar pada anggota lain di database."})
            if email_in_db:
                errors.append({"field": "email", "reason": f"Email '{email}' sudah terdaftar di database."})

    # Determine row status
    if errors:
        row_status = "INVALID"
    elif warnings:
        row_status = "WARNING"
    else:
        row_status = "VALID"

    return row_status, action_type, errors, warnings
