import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import init_db, get_db
from app.config import ROLE_SUPER_ADMIN, ROLE_ADMIN_KOPERASI, ROLE_KETUA, ROLE_BENDAHARA, ROLE_ATASAN_APPROVER, ROLE_ANGGOTA
from app.auth.service import create_user_invitation

def bootstrap_production_admin(admin_email=None, admin_name=None):
    init_db()
    email = (admin_email or os.environ.get('INITIAL_ADMIN_EMAIL', 'superadmin@koperasi.local')).strip().lower()
    full_name = (admin_name or os.environ.get('INITIAL_ADMIN_NAME', 'Super Administrator')).strip()
    with get_db() as conn:
        roles = [
            (ROLE_SUPER_ADMIN, 'Super Admin', 'Sistem & keamanan tertinggi'),
            (ROLE_ADMIN_KOPERASI, 'Admin Koperasi', 'Operasional & keanggotaan'),
            (ROLE_KETUA, 'Ketua Koperasi', 'Persetujuan kebijakan & pinjaman'),
            (ROLE_BENDAHARA, 'Bendahara', 'Pencairan kas & keuangan'),
            (ROLE_ATASAN_APPROVER, 'Atasan Approver', 'Persetujuan bawahan'),
            (ROLE_ANGGOTA, 'Anggota', 'Layanan mandiri anggota'),
        ]
        for code, name, desc in roles:
            conn.execute('INSERT INTO roles (code, name, description) VALUES (?, ?, ?) ON CONFLICT (code) DO NOTHING', (code, name, desc))
        existing = conn.execute('SELECT id, status FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            return None

    inv = create_user_invitation(email=email, full_name=full_name, role_codes=[ROLE_SUPER_ADMIN], creator_user_id=1)
    return inv

if __name__ == '__main__':
    res = bootstrap_production_admin()
    if res:
        print(f"Admin invited successfully. Activation token: {res['token']}")
    else:
        print("Admin already exists or bootstrap failed.")
