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
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Iterator


@dataclass(frozen=True)
class StorageProviderConfig:
    """Resolved storage provider settings without exposing persisted secrets."""

    id: str | None
    name: str
    backend: str
    endpoint_url: str
    bucket: str
    region: str
    access_key_id: str
    secret_access_key: str
    force_path_style: bool
    verify_tls: bool
    is_default: bool = False
    notes: str = ""
    source: str = "environment"
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class StorageUsageBinding:
    purpose: str
    provider_mode: str
    provider_id: str | None
    bucket_override: str | None
    key_prefix: str
    updated_at: str = ""


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
    storage_config_id: str | None = None


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
        # A missing bucket is a provider/configuration failure, not a missing
        # object. Preserve it as StorageError so callers do not report a valid
        # PAM/config object as a user-facing 404.
        code = str(error.get("Code", ""))
        if code == "NoSuchBucket":
            return False
        return code in {"404", "NoSuchKey", "NotFound"}

    @staticmethod
    def _safe_error_detail(exc: Exception) -> str:
        """Return an S3 error code/status without provider-controlled text."""
        response = getattr(exc, "response", None)
        error = response.get("Error") if isinstance(response, dict) else None
        code = error.get("Code") if isinstance(error, dict) else None
        metadata = response.get("ResponseMetadata") if isinstance(response, dict) else None
        status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
        safe_code = (
            str(code)
            if isinstance(code, (str, int))
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(code))
            else None
        )
        safe_status = status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else None
        if safe_code and safe_status:
            return f"{safe_code} (HTTP {safe_status})"
        if safe_code:
            return safe_code
        if safe_status:
            return f"HTTP {safe_status}"
        return type(exc).__name__

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
            raise StorageError(f"S3 upload failed: {self._safe_error_detail(exc)}") from exc
        finally:
            handle.close()

    def get_stream(self, key: str) -> BinaryIO:
        normalized = normalize_object_key(key)
        try:
            return self._client().get_object(Bucket=self.bucket, Key=normalized)["Body"]
        except Exception as exc:
            if self._is_not_found(exc):
                raise StorageNotFound(normalized) from exc
            raise StorageError(f"S3 download failed: {self._safe_error_detail(exc)}") from exc

    def delete(self, key: str) -> None:
        normalized = normalize_object_key(key)
        try:
            self._client().delete_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:
            raise StorageError(f"S3 delete failed: {self._safe_error_detail(exc)}") from exc

    def stat(self, key: str) -> StorageObjectMeta:
        normalized = normalize_object_key(key)
        try:
            response = self._client().head_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:
            if self._is_not_found(exc):
                raise StorageNotFound(normalized) from exc
            raise StorageError(f"S3 stat failed: {self._safe_error_detail(exc)}") from exc
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
            # S3 ClientError messages can contain provider-controlled text. Only
            # surface a compact code and numeric status; never return the raw
            # exception or response body, which may contain sensitive details.
            return False, f"S3 storage check failed: {self._safe_error_detail(exc)}"


class StorageService:
    """Business-facing facade over one explicitly selected provider."""

    def __init__(
        self,
        backend: StorageBackend,
        *,
        storage_config_id: str | None = None,
        key_prefix: str = "",
        purpose: str | None = None,
    ):
        self.backend = backend
        self.storage_config_id = storage_config_id
        self.key_prefix = normalize_relative_prefix(key_prefix)
        self.purpose = purpose

    @property
    def name(self) -> str:
        return self.backend.name

    @property
    def bucket(self) -> str:
        return str(getattr(self.backend, "bucket", "") or "")

    def full_key(self, key: str) -> str:
        normalized = normalize_object_key(key)
        if not self.key_prefix:
            return normalized
        return normalize_object_key(f"{self.key_prefix}/{normalized}")

    def put_stream(self, key: str, stream, content_type: str | None = None) -> StorageObject:
        stored = self.backend.put_stream(self.full_key(key), stream, content_type)
        return replace(stored, storage_config_id=self.storage_config_id)

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


def _environment_provider() -> StorageProviderConfig:
    from core.config import settings

    backend = str(settings.STORAGE_BACKEND or "local").strip().lower()
    return StorageProviderConfig(
        # The environment profile is virtual and must never be persisted as a
        # foreign-key value on object rows.
        id=None,
        name="Environment",
        backend=backend,
        endpoint_url=str(settings.S3_ENDPOINT_URL or ""),
        bucket=str(settings.S3_BUCKET or ""),
        # SigV4 requires a signing region; keep the S3-compatible default
        # internal instead of exposing an unnecessary deployment variable.
        region="us-east-1",
        access_key_id=str(settings.S3_ACCESS_KEY_ID or ""),
        secret_access_key=str(settings.S3_SECRET_ACCESS_KEY or ""),
        force_path_style=bool(settings.S3_FORCE_PATH_STYLE),
        verify_tls=bool(settings.S3_VERIFY_TLS),
        source="environment",
    )


def _row_value(row, name: str, default=None):
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return default


def _database_provider(provider_id: str) -> StorageProviderConfig:
    if provider_id == "environment":
        return _environment_provider()
    try:
        from core.crypto import decrypt_credential
        from database import get_db_connection

        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM storage_provider_configs WHERE id = ?", (provider_id,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        raise StorageError("Storage provider configuration is unavailable") from exc
    if not row:
        raise StorageError("Storage provider configuration was not found")
    encrypted_access_key = str(_row_value(row, "access_key_id_encrypted", "") or "")
    encrypted_secret_key = str(_row_value(row, "secret_access_key_encrypted", "") or "")
    try:
        access_key = decrypt_credential(encrypted_access_key)
        secret_key = decrypt_credential(encrypted_secret_key)
    except Exception as exc:
        raise StorageError("Storage provider credentials could not be decrypted") from exc
    if (encrypted_access_key and access_key is None) or (encrypted_secret_key and secret_key is None):
        raise StorageError("Storage provider credentials could not be decrypted")
    if not str(access_key or "").strip() or not str(secret_key or "").strip():
        raise StorageError("Storage provider credentials are not configured")
    return StorageProviderConfig(
        id=str(_row_value(row, "id", provider_id)),
        name=str(_row_value(row, "name", "")),
        backend=str(_row_value(row, "backend", "s3") or "s3").strip().lower(),
        endpoint_url=str(_row_value(row, "endpoint_url", "") or ""),
        bucket=str(_row_value(row, "bucket", "") or ""),
        region=str(_row_value(row, "region", "us-east-1") or "us-east-1"),
        access_key_id=access_key,
        secret_access_key=secret_key,
        force_path_style=bool(_row_value(row, "force_path_style", True)),
        verify_tls=bool(_row_value(row, "verify_tls", True)),
        is_default=bool(_row_value(row, "is_default", False)),
        notes=str(_row_value(row, "notes", "") or ""),
        source="database",
        created_at=str(_row_value(row, "created_at", "") or ""),
        updated_at=str(_row_value(row, "updated_at", "") or ""),
    )


def list_storage_provider_configs(*, include_environment: bool = False) -> list[StorageProviderConfig]:
    """Return database profiles, with the environment profile when applicable."""
    from core.config import settings
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM storage_provider_configs ORDER BY is_default DESC, name ASC"
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        raise StorageError("Storage provider configuration is unavailable") from exc
    profiles = [
        _database_provider(str(_row_value(row, "id", "")))
        for row in rows
    ]
    if str(settings.STORAGE_BACKEND or "").lower() == "s3":
        profiles.append(_environment_provider())
    return profiles


def effective_storage_provider() -> StorageProviderConfig:
    profiles = list_storage_provider_configs()
    for profile in profiles:
        if profile.source == "database" and profile.is_default:
            return profile
    return _environment_provider()


def get_storage_provider_config(provider_id: str) -> StorageProviderConfig:
    return _database_provider(str(provider_id or "").strip())


def resolve_storage_usage(purpose: str) -> tuple[StorageUsageBinding, StorageProviderConfig]:
    binding = _load_storage_usage(str(purpose).strip())
    if binding.provider_mode == "profile":
        profile = _database_provider(str(binding.provider_id))
    elif binding.provider_mode == "environment":
        profile = _environment_provider()
    else:
        profile = effective_storage_provider()
    return binding, profile


def normalize_relative_prefix(value: object) -> str:
    """Normalize a usage prefix while rejecting absolute/traversal paths."""

    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if "\x00" in raw or ".." in raw or raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise ValueError("Storage key prefix must be relative")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("Storage key prefix traversal is not allowed")
    return "/".join(parts)


USAGE_PURPOSES = ("config_backup", "pam_recording")


def _load_storage_usage(purpose: str) -> StorageUsageBinding:
    if purpose not in USAGE_PURPOSES:
        raise StorageError("Unsupported storage usage purpose")
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT purpose, provider_mode, provider_id, bucket_override, key_prefix, updated_at "
                "FROM storage_usage_bindings WHERE purpose = ?",
                (purpose,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        raise StorageError("Storage usage configuration is unavailable") from exc
    if not row:
        raise StorageError("Storage usage configuration was not found")
    mode = str(_row_value(row, "provider_mode", "") or "").strip().lower()
    provider_id = str(_row_value(row, "provider_id", "") or "").strip() or None
    if mode not in {"default", "environment", "profile"}:
        raise StorageError("Storage usage configuration is invalid")
    if mode == "profile" and not provider_id:
        raise StorageError("Storage usage profile is not configured")
    if mode != "profile":
        provider_id = None
    try:
        prefix = normalize_relative_prefix(_row_value(row, "key_prefix", "") or "")
    except ValueError as exc:
        raise StorageError("Storage usage key prefix is invalid") from exc
    return StorageUsageBinding(
        purpose=purpose,
        provider_mode=mode,
        provider_id=provider_id,
        bucket_override=str(_row_value(row, "bucket_override", "") or "").strip() or None,
        key_prefix=prefix,
        updated_at=str(_row_value(row, "updated_at", "") or ""),
    )


def list_storage_usage_bindings() -> list[StorageUsageBinding]:
    return [_load_storage_usage(purpose) for purpose in USAGE_PURPOSES]


def _service_for_profile(
    profile: StorageProviderConfig,
    *,
    bucket: str | None = None,
    key_prefix: str = "",
    purpose: str | None = None,
) -> StorageService:
    from core.config import settings

    backend_name = profile.backend.strip().lower()
    if backend_name == "local":
        return StorageService(
            LocalStorageBackend(settings.STORAGE_LOCAL_ROOT, bucket=bucket or None),
            storage_config_id=profile.id,
            key_prefix=key_prefix,
            purpose=purpose,
        )
    if backend_name == "s3":
        return StorageService(
            S3StorageBackend(
                endpoint_url=profile.endpoint_url,
                bucket=bucket or profile.bucket,
                region=profile.region,
                access_key_id=profile.access_key_id,
                secret_access_key=profile.secret_access_key,
                force_path_style=profile.force_path_style,
                verify_tls=profile.verify_tls,
                connect_timeout=settings.S3_CONNECT_TIMEOUT_SECONDS,
                read_timeout=settings.S3_READ_TIMEOUT_SECONDS,
            ),
            storage_config_id=profile.id,
            key_prefix=key_prefix,
            purpose=purpose,
        )
    raise StorageError(f"Unsupported STORAGE_BACKEND: {backend_name}")


def build_storage_service(
    *,
    backend_name: str | None = None,
    bucket: str | None = None,
    storage_config_id: str | None = None,
    purpose: str | None = None,
) -> StorageService:
    """Build a provider by row ID, current DB default, or legacy environment."""

    if purpose:
        binding, profile = resolve_storage_usage(str(purpose).strip())
        return _service_for_profile(
            profile,
            bucket=binding.bucket_override,
            key_prefix=binding.key_prefix,
            purpose=binding.purpose,
        )
    if storage_config_id:
        return _service_for_profile(_database_provider(str(storage_config_id)), bucket=bucket)
    if backend_name is None and bucket is None:
        return _service_for_profile(effective_storage_provider())
    profile = _environment_provider()
    profile = replace(profile, backend=str(backend_name or profile.backend).strip().lower())
    return _service_for_profile(profile, bucket=bucket)


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
    "StorageProviderConfig",
    "StorageUsageBinding",
    "USAGE_PURPOSES",
    "build_storage_service",
    "effective_storage_provider",
    "get_storage_provider_config",
    "list_storage_provider_configs",
    "list_storage_usage_bindings",
    "resolve_storage_usage",
    "iter_stream",
    "normalize_object_key",
    "normalize_relative_prefix",
]
