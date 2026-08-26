"""Read-only CAT-013 catalog adapter until DB-006 physical migration is gated.

The reviewed YAML seeds remain the only authority at this stage.  This service
exposes them to the UI and offers a dry-run Alias resolver, while explicitly
refusing to pretend that draft rows are durable production catalog facts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ai.services.product_alias_service import (
    AliasCandidateList,
    AliasRecord,
    build_alias_record,
    detect_alias_conflicts,
    list_alias_candidates,
)


_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_DIR = _ROOT / "docs" / "knowledge-engine-v2" / "catalog"
_PRODUCT_FILES = (
    _CATALOG_DIR / "CAT-005-HUAWEI-CE6800.yaml",
    _CATALOG_DIR / "CAT-006-CISCO-C9300.yaml",
    _CATALOG_DIR / "CAT-016-H3C-COMWARE.yaml",
    _CATALOG_DIR / "CAT-017-RUIJIE-RGOS.yaml",
)
_ALIAS_FILE = _CATALOG_DIR / "CAT-010-ALIAS-SAMPLES.yaml"
PERSISTENCE_STATUS = "contract_only_read_only_seed"
_REVIEWED_SEED_TENANT = "tenant-default-reviewed"
_RUNTIME_DEFAULT_TENANT = "tenant-default"
_CONTROL_CHARS = tuple(chr(value) for value in list(range(0, 32)) + [127])


class ProductCatalogError(ValueError):
    """Stable, user-safe catalog adapter error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _safe_text(value: Any, *, field: str, max_length: int = 256) -> str:
    text = str(value or "").strip()
    if len(text) > max_length or any(char in text for char in _CONTROL_CHARS):
        raise ProductCatalogError("CATALOG_FILTER_INVALID", f"{field} filter is invalid")
    return text


def _load(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProductCatalogError("CATALOG_SEED_UNAVAILABLE", "Reviewed catalog seed is unavailable", status_code=503) from exc
    if not isinstance(value, dict):
        raise ProductCatalogError("CATALOG_SEED_INVALID", "Reviewed catalog seed must be an object", status_code=503)
    return value


def _tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "tenant-default-reviewed").strip()


def _seed_model_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _PRODUCT_FILES:
        data = _load(path)
        vendor = data.get("vendor") or {}
        family = data.get("product_family") or {}
        series_rows = family.get("product_series") or []
        if not isinstance(vendor, dict) or not isinstance(family, dict) or not isinstance(series_rows, list):
            raise ProductCatalogError("CATALOG_SEED_INVALID", "Product hierarchy seed is malformed", status_code=503)
        vendor_id = str(vendor.get("vendor_id") or "").strip()
        family_code = str(family.get("code") or "").strip()
        for series in series_rows:
            if not isinstance(series, dict):
                continue
            series_code = str(series.get("code") or "").strip()
            for model in series.get("model_samples") or []:
                if not isinstance(model, dict):
                    continue
                model_code = str(model.get("model_code") or "").strip()
                if not vendor_id or not family_code or not series_code or not model_code:
                    continue
                rows.append({
                    "product_model_id": f"{vendor_id}:{family_code}:{series_code}:{model_code.lower()}",
                    "tenant_id": "tenant-default-reviewed",
                    "vendor_id": vendor_id,
                    "vendor_name": vendor.get("display_name") or vendor_id,
                    "family_code": family_code,
                    "family_name": family.get("display_name") or family_code,
                    "series_code": series_code,
                    "series_name": series.get("display_name") or series_code,
                    "model_code": model_code,
                    "display_name": model.get("display_name") or model_code,
                    "status": model.get("status") or "draft",
                    "review_status": model.get("review_status") or "pending_review",
                    "source_refs": list(model.get("source_refs") or []),
                    "software_scope": data.get("software_scope") or {},
                    "platform_binding_advisory": data.get("platform_binding_advisory") or {},
                    "source_artifact": path.name,
                })
    return sorted(rows, key=lambda item: (item["vendor_id"], item["family_code"], item["series_code"], item["model_code"]))


def _model_rows(tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return the reviewed seed or an explicitly imported tenant snapshot."""
    rows: list[dict[str, Any]] | None = None
    try:
        from services.catalog_version_service import get_active_catalog_rows

        rows = get_active_catalog_rows(tenant_id=tenant_id)
    except (ImportError, AttributeError):
        rows = None
    if rows is None:
        rows = _seed_model_rows()
    return rows


def _tenant_model_rows(tenant_id: str) -> list[dict[str, Any]]:
    """Return only the caller's catalog projection.

    The reviewed seed predates the runtime bootstrap tenant and is labelled
    ``tenant-default-reviewed`` in its source artifacts.  The built-in
    ``tenant-default`` admin tenant is allowed a read-only projection of that
    same official seed, with the response rows relabelled to the caller's
    tenant.  No other tenant receives the seed, and imported tenant snapshots
    remain authoritative when present.
    """
    rows = _model_rows(tenant_id)
    if tenant_id == _RUNTIME_DEFAULT_TENANT and rows and all(
        str(item.get("tenant_id") or "") == _REVIEWED_SEED_TENANT for item in rows
    ):
        return [{**item, "tenant_id": tenant_id} for item in rows]
    return [item for item in rows if str(item.get("tenant_id") or "") == tenant_id]


def _official_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate every catalog projection with the CAT-018 immutable boundary."""
    return [
        {
            **dict(item),
            "collection_kind": "official_catalog",
            "official": True,
            "read_only": True,
            "mutable": False,
            "custom_collection_id": None,
        }
        for item in rows
    ]


def _collection_boundary() -> dict[str, Any]:
    # Local import avoids coupling the CAT-013 seed adapter to the collection
    # registry implementation during application bootstrap.
    from services.catalog_collection_service import collection_boundary

    return collection_boundary()


def _alias_records(model_rows: list[dict[str, Any]], *, tenant_id: str) -> tuple[list[dict[str, Any]], list[AliasRecord], dict[str, dict[str, Any]]]:
    data = _load(_ALIAS_FILE)
    model_by_id = {item["product_model_id"]: item for item in model_rows}
    samples = data.get("alias_samples") or []
    if not isinstance(samples, list):
        raise ProductCatalogError("CATALOG_SEED_INVALID", "Alias sample seed is malformed", status_code=503)
    rows: list[dict[str, Any]] = []
    records: list[AliasRecord] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        model_id = str(sample.get("product_model_id") or "")
        if model_id not in model_by_id:
            continue
        record = build_alias_record({
            "id": sample.get("sample_id"),
            "tenant_id": tenant_id,
            "product_model_id": model_id,
            "alias": sample.get("alias"),
            "alias_kind": sample.get("alias_kind"),
            # Dry-run resolution uses only an in-memory active projection;
            # the response retains the original draft seed status.
            "status": "active",
        })
        records.append(record)
        row = record.to_dict()
        row["seed_status"] = sample.get("status") or "draft"
        row["expected_outcome"] = sample.get("expected_outcome") or ""
        row["model"] = model_by_id[model_id]
        rows.append(row)
    return rows, records, model_by_id


def list_product_catalog(
    user: dict[str, Any],
    *,
    vendor_id: str = "",
    family_code: str = "",
    series_code: str = "",
    model: str = "",
    software_version: str = "",
    status: str = "all",
    search: str = "",
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    rows = _tenant_model_rows(tenant_id)
    all_rows = list(rows)
    filters = {
        "vendor_id": _safe_text(vendor_id, field="vendor_id", max_length=64).casefold(),
        "family_code": _safe_text(family_code, field="family_code", max_length=64).casefold(),
        "series_code": _safe_text(series_code, field="series_code", max_length=64).casefold(),
        "model": _safe_text(model, field="model", max_length=128).casefold(),
        "software_version": _safe_text(software_version, field="software_version", max_length=128).casefold(),
        "status": _safe_text(status, field="status", max_length=32).casefold() or "all",
        "search": _safe_text(search, field="search", max_length=256).casefold(),
    }
    if filters["status"] not in {"all", "draft", "active", "disabled", "archived"}:
        raise ProductCatalogError("CATALOG_STATUS_INVALID", "status filter is invalid")
    if filters["vendor_id"]:
        rows = [item for item in rows if item["vendor_id"].casefold() == filters["vendor_id"]]
    if filters["family_code"]:
        rows = [item for item in rows if item["family_code"].casefold() == filters["family_code"]]
    if filters["series_code"]:
        rows = [item for item in rows if item["series_code"].casefold() == filters["series_code"]]
    if filters["model"]:
        rows = [item for item in rows if filters["model"] in item["model_code"].casefold() or filters["model"] in item["display_name"].casefold()]
    if filters["software_version"]:
        def version_matches(item: dict[str, Any]) -> bool:
            scope = item.get("software_scope") or {}
            values = [
                scope.get("primary_version"),
                scope.get("compatibility_version"),
                *(scope.get("software_versions") or []),
            ]
            return any(str(value or "").casefold() == filters["software_version"] for value in values)

        rows = [item for item in rows if version_matches(item)]
    if filters["status"] != "all":
        rows = [item for item in rows if str(item["status"]).casefold() == filters["status"]]
    if filters["search"]:
        needle = filters["search"]

        def search_matches(item: dict[str, Any]) -> bool:
            scope = item.get("software_scope") or {}
            values = (
                item.get("vendor_id"), item.get("vendor_name"), item.get("family_code"),
                item.get("family_name"), item.get("series_code"), item.get("series_name"),
                item.get("model_code"), item.get("display_name"), scope.get("os_family"),
                scope.get("software_train"), scope.get("primary_version"),
                scope.get("compatibility_version"), *(scope.get("software_versions") or []),
            )
            return any(needle in str(value or "").casefold() for value in values)

        rows = [item for item in rows if search_matches(item)]
    rows = _official_rows(rows)
    return {
        "persistence_status": PERSISTENCE_STATUS,
        "tenant_id": tenant_id,
        "items": rows,
        "total": len(rows),
        "read_only": True,
        "collection_kind": "official_catalog",
        "mutable": False,
        "boundary": _collection_boundary(),
        "source_artifacts": [path.name for path in _PRODUCT_FILES],
        "facets": {
            "vendors": sorted({str(item.get("vendor_id") or "") for item in all_rows if item.get("vendor_id")}),
            "families": sorted({str(item.get("family_code") or "") for item in all_rows if item.get("family_code")}),
            "series": sorted({str(item.get("series_code") or "") for item in all_rows if item.get("series_code")}),
            "software_versions": sorted({
                str(value)
                for item in all_rows
                for value in (
                    (item.get("software_scope") or {}).get("primary_version"),
                    (item.get("software_scope") or {}).get("compatibility_version"),
                    *((item.get("software_scope") or {}).get("software_versions") or []),
                )
                if value
            }),
        },
    }


def list_product_aliases(
    user: dict[str, Any],
    *,
    alias: str = "",
    alias_kind: str = "",
    conflict_status: str = "all",
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    rows, records, _ = _alias_records(_tenant_model_rows(tenant_id), tenant_id=tenant_id)
    annotated, conflicts = detect_alias_conflicts(records)
    annotated_by_id = {item.id: item for item in annotated}
    alias_filter = _safe_text(alias, field="alias", max_length=256).casefold()
    kind_filter = _safe_text(alias_kind, field="alias_kind", max_length=32).casefold()
    conflict_filter = _safe_text(conflict_status, field="conflict_status", max_length=64).casefold() or "all"
    output: list[dict[str, Any]] = []
    for row in rows:
        if row["tenant_id"] != tenant_id:
            continue
        record = annotated_by_id[row["id"]]
        result = dict(row)
        result["model"] = _official_rows([result["model"]])[0]
        result.update({
            "normalized_alias": record.normalized_alias,
            "conflict_status": record.conflict_status,
            "conflict_group": record.conflict_group,
            "conflict_reason": record.conflict_reason,
            "conflict_count": record.conflict_count,
        })
        if alias_filter and alias_filter not in record.normalized_alias:
            continue
        if kind_filter and record.alias_kind != kind_filter:
            continue
        if conflict_filter != "all" and record.conflict_status != conflict_filter:
            continue
        output.append(result)
    return {
        "persistence_status": PERSISTENCE_STATUS,
        "tenant_id": tenant_id,
        "items": output,
        "conflicts": [item.to_dict() for item in conflicts if item.tenant_id == tenant_id],
        "total": len(output),
        "read_only": True,
        "collection_kind": "official_catalog",
        "mutable": False,
        "boundary": _collection_boundary(),
        "source_artifact": _ALIAS_FILE.name,
    }


def resolve_product_alias_dry_run(user: dict[str, Any], query: str, *, limit: int = 20) -> dict[str, Any]:
    tenant_id = _tenant(user)
    query_text = _safe_text(query, field="query", max_length=256)
    if not query_text:
        raise ProductCatalogError("CATALOG_QUERY_REQUIRED", "query is required")
    model_rows = _tenant_model_rows(tenant_id)
    _, records, model_by_id = _alias_records(model_rows, tenant_id=tenant_id)
    candidates: AliasCandidateList = list_alias_candidates(query_text, records, tenant_id=tenant_id, limit=limit)
    payload = candidates.to_dict()
    payload["candidates"] = [
        {
            **item,
            "model": (
                _official_rows([model_by_id[item.get("product_model_id")]])[0]
                if model_by_id.get(item.get("product_model_id"))
                else None
            ),
        }
        for item in payload["candidates"]
    ]
    payload.update({
        "persistence_status": PERSISTENCE_STATUS,
        "tenant_id": tenant_id,
        "dry_run": True,
        "read_only": True,
        "collection_kind": "official_catalog",
        "mutable": False,
        "boundary": _collection_boundary(),
        "driver_selection_allowed": False,
    })
    return payload
