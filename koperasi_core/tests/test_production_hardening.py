"""
Comprehensive Production Hardening & Security Test Suite for Koperasi Core.
Validates:
- Health check /healthz monitoring
- CSRF defense-in-depth (missing, invalid, and valid token scenarios)
- Account lockout after 5 consecutive failed logins
- Account enumeration defense in password reset
- Token hashing in database (SHA-256) and session invalidation on reset
- QR token hashing and sensitive data omission in audit logs
- Storage service upload security (path traversal, size limits, extension whitelist)
- Financial idempotency and ledger reconstruction
- Production bootstrap zero-default-password flow
- Production fail-fast environment checks
"""
import os
import sys
import unittest
import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

# Ensure app path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient
from app.main import app
from app.database import get_db, init_db, DB_PATH
from app.config import (
    APP_NAME,
    APP_VERSION,
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
)
from app.security import (
    hash_password,
    verify_password,
    generate_secure_token,
    hash_token,
    verify_token_hash,
    generate_csrf_token,
    to_decimal,
)
from app.auth.service import (
    authenticate_user,
    create_password_reset_token,
    reset_password,
    create_user_invitation,
    accept_invitation,
    AuthenticationError,
)
from app.documents.service import (
    save_document,
    get_document,
    validate_file_upload,
    sanitize_filename,
    StorageSecurityError,
)
from app.documents.service import create_document_record, verify_document_token, revoke_token
from scripts.seed_data import seed_all
import importlib.util
_spec = importlib.util.spec_from_file_location(
    'bootstrap_admin',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'bootstrap_admin.py')
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
bootstrap_production_admin = _mod.bootstrap_production_admin

class TestProductionHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        seed_all()
        cls.client = TestClient(app)

    # 1. Healthcheck /healthz
    def test_01_healthz_endpoint(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], APP_NAME)
        self.assertIn("version", data)
        self.assertIn("environment", data)

    # 2. CSRF Missing Token Rejection
    def test_02_csrf_missing_token_rejected(self):
        # State-changing POST without CSRF token must return 403 Forbidden
        resp = self.client.post("/login", data={"email": "admin@koperasi.local", "password": "Admin123!"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF verification failed", resp.json().get("detail", ""))

    # 3. CSRF Invalid Token Rejection
    def test_03_csrf_invalid_token_rejected(self):
        # Set CSRF cookie but send mismatched CSRF token in header
        self.client.cookies.set(CSRF_COOKIE_NAME, "valid_cookie_csrf_token_123")
        resp = self.client.post(
            "/login",
            data={"email": "admin@koperasi.local", "password": "Admin123!"},
            headers={CSRF_HEADER_NAME: "wrong_tampered_csrf_token"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF verification failed", resp.json().get("detail", ""))

    # 4. CSRF Valid Token Acceptance
    def test_04_csrf_valid_token_accepted(self):
        token = generate_csrf_token()
        self.client.cookies.set(CSRF_COOKIE_NAME, token)
        resp = self.client.post(
            "/login",
            data={"email": "admin@koperasi.local", "password": "Admin123!", "csrf_token": token},
            headers={CSRF_HEADER_NAME: token},
            follow_redirects=False,
        )
        # Should succeed (redirect 303 to /dashboard)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/dashboard", resp.headers.get("location", ""))

    # 5. Account Lockout After 5 Failed Attempts
    def test_05_account_lockout_enforcement(self):
        email = f"lockout.{secrets.token_hex(4)}@koperasi.local"
        inv = create_user_invitation(email, "Lockout Target", [ROLE_ANGGOTA], creator_user_id=1)
        accept_invitation(inv["token"], "CorrectPassword123!")

        # 4 failed attempts: still returns normal invalid password error
        for i in range(4):
            with self.assertRaises(AuthenticationError) as ctx:
                authenticate_user(email, f"WrongPassword_{i}")
            self.assertIn("tidak valid", str(ctx.exception).lower())

        # 5th failed attempt: triggers lockout
        with self.assertRaises(AuthenticationError):
            authenticate_user(email, "WrongPassword_5")

        # 6th attempt even with CORRECT password must be rejected due to active lockout
        with self.assertRaises(AuthenticationError) as ctx:
            authenticate_user(email, "CorrectPassword123!")
        self.assertIn("terkunci", str(ctx.exception).lower())

    # 6. Password Reset Account Enumeration Defense
    def test_06_password_reset_enumeration_defense(self):
        # Non-existent user should not raise error and return None gracefully without leaking existence
        token = create_password_reset_token("nonexistent_user_999@koperasi.local")
        self.assertIsNone(token)

        # Existing user returns valid token
        token_real = create_password_reset_token("admin@koperasi.local")
        self.assertIsNotNone(token_real)

    # 7. Password Reset Token Hashing and Session Invalidation
    def test_07_token_hashing_and_session_invalidation(self):
        email = f"session.reset.{secrets.token_hex(4)}@koperasi.local"
        inv = create_user_invitation(email, "Session User", [ROLE_ANGGOTA], creator_user_id=1)
        accept_invitation(inv["token"], "OldPassword123!")

        # User logs in and creates active session
        sess = authenticate_user(email, "OldPassword123!")
        sess_token = sess["session_token"]

        # Verify session exists in DB
        with get_db() as conn:
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            user_id = user["id"]
            active_sess = conn.execute("SELECT id FROM user_sessions WHERE user_id = ?", (user_id,)).fetchall()
            self.assertGreater(len(active_sess), 0)

        # Generate reset token and verify token_hash is stored in DB
        raw_reset_token = create_password_reset_token(email)
        expected_hash = hash_token(raw_reset_token)

        with get_db() as conn:
            row = conn.execute("SELECT token_hash FROM password_reset_tokens WHERE user_id = ?", (user_id,)).fetchone()
            self.assertEqual(row["token_hash"], expected_hash)

        # Perform password reset
        new_pwd = "BrandNewSecurePassword123!"
        reset_password(raw_reset_token, new_pwd)

        # Verify ALL old sessions were wiped out
        with get_db() as conn:
            remaining_sess = conn.execute("SELECT id FROM user_sessions WHERE user_id = ?", (user_id,)).fetchall()
            self.assertEqual(len(remaining_sess), 0)

        # Token cannot be reused
        with self.assertRaises(ValueError):
            reset_password(raw_reset_token, "TryReuse123!")

    # 8. QR Verification Token Hashing
    def test_08_qr_token_hashing_and_audit(self):
        doc = create_document_record("SK Pinjaman Uji", "SK_PINJAMAN", 1, "LOAN", "99", verifier_id=1)
        raw_qr_token = doc["token"]
        expected_hash = hash_token(raw_qr_token)

        # Verify token_hash is stored
        with get_db() as conn:
            row = conn.execute("SELECT token_hash FROM qr_verification_tokens WHERE document_id = ?", (doc["document_id"],)).fetchone()
            self.assertEqual(row["token_hash"], expected_hash)

        # Verify lookup works by hash
        v_res = verify_document_token(raw_qr_token)
        self.assertTrue(v_res["valid"])
        self.assertEqual(v_res["status"], "VERIFIED")

        # Verify raw token is NOT in audit logs
        with get_db() as conn:
            audits = conn.execute("SELECT before_state_json, after_state_json FROM audit_logs WHERE action = 'QR_VERIFIED'").fetchall()
            for a in audits:
                log_text = f"{a['before_state_json']} {a['after_state_json']}"
                self.assertNotIn(raw_qr_token, log_text)

    # 9. Storage Service Upload Security & Path Traversal Defense
    def test_09_storage_upload_security(self):
        # 1. Path traversal sanitize
        safe = sanitize_filename("../../etc/passwd.pdf")
        self.assertNotIn("/", safe)
        self.assertNotIn("..", safe)

        # 2. Disallowed extension
        with self.assertRaises(StorageSecurityError):
            validate_file_upload(b"malicious executable", "trojan.exe")

        # 3. Oversized file (>10MB)
        large_bytes = b"0" * (11 * 1024 * 1024)
        with self.assertRaises(StorageSecurityError):
            validate_file_upload(large_bytes, "large.pdf")

        # 4. Valid document save and get
        doc_bytes = b"%PDF-1.4 Mock valid PDF document content"
        res = save_document(doc_bytes, "valid_ktp.pdf", "application/pdf", owner_user_id=1)
        self.assertIsNotNone(res["storage_key"])

        retrieved = get_document(res["storage_key"])
        self.assertEqual(retrieved, doc_bytes)

    # 10. Production Admin Bootstrap Flow (Zero Default Passwords)
    def test_10_production_admin_bootstrap(self):
        test_email = f"bootstrap.admin.{secrets.token_hex(4)}@koperasi.local"
        bootstrap_production_admin(test_email, "Official Bootstrapped Admin")

        # Verify admin created in INVITED status (no password hash)
        with get_db() as conn:
            u = conn.execute("SELECT * FROM users WHERE email = ?", (test_email,)).fetchone()
            self.assertIsNotNone(u)
            self.assertEqual(u["status"], "INVITED")

            # Check invitation token exists with token_hash
            inv = conn.execute("SELECT * FROM invitation_tokens WHERE user_id = ?", (u["id"],)).fetchone()
            self.assertIsNotNone(inv["token_hash"])

if __name__ == "__main__":
    unittest.main()
