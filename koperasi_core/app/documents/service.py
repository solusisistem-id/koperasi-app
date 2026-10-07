"""
Document Management and QR Token Verification Service for Koperasi Core.
Generates server-side verifiable random tokens and supports revocation.
"""
from typing import Dict, Any, Optional
from datetime import datetime

from app.database import get_db
from app.security import generate_secure_token, generate_reference_number, log_audit

class DocumentError(Exception):
    pass

def create_document_record(
    title: str,
    document_type: str,
    owner_user_id: int,
    reference_type: str,
    reference_id: str,
    verifier_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a verified document record and issue a random verification token."""
    with get_db() as conn:
        doc_num = generate_reference_number("DOC")
        cur_d = conn.execute(
            """
            INSERT INTO documents (
                document_number, title, document_type, owner_user_id, reference_type,
                reference_id, storage_key, verification_status, verified_by, verified_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'VERIFIED', ?, datetime('now'), datetime('now'))
            """,
            (
                doc_num,
                title,
                document_type,
                owner_user_id,
                reference_type,
                reference_id,
                generate_secure_token(16),
                verifier_id,
            ),
        )
        doc_id = cur_d.lastrowid

        token = generate_secure_token(24)
        conn.execute(
            """
            INSERT INTO qr_verification_tokens (token, document_id, is_revoked, created_at)
            VALUES (?, ?, 0, datetime('now'))
            """,
            (token, doc_id),
        )

        return {
            "document_id": doc_id,
            "document_number": doc_num,
            "title": title,
            "token": token,
            "verification_url": f"/verify/{token}",
        }

def verify_document_token(token: str, ip_address: Optional[str] = None) -> Dict[str, Any]:
    """
    Public server-side verification of a QR token.
    Checks if token exists, whether it is revoked, and returns server truth.
    """
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT qr.id as qr_id, qr.token, qr.is_revoked, qr.revoked_at,
                   d.id as doc_id, d.document_number, d.title, d.document_type,
                   d.reference_type, d.reference_id, d.verification_status, d.verified_at,
                   u.full_name as verifier_name
            FROM qr_verification_tokens qr
            JOIN documents d ON qr.document_id = d.id
            LEFT JOIN users u ON d.verified_by = u.id
            WHERE qr.token = ?
            """,
            (token,),
        ).fetchone()

        if not row:
            return {
                "valid": False,
                "reason": "Token verifikasi dokumen tidak ditemukan atau tidak valid.",
                "status": "NOT_FOUND",
            }

        if row["is_revoked"] or row["verification_status"] == "REVOKED":
            log_audit(
                conn,
                actor_id=None,
                actor_name="PUBLIC_VERIFIER",
                actor_role="ANONYMOUS",
                action="QR_VERIFIED",
                entity="documents",
                entity_id=str(row["doc_id"]),
                before_state={"token": token, "result": "REVOKED"},
                result="FAILURE",
                ip_address=ip_address,
            )
            return {
                "valid": False,
                "reason": "Dokumen ini telah dicabut (REVOKED) oleh pihak Koperasi.",
                "status": "REVOKED",
                "revoked_at": row["revoked_at"],
            }

        log_audit(
            conn,
            actor_id=None,
            actor_name="PUBLIC_VERIFIER",
            actor_role="ANONYMOUS",
            action="QR_VERIFIED",
            entity="documents",
            entity_id=str(row["doc_id"]),
            after_state={"token": token, "result": "VERIFIED"},
            result="SUCCESS",
            ip_address=ip_address,
        )

        return {
            "valid": True,
            "status": "VERIFIED",
            "document_number": row["document_number"],
            "title": row["title"],
            "document_type": row["document_type"],
            "verified_at": row["verified_at"],
            "verifier_name": row["verifier_name"] or "Sistem Koperasi Core",
        }

def revoke_token(token: str, revoker_user_id: int) -> bool:
    """Revoke a QR verification token and document."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT qr.id, qr.document_id FROM qr_verification_tokens qr WHERE qr.token = ?",
            (token,),
        ).fetchone()

        if not row:
            raise DocumentError("Token tidak ditemukan.")

        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE qr_verification_tokens SET is_revoked = 1, revoked_at = ?, revoked_by = ? WHERE id = ?",
            (now_str, revoker_user_id, row["id"]),
        )
        conn.execute(
            "UPDATE documents SET verification_status = 'REVOKED' WHERE id = ?",
            (row["document_id"],),
        )

        revoker = conn.execute("SELECT full_name FROM users WHERE id = ?", (revoker_user_id,)).fetchone()
        log_audit(
            conn,
            actor_id=revoker_user_id,
            actor_name=revoker["full_name"] if revoker else "ADMIN",
            actor_role="ADMIN",
            action="DOCUMENT_VERIFIED",
            entity="documents",
            entity_id=str(row["document_id"]),
            after_state={"action": "REVOKED", "token": token},
            result="SUCCESS",
        )
        return True
