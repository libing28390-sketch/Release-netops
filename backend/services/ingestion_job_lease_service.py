"""Database-backed Import Job leases for ING-017.

The existing ``scheduler_locks`` table is the already-migrated, PostgreSQL
authoritative lock primitive used by DB-022.  Reusing it keeps this change
additive and avoids a second lock table while the durable ``kb_import_job``
schema remains release-gated by DB-011/MIG.  The lock name is tenant-hashed,
and the opaque owner token is never part of an API response.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection
from ai.services.metrics import ai_metrics
from services.ingestion_pipeline_service import (
    IngestionJob,
    IngestionPipeline,
    IngestionPipelineError,
    LeaseError,
    ingestion_pipeline,
)


_DEFAULT_LEASE_SECONDS = 60
_MAX_LEASE_SECONDS = 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _text(value: Any, *, field: str, maximum: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise IngestionPipelineError("INVALID_PIPELINE_INPUT", f"{field} is required")
    if len(text) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise IngestionPipelineError("INVALID_PIPELINE_INPUT", f"{field} is invalid")
    return text


def _lease_seconds(value: Any) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise LeaseError("LEASE_INVALID", "lease_seconds is invalid") from exc
    if seconds < 1 or seconds > _MAX_LEASE_SECONDS:
        raise LeaseError("LEASE_INVALID", "lease_seconds is outside the allowed range")
    return seconds


def _lock_name(tenant_id: str, job_id: str) -> str:
    tenant_key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
    return f"knowledge_import:{tenant_key}:{job_id}"


@dataclass
class ImportJobLease:
    tenant_id: str
    job_id: str
    worker_id: str
    lease_seconds: int = _DEFAULT_LEASE_SECONDS
    owner_token: str = ""
    held: bool = False

    def __post_init__(self) -> None:
        self.tenant_id = _text(self.tenant_id, field="tenant_id", maximum=128)
        self.job_id = _text(self.job_id, field="job_id", maximum=128)
        self.worker_id = _text(self.worker_id, field="worker_id", maximum=256)
        self.lease_seconds = _lease_seconds(self.lease_seconds)
        self.lock_name = _lock_name(self.tenant_id, self.job_id)

    def acquire(self, *, now: datetime | None = None) -> bool:
        if self.held:
            return True
        moment = now or _now()
        expires = moment + timedelta(seconds=self.lease_seconds)
        # Persist only an opaque random fence; worker identity remains in the
        # bounded state-machine audit event and is never embedded in the DB
        # lock value or public snapshot.
        token = uuid.uuid4().hex
        with get_db_connection() as conn:
            try:
                conn.execute("DELETE FROM scheduler_locks WHERE expires_at < ?", (_iso(moment),))
                conn.execute(
                    "INSERT INTO scheduler_locks (lock_name, locked_at, expires_at) VALUES (?, ?, ?)",
                    (self.lock_name, token, _iso(expires)),
                )
                conn.commit()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                # A unique-key collision is the normal duplicate-worker path;
                # all other database failures fail closed as unavailable.
                pgcode = str(getattr(exc, "pgcode", "") or "")
                if pgcode == "23505" or "unique" in str(exc).casefold() or "constraint" in str(exc).casefold() or "duplicate" in str(exc).casefold():
                    ai_metrics.job_event("import", "lease_held")
                    return False
                raise LeaseError("LEASE_STORAGE_UNAVAILABLE", "The Import Job lease store is unavailable") from exc
        self.owner_token = token
        self.held = True
        ai_metrics.job_event("import", "lease_acquired")
        return True

    def heartbeat(self, *, now: datetime | None = None) -> bool:
        if not self.held or not self.owner_token:
            raise LeaseError("STALE_LEASE", "The worker lease is stale")
        moment = now or _now()
        expires = moment + timedelta(seconds=self.lease_seconds)
        with get_db_connection() as conn:
            try:
                cursor = conn.execute(
                    "UPDATE scheduler_locks SET expires_at = ? "
                    "WHERE lock_name = ? AND locked_at = ? AND expires_at >= ?",
                    (_iso(expires), self.lock_name, self.owner_token, _iso(moment)),
                )
                conn.commit()
                if int(getattr(cursor, "rowcount", 0) or 0) != 1:
                    self.held = False
                    ai_metrics.job_event("import", "lease_lost")
                    raise LeaseError("STALE_LEASE", "The worker lease is stale")
                return True
            except LeaseError:
                raise
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                self.held = False
                ai_metrics.job_event("import", "lease_error")
                raise LeaseError("LEASE_STORAGE_UNAVAILABLE", "The Import Job lease store is unavailable") from exc

    def release(self) -> bool:
        if not self.held or not self.owner_token:
            return False
        with get_db_connection() as conn:
            try:
                cursor = conn.execute(
                    "DELETE FROM scheduler_locks WHERE lock_name = ? AND locked_at = ?",
                    (self.lock_name, self.owner_token),
                )
                conn.commit()
                released = int(getattr(cursor, "rowcount", 0) or 0) == 1
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise LeaseError("LEASE_STORAGE_UNAVAILABLE", "The Import Job lease store is unavailable") from exc
            finally:
                self.held = False
        return released

    def __enter__(self) -> "ImportJobLease":
        if not self.acquire():
            raise LeaseError("LEASE_HELD", "Another worker currently holds the Import Job lease")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


@dataclass
class ImportJobLeaseClaim:
    job: IngestionJob
    lease: ImportJobLease

    @property
    def fencing_token(self) -> str:
        """Return the process-local job fence for internal worker calls only."""
        return str(self.job.fencing_token)

    def snapshot(self) -> dict[str, Any]:
        result = self.job.to_dict()
        result.pop("fencing_token", None)
        result["lease_owner"] = ""
        result["lease_held"] = bool(self.lease.held)
        return result


class IngestionJobLeaseCoordinator:
    """Join the DB lease and the ING-001 state-machine fence."""

    def __init__(self, pipeline: IngestionPipeline = ingestion_pipeline) -> None:
        self.pipeline = pipeline

    def claim(
        self,
        job_id: str,
        *,
        tenant_id: str,
        worker_id: str,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
        request_id: str = "",
    ) -> ImportJobLeaseClaim:
        lease = ImportJobLease(tenant_id, job_id, worker_id, lease_seconds)
        if not lease.acquire(now=now):
            raise LeaseError("LEASE_HELD", "Another worker currently holds the Import Job lease")
        try:
            job = self.pipeline.claim_job(
                job_id,
                tenant_id=tenant_id,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                now=now,
                request_id=request_id,
            )
            return ImportJobLeaseClaim(job=job, lease=lease)
        except Exception:
            lease.release()
            raise

    def heartbeat(self, claim: ImportJobLeaseClaim, *, request_id: str = "", now: datetime | None = None) -> dict[str, Any]:
        claim.lease.heartbeat(now=now)
        try:
            claim.job.heartbeat(
                claim.lease.worker_id,
                claim.fencing_token,
                lease_seconds=claim.lease.lease_seconds,
                now=now,
                request_id=request_id,
            )
        except Exception:
            claim.lease.release()
            raise
        return claim.snapshot()

    def release(self, claim: ImportJobLeaseClaim) -> bool:
        if claim.job.execution_state not in {"succeeded", "failed", "cancelled"}:
            raise LeaseError("LEASE_RELEASE_NOT_ALLOWED", "A running Import Job lease cannot be released before a terminal state")
        return claim.lease.release()


ingestion_job_lease_coordinator = IngestionJobLeaseCoordinator()


__all__ = ["ImportJobLease", "ImportJobLeaseClaim", "IngestionJobLeaseCoordinator", "ingestion_job_lease_coordinator"]
