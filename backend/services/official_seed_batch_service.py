"""ING-022 bounded official Seed URL batch collection.

The batch adapter composes the reviewed single-URL importer. CAT-001,
CAT-003 and CAT-004 remain the only URL, source-registry and network
authorities while this module adds a small tenant-scoped scheduler.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from services.official_url_import_service import OfficialUrlImportError, import_single_official_url
from services.source_registry_service import SourceRegistryError, validate_official_url_input


MAX_SEED_ITEMS = 20
MAX_RATE_LIMIT_PER_MINUTE = 30
DEFAULT_RATE_LIMIT_PER_MINUTE = 6


class OfficialSeedBatchError(ValueError):
    """Stable, safe error for a rejected batch before network activity."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class _TenantHostRateLimiter:
    """Process-local fixed-spacing limiter; reservation is concurrency-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_allowed: dict[tuple[str, str], float] = {}

    def reserve(self, *, tenant_id: str, host: str, rate_limit_per_minute: int, now: float | None = None) -> float:
        interval = 60.0 / float(rate_limit_per_minute)
        moment = time.monotonic() if now is None else float(now)
        key = (str(tenant_id), str(host).lower())
        with self._lock:
            scheduled = max(moment, self._next_allowed.get(key, moment))
            self._next_allowed[key] = scheduled + interval
        return max(0.0, scheduled - moment)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._next_allowed.clear()


rate_limiter = _TenantHostRateLimiter()


def _tenant(user: Mapping[str, Any]) -> str:
    return str(user.get("tenant_id") or "tenant-default").strip() or "tenant-default"


def _bounded_text(value: Any, *, maximum: int = 256) -> str:
    text = str(value or "").strip()
    return text[:maximum]


def _item_payload(item: Mapping[str, Any], *, index: int, batch_request_id: str) -> dict[str, Any]:
    payload = copy.deepcopy(dict(item))
    payload["request_id"] = _bounded_text(payload.get("request_id") or f"{batch_request_id}:item:{index + 1}", maximum=256)
    return payload


def _preflight_item(item: Mapping[str, Any], *, index: int, user: Mapping[str, Any]) -> dict[str, Any]:
    url = _bounded_text(item.get("url"), maximum=4096)
    source_kind = _bounded_text(item.get("source_kind") or "product_page", maximum=64).lower()
    metadata = {
        "vendor": _bounded_text(item.get("vendor"), maximum=128),
        "product_family": _bounded_text(item.get("product_family"), maximum=256),
        "version_scope": copy.deepcopy(item.get("version_scope") or {}),
        "terms_review_status": _bounded_text(item.get("terms_review_status"), maximum=32).lower(),
        "reviewer": _bounded_text(item.get("reviewer") or user.get("username") or user.get("id") or "system", maximum=256),
        "reviewed_at": _bounded_text(item.get("reviewed_at"), maximum=128),
    }
    try:
        preflight = validate_official_url_input(url, source_kind=source_kind, metadata=metadata)
    except SourceRegistryError as exc:
        detail = {"index": index, "code": str(exc.code or "SEED_PREFLIGHT_FAILED")[:128]}
        raise OfficialSeedBatchError(
            "SEED_PREFLIGHT_FAILED",
            "One or more Seed URLs failed the official-source preflight",
            status_code=exc.status_code,
            details=[detail],
        ) from exc
    return {
        "index": index,
        "canonical_url": str(preflight.get("canonical_url") or ""),
        "host": str(urlsplit(str(preflight.get("canonical_url") or url)).hostname or "").lower(),
        "source_kind": source_kind,
        "payload": dict(item),
    }


def _public_result(result: Mapping[str, Any], *, index: int, canonical_url: str) -> dict[str, Any]:
    job = result.get("job") if isinstance(result.get("job"), Mapping) else {}
    source = result.get("source") if isinstance(result.get("source"), Mapping) else {}
    version = result.get("version") if isinstance(result.get("version"), Mapping) else {}
    error = result.get("error") if isinstance(result.get("error"), Mapping) else {}
    return {
        "index": index,
        "url": canonical_url,
        "success": bool(result.get("success")),
        "replayed": bool(result.get("replayed")),
        "continuation_required": bool(result.get("continuation_required")),
        "job": {
            "id": str(job.get("id") or ""),
            "execution_state": str(job.get("execution_state") or ""),
            "phase": str(job.get("phase") or ""),
            "progress_percent": float(job.get("progress_percent") or 0),
        },
        "source_id": str(source.get("id") or ""),
        "source_version_id": str(version.get("id") or ""),
        "error": {
            "code": str(error.get("code") or "")[:128],
            "retryable": bool(error.get("retryable")),
        } if error else None,
    }


def collect_official_seed_batch(
    user: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
    request_id: str = "",
    importer: Callable[..., dict[str, Any]] = import_single_official_url,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect at most 20 reviewed URLs sequentially.

    Every item is preflighted before the first network call. A single invalid
    URL therefore cannot create a partially collected batch. Runtime source
    errors are represented per item so successful results stay visible.
    """

    if not isinstance(items, Sequence) or isinstance(items, (str, bytes, bytearray)):
        raise OfficialSeedBatchError("SEED_ITEMS_INVALID", "Seed items must be a list", status_code=400)
    if not 1 <= len(items) <= MAX_SEED_ITEMS:
        raise OfficialSeedBatchError(
            "SEED_BATCH_SIZE_INVALID",
            f"Seed batch must contain 1 to {MAX_SEED_ITEMS} items",
            status_code=400,
        )
    try:
        rate = int(rate_limit_per_minute)
    except (TypeError, ValueError) as exc:
        raise OfficialSeedBatchError("SEED_RATE_LIMIT_INVALID", "rate_limit_per_minute must be an integer", status_code=400) from exc
    if not 1 <= rate <= MAX_RATE_LIMIT_PER_MINUTE:
        raise OfficialSeedBatchError(
            "SEED_RATE_LIMIT_INVALID",
            f"rate_limit_per_minute must be between 1 and {MAX_RATE_LIMIT_PER_MINUTE}",
            status_code=400,
        )
    batch_request_id = _bounded_text(request_id or f"seed_batch_{uuid.uuid4().hex[:16]}", maximum=256)
    preflighted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise OfficialSeedBatchError("SEED_ITEM_INVALID", "Each Seed item must be an object", status_code=400, details=[{"index": index}])
        candidate = _preflight_item(item, index=index, user=user)
        if not candidate["canonical_url"] or candidate["canonical_url"] in seen:
            raise OfficialSeedBatchError("SEED_DUPLICATE_URL", "Seed URLs must be unique after canonicalization", status_code=409, details=[{"index": index}])
        seen.add(candidate["canonical_url"])
        preflighted.append(candidate)

    started = time.monotonic()
    results: list[dict[str, Any]] = []
    for candidate in preflighted:
        wait_seconds = rate_limiter.reserve(
            tenant_id=_tenant(user),
            host=candidate["host"],
            rate_limit_per_minute=rate,
        )
        if wait_seconds > 0:
            sleeper(wait_seconds)
        payload = _item_payload(candidate["payload"], index=candidate["index"], batch_request_id=batch_request_id)
        try:
            result = importer(user, payload)
        except OfficialUrlImportError as exc:
            result = {
                "success": False,
                "error": {"code": str(exc.code or "SEED_IMPORT_FAILED")[:128], "retryable": False},
                "continuation_required": False,
                "replayed": False,
            }
        except Exception:
            result = {
                "success": False,
                "error": {"code": "SEED_IMPORT_FAILED", "retryable": True},
                "continuation_required": False,
                "replayed": False,
            }
        results.append(_public_result(result, index=candidate["index"], canonical_url=candidate["canonical_url"]))
    succeeded = sum(1 for item in results if item["success"])
    return {
        "batch_id": batch_request_id,
        "tenant_id": _tenant(user),
        "item_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": len(results) - succeeded,
        "rate_limit_per_minute": rate,
        "elapsed_ms": max(0, int((time.monotonic() - started) * 1000)),
        "items": results,
    }


__all__ = [
    "DEFAULT_RATE_LIMIT_PER_MINUTE",
    "MAX_RATE_LIMIT_PER_MINUTE",
    "MAX_SEED_ITEMS",
    "OfficialSeedBatchError",
    "collect_official_seed_batch",
    "rate_limiter",
]
