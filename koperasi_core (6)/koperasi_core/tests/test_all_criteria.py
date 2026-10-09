"""
Comprehensive Test Suite for Koperasi Core.
Validates all 20 mandatory acceptance criteria specified in Blueprint Section 20.
"""
import os
import sys
import unittest
import json
import io
import csv
from datetime import datetime, timedelta
from decimal import Decimal

# Add koperasi_core to path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.database import get_db, init_db, DB_PATH
from app.config import (
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)
from app.security import hash_password, verify_password, to_decimal
from app.auth.service import (
    authenticate_user,
    create_password_reset_token,
    reset_password,
    create_user_invitation,
    accept_invitation,
    change_user_status,
    AuthenticationError,
)
from app.members.service import (
    list_members,
    get_member_by_id,
    create_member_manual,
    create_user_for_member,
    MemberAccessForbidden,
)
from app.bulk_import.engine import (
    stage_and_preview_import,
    commit_import_batch,
    generate_error_report_csv,
    generate_member_import_template,
)
from app.savings.service import (
    record_opening_balance,
    get_member_savings_summary,
    record_deposit,
)
from app.loans.service import (
    apply_for_loan,
    process_approval,
    disburse_loan,
    pay_loan_installment,
    get_loan_details,
    calculate_loan_schedule,
    MakerCheckerViolation,
    LoanError,
)
from app.documents.service import verify_document_token, revoke_token, create_document_record
from scripts.seed_data import seed_all

class TestKoperasiCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Remove old db if exists for clean, predictable isolation
        if os.path.exists(DB_PATH):
            try:
                os.remove(DB_PATH)
            except Exception:
                pass
        seed_all()

    def setUp(self):
        self.superadmin = {"id": 1, "full_name": "Super Admin", "email": "superadmin@koperasi.local", "roles": [ROLE_SUPER_ADMIN]}
        self.admin = {"id": 2, "full_name": "Admin Koperasi", "email": "admin@koperasi.local", "roles": [ROLE_ADMIN_KOPERASI]}
        self.ketua = {"id": 3, "full_name": "Ketua", "email": "ketua@koperasi.local", "roles": [ROLE_KETUA, ROLE_ATASAN_APPROVER]}
        self.bendahara = {"id": 4, "full_name": "Bendahara", "email": "bendahara@koperasi.local", "roles": [ROLE_BENDAHARA]}
        self.manager = {"id": 5, "full_name": "Budi Santoso", "email": "manager.budi@koperasi.local", "roles": [ROLE_ATASAN_APPROVER]}
        self.member_andi = {"id": 6, "full_name": "Andi Pratama", "email": "member.andi@koperasi.local", "roles": [ROLE_ANGGOTA], "member_id": 1}

    # Criterion 1: Valid Import
    def test_01_valid_bulk_import(self):
        csv_data = (
            "member_number,employee_id,name,nik,email,phone,department,position,membership_date,membership_status,address,bank_account\n"
            "MEM-201,EMP-201,Doni Setiawan,3171011111900001,doni@koperasi.local,081234567811,IT,Software Engineer,2024-03-01,ACTIVE,Jl. Mawar 1,BCA 11111\n"
            "MEM-202,EMP-202,Eka Putri,3171012222900002,eka@koperasi.local,081234567812,HR,HR Specialist,2024-03-01,ACTIVE,Jl. Mawar 2,BRI 22222\n"
        ).encode("utf-8")

        preview = stage_and_preview_import(
            file_bytes=csv_data,
            filename="valid_import.csv",
            mode="ADD_ONLY",
            current_user=self.admin,
            dry_run=False,
        )

        self.assertEqual(preview["summary"]["total_rows"], 2)
        self.assertEqual(preview["summary"]["valid_rows"], 2)
        self.assertEqual(preview["summary"]["invalid_rows"], 0)
        self.assertTrue(preview["can_commit"])

        commit_res = commit_import_batch(preview["batch_id"], self.admin)
        self.assertEqual(commit_res["created_rows"], 2)
        self.assertEqual(commit_res["failed_rows"], 0)

        # Verify members exist
        m = get_member_by_id(commit_res["created_rows"], self.admin)
        self.assertIsNotNone(m)

    # Criterion 2: Invalid Header Check
    def test_02_invalid_header(self):
        bad_csv = "wrong_head1,wrong_head2\n1,2\n".encode("utf-8")
        with self.assertRaises(ValueError) as ctx:
            stage_and_preview_import(bad_csv, "bad_head.csv", "ADD_ONLY", self.admin)
        self.assertIn("Header wajib tidak ditemukan", str(ctx.exception))

    # Criterion 3: Missing Fields
    def test_03_missing_required_fields(self):
        csv_missing = (
            "member_number,employee_id,name,nik,email\n"
            "MEM-203,EMP-203,,,missing_name_nik@koperasi.local\n"
        ).encode("utf-8")
        preview = stage_and_preview_import(csv_missing, "missing.csv", "ADD_ONLY", self.admin)
        self.assertEqual(preview["summary"]["invalid_rows"], 1)
        self.assertFalse(preview["can_commit"])

    # Criterion 4: Intra-file and DB Duplicates
    def test_04_duplicates_detection(self):
        dup_csv = (
            "member_number,employee_id,name,nik,email\n"
            "MEM-204,EMP-204,User A,3171013333900003,userA@koperasi.local\n"
            "MEM-204,EMP-205,User B,3171014444900004,userB@koperasi.local\n"
        ).encode("utf-8")
        preview = stage_and_preview_import(dup_csv, "dup_in_file.csv", "ADD_ONLY", self.admin)
        self.assertEqual(preview["summary"]["invalid_rows"], 1)
        self.assertFalse(preview["can_commit"])

    # Criterion 5: Invalid Email, Date, Status
    def test_05_invalid_email_date_status(self):
        bad_data_csv = (
            "member_number,employee_id,name,nik,email,membership_date,membership_status\n"
            "MEM-205,EMP-206,User C,3171015555900005,not-an-email,99-99-9999,INVALID_STATUS\n"
        ).encode("utf-8")
        preview = stage_and_preview_import(bad_data_csv, "bad_data.csv", "ADD_ONLY", self.admin)
        self.assertEqual(preview["summary"]["invalid_rows"], 1)
        err_fields = [e["field"] for e in preview["all_errors"]]
        self.assertIn("email", err_fields)
        self.assertIn("membership_date", err_fields)
        self.assertIn("membership_status", err_fields)

    # Criterion 6: Dry-run Isolation
    def test_06_dry_run_isolation(self):
        dry_csv = (
            "member_number,employee_id,name,nik,email\n"
            "MEM-DRY,EMP-DRY,Dry Run Member,3171016666900006,dry@koperasi.local\n"
        ).encode("utf-8")
        preview = stage_and_preview_import(dry_csv, "dry.csv", "ADD_ONLY", self.admin, dry_run=True)
        self.assertTrue(preview["dry_run"])
        with get_db() as conn:
            exists = conn.execute("SELECT id FROM members WHERE member_number = 'MEM-DRY'").fetchone()
            self.assertIsNone(exists)

    # Criterion 7: Preview / Commit Consistency
    def test_07_preview_commit_consistency(self):
        test_csv = (
            "member_number,employee_id,name,nik,email\n"
            "MEM-207,EMP-207,User 207,3171017777900007,user207@koperasi.local\n"
        ).encode("utf-8")
        preview = stage_and_preview_import(test_csv, "c207.csv", "ADD_ONLY", self.admin)
        self.assertEqual(preview["summary"]["valid_rows"], 1)

        res = commit_import_batch(preview["batch_id"], self.admin)
        self.assertEqual(res["created_rows"], 1)

        # Re-commit should be rejected
        with self.assertRaises(ValueError):
            commit_import_batch(preview["batch_id"], self.admin)

    # Criterion 8: Update / Upsert Modes
    def test_08_import_modes_update_and_upsert(self):
        # Update existing member MEM-207 (created in test_07)
        update_csv = (
            "member_number,employee_id,name,nik,email\n"
            "MEM-207,EMP-207,User 207 Renamed,3171017777900007,user207@koperasi.local\n"
        ).encode("utf-8")

        # In ADD_ONLY mode, should fail because MEM-207 already exists
        preview_add = stage_and_preview_import(update_csv, "up_add.csv", "ADD_ONLY", self.admin)
        self.assertEqual(preview_add["summary"]["invalid_rows"], 1)

        # In UPDATE_EXISTING mode, should be VALID and action_type UPDATE
        preview_up = stage_and_preview_import(update_csv, "up_exist.csv", "UPDATE_EXISTING", self.admin)
        self.assertEqual(preview_up["summary"]["valid_rows"], 1)
        commit_res = commit_import_batch(preview_up["batch_id"], self.admin)
        self.assertEqual(commit_res["updated_rows"], 1)

        # Verify updated name
        with get_db() as conn:
            m = conn.execute("SELECT name FROM members WHERE member_number = 'MEM-207'").fetchone()
            self.assertEqual(m["name"], "User 207 Renamed")

        # In UPSERT mode: MEM-207 updated, MEM-208 created
        upsert_csv = (
            "member_number,employee_id,name,nik,email\n"
            "MEM-207,EMP-207,User 207 Upserted,3171017777900007,user207@koperasi.local\n"
            "MEM-208,EMP-208,Brand New 208,3171018888900008,new208@koperasi.local\n"
        ).encode("utf-8")
        preview_upsert = stage_and_preview_import(upsert_csv, "upsert.csv", "UPSERT", self.admin)
        self.assertEqual(preview_upsert["summary"]["valid_rows"], 2)
        commit_upsert = commit_import_batch(preview_upsert["batch_id"], self.admin)
        self.assertEqual(commit_upsert["updated_rows"], 1)
        self.assertEqual(commit_upsert["created_rows"], 1)

    # Criterion 9: Import Audit Trail
    def test_09_import_audit_trail(self):
        with get_db() as conn:
            audit = conn.execute("SELECT * FROM audit_logs WHERE action IN ('IMPORT_STARTED', 'IMPORT_COMPLETED')").fetchall()
            self.assertGreater(len(audit), 0)

    # Criterion 10: Error Report Download
    def test_10_error_report_download(self):
        bad_csv = "member_number,name,nik,email\nMEM-BAD,,,\n".encode("utf-8")
        preview = stage_and_preview_import(bad_csv, "err_rep.csv", "ADD_ONLY", self.admin)
        content, fname = generate_error_report_csv(preview["batch_id"])
        self.assertIn("error_report_", fname)
        text = content.decode("utf-8")
        self.assertIn("Row Number", text)
        self.assertIn("name", text)

    # Criterion 11: Opening Balance Ledger Reconstruction
    def test_11_opening_balance_ledger_reconstruction(self):
        mem_id = create_member_manual({
            "member_number": "MEM-OB-TEST",
            "name": "OB Test Member",
            "nik": "3171019999900009",
            "email": "obtest@koperasi.local",
        }, self.admin)

        record_opening_balance(mem_id, "POKOK", "1000000", "2024-01-01", "OB-TEST-1", "Test OB", self.admin)
        record_opening_balance(mem_id, "SUKARELA", "500000", "2024-01-01", "OB-TEST-2", "Test OB", self.admin)

        summary = get_member_savings_summary(mem_id, self.admin)
        self.assertEqual(to_decimal(summary["total_balance"]), Decimal("1500000.00"))

    # Criterion 12: Member Isolation (Object-level authorization)
    def test_12_member_isolation(self):
        with self.assertRaises(MemberAccessForbidden):
            get_member_by_id(2, self.member_andi)

        own_data = get_member_by_id(1, self.member_andi)
        self.assertEqual(own_data["member_number"], "MEM-001")

    # Criterion 13: Role Authorization
    def test_13_role_authorization(self):
        with self.assertRaises(MemberAccessForbidden):
            create_member_manual({"member_number": "MEM-FAIL", "name": "Fail", "nik": "123", "email": "f@f.com"}, self.member_andi)

    # Criterion 14: Manager Routing from Employee Hierarchy
    def test_14_manager_hierarchy_routing(self):
        app_res = apply_for_loan(
            member_id=1,
            amount_str="3000000",
            tenor_months=6,
            purpose="Kebutuhan Operasional Laptop",
            current_user=self.member_andi,
        )
        app_id = app_res["application_id"]
        with get_db() as conn:
            app_row = conn.execute("SELECT * FROM loan_applications WHERE id = ?", (app_id,)).fetchone()
            self.assertEqual(app_row["assigned_manager_id"], self.manager["id"])
            self.assertEqual(app_row["current_step"], "MANAGER")

    # Criterion 15: Maker-Checker Enforcement
    def test_15_maker_checker_enforcement(self):
        with get_db() as conn:
            app = conn.execute("SELECT id FROM loan_applications WHERE member_id = 1 AND status = 'SUBMITTED'").fetchone()

        with self.assertRaises(MakerCheckerViolation):
            process_approval(app["id"], "APPROVE", "Self approval attempt", self.member_andi)

    # Criterion 16: Complete Loan Lifecycle (Submit -> Manager -> Ketua -> Bendahara Disburse -> Active)
    def test_16_complete_loan_lifecycle(self):
        with get_db() as conn:
            app = conn.execute("SELECT id FROM loan_applications WHERE member_id = 1 AND status = 'SUBMITTED'").fetchone()
        app_id = app["id"]

        # Step 1: Manager Budi approves
        res1 = process_approval(app_id, "APPROVE", "Disetujui atasan", self.manager)
        self.assertEqual(res1["after_status"], "APPROVED_BY_MANAGER")
        self.assertEqual(res1["current_step"], "KETUA")

        # Step 2: Ketua approves
        res2 = process_approval(app_id, "APPROVE", "Disetujui Ketua", self.ketua)
        self.assertEqual(res2["after_status"], "WAITING_DISBURSEMENT")
        self.assertEqual(res2["current_step"], "BENDAHARA")

        # Step 3: Bendahara disburses
        disb_res = disburse_loan(app_id, self.bendahara)
        self.assertEqual(disb_res["status"], "DISBURSED")
        self.assertIsNotNone(disb_res["loan_id"])
        self.assertIsNotNone(disb_res["qr_token"])

        loan_detail = get_loan_details(disb_res["loan_id"], self.member_andi)
        self.assertEqual(loan_detail["loan"]["status"], "ACTIVE")
        self.assertEqual(len(loan_detail["installments"]), 6)

    # Criterion 17: Installment Idempotency
    def test_17_installment_idempotency(self):
        with get_db() as conn:
            loan = conn.execute("SELECT id FROM loans WHERE status = 'ACTIVE' ORDER BY id DESC LIMIT 1").fetchone()
            inst = conn.execute("SELECT * FROM loan_installments WHERE loan_id = ? AND status = 'PENDING' LIMIT 1", (loan["id"],)).fetchone()

        idemp_key = f"TEST-IDEMP-{inst['id']}"

        res1 = pay_loan_installment(inst["id"], inst["amount"], idemp_key, self.member_andi)
        self.assertEqual(res1["status"], "PAID")

        res2 = pay_loan_installment(inst["id"], inst["amount"], idemp_key, self.member_andi)
        self.assertTrue(res2.get("already_processed"))

    # Criterion 18: QR Token Verification and Revocation
    def test_18_qr_token_verification_and_revocation(self):
        doc = create_document_record("Surat Keputusan Uji", "SK_PINJAMAN", 1, "LOAN", "1", verifier_id=1)
        token = doc["token"]

        v1 = verify_document_token(token)
        self.assertTrue(v1["valid"])
        self.assertEqual(v1["status"], "VERIFIED")

        revoke_token(token, revoker_user_id=1)

        v2 = verify_document_token(token)
        self.assertFalse(v2["valid"])
        self.assertEqual(v2["status"], "REVOKED")

    # Criterion 19: Password Reset Security Lifecycle
    def test_19_password_reset_lifecycle(self):
        token = create_password_reset_token("superadmin@koperasi.local")
        self.assertIsNotNone(token)

        new_pwd = "SuperAdminNewPass123!"
        ok = reset_password(token, new_pwd)
        self.assertTrue(ok)

        with self.assertRaises(ValueError):
            reset_password(token, "AnotherPass123!")

        sess = authenticate_user("superadmin@koperasi.local", new_pwd)
        self.assertIsNotNone(sess["session_token"])

    # Criterion 20: Deactivated Account Login Prevention
    def test_20_deactivated_account_prevention(self):
        inv = create_user_invitation("temp.user2@koperasi.local", "Temp User 2", [ROLE_ANGGOTA], creator_user_id=1)
        accept_invitation(inv["token"], "TempPassword123!")

        change_user_status(inv["user_id"], "DEACTIVATED", actor_user_id=1)

        with self.assertRaises(AuthenticationError) as ctx:
            authenticate_user("temp.user2@koperasi.local", "TempPassword123!")
        self.assertIn("deactivated", str(ctx.exception).lower())

if __name__ == "__main__":
    unittest.main()
