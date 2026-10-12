"""Canonical Knowledge Engine ingestion pipeline state machine.

ING-001 deliberately implements the control-plane contract without claiming a
physical import-job migration.  It gives every future URL/file/parser/
embedding worker the same state, phase, progress, lease, cancellation, and
error semantics while leaving the existing V1 reindex rows untouched.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable

from ai.services.metrics import ai_metrics


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_MAX_ERROR_EVENTS = 100
_MAX_AUDIT_EVENTS = 250
_MAX_RETRIES = 100
_DEFAULT_LEASE_SECONDS = 60
_MAX_LEASE_SECONDS = 3600


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class JobKind(_ValueEnum):
    DOCUMENT_IMPORT = "document_import"
    DOCUMENT_REINDEX = "document_reindex"
    CHUNK_REBUILD = "chunk_rebuild"
    EMBEDDING_REBUILD = "embedding_rebuild"
    INDEX_BUILD = "index_build"
    SCOPE_REFRESH = "scope_refresh"
    CATALOG_BACKFILL = "catalog_backfill"
    DRY_RUN_VALIDATION = "dry_run_validation"


class ExecutionState(_ValueEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IngestionPhase(_ValueEnum):
    ACCEPTED = "accepted"
    SCOPED = "scoped"
    FETCHED = "fetched"
    PARSED = "parsed"
    NORMALIZED = "normalized"
    CLASSIFIED = "classified"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    VALIDATED = "validated"
    COMMITTED = "committed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionErrorCode(_ValueEnum):
    SOURCE_TIMEOUT = "SOURCE_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_DATABASE = "TRANSIENT_DATABASE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    WORKER_LOST = "WORKER_LOST"
    INVALID_SCOPE = "INVALID_SCOPE"
    ACL_DENIED = "ACL_DENIED"
    PARSER_CONTRACT = "PARSER_CONTRACT"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    SECRET_OR_SSRF_VIOLATION = "SECRET_OR_SSRF_VIOLATION"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    ROBOTS_DISALLOWED = "ROBOTS_DISALLOWED"
    ROBOTS_UNAVAILABLE = "ROBOTS_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class IngestionPipelineError(ValueError):
    """Stable contract error safe for service/API boundaries."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class InvalidTransitionError(IngestionPipelineError):
    def __init__(self, current: str, target: str):
        super().__init__("INVALID_EXECUTION_TRANSITION", "Execution state transition is not allowed", details={"from": current, "to": target})


class InvalidPhaseError(IngestionPipelineError):
    def __init__(self, current: str, target: str, code: str = "INVALID_PHASE_TRANSITION"):
        super().__init__(code, "Ingestion phase transition is not allowed", details={"from": current, "to": target})


class ProgressInvariantError(IngestionPipelineError):
    def __init__(self, message: str = "Progress counters violate the ingestion contract"):
        super().__init__("PROGRESS_INVARIANT_VIOLATION", message)


class LeaseError(IngestionPipelineError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, status_code=409)


class IdempotencyConflictError(IngestionPipelineError):
    def __init__(self):
        super().__init__("IDEMPOTENCY_KEY_CONFLICT", "The idempotency key was already used for a different scope", status_code=409)


JOB_KINDS = tuple(item.value for item in JobKind)
EXECUTION_STATES = tuple(item.value for item in ExecutionState)
TERMINAL_EXECUTION_STATES = frozenset({ExecutionState.CANCELLED.value, ExecutionState.SUCCEEDED.value, ExecutionState.FAILED.value})
PHASES = tuple(item.value for item in IngestionPhase)
PHASE_ORDER = tuple(item.value for item in IngestionPhase if item not in {IngestionPhase.FAILED, IngestionPhase.CANCELLED})

EXECUTION_TRANSITIONS: dict[str, frozenset[str]] = {
    ExecutionState.QUEUED.value: frozenset({ExecutionState.RUNNING.value, ExecutionState.CANCEL_REQUESTED.value}),
    ExecutionState.RUNNING.value: frozenset({ExecutionState.RETRY_WAIT.value, ExecutionState.PAUSED.value, ExecutionState.CANCEL_REQUESTED.value, ExecutionState.SUCCEEDED.value, ExecutionState.FAILED.value}),
    ExecutionState.RETRY_WAIT.value: frozenset({ExecutionState.RUNNING.value, ExecutionState.FAILED.value}),
    ExecutionState.PAUSED.value: frozenset({ExecutionState.RUNNING.value}),
    ExecutionState.CANCEL_REQUESTED.value: frozenset({ExecutionState.CANCELLED.value}),
    ExecutionState.CANCELLED.value: frozenset(),
    ExecutionState.SUCCEEDED.value: frozenset(),
    ExecutionState.FAILED.value: frozenset(),
}

RETRYABLE_ERROR_CODES = frozenset({
    IngestionErrorCode.SOURCE_TIMEOUT.value,
    IngestionErrorCode.RATE_LIMITED.value,
    IngestionErrorCode.TRANSIENT_DATABASE.value,
    IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
    IngestionErrorCode.WORKER_LOST.value,
    IngestionErrorCode.ROBOTS_UNAVAILABLE.value,
})
NON_RETRYABLE_ERROR_CODES = frozenset({
    IngestionErrorCode.INVALID_SCOPE.value,
    IngestionErrorCode.ACL_DENIED.value,
    IngestionErrorCode.PARSER_CONTRACT.value,
    IngestionErrorCode.UNSUPPORTED_FORMAT.value,
    IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    IngestionErrorCode.DATA_INTEGRITY.value,
    IngestionErrorCode.ROBOTS_DISALLOWED.value,
    IngestionErrorCode.INTERNAL_ERROR.value,
})

ERROR_CATALOG: dict[str, dict[str, Any]] = {
    IngestionErrorCode.SOURCE_TIMEOUT.value: {"retryable": True, "safe_message": "The source did not respond within the ingestion timeout."},
    IngestionErrorCode.RATE_LIMITED.value: {"retryable": True, "safe_message": "The source rate limit requires a later retry."},
    IngestionErrorCode.TRANSIENT_DATABASE.value: {"retryable": True, "safe_message": "A transient database error interrupted ingestion."},
    IngestionErrorCode.PROVIDER_UNAVAILABLE.value: {"retryable": True, "safe_message": "A required provider is temporarily unavailable."},
    IngestionErrorCode.WORKER_LOST.value: {"retryable": True, "safe_message": "The ingestion worker lease expired before completion."},
    IngestionErrorCode.INVALID_SCOPE.value: {"retryable": False, "safe_message": "The ingestion scope is invalid."},
    IngestionErrorCode.ACL_DENIED.value: {"retryable": False, "safe_message": "The actor is not allowed to ingest this source."},
    IngestionErrorCode.PARSER_CONTRACT.value: {"retryable": False, "safe_message": "The parser result did not satisfy the ingestion contract."},
    IngestionErrorCode.UNSUPPORTED_FORMAT.value: {"retryable": False, "safe_message": "The source format is not supported by the ingestion pipeline."},
    IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value: {"retryable": False, "safe_message": "The source violated the secure ingestion policy."},
    IngestionErrorCode.DATA_INTEGRITY.value: {"retryable": False, "safe_message": "The source data failed an integrity check."},
    IngestionErrorCode.ROBOTS_DISALLOWED.value: {"retryable": False, "safe_message": "The source robots policy disallows automated collection."},
    IngestionErrorCode.ROBOTS_UNAVAILABLE.value: {"retryable": True, "safe_message": "The source robots policy could not be verified; collection may be retried later."},
    IngestionErrorCode.INTERNAL_ERROR.value: {"retryable": False, "safe_message": "The ingestion pipeline encountered an internal error."},
}

_ERROR_ALIASES = {
    "SOURCE_TIMEOUT": IngestionErrorCode.SOURCE_TIMEOUT.value,
    "TIMEOUT": IngestionErrorCode.SOURCE_TIMEOUT.value,
    "RATE_LIMITED": IngestionErrorCode.RATE_LIMITED.value,
    "RATE_LIMIT": IngestionErrorCode.RATE_LIMITED.value,
    "TRANSIENT_DATABASE": IngestionErrorCode.TRANSIENT_DATABASE.value,
    "DATABASE_TRANSIENT": IngestionErrorCode.TRANSIENT_DATABASE.value,
    "PROVIDER_UNAVAILABLE": IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
    "WORKER_LOST": IngestionErrorCode.WORKER_LOST.value,
    "INVALID_SCOPE": IngestionErrorCode.INVALID_SCOPE.value,
    "ACL_DENIED": IngestionErrorCode.ACL_DENIED.value,
    "PERMISSION_DENIED": IngestionErrorCode.ACL_DENIED.value,
    "PARSER_CONTRACT": IngestionErrorCode.PARSER_CONTRACT.value,
    "UNSUPPORTED_FORMAT": IngestionErrorCode.UNSUPPORTED_FORMAT.value,
    "SECRET_OR_SSRF_VIOLATION": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "SSRF_BLOCKED": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "DATA_INTEGRITY": IngestionErrorCode.DATA_INTEGRITY.value,
    "OUTBOUND_TIMEOUT": IngestionErrorCode.SOURCE_TIMEOUT.value,
    "OUTBOUND_HTTP_5XX": IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
    "OUTBOUND_TRANSPORT_FAILED": IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
    "OUTBOUND_DNS_RESOLUTION_FAILED": IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
    "OUTBOUND_DNS_EMPTY": IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
    "OUTBOUND_HTTP_4XX": IngestionErrorCode.DATA_INTEGRITY.value,
    "OUTBOUND_DNS_BLOCKED": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "OUTBOUND_IP_LITERAL_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "OUTBOUND_REDIRECT_TARGET_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "OUTBOUND_REDIRECT_HOST_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "OUTBOUND_REDIRECT_PROTOCOL_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "OUTBOUND_REDIRECT_PATH_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "OUTBOUND_SOURCE_NOT_ACTIVE": IngestionErrorCode.INVALID_SCOPE.value,
    "OUTBOUND_SOURCE_NOT_VALIDATED": IngestionErrorCode.INVALID_SCOPE.value,
    "SOURCE_NOT_ACTIVE": IngestionErrorCode.INVALID_SCOPE.value,
    "SOURCE_NOT_VALIDATED": IngestionErrorCode.INVALID_SCOPE.value,
    "SOURCE_VALIDATION_FAILED": IngestionErrorCode.INVALID_SCOPE.value,
    "URL_SCHEME_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "URL_QUERY_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "URL_FRAGMENT_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "URL_USERINFO_FORBIDDEN": IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value,
    "ALLOWLIST_UNAVAILABLE": IngestionErrorCode.PROVIDER_UNAVAILABLE.value,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z") if value else None


def _clean_text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise IngestionPipelineError("INVALID_PIPELINE_INPUT", f"{field} is required")
    if len(text) > maximum or _CONTROL_CHARS.search(text):
        raise IngestionPipelineError("INVALID_PIPELINE_INPUT", f"{field} is invalid")
    return text


def _enum_value(enum_cls: type[Enum], value: Any, *, field: str) -> str:
    try:
        return enum_cls(str(value)).value
    except (TypeError, ValueError) as exc:
        raise IngestionPipelineError("INVALID_PIPELINE_INPUT", f"{field} is not supported") from exc


def _safe_scope_fingerprint(scope: dict[str, Any] | None) -> str:
    if scope is None:
        scope = {}
    if not isinstance(scope, dict):
        raise IngestionPipelineError("INVALID_SCOPE", "Ingestion scope must be an object")
    try:
        payload = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise IngestionPipelineError("INVALID_SCOPE", "Ingestion scope cannot be serialized") from exc
    if _CONTROL_CHARS.search(payload) or len(payload) > 100_000:
        raise IngestionPipelineError("INVALID_SCOPE", "Ingestion scope is invalid")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_uuidish(value: Any, *, field: str, maximum: int = 256) -> str:
    return _clean_text(value, field=field, maximum=maximum, required=False)


def _synchronized(method):
    """Serialize mutations/snapshots of one process-local job.

    The DB-backed lease added by ING-017 fences workers across processes; this
    lock closes the smaller in-process race where two threads call ``claim``
    on the same snapshot at the same time.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class IngestionErrorDetail:
    code: str
    safe_message: str
    phase: str
    item_id: str = ""
    source_id: str = ""
    attempt_no: int = 0
    retryable: bool = False
    occurred_at: str = ""
    correlation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "safe_message": self.safe_message,
            "phase": self.phase,
            "item_id": self.item_id,
            "source_id": self.source_id,
            "attempt_no": self.attempt_no,
            "retryable": self.retryable,
            "occurred_at": self.occurred_at,
            "correlation_id": self.correlation_id,
        }


def _error_code_from_exception(exc: BaseException) -> str:
    explicit = getattr(exc, "code", None) or getattr(exc, "error_code", None)
    normalized = str(explicit or "").strip().upper().replace("-", "_")
    if normalized in ERROR_CATALOG:
        return normalized
    if normalized in _ERROR_ALIASES:
        return _ERROR_ALIASES[normalized]
    name = type(exc).__name__.upper()
    message = str(exc).upper()
    combined = f"{name} {message}"
    if "SSRF" in combined or "SECRET" in combined or "CREDENTIAL" in combined:
        return IngestionErrorCode.SECRET_OR_SSRF_VIOLATION.value
    if "ACL" in combined or "PERMISSION" in combined or "FORBIDDEN" in combined:
        return IngestionErrorCode.ACL_DENIED.value
    if "RATE" in combined or "429" in combined:
        return IngestionErrorCode.RATE_LIMITED.value
    if "TIMEOUT" in combined or isinstance(exc, TimeoutError):
        return IngestionErrorCode.SOURCE_TIMEOUT.value
    if "DATABASE" in combined or "DEADLOCK" in combined or "LOCK" in combined:
        return IngestionErrorCode.TRANSIENT_DATABASE.value
    if "PROVIDER" in combined or isinstance(exc, ConnectionError):
        return IngestionErrorCode.PROVIDER_UNAVAILABLE.value
    if "PARSER" in combined or "SCHEMA" in combined:
        return IngestionErrorCode.PARSER_CONTRACT.value
    if "FORMAT" in combined:
        return IngestionErrorCode.UNSUPPORTED_FORMAT.value
    if "INTEGRITY" in combined or "HASH" in combined:
        return IngestionErrorCode.DATA_INTEGRITY.value
    return IngestionErrorCode.INTERNAL_ERROR.value


def classify_ingestion_error(
    exc: BaseException | str,
    *,
    phase: str = IngestionPhase.ACCEPTED.value,
    item_id: str = "",
    source_id: str = "",
    attempt_no: int = 0,
    correlation_id: str = "",
    occurred_at: datetime | None = None,
) -> IngestionErrorDetail:
    """Map arbitrary worker failures to a stable, redacted error contract."""
    if isinstance(exc, BaseException):
        code = _error_code_from_exception(exc)
    else:
        normalized = str(exc or "").strip().upper().replace("-", "_")
        code = _ERROR_ALIASES.get(normalized, normalized if normalized in ERROR_CATALOG else _error_code_from_exception(RuntimeError(normalized)))
    code = code if code in ERROR_CATALOG else IngestionErrorCode.INTERNAL_ERROR.value
    phase_value = _enum_value(IngestionPhase, phase, field="phase")
    try:
        attempt = max(0, int(attempt_no))
    except (TypeError, ValueError):
        attempt = 0
    return IngestionErrorDetail(
        code=code,
        safe_message=str(ERROR_CATALOG[code]["safe_message"]),
        phase=phase_value,
        item_id=_safe_uuidish(item_id, field="item_id"),
        source_id=_safe_uuidish(source_id, field="source_id"),
        attempt_no=attempt,
        retryable=bool(ERROR_CATALOG[code]["retryable"]),
        occurred_at=_iso(occurred_at or _now()) or "",
        correlation_id=_safe_uuidish(correlation_id, field="correlation_id"),
    )


def error_catalog() -> dict[str, dict[str, Any]]:
    """Return a copy suitable for API/docs generation."""
    return copy.deepcopy(ERROR_CATALOG)


@dataclass
class IngestionJob:
    id: str
    tenant_id: str
    job_kind: str
    idempotency_key: str
    scope_fingerprint: str
    max_retries: int = 0
    dry_run: bool = False
    lifecycle_status: str = "draft"
    execution_state: str = ExecutionState.QUEUED.value
    phase: str = IngestionPhase.ACCEPTED.value
    phase_started_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    created_by: str = "system"
    updated_by: str = "system"
    # A retry is a new job attempt, never an in-place mutation of a terminal
    # job.  Keeping the parent id on the child makes the operator-facing
    # retry flow auditable without changing the V1 reindex rows.
    retry_of_job_id: str = ""
    total_count: int = 0
    processed_count: int = 0
    parsed_count: int = 0
    failed_count: int = 0
    succeeded_count: int = 0
    skipped_count: int = 0
    retryable_failed_count: int = 0
    error_count: int = 0
    progress_percent: float = 100.0
    retry_count: int = 0
    attempt_no: int = 0
    next_retry_at: datetime | None = None
    last_error_code: str = ""
    last_error_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancel_requested_by: str = ""
    cancellation_reason: str = ""
    cancelled_at: datetime | None = None
    cancelled_by: str = ""
    lease_owner: str = ""
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    fencing_token: str = ""
    errors: list[dict[str, Any]] = field(default_factory=list)
    phase_history: list[dict[str, Any]] = field(default_factory=list)
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    _state_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.tenant_id = _clean_text(self.tenant_id, field="tenant_id", maximum=128, required=True)
        self.job_kind = _enum_value(JobKind, self.job_kind, field="job_kind")
        self.execution_state = _enum_value(ExecutionState, self.execution_state, field="execution_state")
        self.phase = _enum_value(IngestionPhase, self.phase, field="phase")
        self.idempotency_key = _clean_text(self.idempotency_key, field="idempotency_key", maximum=256, required=True)
        self.created_by = _clean_text(self.created_by, field="created_by", maximum=256) or "system"
        self.updated_by = _clean_text(self.updated_by, field="updated_by", maximum=256) or "system"
        self.retry_of_job_id = _clean_text(self.retry_of_job_id, field="retry_of_job_id", maximum=128)
        try:
            self.max_retries = int(self.max_retries)
        except (TypeError, ValueError) as exc:
            raise IngestionPipelineError("INVALID_PIPELINE_INPUT", "max_retries is invalid") from exc
        if self.max_retries < 0 or self.max_retries > _MAX_RETRIES:
            raise IngestionPipelineError("INVALID_PIPELINE_INPUT", "max_retries is outside the allowed range")
        self._validate_progress(
            {
                "total_count": self.total_count,
                "processed_count": self.processed_count,
                "parsed_count": self.parsed_count,
                "failed_count": self.failed_count,
                "succeeded_count": self.succeeded_count,
                "skipped_count": self.skipped_count,
                "retryable_failed_count": self.retryable_failed_count,
            }
        )
        self._recompute_progress()

    def _metrics_kind(self) -> str:
        """Map pipeline job kinds to the two OBS-007 queue families."""

        if self.job_kind in {
            JobKind.DOCUMENT_REINDEX.value,
            JobKind.CHUNK_REBUILD.value,
            JobKind.EMBEDDING_REBUILD.value,
            JobKind.INDEX_BUILD.value,
        }:
            return "reindex"
        return "import"

    @property
    def terminal(self) -> bool:
        return self.execution_state in TERMINAL_EXECUTION_STATES

    def _touch(self, actor: str = "system") -> None:
        self.updated_at = _now()
        self.updated_by = _clean_text(actor, field="actor", maximum=256) or "system"

    def _audit(self, event_type: str, *, actor: str = "system", request_id: str = "", **details: Any) -> None:
        event = {
            "event_type": event_type,
            "actor": _clean_text(actor, field="actor", maximum=256) or "system",
            "request_id": _clean_text(request_id, field="request_id", maximum=256),
            "job_id": self.id,
            "tenant_id": self.tenant_id,
            "attempt_no": self.attempt_no,
            "created_at": _iso(_now()),
            **details,
        }
        self.audit_events.append(event)
        del self.audit_events[:-_MAX_AUDIT_EVENTS]

    def _recompute_progress(self) -> None:
        self.progress_percent = 100.0 if self.total_count == 0 else round(min(100.0, self.processed_count * 100.0 / self.total_count), 2)

    @staticmethod
    def _validate_progress(values: dict[str, Any]) -> None:
        normalized: dict[str, int] = {}
        for name, value in values.items():
            if isinstance(value, bool):
                raise ProgressInvariantError(f"{name} must be an integer")
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ProgressInvariantError(f"{name} must be an integer") from exc
            if number < 0:
                raise ProgressInvariantError(f"{name} cannot be negative")
            normalized[name] = number
        total = normalized["total_count"]
        processed = normalized["processed_count"]
        if processed > total:
            raise ProgressInvariantError("processed_count cannot exceed total_count")
        if normalized["parsed_count"] + normalized["skipped_count"] + normalized["failed_count"] > processed:
            raise ProgressInvariantError("parsed + skipped + failed cannot exceed processed_count")
        if normalized["succeeded_count"] + normalized["skipped_count"] + normalized["failed_count"] > processed:
            raise ProgressInvariantError("succeeded + skipped + failed cannot exceed processed_count")
        if normalized["retryable_failed_count"] > processed:
            raise ProgressInvariantError("retryable_failed_count cannot exceed processed_count")

    @_synchronized
    def update_progress(self, *, actor: str = "system", request_id: str = "", **updates: int) -> dict[str, Any]:
        allowed = {"total_count", "processed_count", "parsed_count", "failed_count", "succeeded_count", "skipped_count", "retryable_failed_count"}
        unknown = set(updates) - allowed
        if unknown:
            raise ProgressInvariantError(f"Unsupported progress field(s): {sorted(unknown)}")
        candidate = {
            name: int(updates.get(name, getattr(self, name)))
            for name in allowed
        }
        if candidate["total_count"] < self.total_count:
            raise ProgressInvariantError("total_count cannot decrease")
        self._validate_progress(candidate)
        for name, value in candidate.items():
            setattr(self, name, value)
        self._recompute_progress()
        self._touch(actor)
        self._audit("progress_updated", actor=actor, request_id=request_id, processed_count=self.processed_count, total_count=self.total_count, progress_percent=self.progress_percent)
        return self.to_dict()

    @_synchronized
    def record_error(
        self,
        error: IngestionErrorDetail | BaseException | str,
        *,
        actor: str = "system",
        request_id: str = "",
        item_id: str = "",
        source_id: str = "",
    ) -> dict[str, Any]:
        detail = error if isinstance(error, IngestionErrorDetail) else classify_ingestion_error(
            error,
            phase=self.phase,
            item_id=item_id,
            source_id=source_id,
            attempt_no=self.attempt_no,
            correlation_id=request_id,
        )
        event = detail.to_dict()
        self.errors.append(event)
        del self.errors[:-_MAX_ERROR_EVENTS]
        self.error_count += 1
        self.last_error_code = detail.code
        try:
            self.last_error_at = datetime.fromisoformat(detail.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            self.last_error_at = _now()
        self._touch(actor)
        self._audit("job_failed" if not detail.retryable else "job_error", actor=actor, request_id=request_id, error=event)
        return event

    @_synchronized
    def advance_phase(self, target: str, *, actor: str = "system", request_id: str = "", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        target_value = _enum_value(IngestionPhase, target, field="phase")
        current = self.phase
        if target_value == current:
            return self.to_dict()
        if target_value in {IngestionPhase.FAILED.value, IngestionPhase.CANCELLED.value}:
            expected_state = ExecutionState.FAILED.value if target_value == IngestionPhase.FAILED.value else ExecutionState.CANCELLED.value
            if self.execution_state != expected_state:
                raise InvalidPhaseError(current, target_value)
        else:
            if current in {IngestionPhase.FAILED.value, IngestionPhase.CANCELLED.value}:
                raise InvalidPhaseError(current, target_value)
            if self.execution_state != ExecutionState.RUNNING.value:
                raise InvalidPhaseError(current, target_value, code="PHASE_REQUIRES_RUNNING")
            current_index = PHASE_ORDER.index(current)
            target_index = PHASE_ORDER.index(target_value)
            if target_index < current_index:
                raise InvalidPhaseError(current, target_value)
            if target_index > current_index + 1:
                skipped = (evidence or {}).get("skipped_phases") if isinstance(evidence, dict) else None
                expected = list(PHASE_ORDER[current_index + 1:target_index])
                if sorted(str(item) for item in (skipped or [])) != sorted(expected):
                    raise InvalidPhaseError(current, target_value, code="PHASE_SKIP_EVIDENCE_REQUIRED")
            if target_value == IngestionPhase.COMPLETED.value:
                if self.processed_count != self.total_count:
                    raise InvalidPhaseError(current, target_value, code="COMPLETION_PROGRESS_REQUIRED")
        before = self.phase
        self.phase = target_value
        self.phase_started_at = _now()
        self._touch(actor)
        self._audit("phase_changed", actor=actor, request_id=request_id, before_phase=before, after_phase=target_value, evidence=copy.deepcopy(evidence or {}))
        self.phase_history.append({"before": before, "after": target_value, "actor": actor, "request_id": request_id, "created_at": _iso(_now()), "evidence": copy.deepcopy(evidence or {})})
        del self.phase_history[:-_MAX_AUDIT_EVENTS]
        return self.to_dict()

    @_synchronized
    def transition_execution_state(self, target: str, *, actor: str = "system", request_id: str = "") -> dict[str, Any]:
        target_value = _enum_value(ExecutionState, target, field="execution_state")
        current = self.execution_state
        if target_value == current:
            return self.to_dict()
        if target_value not in EXECUTION_TRANSITIONS.get(current, frozenset()):
            raise InvalidTransitionError(current, target_value)
        if target_value == ExecutionState.SUCCEEDED.value:
            if self.phase != IngestionPhase.COMPLETED.value:
                raise InvalidTransitionError(current, "succeeded_without_completed_phase")
            if self.processed_count != self.total_count:
                raise ProgressInvariantError("succeeded requires processed_count == total_count")
        if target_value == ExecutionState.FAILED.value and not self.last_error_code:
            raise IngestionPipelineError("FAILED_WITHOUT_ERROR", "A failed job must retain a structured error")
        if target_value == ExecutionState.CANCELLED.value and not self.cancel_requested_at:
            raise IngestionPipelineError("CANCELLED_WITHOUT_REQUEST", "A cancelled job must retain a cancellation request")
        before = current
        self.execution_state = target_value
        if target_value == ExecutionState.RUNNING.value:
            self.lifecycle_status = "active"
            self.started_at = self.started_at or _now()
        if target_value in TERMINAL_EXECUTION_STATES:
            self.finished_at = _now()
            self.lease_owner = ""
            self.lease_expires_at = None
            self.heartbeat_at = None
            self.fencing_token = ""
            if target_value == ExecutionState.CANCELLED.value:
                self.cancelled_at = self.cancelled_at or _now()
                self.cancelled_by = self.cancelled_by or self.cancel_requested_by or actor
        self._touch(actor)
        self._audit("execution_state_changed", actor=actor, request_id=request_id, before_state=before, after_state=target_value)
        return self.to_dict()

    @_synchronized
    def claim(self, worker_id: str, *, lease_seconds: int = _DEFAULT_LEASE_SECONDS, now: datetime | None = None, request_id: str = "") -> dict[str, Any]:
        worker = _clean_text(worker_id, field="worker_id", maximum=256, required=True)
        moment = now or _now()
        try:
            seconds = int(lease_seconds)
        except (TypeError, ValueError) as exc:
            raise LeaseError("LEASE_INVALID", "lease_seconds is invalid") from exc
        if seconds < 1 or seconds > _MAX_LEASE_SECONDS:
            raise LeaseError("LEASE_INVALID", "lease_seconds is outside the allowed range")
        if self.execution_state == ExecutionState.RUNNING.value:
            if self.lease_owner == worker and self.lease_expires_at and self.lease_expires_at > moment:
                return self.to_dict()
            if self.lease_owner and self.lease_expires_at and self.lease_expires_at > moment:
                raise LeaseError("LEASE_HELD", "Another worker currently holds the job lease")
            if self.lease_owner and self.lease_expires_at and self.lease_expires_at <= moment:
                ai_metrics.job_event(self._metrics_kind(), "lease_expired")
                raise LeaseError("LEASE_EXPIRED", "The current worker lease must be recovered before a new claim")
        if self.execution_state not in {ExecutionState.QUEUED.value, ExecutionState.RETRY_WAIT.value}:
            raise LeaseError("LEASE_NOT_CLAIMABLE", "The job is not waiting for a worker")
        if self.next_retry_at and self.next_retry_at > moment:
            raise LeaseError("RETRY_NOT_READY", "The retry backoff has not elapsed")
        if self.lease_owner and self.lease_expires_at and self.lease_expires_at > moment:
            raise LeaseError("LEASE_HELD", "Another worker currently holds the job lease")
        before = self.execution_state
        self.execution_state = ExecutionState.RUNNING.value
        self.lifecycle_status = "active"
        self.attempt_no += 1
        self.lease_owner = worker
        self.fencing_token = uuid.uuid4().hex
        self.lease_expires_at = moment + timedelta(seconds=seconds)
        self.heartbeat_at = moment
        self.started_at = self.started_at or moment
        self.next_retry_at = None
        self._touch(worker)
        self._audit("job_claimed", actor=worker, request_id=request_id, before_state=before, after_state=self.execution_state, lease_expires_at=_iso(self.lease_expires_at), fencing_token=self.fencing_token)
        ai_metrics.job_event(self._metrics_kind(), "claimed")
        return self.to_dict()

    @_synchronized
    def heartbeat(self, worker_id: str, fencing_token: str, *, lease_seconds: int = _DEFAULT_LEASE_SECONDS, now: datetime | None = None, request_id: str = "") -> dict[str, Any]:
        worker = _clean_text(worker_id, field="worker_id", maximum=256, required=True)
        token = _clean_text(fencing_token, field="fencing_token", maximum=128, required=True)
        moment = now or _now()
        if self.execution_state != ExecutionState.RUNNING.value or self.lease_owner != worker or self.fencing_token != token:
            ai_metrics.job_event(self._metrics_kind(), "lease_lost")
            raise LeaseError("STALE_LEASE", "The worker lease is stale")
        if not self.lease_expires_at or self.lease_expires_at <= moment:
            ai_metrics.job_event(self._metrics_kind(), "lease_expired")
            raise LeaseError("LEASE_EXPIRED", "The worker lease has expired")
        try:
            seconds = int(lease_seconds)
        except (TypeError, ValueError) as exc:
            raise LeaseError("LEASE_INVALID", "lease_seconds is invalid") from exc
        if seconds < 1 or seconds > _MAX_LEASE_SECONDS:
            raise LeaseError("LEASE_INVALID", "lease_seconds is outside the allowed range")
        self.heartbeat_at = moment
        self.lease_expires_at = moment + timedelta(seconds=seconds)
        self._touch(worker)
        self._audit("lease_heartbeat", actor=worker, request_id=request_id, lease_expires_at=_iso(self.lease_expires_at), fencing_token=self.fencing_token)
        return self.to_dict()

    @_synchronized
    def request_cancel(self, actor: str, *, reason: str = "", request_id: str = "") -> dict[str, Any]:
        actor_value = _clean_text(actor, field="actor", maximum=256, required=True)
        if self.execution_state == ExecutionState.CANCELLED.value:
            return self.to_dict()
        if self.execution_state in TERMINAL_EXECUTION_STATES:
            raise IngestionPipelineError("CANCEL_NOT_ALLOWED", "A terminal job cannot be cancelled", status_code=409)
        if self.execution_state == ExecutionState.CANCEL_REQUESTED.value:
            return self.to_dict()
        if self.execution_state not in {ExecutionState.QUEUED.value, ExecutionState.RUNNING.value}:
            raise IngestionPipelineError("CANCEL_NOT_ALLOWED", "The job cannot be cancelled in its current state", status_code=409)
        self.cancel_requested_at = self.cancel_requested_at or _now()
        self.cancel_requested_by = self.cancel_requested_by or actor_value
        self.cancellation_reason = _clean_text(reason, field="cancellation_reason", maximum=1024)
        self.transition_execution_state(ExecutionState.CANCEL_REQUESTED.value, actor=actor_value, request_id=request_id)
        self._audit("cancel_requested", actor=actor_value, request_id=request_id, cancellation_reason=self.cancellation_reason)
        return self.to_dict()

    @_synchronized
    def acknowledge_cancel(self, worker_id: str = "system", fencing_token: str = "", *, request_id: str = "") -> dict[str, Any]:
        if self.execution_state != ExecutionState.CANCEL_REQUESTED.value:
            if self.execution_state == ExecutionState.CANCELLED.value:
                return self.to_dict()
            raise IngestionPipelineError("CANCEL_NOT_REQUESTED", "Cancellation has not been requested", status_code=409)
        if self.lease_owner:
            if self.lease_owner != worker_id or (fencing_token and fencing_token != self.fencing_token):
                raise LeaseError("STALE_LEASE", "The worker lease is stale")
        self.cancelled_at = self.cancelled_at or _now()
        self.cancelled_by = _clean_text(worker_id, field="worker_id", maximum=256) or "system"
        self.transition_execution_state(ExecutionState.CANCELLED.value, actor=self.cancelled_by, request_id=request_id)
        return self.advance_phase(IngestionPhase.CANCELLED.value, actor=self.cancelled_by, request_id=request_id)

    @_synchronized
    def schedule_retry(self, *, actor: str = "system", request_id: str = "", backoff_seconds: int = 0) -> dict[str, Any]:
        if self.execution_state != ExecutionState.RUNNING.value:
            raise InvalidTransitionError(self.execution_state, ExecutionState.RETRY_WAIT.value)
        if self.retry_count >= self.max_retries:
            raise IngestionPipelineError("RETRY_BUDGET_EXHAUSTED", "The retry budget is exhausted", status_code=409)
        try:
            delay = max(0, min(int(backoff_seconds), 86_400))
        except (TypeError, ValueError) as exc:
            raise IngestionPipelineError("INVALID_RETRY_BACKOFF", "backoff_seconds is invalid") from exc
        self.retry_count += 1
        self.next_retry_at = _now() + timedelta(seconds=delay)
        self.lease_owner = ""
        self.lease_expires_at = None
        self.heartbeat_at = None
        self.fencing_token = ""
        self.transition_execution_state(ExecutionState.RETRY_WAIT.value, actor=actor, request_id=request_id)
        self._audit("retry_scheduled", actor=actor, request_id=request_id, retry_count=self.retry_count, next_retry_at=_iso(self.next_retry_at))
        ai_metrics.job_event(self._metrics_kind(), "retry_scheduled")
        return self.to_dict()

    @_synchronized
    def fail(self, error: IngestionErrorDetail | BaseException | str, *, actor: str = "system", request_id: str = "") -> dict[str, Any]:
        detail = error if isinstance(error, IngestionErrorDetail) else classify_ingestion_error(error, phase=self.phase, attempt_no=self.attempt_no, correlation_id=request_id)
        self.record_error(detail, actor=actor, request_id=request_id)
        if detail.retryable and self.execution_state == ExecutionState.RUNNING.value and self.retry_count < self.max_retries:
            return self.schedule_retry(actor=actor, request_id=request_id)
        if self.phase not in {IngestionPhase.FAILED.value, IngestionPhase.CANCELLED.value}:
            before_phase = self.phase
            self.phase = IngestionPhase.FAILED.value
            self.phase_started_at = _now()
            self._audit("phase_changed", actor=actor, request_id=request_id, before_phase=before_phase, after_phase=IngestionPhase.FAILED.value, evidence={"error_code": detail.code})
        if self.execution_state == ExecutionState.RETRY_WAIT.value:
            self.execution_state = ExecutionState.RUNNING.value
        if self.execution_state != ExecutionState.FAILED.value:
            self.transition_execution_state(ExecutionState.FAILED.value, actor=actor, request_id=request_id)
        ai_metrics.job_event(self._metrics_kind(), "failed")
        return self.to_dict()

    @_synchronized
    def complete(self, *, actor: str = "system", request_id: str = "") -> dict[str, Any]:
        if self.phase != IngestionPhase.COMPLETED.value:
            raise InvalidPhaseError(self.phase, IngestionPhase.COMPLETED.value, code="COMPLETION_PHASE_REQUIRED")
        result = self.transition_execution_state(ExecutionState.SUCCEEDED.value, actor=actor, request_id=request_id)
        ai_metrics.job_event(self._metrics_kind(), "succeeded")
        return result

    @_synchronized
    def recover_expired_lease(self, *, now: datetime | None = None, request_id: str = "") -> dict[str, Any]:
        moment = now or _now()
        if self.execution_state != ExecutionState.RUNNING.value or not self.lease_expires_at or self.lease_expires_at > moment:
            return self.to_dict()
        ai_metrics.job_event(self._metrics_kind(), "lease_expired")
        self.record_error(
            classify_ingestion_error(IngestionErrorCode.WORKER_LOST.value, phase=self.phase, attempt_no=self.attempt_no, correlation_id=request_id, occurred_at=moment),
            actor="system",
            request_id=request_id,
        )
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            self.next_retry_at = moment
            self.lease_owner = ""
            self.lease_expires_at = None
            self.heartbeat_at = None
            self.fencing_token = ""
            self.transition_execution_state(ExecutionState.RETRY_WAIT.value, actor="system", request_id=request_id)
            self._audit("lease_expired", actor="system", request_id=request_id, next_retry_at=_iso(self.next_retry_at))
            ai_metrics.job_event(self._metrics_kind(), "retry_scheduled")
            return self.to_dict()
        self.phase = IngestionPhase.FAILED.value
        self.transition_execution_state(ExecutionState.FAILED.value, actor="system", request_id=request_id)
        self._audit("lease_expired", actor="system", request_id=request_id, terminal=True)
        ai_metrics.job_event(self._metrics_kind(), "failed")
        return self.to_dict()

    @_synchronized
    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "job_kind": self.job_kind,
            "idempotency_key": self.idempotency_key,
            "scope_fingerprint": self.scope_fingerprint,
            "dry_run": bool(self.dry_run),
            "status": self.lifecycle_status,
            "lifecycle_status": self.lifecycle_status,
            "execution_state": self.execution_state,
            "phase": self.phase,
            "phase_started_at": _iso(self.phase_started_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "retry_of_job_id": self.retry_of_job_id,
            "total_count": self.total_count,
            "processed_count": self.processed_count,
            "parsed_count": self.parsed_count,
            "failed_count": self.failed_count,
            "succeeded_count": self.succeeded_count,
            "skipped_count": self.skipped_count,
            "retryable_failed_count": self.retryable_failed_count,
            "error_count": self.error_count,
            "progress_percent": self.progress_percent,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "attempt_no": self.attempt_no,
            "next_retry_at": _iso(self.next_retry_at),
            "last_error_code": self.last_error_code,
            "last_error_at": _iso(self.last_error_at),
            "cancel_requested_at": _iso(self.cancel_requested_at),
            "cancel_requested_by": self.cancel_requested_by,
            "cancellation_reason": self.cancellation_reason,
            "cancelled_at": _iso(self.cancelled_at),
            "cancelled_by": self.cancelled_by,
            "lease_owner": self.lease_owner,
            "lease_expires_at": _iso(self.lease_expires_at),
            "heartbeat_at": _iso(self.heartbeat_at),
            "fencing_token": self.fencing_token,
            "errors": copy.deepcopy(self.errors),
            "phase_history": copy.deepcopy(self.phase_history),
            "audit_events": copy.deepcopy(self.audit_events),
        }
        return result

    @_synchronized
    def to_public_dict(self) -> dict[str, Any]:
        """Return an operator snapshot without worker fence material."""
        result = self.to_dict()
        result["lease_held"] = bool(result.get("lease_owner"))
        result["lease_owner"] = ""
        result.pop("fencing_token", None)
        for event in result.get("audit_events", []):
            if isinstance(event, dict):
                event.pop("fencing_token", None)
                event.pop("lease_owner", None)
        return result


class IngestionPipeline:
    """Thread-safe contract repository used until the DB-011 migration gate."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, IngestionJob] = {}
        self._idempotency: dict[tuple[str, str], str] = {}

    def _job_for_tenant_locked(self, job_id: str, tenant_id: str) -> IngestionJob:
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        job = self._jobs.get(str(job_id))
        if not job or job.tenant_id != tenant:
            raise IngestionPipelineError("JOB_NOT_FOUND", "The ingestion job was not found", status_code=404)
        return job

    def claim_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        worker_id: str,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
        request_id: str = "",
    ) -> IngestionJob:
        """Atomically resolve a tenant job and claim its process-local lease."""
        with self._lock:
            job = self._job_for_tenant_locked(job_id, tenant_id)
            moment = now or _now()
            if job.execution_state == ExecutionState.RUNNING.value and job.lease_expires_at and job.lease_expires_at <= moment:
                job.recover_expired_lease(now=moment, request_id=request_id)
            job.claim(worker_id, lease_seconds=lease_seconds, now=now, request_id=request_id)
            return job

    def heartbeat_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        worker_id: str,
        fencing_token: str,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
        now: datetime | None = None,
        request_id: str = "",
    ) -> IngestionJob:
        """Heartbeat only when the tenant, worker and fencing token match."""
        with self._lock:
            job = self._job_for_tenant_locked(job_id, tenant_id)
            job.heartbeat(worker_id, fencing_token, lease_seconds=lease_seconds, now=now, request_id=request_id)
            return job

    def acknowledge_cancel_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        worker_id: str = "system",
        fencing_token: str = "",
        request_id: str = "",
    ) -> IngestionJob:
        with self._lock:
            job = self._job_for_tenant_locked(job_id, tenant_id)
            job.acknowledge_cancel(worker_id, fencing_token, request_id=request_id)
            return job

    def request_cancel(
        self,
        job_id: str,
        *,
        tenant_id: str,
        actor: str,
        reason: str = "",
        request_id: str = "",
        acknowledge_unclaimed: bool = True,
    ) -> IngestionJob:
        """Request cooperative cancellation for one tenant-scoped job.

        A queued job has no side effect or worker lease, so the API may safely
        acknowledge that request immediately.  A running job remains in
        ``cancel_requested`` until its current worker reaches a safe point.
        Repeated requests return the same snapshot and do not create extra
        work or audit side effects.
        """
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        actor_value = _clean_text(actor, field="actor", maximum=256, required=True)
        with self._lock:
            job = self._job_for_tenant_locked(job_id, tenant)
            job.request_cancel(actor_value, reason=reason, request_id=request_id)
            if acknowledge_unclaimed and job.execution_state == ExecutionState.CANCEL_REQUESTED.value and not job.lease_owner:
                job.acknowledge_cancel(actor_value, request_id=request_id)
            return job

    def retry_job(
        self,
        job_id: str,
        *,
        tenant_id: str,
        actor: str,
        request_id: str = "",
    ) -> IngestionJob:
        """Create a new queued attempt for a terminal failed job.

        Terminal success/cancellation is never replayed.  A failed job is
        retained as evidence and a child job receives a deterministic retry
        key.  This keeps idempotency and side-effect boundaries explicit until
        the durable Import Job migration is enabled by ING-017/MIG gates.
        """
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        actor_value = _clean_text(actor, field="actor", maximum=256, required=True)
        request_value = _clean_text(request_id, field="request_id", maximum=256)
        with self._lock:
            original = self._jobs.get(str(job_id))
            if not original or original.tenant_id != tenant:
                raise IngestionPipelineError("JOB_NOT_FOUND", "The ingestion job was not found", status_code=404)
            if original.execution_state == ExecutionState.RETRY_WAIT.value:
                raise IngestionPipelineError("RETRY_ALREADY_SCHEDULED", "The ingestion job is already waiting for a retry", status_code=409)
            if original.execution_state != ExecutionState.FAILED.value:
                raise IngestionPipelineError("RETRY_NOT_ALLOWED", "Only a failed ingestion job can be retried", status_code=409)

            # A repeated request for the same failed parent returns the latest
            # non-terminal child.  This is the process-local equivalent of a
            # tenant/request idempotency key and prevents duplicate attempts.
            children = [
                item for item in self._jobs.values()
                if item.tenant_id == tenant and item.retry_of_job_id == original.id
            ]
            active_children = [item for item in children if not item.terminal]
            if active_children:
                child = sorted(active_children, key=lambda item: (item.created_at, item.id))[-1]
                if request_value:
                    child._audit("retry_replayed", actor=actor_value, request_id=request_value, retry_of_job_id=original.id)
                return child

            attempt = len(children) + 1
            retry_key = f"{original.idempotency_key}:retry:{attempt}"
            if len(retry_key) > 256:
                retry_key = retry_key[:256]
            child = IngestionJob(
                id=f"ing_{uuid.uuid4().hex}",
                tenant_id=tenant,
                job_kind=original.job_kind,
                idempotency_key=retry_key,
                scope_fingerprint=original.scope_fingerprint,
                max_retries=original.max_retries,
                dry_run=original.dry_run,
                created_by=actor_value,
                updated_by=actor_value,
                retry_of_job_id=original.id,
            )
            child._audit(
                "job_created",
                actor=actor_value,
                request_id=request_value,
                scope_fingerprint=child.scope_fingerprint,
                dry_run=child.dry_run,
                retry_of_job_id=original.id,
            )
            original._touch(actor_value)
            original._audit("retry_requested", actor=actor_value, request_id=request_value, retry_job_id=child.id)
            self._jobs[child.id] = child
            self._idempotency[(tenant, retry_key)] = child.id
            ai_metrics.job_event(child._metrics_kind(), "enqueued")
            ai_metrics.job_event(child._metrics_kind(), "retry_created")
            return child

    def create_job(
        self,
        *,
        tenant_id: str,
        job_kind: str,
        idempotency_key: str,
        scope: dict[str, Any] | None = None,
        dry_run: bool = False,
        max_retries: int = 0,
        actor: str = "system",
    ) -> IngestionJob:
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        kind = _enum_value(JobKind, job_kind, field="job_kind")
        key = _clean_text(idempotency_key, field="idempotency_key", maximum=256, required=True)
        fingerprint = _safe_scope_fingerprint(scope)
        with self._lock:
            existing_id = self._idempotency.get((tenant, key))
            if existing_id:
                existing = self._jobs[existing_id]
                if existing.scope_fingerprint != fingerprint or existing.job_kind != kind:
                    raise IdempotencyConflictError()
                return existing
            job = IngestionJob(
                id=f"ing_{uuid.uuid4().hex}",
                tenant_id=tenant,
                job_kind=kind,
                idempotency_key=key,
                scope_fingerprint=fingerprint,
                max_retries=max_retries,
                dry_run=bool(dry_run),
                created_by=actor,
                updated_by=actor,
            )
            job._audit("job_created", actor=actor, scope_fingerprint=fingerprint, dry_run=bool(dry_run))
            self._jobs[job.id] = job
            self._idempotency[(tenant, key)] = job.id
            ai_metrics.job_event(job._metrics_kind(), "enqueued")
            return job

    def get_job(self, job_id: str, *, tenant_id: str) -> IngestionJob | None:
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job or job.tenant_id != tenant:
                return None
            return job

    def list_jobs(self, *, tenant_id: str, execution_state: str = "") -> list[dict[str, Any]]:
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        state = _enum_value(ExecutionState, execution_state, field="execution_state") if execution_state else ""
        with self._lock:
            values = [job.to_dict() for job in self._jobs.values() if job.tenant_id == tenant and (not state or job.execution_state == state)]
        return sorted(values, key=lambda item: (item["created_at"] or "", item["id"]))

    def list_jobs_page(
        self,
        *,
        tenant_id: str,
        execution_state: str = "",
        phase: str = "",
        job_kind: str = "",
        search: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a bounded tenant-scoped job summary page.

        The in-process pipeline remains the compatibility implementation until
        DB-011 is physically migrated.  Keeping filtering and slicing here
        preserves the same API contract when the repository is replaced by a
        PostgreSQL query, and prevents the list endpoint from returning the
        full error/audit payload for every job.
        """
        tenant = _clean_text(tenant_id, field="tenant_id", maximum=128, required=True)
        state = _enum_value(ExecutionState, execution_state, field="execution_state") if execution_state else ""
        phase_value = _enum_value(IngestionPhase, phase, field="phase") if phase else ""
        kind_value = _enum_value(JobKind, job_kind, field="job_kind") if job_kind else ""
        query = _clean_text(search, field="search", maximum=128, required=False).casefold()
        if page < 1 or page_size < 1 or page_size > 100:
            raise IngestionPipelineError("INVALID_PIPELINE_INPUT", "page must be >= 1 and page_size must be between 1 and 100")
        with self._lock:
            values = []
            for job in self._jobs.values():
                if job.tenant_id != tenant:
                    continue
                if state and job.execution_state != state:
                    continue
                if phase_value and job.phase != phase_value:
                    continue
                if kind_value and job.job_kind != kind_value:
                    continue
                if query:
                    haystack = " ".join(
                        str(value or "")
                        for value in (job.id, job.job_kind, job.execution_state, job.phase, job.last_error_code, job.scope_fingerprint)
                    ).casefold()
                    if query not in haystack:
                        continue
                values.append(job.to_dict())
        values.sort(key=lambda item: (item.get("created_at") or "", item.get("id") or ""), reverse=True)
        total = len(values)
        offset = (page - 1) * page_size
        return values[offset:offset + page_size], total

    def reset_for_tests(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._idempotency.clear()

    def observability_snapshot(self, *, family: str = "import", now: datetime | None = None) -> dict[str, int]:
        """Return aggregate Import/Reindex queue gauges without identifiers."""

        selected_family = str(family or "import").strip().lower()
        if selected_family not in {"import", "reindex"}:
            selected_family = "import"
        moment = now or _now()
        counts = {
            "queued": 0,
            "retry_wait": 0,
            "running": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
            "backlog": 0,
            "lease_anomalies": 0,
            "lease_expired": 0,
            "document_failures": 0,
        }
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job._metrics_kind() != selected_family:
                continue
            state = str(job.execution_state or "").lower()
            if state in counts:
                counts[state] += 1
            if state in {ExecutionState.QUEUED.value, ExecutionState.RETRY_WAIT.value}:
                counts["backlog"] += 1
            if state == ExecutionState.RUNNING.value:
                if not job.lease_owner or not job.lease_expires_at or job.lease_expires_at <= moment:
                    counts["lease_anomalies"] += 1
                    counts["lease_expired"] += 1
            counts["document_failures"] += max(0, int(job.failed_count or 0))
            for event in job.audit_events:
                if isinstance(event, dict) and event.get("event_type") == "lease_expired":
                    counts["lease_expired"] += 1
        return counts

    def recover_expired_leases(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [job.recover_expired_lease(now=now) for job in self._jobs.values()]


ingestion_pipeline = IngestionPipeline()


def create_ingestion_job(**kwargs: Any) -> dict[str, Any]:
    return ingestion_pipeline.create_job(**kwargs).to_dict()


__all__ = [
    "ERROR_CATALOG",
    "EXECUTION_STATES",
    "EXECUTION_TRANSITIONS",
    "IngestionErrorCode",
    "IngestionErrorDetail",
    "IngestionJob",
    "IngestionPhase",
    "IngestionPipeline",
    "IngestionPipelineError",
    "InvalidPhaseError",
    "InvalidTransitionError",
    "JOB_KINDS",
    "JobKind",
    "LeaseError",
    "NON_RETRYABLE_ERROR_CODES",
    "PHASE_ORDER",
    "PHASES",
    "ProgressInvariantError",
    "RETRYABLE_ERROR_CODES",
    "classify_ingestion_error",
    "create_ingestion_job",
    "error_catalog",
    "ingestion_pipeline",
]
