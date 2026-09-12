"""Product catalog projection, alias resolution, and tenant master-data CRUD.

Reviewed YAML rows remain immutable official facts. Tenant-owned rows are kept
in the CAT-006 master-data tables and are merged into the read projection;
mutations are permission checked, transactional, audited, and soft-deleted.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
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
from core.rbac import authorize_resource
from database import get_db_connection
from services.audit_service import log_audit_event


_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_DIR = _ROOT / "docs" / "knowledge-engine" / "catalog"
_PRODUCT_FILES = (
    _CATALOG_DIR / "CAT-005-HUAWEI-CE6800.yaml",
    _CATALOG_DIR / "CAT-006-CISCO-C9300.yaml",
    _CATALOG_DIR / "CAT-016-H3C-COMWARE.yaml",
    _CATALOG_DIR / "CAT-017-RUIJIE-RGOS.yaml",
)
_ALIAS_FILE = _CATALOG_DIR / "CAT-010-ALIAS-SAMPLES.yaml"
PERSISTENCE_STATUS = "contract_only_read_only_seed"
CUSTOM_PERSISTENCE_STATUS = "tenant_custom_catalog"
_REVIEWED_SEED_TENANT = "tenant-default-reviewed"
_RUNTIME_DEFAULT_TENANT = "tenant-default"
_CONTROL_CHARS = tuple(chr(value) for value in list(range(0, 32)) + [127])
_CATALOG_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CUSTOM_STATUSES = {"draft", "active", "disabled", "archived", "deleted"}

_CUSTOM_MODEL_SELECT = """
    SELECT m.id, m.tenant_id, v.id, v.name, f.code, f.name, s.code, s.name,
           m.code, m.display_name, m.status, m.review_status, m.source_refs_json,
           m.software_scope_json, m.platform_binding_advisory_json, m.source_kind,
           m.description, m.created_at, m.updated_at
    FROM kb_product_model m
    JOIN kb_product_series s ON s.tenant_id = m.tenant_id AND s.id = m.series_id
    JOIN kb_product_family f ON f.tenant_id = s.tenant_id AND f.id = s.family_id
    JOIN kb_vendor v ON v.tenant_id = f.tenant_id AND v.id = f.vendor_id
"""


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


def _catalog_code(value: Any, *, field: str, max_length: int = 128) -> str:
    code = _safe_text(value, field=field, max_length=max_length)
    if not code or not _CATALOG_CODE_PATTERN.fullmatch(code):
        raise ProductCatalogError("CATALOG_CODE_INVALID", f"{field} must be a single-line identifier")
    return code


def _required_text(value: Any, *, field: str, max_length: int = 256) -> str:
    text = _safe_text(value, field=field, max_length=max_length)
    if not text:
        raise ProductCatalogError("CATALOG_PAYLOAD_INVALID", f"{field} is required")
    return text


def _json_object(value: Any, *, field: str, max_entries: int = 64) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > max_entries:
        raise ProductCatalogError("CATALOG_PAYLOAD_INVALID", f"{field} must be a bounded object")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 12000 or any(char in encoded for char in _CONTROL_CHARS):
        raise ProductCatalogError("CATALOG_PAYLOAD_INVALID", f"{field} is invalid")
    return value


def _json_string_list(value: Any, *, field: str, max_items: int = 32) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > max_items:
        raise ProductCatalogError("CATALOG_PAYLOAD_INVALID", f"{field} must be a bounded list")
    output = []
    for item in value:
        text = _safe_text(item, field=field, max_length=256)
        if not text:
            raise ProductCatalogError("CATALOG_PAYLOAD_INVALID", f"{field} contains an empty value")
        output.append(text)
    return output


def _catalog_action(user: dict[str, Any], action: str, tenant_id: str) -> None:
    if not authorize_resource(user, "knowledge_catalog", action, tenant_id=tenant_id):
        raise ProductCatalogError("CATALOG_PERMISSION_DENIED", "Catalog master-data permission is required", status_code=403)


def _custom_model_from_row(row) -> dict[str, Any]:
    def decode_object(value: Any) -> dict[str, Any]:
        try:
            parsed = json.loads(value or "{}") if isinstance(value, str) else value
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def decode_list(value: Any) -> list[str]:
        try:
            parsed = json.loads(value or "[]") if isinstance(value, str) else value
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    return {
        "product_model_id": str(row[0]),
        "tenant_id": str(row[1]),
        "vendor_id": str(row[2]),
        "vendor_name": str(row[3]),
        "family_code": str(row[4]),
        "family_name": str(row[5]),
        "series_code": str(row[6]),
        "series_name": str(row[7]),
        "model_code": str(row[8]),
        "display_name": str(row[9]),
        "status": str(row[10] or "draft"),
        "review_status": str(row[11] or "manual_review"),
        "source_refs": decode_list(row[12]),
        "software_scope": decode_object(row[13]),
        "platform_binding_advisory": decode_object(row[14]),
        "source_artifact": str(row[15] or "tenant_custom_catalog"),
        "description": str(row[16] or ""),
        "created_at": row[17],
        "updated_at": row[18],
        "collection_kind": "custom_catalog",
        "official": False,
        "read_only": False,
        "mutable": True,
        "custom_collection_id": str(row[0]),
    }


def _custom_model_audit_snapshot(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_model_id": model["product_model_id"],
        "tenant_id": model["tenant_id"],
        "vendor_id": model["vendor_id"],
        "family_code": model["family_code"],
        "series_code": model["series_code"],
        "model_code": model["model_code"],
        "display_name": model["display_name"],
        "status": model["status"],
        "review_status": model["review_status"],
        "source_artifact": model["source_artifact"],
        "updated_at": str(model.get("updated_at") or ""),
    }


def _write_catalog_model_audit(
    conn,
    user: dict[str, Any],
    *,
    operation: str,
    model: dict[str, Any],
    before: dict[str, Any] | None,
    details: dict[str, Any],
) -> str:
    return log_audit_event(
        event_type=f"knowledge_catalog_model_{operation}",
        category="knowledge_catalog",
        severity="info",
        status="success",
        summary=f"Knowledge catalog model {operation}",
        actor_id=str(user.get("id") or user.get("user_id") or user.get("username") or "system"),
        actor_username=str(user.get("username") or user.get("id") or "system"),
        actor_role=str(user.get("role") or "system"),
        target_type="knowledge_catalog_model",
        target_id=model["product_model_id"],
        target_name=model["display_name"],
        before=before,
        after=_custom_model_audit_snapshot(model),
        details=details,
        conn=conn,
    )


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


def _custom_model_rows(tenant_id: str) -> list[dict[str, Any]]:
    """Load only durable tenant-owned models from the master-data tables."""
    with get_db_connection() as conn:
        rows = conn.execute(
            _CUSTOM_MODEL_SELECT + " WHERE m.tenant_id = ? ORDER BY m.created_at ASC, m.id ASC",
            (tenant_id,),
        ).fetchall()
    return [_custom_model_from_row(row) for row in rows]


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
        official_rows = [{**item, "tenant_id": tenant_id} for item in rows]
    else:
        official_rows = [item for item in rows if str(item.get("tenant_id") or "") == tenant_id]
    return official_rows + _custom_model_rows(tenant_id)


def _official_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate official rows while preserving the mutable custom boundary."""
    return [
        ({**dict(item), "collection_kind": "custom_catalog", "official": False, "read_only": False, "mutable": True, "custom_collection_id": item.get("product_model_id")}
         if item.get("collection_kind") == "custom_catalog" or item.get("mutable")
         else {**dict(item), "collection_kind": "official_catalog", "official": True, "read_only": True, "mutable": False, "custom_collection_id": None})
        for item in rows
    ]


def _catalog_hierarchy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a compact Vendor → Family → Series → Model navigation index.

    The catalog table remains paginated at the API boundary. This index is
    deliberately limited to identifiers, display labels and counts so the UI
    can browse valid parent/child combinations without receiving source
    artifacts, software scopes, or another unbounded copy of every row.
    """
    vendors: dict[str, dict[str, Any]] = {}
    for item in rows:
        vendor_id = str(item.get("vendor_id") or "").strip()
        family_code = str(item.get("family_code") or "").strip()
        series_code = str(item.get("series_code") or "").strip()
        model_code = str(item.get("model_code") or "").strip()
        if not vendor_id or not family_code or not series_code or not model_code:
            continue

        vendor = vendors.setdefault(vendor_id, {
            "vendor_id": vendor_id,
            "vendor_name": str(item.get("vendor_name") or vendor_id),
            "model_count": 0,
            "families": {},
        })
        family = vendor["families"].setdefault(family_code, {
            "family_code": family_code,
            "family_name": str(item.get("family_name") or family_code),
            "model_count": 0,
            "series": {},
        })
        series = family["series"].setdefault(series_code, {
            "series_code": series_code,
            "series_name": str(item.get("series_name") or series_code),
            "model_count": 0,
            "models": [],
        })
        model_key = str(item.get("product_model_id") or f"{vendor_id}:{family_code}:{series_code}:{model_code.lower()}")
        if not any(model.get("product_model_id") == model_key for model in series["models"]):
            series["models"].append({
                "product_model_id": model_key,
                "model_code": model_code,
                "display_name": str(item.get("display_name") or model_code),
                "status": str(item.get("status") or "draft"),
            })

    def finalize_vendor(vendor: dict[str, Any]) -> dict[str, Any]:
        families = []
        for family in vendor.pop("families").values():
            series = []
            for series_item in family.pop("series").values():
                series_item["models"] = sorted(
                    series_item["models"],
                    key=lambda model: (model["model_code"].casefold(), model["model_code"]),
                )
                series_item["model_count"] = len(series_item["models"])
                series.append(series_item)
            family["series"] = sorted(series, key=lambda item: (item["series_code"].casefold(), item["series_code"]))
            family["model_count"] = sum(item["model_count"] for item in family["series"])
            families.append(family)
        vendor["families"] = sorted(families, key=lambda item: (item["family_code"].casefold(), item["family_code"]))
        vendor["model_count"] = sum(item["model_count"] for item in vendor["families"])
        return vendor

    return [
        finalize_vendor(vendor)
        for vendor in sorted(vendors.values(), key=lambda item: (item["vendor_id"].casefold(), item["vendor_id"]))
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
    if filters["status"] not in {"all", "draft", "active", "disabled", "archived", "deleted"}:
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
    else:
        # Deletion is a recoverable control-plane action, but deleted custom
        # rows must not remain in the default browse/resolve projection. An
        # explicit status=deleted query is still available for audit/recovery
        # tooling.
        rows = [item for item in rows if str(item.get("status") or "").casefold() != "deleted"]
    if filters["status"] != "deleted":
        all_rows = [item for item in all_rows if str(item.get("status") or "").casefold() != "deleted"]
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
    annotated_rows = _official_rows(rows)
    annotated_all_rows = _official_rows(all_rows)
    has_custom_rows = any(item.get("mutable") for item in annotated_all_rows)
    collection_kind = "mixed_catalog" if has_custom_rows and any(item.get("official") for item in annotated_all_rows) else ("custom_catalog" if has_custom_rows else "official_catalog")
    return {
        "persistence_status": CUSTOM_PERSISTENCE_STATUS if has_custom_rows else PERSISTENCE_STATUS,
        "tenant_id": tenant_id,
        "items": annotated_rows,
        "total": len(annotated_rows),
        "read_only": not has_custom_rows,
        "collection_kind": collection_kind,
        "mutable": has_custom_rows,
        "boundary": _collection_boundary(),
        "source_artifacts": [path.name for path in _PRODUCT_FILES] + (["tenant_custom_catalog"] if has_custom_rows else []),
        "facets": {
            "hierarchy": _catalog_hierarchy(all_rows),
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


def _validated_custom_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor_code": _catalog_code(payload.get("vendor_code"), field="vendor_code", max_length=64),
        "vendor_name": _required_text(payload.get("vendor_name"), field="vendor_name", max_length=256),
        "family_code": _catalog_code(payload.get("family_code"), field="family_code", max_length=64),
        "family_name": _required_text(payload.get("family_name"), field="family_name", max_length=256),
        "series_code": _catalog_code(payload.get("series_code"), field="series_code", max_length=64),
        "series_name": _required_text(payload.get("series_name"), field="series_name", max_length=256),
        "model_code": _catalog_code(payload.get("model_code"), field="model_code", max_length=128),
        "display_name": _required_text(payload.get("display_name"), field="display_name", max_length=256),
        "status": _safe_text(payload.get("status") or "draft", field="status", max_length=32).casefold(),
        "description": _safe_text(payload.get("description"), field="description", max_length=4000),
        "software_scope": _json_object(payload.get("software_scope"), field="software_scope"),
        "platform_binding_advisory": _json_object(payload.get("platform_binding_advisory"), field="platform_binding_advisory"),
        "source_refs": _json_string_list(payload.get("source_refs"), field="source_refs"),
    }


def _ensure_custom_parent(
    cursor,
    *,
    table: str,
    tenant_id: str,
    code: str,
    name: str,
    parent_column: str | None,
    parent_id: str | None,
    username: str,
    now_iso: str,
) -> str:
    if table == "kb_vendor":
        existing = cursor.execute(
            "SELECT id, name, status FROM kb_vendor WHERE tenant_id = ? AND code = ? FOR UPDATE",
            (tenant_id, code),
        ).fetchone()
    elif table == "kb_product_family":
        existing = cursor.execute(
            "SELECT id, name, status FROM kb_product_family WHERE tenant_id = ? AND vendor_id = ? AND code = ? FOR UPDATE",
            (tenant_id, parent_id, code),
        ).fetchone()
    else:
        existing = cursor.execute(
            "SELECT id, name, status FROM kb_product_series WHERE tenant_id = ? AND family_id = ? AND code = ? FOR UPDATE",
            (tenant_id, parent_id, code),
        ).fetchone()
    if existing:
        if str(existing[2] or "").casefold() == "deleted":
            raise ProductCatalogError("CATALOG_PARENT_DELETED", f"Cannot use deleted {table} parent", status_code=409)
        if str(existing[1]) != name:
            raise ProductCatalogError("CATALOG_PARENT_NAME_CONFLICT", f"{code} already has a different display name", status_code=409)
        return str(existing[0])

    parent_id_value = f"custom_{table.removeprefix('kb_product_').removeprefix('kb_')}_{uuid.uuid4().hex[:12]}"
    columns = ["id", "tenant_id"]
    values: list[Any] = [parent_id_value, tenant_id]
    if table == "kb_product_family":
        columns.append("vendor_id")
        values.append(parent_id)
    elif table == "kb_product_series":
        columns.append("family_id")
        values.append(parent_id)
    columns.extend(["code", "name", "status", "description", "metadata_json", "source_kind", "created_by", "created_at", "updated_by", "updated_at"])
    values.extend([code, name, "active", "", "{}", "custom", username, now_iso, username, now_iso])
    placeholders = ", ".join("?" for _ in columns)
    cursor.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", tuple(values))
    return parent_id_value


def _custom_model_row(cursor, model_id: str, tenant_id: str, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    return cursor.execute(
        _CUSTOM_MODEL_SELECT + f" WHERE m.tenant_id = ? AND m.id = ?{suffix}",
        (tenant_id, model_id),
    ).fetchone()


def create_custom_product_model(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Create a tenant-owned Vendor → Family → Series → Model branch."""
    tenant_id = _tenant(user)
    _catalog_action(user, "create", tenant_id)
    values = _validated_custom_model_payload(payload)
    if values["status"] not in _CUSTOM_STATUSES - {"deleted"}:
        raise ProductCatalogError("CATALOG_STATUS_INVALID", "status is invalid")
    username = str(user.get("username") or user.get("id") or "system")
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        duplicate = cursor.execute(
            """
            SELECT m.id FROM kb_product_model m
            JOIN kb_product_series s ON s.tenant_id = m.tenant_id AND s.id = m.series_id
            JOIN kb_product_family f ON f.tenant_id = s.tenant_id AND f.id = s.family_id
            JOIN kb_vendor v ON v.tenant_id = f.tenant_id AND v.id = f.vendor_id
            WHERE m.tenant_id = ? AND v.code = ? AND f.code = ? AND s.code = ? AND m.code = ?
            """,
            (tenant_id, values["vendor_code"], values["family_code"], values["series_code"], values["model_code"]),
        ).fetchone()
        if duplicate:
            raise ProductCatalogError("CATALOG_MODEL_DUPLICATE", "A model with the same hierarchy and code already exists", status_code=409)
        official_duplicate = next(
            (
                item for item in _tenant_model_rows(tenant_id)
                if not item.get("mutable")
                and str(item.get("vendor_id") or "").casefold() == values["vendor_code"].casefold()
                and str(item.get("family_code") or "").casefold() == values["family_code"].casefold()
                and str(item.get("series_code") or "").casefold() == values["series_code"].casefold()
                and str(item.get("model_code") or "").casefold() == values["model_code"].casefold()
            ),
            None,
        )
        if official_duplicate:
            raise ProductCatalogError("CATALOG_MODEL_DUPLICATE", "A model with the same hierarchy and code already exists", status_code=409)
        vendor_id = _ensure_custom_parent(
            cursor, table="kb_vendor", tenant_id=tenant_id, code=values["vendor_code"], name=values["vendor_name"],
            parent_column=None, parent_id=None, username=username, now_iso=now_iso,
        )
        family_id = _ensure_custom_parent(
            cursor, table="kb_product_family", tenant_id=tenant_id, code=values["family_code"], name=values["family_name"],
            parent_column="vendor_id", parent_id=vendor_id, username=username, now_iso=now_iso,
        )
        series_id = _ensure_custom_parent(
            cursor, table="kb_product_series", tenant_id=tenant_id, code=values["series_code"], name=values["series_name"],
            parent_column="family_id", parent_id=family_id, username=username, now_iso=now_iso,
        )
        model_id = f"custom_model_{uuid.uuid4().hex[:12]}"
        cursor.execute(
            """
            INSERT INTO kb_product_model (
                id, tenant_id, series_id, code, display_name, status, description,
                review_status, source_refs_json, software_scope_json,
                platform_binding_advisory_json, metadata_json, source_kind,
                created_by, created_at, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'manual_review', ?, ?, ?, '{}', 'custom', ?, ?, ?, ?)
            """,
            (
                model_id, tenant_id, series_id, values["model_code"], values["display_name"], values["status"],
                values["description"], json.dumps(values["source_refs"], ensure_ascii=False),
                json.dumps(values["software_scope"], ensure_ascii=False),
                json.dumps(values["platform_binding_advisory"], ensure_ascii=False),
                username, now_iso, username, now_iso,
            ),
        )
        created_row = _custom_model_row(cursor, model_id, tenant_id)
        created = _custom_model_from_row(created_row)
        _write_catalog_model_audit(
            conn, user, operation="create", model=created, before=None,
            details={"change_reason": _safe_text(payload.get("change_reason") or "Catalog model created", field="change_reason", max_length=500), "changed_fields": ["hierarchy", "model"]},
        )
        conn.commit()
    return created


def update_custom_product_model(user: dict[str, Any], model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _catalog_action(user, "update", tenant_id)
    model_id = _safe_text(model_id, field="model_id", max_length=256)
    reason = _safe_text(payload.get("change_reason") or "Catalog model updated", field="change_reason", max_length=500)
    expected_updated_at = payload.get("expected_updated_at")
    values: dict[str, Any] = {}
    for key in ("display_name", "description"):
        if key in payload and payload[key] is not None:
            values[key] = _safe_text(payload[key], field=key, max_length=4000 if key == "description" else 256)
    if "status" in payload and payload["status"] is not None:
        values["status"] = _safe_text(payload["status"], field="status", max_length=32).casefold()
        if values["status"] not in _CUSTOM_STATUSES:
            raise ProductCatalogError("CATALOG_STATUS_INVALID", "status is invalid")
    for key in ("software_scope", "platform_binding_advisory"):
        if key in payload and payload[key] is not None:
            values[key] = _json_object(payload[key], field=key)
    if "source_refs" in payload and payload["source_refs"] is not None:
        values["source_refs"] = _json_string_list(payload["source_refs"], field="source_refs")
    if expected_updated_at is not None:
        expected_updated_at = _safe_text(expected_updated_at, field="expected_updated_at", max_length=80)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        row = _custom_model_row(cursor, model_id, tenant_id, lock=True)
        if not row:
            official = any(item.get("product_model_id") == model_id and not item.get("mutable") for item in _tenant_model_rows(tenant_id))
            if official:
                raise ProductCatalogError("CATALOG_OFFICIAL_READ_ONLY", "Official catalog models cannot be edited", status_code=403)
            raise ProductCatalogError("CATALOG_MODEL_NOT_FOUND", "Custom catalog model not found", status_code=404)
        before = _custom_model_from_row(row)
        if expected_updated_at is not None and str(row[18]) != expected_updated_at:
            raise ProductCatalogError("CATALOG_VERSION_CONFLICT", "Catalog model changed since it was loaded", status_code=409)
        if not values:
            return before
        encoded_values = {
            "software_scope": json.dumps(values["software_scope"], ensure_ascii=False) if "software_scope" in values else None,
            "platform_binding_advisory": json.dumps(values["platform_binding_advisory"], ensure_ascii=False) if "platform_binding_advisory" in values else None,
            "source_refs": json.dumps(values["source_refs"], ensure_ascii=False) if "source_refs" in values else None,
        }
        fields: list[str] = []
        params: list[Any] = []
        column_map = {"display_name": "display_name", "description": "description", "status": "status", "software_scope": "software_scope_json", "platform_binding_advisory": "platform_binding_advisory_json", "source_refs": "source_refs_json"}
        for key, column in column_map.items():
            if key in values:
                fields.append(f"{column} = ?")
                params.append(encoded_values[key] if key in encoded_values and encoded_values[key] is not None else values[key])
        now_iso = datetime.now(timezone.utc).isoformat()
        fields.extend(["updated_by = ?", "updated_at = ?"])
        params.extend([str(user.get("username") or user.get("id") or "system"), now_iso, tenant_id, model_id])
        cursor.execute(f"UPDATE kb_product_model SET {', '.join(fields)} WHERE tenant_id = ? AND id = ?", tuple(params))
        after = _custom_model_from_row(_custom_model_row(cursor, model_id, tenant_id))
        _write_catalog_model_audit(
            conn, user, operation="update", model=after, before=_custom_model_audit_snapshot(before),
            details={"change_reason": reason, "changed_fields": list(values)},
        )
        conn.commit()
    return after


def delete_custom_product_model(user: dict[str, Any], model_id: str, *, reason: str = "Catalog model archived") -> dict[str, Any]:
    tenant_id = _tenant(user)
    _catalog_action(user, "delete", tenant_id)
    model_id = _safe_text(model_id, field="model_id", max_length=256)
    reason = _safe_text(reason, field="reason", max_length=500)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        row = _custom_model_row(cursor, model_id, tenant_id, lock=True)
        if not row:
            official = any(item.get("product_model_id") == model_id and not item.get("mutable") for item in _tenant_model_rows(tenant_id))
            if official:
                raise ProductCatalogError("CATALOG_OFFICIAL_READ_ONLY", "Official catalog models cannot be deleted", status_code=403)
            raise ProductCatalogError("CATALOG_MODEL_NOT_FOUND", "Custom catalog model not found", status_code=404)
        before = _custom_model_from_row(row)
        if before["status"] == "deleted":
            return before
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            "UPDATE kb_product_model SET status = 'deleted', updated_by = ?, updated_at = ? WHERE tenant_id = ? AND id = ?",
            (str(user.get("username") or user.get("id") or "system"), now_iso, tenant_id, model_id),
        )
        after = _custom_model_from_row(_custom_model_row(cursor, model_id, tenant_id))
        _write_catalog_model_audit(
            conn, user, operation="delete", model=after, before=_custom_model_audit_snapshot(before),
            details={"change_reason": reason, "soft_delete": True},
        )
        conn.commit()
    return after


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
