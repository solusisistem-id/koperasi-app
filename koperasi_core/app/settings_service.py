"""
Settings Service for Koperasi Core.
Manages cooperative profile, product policies (savings, loans, business units),
SHU distribution percentages, and database backup.
"""
from typing import Dict, Any, Tuple
from datetime import datetime
import os
import shutil

from app.database import get_db, DB_PATH
from app.security import log_audit

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
    db_file = DB_PATH
    if not os.path.exists(db_file):
        raise FileNotFoundError(f"Database file not found at {db_file}")

    with open(db_file, "rb") as f:
        content = f.read()

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_koperasi_{timestamp}.db"
    return content, filename
