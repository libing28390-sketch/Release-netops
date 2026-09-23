"""Provider-neutral blob storage for recordings and configuration snapshots.

The application stores metadata in PostgreSQL and delegates blob I/O to one
explicit backend selected by ``STORAGE_BACKEND``.  The local provider and the
S3 provider intentionally share the same object-key contract so the business
APIs do not need to know whether SeaweedFS, another S3-compatible service, or
the local filesystem is in use.

This module is synchronous by design.  Callers that run inside async routes
must use ``asyncio.to_thread`` (or an existing worker) around the blocking
methods.  There is deliberately no runtime fallback from S3 to local storage;
the local files used while a recording is in progress are explicit spool data.
"""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator


class StorageError(RuntimeError):
    """Base error for a failed storage operation."""


class StorageNotFound(StorageError):
    """Raised when an object does not exist."""


@dataclass(frozen=True)
class StorageObject:
    backend: str
    bucket: str | None
    object_key: str
    version_id: str | None = None
    size: int = 0
    sha256: str | None = None
    content_type: str | None = None
    etag: str | None = None


StorageObjectMeta = StorageObject


def normalize_object_key(value: object) -> str:
    """Return a safe, portable object key and reject traversal attempts."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw:
        raise ValueError("Object key must be non-empty and contain no NUL bytes")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError("Absolute object keys are not allowed")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("Object key traversal is not allowed")
    return "/".join(parts)


def _binary_stream(value: BinaryIO | bytes | bytearray | memoryview) -> BinaryIO:
    if isinstance(value, bytes):
        return io.BytesIO(value)
    if isinstance(value, (bytearray, memoryview)):
        return io.BytesIO(bytes(value))
    if not hasattr(value, "read"):
        raise TypeError("Storage upload requires a binary stream or bytes")
    return value  # type: ignore[return-value]


def _materialize_stream(value: BinaryIO | bytes | bytearray | memoryview) -> tuple[tempfile.SpooledTemporaryFile, int, str]:
    """Spool a stream once so every provider gets size and SHA-256 metadata."""

    source = _binary_stream(value)
    digest = hashlib.sha256()
    size = 0
    handle = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray, memoryview)):
                raise TypeError("Storage upload stream must return bytes")
            chunk_bytes = bytes(chunk)
            handle.write(chunk_bytes)
            digest.update(chunk_bytes)
            size += len(chunk_bytes)
        handle.seek(0)
        return handle, size, digest.hexdigest()
    except Exception:
        handle.close()
        raise


class StorageBackend:
    """Small synchronous interface shared by local and S3 providers."""

    name = "unknown"

    def put_stream(
        self,
        key: str,
        stream: BinaryIO | bytes | bytearray | memoryview,
        content_type: str | None = None,
    ) -> StorageObject:
        raise NotImplementedError

    def get_stream(self, key: str) -> BinaryIO:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def stat(self, key: str) -> StorageObjectMeta:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        try:
            self.stat(key)
            return True
        except StorageNotFound:
            return False

    def health_check(self) -> tuple[bool, str]:
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    """Atomic filesystem provider rooted at one configured directory."""

    name = "local"

    def __init__(self, root: str | os.PathLike[str], bucket: str | None = None):
        self.root = Path(root).expanduser().resolve()
        self.bucket = bucket

    def _path(self, key: str) -> Path:
        normalized = normalize_object_key(key)
        candidate = (self.root / Path(*normalized.split("/"))).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Object key resolves outside the local storage root") from exc
        return candidate

    def put_stream(
        self,
        key: str,
        stream: BinaryIO | bytes | bytearray | memoryview,
        content_type: str | None = None,
    ) -> StorageObject:
        normalized = normalize_object_key(key)
        destination = self._path(normalized)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        digest = hashlib.sha256()
        size = 0
        source = _binary_stream(stream)
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".storage-upload-",
                suffix=".tmp",
                dir=str(destination.parent),
                delete=False,
            ) as handle:
                temporary_name = handle.name
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("Storage upload stream must return bytes")
                    chunk_bytes = bytes(chunk)
                    handle.write(chunk_bytes)
                    digest.update(chunk_bytes)
                    size += len(chunk_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
        return StorageObject(
            backend=self.name,
            bucket=self.bucket,
            object_key=normalized,
            size=size,
            sha256=digest.hexdigest(),
            content_type=content_type,
            etag=digest.hexdigest(),
        )

    def get_stream(self, key: str) -> BinaryIO:
        path = self._path(key)
        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise StorageNotFound(normalize_object_key(key)) from exc

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        # Remove empty parents without ever removing the configured root.
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def stat(self, key: str) -> StorageObjectMeta:
        normalized = normalize_object_key(key)
        path = self._path(normalized)
        try:
            size = path.stat().st_size
        except FileNotFoundError as exc:
            raise StorageNotFound(normalized) from exc
        return StorageObject(
            backend=self.name,
            bucket=self.bucket,
            object_key=normalized,
            size=size,
        )

    def health_check(self) -> tuple[bool, str]:
        try:
            if not self.root.exists():
                return False, "Storage directory does not exist"
            if not self.root.is_dir():
                return False, "Storage path is not a directory"
            if not os.access(self.root, os.W_OK):
                return False, "Storage directory is not writable"
            return True, "Local storage is ready"
        except OSError as exc:
            return False, f"Local storage check failed: {type(exc).__name__}"


class S3StorageBackend(StorageBackend):
    """S3-compatible provider, including SeaweedFS ``weed mini``."""

    name = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        region: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
        force_path_style: bool = True,
        verify_tls: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ):
        if not endpoint_url.strip():
            raise StorageError("S3 endpoint is not configured")
        if not bucket.strip():
            raise StorageError("S3 bucket is not configured")
        self.endpoint_url = endpoint_url.strip().rstrip("/")
        self.bucket = bucket.strip()
        self.region = region.strip() or "us-east-1"
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.force_path_style = bool(force_path_style)
        self.verify_tls = verify_tls
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self._client_instance = None

    def _client(self):
        if self._client_instance is not None:
            return self._client_instance
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise StorageError("boto3 is required when STORAGE_BACKEND=s3") from exc
        self._client_instance = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key_id or None,
            aws_secret_access_key=self.secret_access_key or None,
            verify=self.verify_tls,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if self.force_path_style else "auto"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=self.connect_timeout,
                read_timeout=self.read_timeout,
            ),
        )
        return self._client_instance

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        response = getattr(exc, "response", {}) or {}
        error = response.get("Error", {}) if isinstance(response, dict) else {}
        return str(error.get("Code", "")) in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}

    def put_stream(
        self,
        key: str,
        stream: BinaryIO | bytes | bytearray | memoryview,
        content_type: str | None = None,
    ) -> StorageObject:
        normalized = normalize_object_key(key)
        handle, size, digest = _materialize_stream(stream)
        try:
            extra_args = {"ContentType": content_type} if content_type else {}
            from boto3.s3.transfer import TransferConfig

            self._client().upload_fileobj(
                handle,
                self.bucket,
                normalized,
                ExtraArgs=extra_args,
                Config=TransferConfig(use_threads=False),
            )
            metadata = self.stat(normalized)
            return StorageObject(
                backend=self.name,
                bucket=self.bucket,
                object_key=normalized,
                version_id=metadata.version_id,
                size=size,
                sha256=digest,
                content_type=content_type or metadata.content_type,
                etag=metadata.etag,
            )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"S3 upload failed: {type(exc).__name__}") from exc
        finally:
            handle.close()

    def get_stream(self, key: str) -> BinaryIO:
        normalized = normalize_object_key(key)
        try:
            return self._client().get_object(Bucket=self.bucket, Key=normalized)["Body"]
        except Exception as exc:
            if self._is_not_found(exc):
                raise StorageNotFound(normalized) from exc
            raise StorageError(f"S3 download failed: {type(exc).__name__}") from exc

    def delete(self, key: str) -> None:
        normalized = normalize_object_key(key)
        try:
            self._client().delete_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:
            raise StorageError(f"S3 delete failed: {type(exc).__name__}") from exc

    def stat(self, key: str) -> StorageObjectMeta:
        normalized = normalize_object_key(key)
        try:
            response = self._client().head_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:
            if self._is_not_found(exc):
                raise StorageNotFound(normalized) from exc
            raise StorageError(f"S3 stat failed: {type(exc).__name__}") from exc
        return StorageObject(
            backend=self.name,
            bucket=self.bucket,
            object_key=normalized,
            version_id=response.get("VersionId"),
            size=int(response.get("ContentLength") or 0),
            content_type=response.get("ContentType"),
            etag=str(response.get("ETag") or "").strip('"') or None,
        )

    def health_check(self) -> tuple[bool, str]:
        try:
            self._client().list_objects_v2(Bucket=self.bucket, MaxKeys=1)
            return True, "S3-compatible storage is ready"
        except Exception as exc:
            return False, f"S3 storage check failed: {type(exc).__name__}"


class StorageService:
    """Business-facing facade over one explicitly selected provider."""

    def __init__(self, backend: StorageBackend):
        self.backend = backend

    @property
    def name(self) -> str:
        return self.backend.name

    def put_stream(self, key: str, stream, content_type: str | None = None) -> StorageObject:
        return self.backend.put_stream(key, stream, content_type)

    def get_stream(self, key: str):
        return self.backend.get_stream(key)

    def delete(self, key: str) -> None:
        return self.backend.delete(key)

    def stat(self, key: str) -> StorageObjectMeta:
        return self.backend.stat(key)

    def exists(self, key: str) -> bool:
        return self.backend.exists(key)

    def health_check(self) -> tuple[bool, str]:
        return self.backend.health_check()


def build_storage_service(*, backend_name: str | None = None, bucket: str | None = None) -> StorageService:
    """Build the provider selected by the deployment configuration."""

    from core.config import settings

    backend_name = str(backend_name or settings.STORAGE_BACKEND or "local").strip().lower()
    if backend_name == "local":
        return StorageService(LocalStorageBackend(settings.STORAGE_LOCAL_ROOT, bucket=bucket or None))
    if backend_name == "s3":
        return StorageService(
            S3StorageBackend(
                endpoint_url=settings.S3_ENDPOINT_URL,
                bucket=bucket or settings.S3_BUCKET,
                region=settings.S3_REGION,
                access_key_id=settings.S3_ACCESS_KEY_ID,
                secret_access_key=settings.S3_SECRET_ACCESS_KEY,
                force_path_style=settings.S3_FORCE_PATH_STYLE,
                verify_tls=settings.S3_VERIFY_TLS,
                connect_timeout=settings.S3_CONNECT_TIMEOUT_SECONDS,
                read_timeout=settings.S3_READ_TIMEOUT_SECONDS,
            )
        )
    raise StorageError(f"Unsupported STORAGE_BACKEND: {backend_name}")


def iter_stream(stream, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield chunks and close a provider stream when iteration completes."""

    try:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        close = getattr(stream, "close", None)
        if close:
            close()


__all__ = [
    "LocalStorageBackend",
    "S3StorageBackend",
    "StorageBackend",
    "StorageError",
    "StorageNotFound",
    "StorageObject",
    "StorageObjectMeta",
    "StorageService",
    "build_storage_service",
    "iter_stream",
    "normalize_object_key",
]
