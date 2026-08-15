"""Periodic source freshness refresh for ING-018.

The scheduler invokes this bounded worker every 30 minutes.  It reuses the
CAT-004 outbound boundary and Source Registry write boundary, so validators
are sent only from server-owned manifests and a refresh never returns or
persists a response body.  Errors are reduced to stable codes per source.
"""

from __future__ import annotations

import logging
from typing import Any

import database as _database
from database import get_db_connection
from services.source_registry_service import (
    SourceRegistryError,
    collect_source,
    list_sources,
    record_source_refresh_observation,
)


logger = logging.getLogger(__name__)
DEFAULT_REFRESH_LIMIT = 100
MAX_REFRESH_LIMIT = 500
REFRESH_INTERVAL_MINUTES = 30


def _freshness_schema_ready() -> bool:
    """Keep the V1-only runtime quiet until the release-gated V2 schema exists."""
    try:
        with get_db_connection() as conn:
            if _database._USE_PG:
                row = conn.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'kb_source_refresh_observation' AND column_name = 'detection_type'"
                ).fetchone()
                return bool(row)
            row = conn.execute(
                "SELECT 1 FROM pragma_table_info('kb_source_refresh_observation') WHERE name = ?",
                ("detection_type",),
            ).fetchone()
            return bool(row)
    except Exception:
        return False


def _scheduler_user(tenant_id: str | None = None) -> dict[str, Any]:
    user: dict[str, Any] = {
        "id": "scheduler:knowledge-source-freshness",
        "user_id": "scheduler:knowledge-source-freshness",
        "username": "knowledge-source-freshness",
        "role": "Administrator",
    }
    if tenant_id:
        user["tenant_id"] = str(tenant_id)
    return user


def _safe_error_code(exc: BaseException) -> str:
    code = str(getattr(exc, "code", "SOURCE_REFRESH_FAILED") or "SOURCE_REFRESH_FAILED")
    return code[:128] if code.replace("_", "").isalnum() else "SOURCE_REFRESH_FAILED"


def refresh_sources(
    *,
    tenant_id: str | None = None,
    limit: int = DEFAULT_REFRESH_LIMIT,
    user: dict[str, Any] | None = None,
    transport: Any = None,
    resolver: Any = None,
    client_factory: Any = None,
) -> dict[str, Any]:
    """Refresh active sources in one tenant-scoped, bounded batch.

    ``transport``, ``resolver`` and ``client_factory`` are test-only seams;
    production callers leave them unset so CAT-004 owns DNS, TLS, redirects,
    response limits and proxy disabling.
    """
    try:
        bounded_limit = max(1, min(MAX_REFRESH_LIMIT, int(limit)))
    except (TypeError, ValueError) as exc:
        raise SourceRegistryError("INVALID_REFRESH_LIMIT", "Refresh limit is invalid") from exc
    if not _freshness_schema_ready():
        raise SourceRegistryError(
            "SOURCE_FRESHNESS_SCHEMA_UNAVAILABLE",
            "Knowledge source freshness schema is not enabled",
            status_code=503,
        )
    actor = user or _scheduler_user(tenant_id)
    sources = list_sources(actor, status="active", tenant_id=tenant_id)
    sources = sources[:bounded_limit]
    summary: dict[str, Any] = {
        "tenant_id": str(tenant_id or "") if tenant_id else None,
        "selected": len(sources),
        "checked": 0,
        "not_modified": 0,
        "unchanged": 0,
        "changed": 0,
        "failed": 0,
        "removed": 0,
        "replacement": 0,
        "version_updated": 0,
        "results": [],
    }
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        try:
            result = collect_source(
                source_id,
                {"method": "GET", "refresh": True},
                actor,
                transport=transport,
                resolver=resolver,
                client_factory=client_factory,
            )
            refresh = result.get("refresh") or {}
            outcome = str(refresh.get("outcome") or ("unchanged" if (result.get("version") or {}).get("deduplicated") else "changed"))
            if outcome not in {"not_modified", "unchanged", "changed"}:
                outcome = "changed"
            summary[outcome] += 1
            detection_type = str(refresh.get("detection_type") or "none")
            if detection_type in {"removed", "replacement", "version_updated"}:
                summary[detection_type] += 1
            summary["checked"] += 1
            # Keep the scheduler result ID/hash-only.  No source URL, body or
            # response error text crosses this operational boundary.
            summary["results"].append({
                "source_id": source_id,
                "outcome": outcome,
                "content_hash": str(refresh.get("content_hash") or (result.get("version") or {}).get("content_hash") or "")[:64],
                "detection_type": detection_type,
                "action_status": str(((refresh.get("change_application") or {}).get("action_status") or ""))[:32],
            })
        except SourceRegistryError as exc:
            code = _safe_error_code(exc)
            details = exc.details if isinstance(exc.details, dict) else {}
            raw_http_status = details.get("http_status")
            http_status = int(raw_http_status) if isinstance(raw_http_status, int) and 100 <= raw_http_status <= 599 else None
            summary["failed"] += 1
            summary["checked"] += 1
            try:
                record_source_refresh_observation(
                    source_id,
                    {
                        "request_method": "GET",
                        "http_status": http_status,
                        "outcome": "failed",
                        "error_code": code,
                        "error": {"code": code},
                        "metadata": {"worker": "knowledge-source-freshness"},
                    },
                    actor,
                )
            except Exception:
                logger.warning("Could not persist source refresh failure observation", extra={"source_id": source_id, "code": code})
            summary["results"].append({"source_id": source_id, "outcome": "failed", "error_code": code})
        except Exception:
            # A single source cannot stop the tenant batch.  Deliberately do
            # not expose the exception text; it may contain provider details.
            summary["failed"] += 1
            summary["checked"] += 1
            try:
                record_source_refresh_observation(
                    source_id,
                    {
                        "request_method": "GET",
                        "outcome": "failed",
                        "error_code": "SOURCE_REFRESH_FAILED",
                        "error": {"code": "SOURCE_REFRESH_FAILED"},
                        "metadata": {"worker": "knowledge-source-freshness"},
                    },
                    actor,
                )
            except Exception:
                logger.warning("Could not persist source refresh failure observation", extra={"source_id": source_id})
            summary["results"].append({"source_id": source_id, "outcome": "failed", "error_code": "SOURCE_REFRESH_FAILED"})
    return summary


def run_scheduled_source_freshness_refresh() -> dict[str, Any]:
    """APScheduler entrypoint; all cross-instance locking is external."""
    try:
        result = refresh_sources()
    except SourceRegistryError as exc:
        # V1 installations may not yet have the release-gated V2 migrations.
        # The periodic job must be a no-op with a stable, redacted status until
        # the migration cutover is approved.
        if exc.code != "SOURCE_FRESHNESS_SCHEMA_UNAVAILABLE":
            raise
        result = {
            "tenant_id": None,
            "selected": 0,
            "checked": 0,
            "not_modified": 0,
            "unchanged": 0,
            "changed": 0,
            "failed": 0,
            "removed": 0,
            "replacement": 0,
            "version_updated": 0,
            "status": "blocked_schema",
            "error_code": exc.code,
            "results": [],
        }
    logger.info(
        "Knowledge source freshness refresh completed selected=%s checked=%s changed=%s unchanged=%s not_modified=%s failed=%s removed=%s replacement=%s version_updated=%s",
        result["selected"], result["checked"], result["changed"], result["unchanged"], result["not_modified"], result["failed"],
        result["removed"], result["replacement"], result["version_updated"],
    )
    return result


__all__ = [
    "DEFAULT_REFRESH_LIMIT",
    "MAX_REFRESH_LIMIT",
    "REFRESH_INTERVAL_MINUTES",
    "refresh_sources",
    "run_scheduled_source_freshness_refresh",
]
