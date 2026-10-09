"""
Document Management, Storage Abstraction, and QR Token Verification Service for Koperasi Core.
Hardened with Token Hashing (SHA-256), Revocation, Sensitive Data Minimization,
and Object Storage Abstraction (Local & S3-compatible: AWS S3, Cloudflare R2, MinIO, GCS).
"""
import os
import re
import secrets
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from app.database import get_db, execute_insert
from app.config import (
    UPLOADS_DIR,
    STORAGE_BACKEND,
    STORAGE_BUCKET,
    STORAGE_ENDPOINT,
    STORAGE_REGION,
    STORAGE_ACCESS_KEY,
    STORAGE_SECRET_KEY,
    APP_ENV,
)
from app.security import (
    generate_secure_token,
    generate_reference_number,
    hash_token,
    log_audit,
)

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

class DocumentError(Exception):
    pass

class StorageSecurityError(Exception):
    pass

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and special character exploitation."""
    base = os.path.basename(filename)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    if not safe:
        safe = f"file_{secrets.token_hex(4)}"
    return safe

def validate_file_upload(file_bytes: bytes, filename: str, mime_type: Optional[str] = None):
    """Validate file content, size limit, and extension whitelist."""
    if not file_bytes:
        raise StorageSecurityError("Berkas kosong tidak dapat diunggah.")
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise StorageSecurityError(f"Ukuran berkas melebihi batas maksimal {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.")
    safe_name = sanitize_filename(filename)
    _, ext = os.path.splitext(safe_name)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        raise StorageSecurityError(f"Ekstensi berkas '{ext}' tidak diizinkan. Hanya diizinkan: {', '.join(sorted(ALLOWED_EXTENSIONS))}")
    if chr(0) in filename:
        raise StorageSecurityError("Nama berkas terdeteksi tidak aman.")


# ==============================================================================
# Storage Service Interface & Implementations
# ==============================================================================

class StorageService(ABC):
    """Abstract interface for document object storage."""

    @abstractmethod
    def upload(self, file_bytes: bytes, storage_key: str, mime_type: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def download(self, storage_key: str) -> bytes:
        pass

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        pass

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        pass

    @abstractmethod
    def generate_signed_url(self, storage_key: str, expires_in_seconds: int = 3600) -> str:
        pass


class LocalStorageService(StorageService):
    """Local filesystem storage implementation for development and testing."""

    def __init__(self, base_dir: str = UPLOADS_DIR):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_path(self, storage_key: str) -> str:
        safe_key = os.path.basename(storage_key)
        return os.path.join(self.base_dir, safe_key)

    def upload(self, file_bytes: bytes, storage_key: str, mime_type: str) -> Dict[str, Any]:
        target_path = self._get_path(storage_key)
        with open(target_path, "wb") as f:
            f.write(file_bytes)
        return {
            "storage_key": storage_key,
            "storage_backend": "local",
            "file_size": len(file_bytes),
            "location": target_path,
        }

    def download(self, storage_key: str) -> bytes:
        path = self._get_path(storage_key)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Dokumen dengan storage_key '{storage_key}' tidak ditemukan.")
        with open(path, "rb") as f:
            return f.read()

    def delete(self, storage_key: str) -> bool:
        path = self._get_path(storage_key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def exists(self, storage_key: str) -> bool:
        return os.path.exists(self._get_path(storage_key))

    def generate_signed_url(self, storage_key: str, expires_in_seconds: int = 3600) -> str:
        safe_key = os.path.basename(storage_key)
        return f"/documents/download/{safe_key}"


class S3StorageService(StorageService):
    """S3-compatible Object Storage implementation for production Render."""

    def __init__(
        self,
        bucket: str = STORAGE_BUCKET,
        endpoint_url: Optional[str] = STORAGE_ENDPOINT,
        region_name: str = STORAGE_REGION,
        access_key_id: Optional[str] = STORAGE_ACCESS_KEY,
        secret_access_key: Optional[str] = STORAGE_SECRET_KEY,
    ):
        self.bucket = bucket
        self.endpoint_url = endpoint_url or None
        self.region_name = region_name or "auto"
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
                self._client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    region_name=self.region_name,
                    aws_access_key_id=self.access_key_id,
                    aws_secret_access_key=self.secret_access_key,
                    config=Config(signature_version="s3v4"),
                )
            except ImportError:
                raise RuntimeError("boto3 is required when STORAGE_BACKEND=s3.")
        return self._client

    def upload(self, file_bytes: bytes, storage_key: str, mime_type: str) -> Dict[str, Any]:
        client = self._get_client()
        client.put_object(
            Bucket=self.bucket,
            Key=storage_key,
            Body=file_bytes,
            ContentType=mime_type or "application/octet-stream",
        )
        return {
            "storage_key": storage_key,
            "storage_backend": "s3",
            "bucket": self.bucket,
            "file_size": len(file_bytes),
        }

    def download(self, storage_key: str) -> bytes:
        client = self._get_client()
        response = client.get_object(Bucket=self.bucket, Key=storage_key)
        return response["Body"].read()

    def delete(self, storage_key: str) -> bool:
        client = self._get_client()
        client.delete_object(Bucket=self.bucket, Key=storage_key)
        return True

    def exists(self, storage_key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except Exception:
            return False

    def generate_signed_url(self, storage_key: str, expires_in_seconds: int = 3600) -> str:
        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": storage_key},
            ExpiresIn=expires_in_seconds,
        )


_storage_singleton: Optional[StorageService] = None

def get_storage_service() -> StorageService:
    global _storage_singleton
    if _storage_singleton is None:
        backend = (STORAGE_BACKEND or "local").lower()
        if backend == "s3":
            _storage_singleton = S3StorageService()
        else:
            _storage_singleton = LocalStorageService()
    return _storage_singleton


# ==============================================================================
# Document & QR Records
# ==============================================================================

def create_document_record(
    title: str,
    document_type: str,
    owner_user_id: int,
    reference_type: str,
    reference_id: str,
    verifier_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a verified document record and issue a random verification token stored as hash."""
    with get_db() as conn:
        doc_num = generate_reference_number("DOC")
        doc_id = execute_insert(
            conn,
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

        raw_token = generate_secure_token(24)
        token_digest = hash_token(raw_token)
        token_display = f"{raw_token[:4]}...{raw_token[-4:]}"

        conn.execute(
            """
            INSERT INTO qr_verification_tokens (token_hash, token_display, document_id, is_revoked, created_at)
            VALUES (?, ?, ?, 0, datetime('now'))
            """,
            (token_digest, token_display, doc_id),
        )

        return {
            "document_id": doc_id,
            "document_number": doc_num,
            "title": title,
            "token": raw_token,
            "token_hash": token_digest,
            "verification_url": f"/verify/{raw_token}",
        }

def verify_document_token(token: str, ip_address: Optional[str] = None) -> Dict[str, Any]:
    """
    Public server-side verification of a QR token.
    Checks token hash against database. Never logs raw token into audit logs.
    """
    token_digest = hash_token(token) if token else ""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT qr.id as qr_id, qr.token_hash, qr.is_revoked, qr.revoked_at,
                   d.id as doc_id, d.document_number, d.title, d.document_type,
                   d.reference_type, d.reference_id, d.verification_status, d.verified_at,
                   u.full_name as verifier_name
            FROM qr_verification_tokens qr
            JOIN documents d ON qr.document_id = d.id
            LEFT JOIN users u ON d.verified_by = u.id
            WHERE qr.token_hash = ?
            """,
            (token_digest,),
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
                before_state={"token_hash": token_digest[:8] + "...", "result": "REVOKED"},
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
            after_state={"token_hash": token_digest[:8] + "...", "result": "VERIFIED"},
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
    """Revoke a QR verification token and associated document."""
    token_digest = hash_token(token) if token else ""
    with get_db() as conn:
        row = conn.execute(
            "SELECT qr.id, qr.document_id FROM qr_verification_tokens qr WHERE qr.token_hash = ?",
            (token_digest,),
        ).fetchone()

        if not row:
            raise DocumentError("Token tidak ditemukan.")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
            after_state={"action": "REVOKED", "token_hash": token_digest[:8] + "..."},
            result="SUCCESS",
        )
        return True


def save_document(
    file_bytes: bytes,
    original_filename: str,
    mime_type: str,
    owner_user_id: int,
    entity_type: str = "DOCUMENT",
    entity_id: str = "0",
) -> Dict[str, Any]:
    """Validate, generate secure storage key, and upload document to storage backend."""
    validate_file_upload(file_bytes, original_filename, mime_type)
    safe_name = sanitize_filename(original_filename)
    _, ext = os.path.splitext(safe_name)
    storage_key = f"{secrets.token_hex(16)}{ext.lower()}"

    storage = get_storage_service()
    res = storage.upload(file_bytes, storage_key, mime_type)

    return {
        "storage_key": storage_key,
        "file_name": safe_name,
        "file_size": len(file_bytes),
        "mime_type": mime_type or "application/octet-stream",
        "location": res.get("location") or storage_key,
        "storage_backend": res.get("storage_backend", "local"),
    }

def get_document(storage_key: str) -> bytes:
    """Retrieve document bytes from configured storage service."""
    storage = get_storage_service()
    return storage.download(storage_key)

def delete_document(storage_key: str) -> bool:
    """Delete document from storage backend."""
    storage = get_storage_service()
    return storage.delete(storage_key)
