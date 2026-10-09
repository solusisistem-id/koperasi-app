"""
Storage abstraction service for Koperasi Core.
Supports local filesystem (dev/test) and S3-compatible Object Storage (production Render/AWS/Cloudflare R2/MinIO).
"""
import os
import re
import secrets
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

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

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

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


class StorageService(ABC):
    """Abstract interface for document object storage."""

    @abstractmethod
    def upload(self, file_bytes: bytes, storage_key: str, mime_type: str) -> Dict[str, Any]:
        """Upload file content to storage backend."""
        pass

    @abstractmethod
    def download(self, storage_key: str) -> bytes:
        """Download file content from storage backend."""
        pass

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Delete file from storage backend."""
        pass

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Check if file exists in storage backend."""
        pass

    @abstractmethod
    def generate_signed_url(self, storage_key: str, expires_in_seconds: int = 3600) -> str:
        """Generate a temporary signed URL for viewing/downloading."""
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
        # In local development, return local document retrieval path
        safe_key = os.path.basename(storage_key)
        return f"/documents/download/{safe_key}"


class S3StorageService(StorageService):
    """
    S3-compatible Object Storage implementation for production Render environment.
    Supports AWS S3, Cloudflare R2, MinIO, and Google Cloud Storage S3 API.
    """

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
                raise RuntimeError(
                    "boto3 is required when STORAGE_BACKEND=s3. Please ensure boto3 is installed."
                )
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
    """Factory function returning the configured StorageService implementation."""
    global _storage_singleton
    if _storage_singleton is None:
        backend = (STORAGE_BACKEND or "local").lower()
        if backend == "s3":
            _storage_singleton = S3StorageService()
        else:
            _storage_singleton = LocalStorageService()
    return _storage_singleton
