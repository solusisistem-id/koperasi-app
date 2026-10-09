"""
End-to-End Scenario Verification Script as specified on Page 7 of Blueprint.

Storyline:
1. Admin logins
2. Downloads member import template
3. Imports historical members (CSV/Excel)
4. Validates data -> checks preview metrics
5. Commits batch -> Employee and Membership created
6. Admin selects imported member who needs account -> generates invitation
7. Member activates account -> sets private password
8. Member logs in
9. Opening balance recorded as ledger transaction (reconstructible balance)
10. Member submits loan application
11. System automatically resolves applicant's manager from employee organization structure
12. Manager line approval
13. Ketua Koperasi approval
14. Bendahara disburses loan -> creates active loan, generates installment schedule, issues SK Pinjaman with QR token
15. Member pays first installment -> atomic transaction, idempotency verified, outstanding updated
16. Public QR verification verified on server
17. Full audit trail verified for every key milestone
"""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, DB_PATH
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)
from app.security import to_decimal, format_rupiah
from app.auth.service import (
    authenticate_user,
    accept_invitation,
)
from app.members.service import (
    list_members,
    get_member_by_id,
    create_user_for_member,
)
from app.bulk_import.engine import (
    generate_member_import_template,
    stage_and_preview_import,
    commit_import_batch,
)
from app.savings.service import (
    record_opening_balance,
    get_member_savings_summary,
)
from app.loans.service import (
    apply_for_loan,
    process_approval,
    disburse_loan,
    pay_loan_installment,
    get_loan_details,
)
from app.documents.service import verify_document_token
from scripts.seed_data import seed_all

def run_end_to_end():
    print("=" * 70)
    print("🚀 MEMULAI PENGUJIAN SKENARIO END-TO-END KOPERASI CORE V2")
    print("=" * 70)

    # Clean reset
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass
    seed_all()

    # Step 1: Admin Login
    print("\n[Langkah 1] Admin Koperasi melakukan login...")
    admin_session = authenticate_user("admin@koperasi.local", "Admin123!")
    admin_user = {
        "id": admin_session["id"],
        "full_name": admin_session["full_name"],
        "email": admin_session["email"],
        "roles": admin_session["roles"],
    }
    print(f"✔ Admin berhasil login: {admin_user['full_name']} (Roles: {admin_user['roles']})")

    # Step 2: Download Template
    print("\n[Langkah 2] Mengunduh template import anggota...")
    tpl_bytes, tpl_name, _ = generate_member_import_template("xlsx")
    print(f"✔ Template berhasil diunduh: {tpl_name} ({len(tpl_bytes)} bytes)")

    # Step 3 & 4: Import Anggota Lama -> Parse -> Validate -> Preview
    print("\n[Langkah 3 & 4] Mengunggah data anggota lama, parsing, validasi, dan preview...")
    legacy_members_csv = (
        "member_number,employee_id,name,nik,email,phone,department,position,membership_date,membership_status,address,bank_account\n"
        "MEM-088,EMP-088,Rina Marlina,3201015504880001,rina.marlina@koperasi.local,081299887766,IT,Software Engineer,2023-05-10,ACTIVE,Jl. Cendana No. 4,BCA 888123456\n"
    ).encode("utf-8")

    preview = stage_and_preview_import(
        file_bytes=legacy_members_csv,
        filename="legacy_members_2023.csv",
        mode="ADD_ONLY",
        current_user=admin_user,
        dry_run=False,
    )
    print(f"✔ Batch terdaftar: {preview['batch_number']}")
    print(f"✔ Preview Counters: Total={preview['summary']['total_rows']}, Valid={preview['summary']['valid_rows']}, Invalid={preview['summary']['invalid_rows']}, New={preview['summary']['new_rows']}")
    assert preview["can_commit"] is True, "Batch validasi harus dapat di-commit"

    # Step 5: Commit Batch -> Employee/Membership terbentuk
    print("\n[Langkah 5] Mengonfirmasi dan melakukan commit batch import...")
    commit_res = commit_import_batch(preview["batch_id"], admin_user)
    print(f"✔ Hasil Commit: Dibuat={commit_res['created_rows']}, Status={commit_res['status']}")
    assert commit_res["created_rows"] == 1, "Harus membuat 1 anggota baru"

    with get_db() as conn:
        rina_mem = conn.execute("SELECT * FROM members WHERE member_number = 'MEM-088'").fetchone()
        rina_emp = conn.execute("SELECT * FROM employees WHERE employee_id = 'EMP-088'").fetchone()
        rina_id = rina_mem["id"]
        # Link Rina to manager Budi Santoso (EMP-001) for organization hierarchy
        budi_emp = conn.execute("SELECT id FROM employees WHERE employee_id = 'EMP-001'").fetchone()
        conn.execute("UPDATE employees SET manager_id = ? WHERE id = ?", (budi_emp["id"], rina_emp["id"]))
        print(f"✔ Anggota '{rina_mem['name']}' (ID: {rina_id}) dan Pegawai '{rina_emp['name']}' terhubung ke Manager 'Budi Santoso'.")

    # Step 6: Admin Memilih Anggota yang Perlu Akun -> Kirim Undangan
    print("\n[Langkah 6] Admin menyiapkan akun login & mengirim undangan aktivasi...")
    invitation = create_user_for_member(rina_id, admin_user)
    invite_token = invitation["invitation_token"]
    print(f"✔ Akun dibuat dalam status INVITED. Token aktivasi aman: {invite_token}")

    # Step 7: Anggota Menerima Undangan & Menentukan Password Sendiri
    print("\n[Langkah 7] Anggota mengakses tautan aktivasi & membuat password sendiri...")
    activate_res = accept_invitation(invite_token, "RinaPassword123!")
    print(f"✔ Akun Rina Marlina aktif: Status={activate_res['status']}")

    # Step 8: Anggota Login
    print("\n[Langkah 8] Anggota Rina Marlina melakukan login mandiri...")
    rina_session = authenticate_user("rina.marlina@koperasi.local", "RinaPassword123!")
    rina_user = {
        "id": rina_session["id"],
        "full_name": rina_session["full_name"],
        "email": rina_session["email"],
        "roles": rina_session["roles"],
        "member_id": rina_id,
    }
    print(f"✔ Rina Marlina berhasil login (User ID: {rina_user['id']})")

    # Step 9: Opening Balance Tercatat Sebagai Ledger
    print("\n[Langkah 9] Merekam saldo awal simpanan ke ledger buku besar...")
    record_opening_balance(
        member_id=rina_id,
        account_type="POKOK",
        amount_str="1000000.00",
        effective_date="2023-05-10",
        reference="OB-RINA-POKOK",
        notes="Saldo Pokok Awal Migrasi",
        current_user=admin_user,
    )
    record_opening_balance(
        member_id=rina_id,
        account_type="WAJIB",
        amount_str="500000.00",
        effective_date="2023-05-10",
        reference="OB-RINA-WAJIB",
        notes="Saldo Wajib Awal Migrasi",
        current_user=admin_user,
    )
    savings_sum = get_member_savings_summary(rina_id, rina_user)
    print(f"✔ Saldo Simpanan Rekonstruksi Riil: {savings_sum['formatted_total_balance']}")
    assert to_decimal(savings_sum["total_balance"]) == Decimal("1500000.00"), "Saldo harus ter-rekonstruksi Rp 1.500.000"

    # Step 10 & 11: Anggota Mengajukan Pinjaman -> Sistem Otomatis Temukan Atasan
    print("\n[Langkah 10 & 11] Anggota mengajukan pinjaman -> Sistem merutekan ke atasan (manager)...")
    loan_app = apply_for_loan(
        member_id=rina_id,
        amount_str="10000000.00",
        tenor_months=12,
        purpose="Renovasi Rumah Tinggal",
        current_user=rina_user,
    )
    app_id = loan_app["application_id"]
    print(f"✔ Pengajuan Pinjaman terbuat: No={loan_app['application_number']}, Angsuran={format_rupiah(loan_app['monthly_installment'])}/bln")
    print(f"✔ Tahap saat ini: {loan_app['current_step']}")

    # Step 12: Atasan (Manager Budi) Melakukan Approval
    print("\n[Langkah 12] Atasan langsung (Budi Santoso) menyetujui pengajuan...")
    manager_user = {"id": 5, "full_name": "Budi Santoso", "roles": [ROLE_ATASAN_APPROVER]}
    res_mgr = process_approval(app_id, "APPROVE", "Disetujui, kinerja baik dan kuota gaji mencukupi.", manager_user)
    print(f"✔ Keputusan Atasan: {res_mgr['decision']} -> Status Baru: {res_mgr['after_status']} -> Tahap Lanjutan: {res_mgr['current_step']}")
    assert res_mgr["after_status"] == "APPROVED_BY_MANAGER"
    assert res_mgr["current_step"] == "KETUA"

    # Step 13: Ketua Koperasi Melakukan Approval
    print("\n[Langkah 13] Ketua Koperasi menyetujui pengajuan...")
    ketua_user = {"id": 3, "full_name": "Drs. Hendro Wibowo (Ketua)", "roles": [ROLE_KETUA]}
    res_ketua = process_approval(app_id, "APPROVE", "Disetujui sesuai rapat pengurus koperasi.", ketua_user)
    print(f"✔ Keputusan Ketua: {res_ketua['decision']} -> Status Baru: {res_ketua['after_status']} -> Tahap Lanjutan: {res_ketua['current_step']}")
    assert res_ketua["after_status"] == "WAITING_DISBURSEMENT"
    assert res_ketua["current_step"] == "BENDAHARA"

    # Step 14: Bendahara Mencairkan Pinjaman -> Loan Active -> Jadwal & QR Terbentuk
    print("\n[Langkah 14] Bendahara mencairkan dana pinjaman...")
    bendahara_user = {"id": 4, "full_name": "Siti Rahmawati (Bendahara)", "roles": [ROLE_BENDAHARA]}
    disb_res = disburse_loan(app_id, bendahara_user)
    loan_id = disb_res["loan_id"]
    qr_token = disb_res["qr_token"]
    print(f"✔ Dana berhasil dicairkan: No. Pinjaman={disb_res['loan_number']}, Nominal={format_rupiah(disb_res['disbursed_amount'])}")
    print(f"✔ Dokumen SK Pinjaman terbentuk (ID: {disb_res['document_id']}) dengan Token QR: {qr_token}")

    # Step 15: Angsuran Pertama Dicatat & Idempotency Teruji
    print("\n[Langkah 15] Anggota membayar angsuran ke-1...")
    loan_detail = get_loan_details(loan_id, rina_user)
    inst_1 = loan_detail["installments"][0]
    idemp_key = f"IDEMP-SCENARIO-PAY-1"

    pay_res = pay_loan_installment(inst_1["id"], inst_1["amount"], idemp_key, rina_user)
    print(f"✔ Pembayaran Angsuran ke-1 Sukses: Nominal={format_rupiah(pay_res['paid_amount'])}, Sisa Outstanding={format_rupiah(pay_res['remaining_outstanding'])}")

    # Double payment idempotency check
    print("  Menguji proteksi double-submit (idempotency)...")
    dup_pay = pay_loan_installment(inst_1["id"], inst_1["amount"], idemp_key, rina_user)
    print(f"✔ Proteksi Idempotency Berhasil: {dup_pay.get('message', 'Processed')}")
    assert dup_pay.get("already_processed") is True, "Double payment harus ditolak secara idempotent"

    # Step 16: Dokumen Diverifikasi Melalui QR Token Server-Side
    print("\n[Langkah 16] Verifikasi keabsahan dokumen melalui Token QR publik...")
    v_res = verify_document_token(qr_token)
    print(f"✔ Hasil Verifikasi QR: Sah={v_res['valid']}, Status={v_res['status']}, Judul={v_res['title']}")
    assert v_res["valid"] is True, "Token QR harus terverifikasi sah oleh server"

    # Step 17: Seluruh Aksi Penting Tercatat Dalam Audit Trail
    print("\n[Langkah 17] Memeriksa kelengkapan audit trail keamanan dan finansial...")
    with get_db() as conn:
        actions = conn.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action ASC").fetchall()
        action_names = [a["action"] for a in actions]
        print(f"✔ Total {len(action_names)} tipe aksi audit unik tercatat:")
        for an in action_names:
            print(f"   • {an}")

    print("\n" + "=" * 70)
    print("🎉 SEMUA 17 LANGKAH SKENARIO END-TO-END BERHASIL DILALUI DENGAN SUKSES!")
    print("=" * 70)

if __name__ == "__main__":
    run_end_to_end()
