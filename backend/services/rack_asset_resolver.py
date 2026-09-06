"""Deterministic RackVision 3D asset resolution.

The resolver is deliberately read-only.  CMDB identity and placement remain
owned by the rack/device tables; this module only chooses the best available
visual representation and reports how much fidelity was achieved.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_DIR = _ROOT / "assets" / "catalog"
_REGISTRY_FILE = _CATALOG_DIR / "asset_registry.json"
_MAPPING_FILE = _CATALOG_DIR / "model_mapping.json"


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _norm_model(value: Any) -> str:
    return _norm(value).replace(" - ", "-").replace("_", "-")


def _fallback_registry() -> list[dict[str, Any]]:
    return [
        {
            "asset_key": "generic_switch_1u_24p",
            "vendor": "generic",
            "family": "switch_1u",
            "exact_models": [],
            "device_type": "switch",
            "height_u": 1,
            "glb_path": "assets/build/glb/generic_switch_1u_24p.glb",
            "public_path": "/assets/3d/generic_switch_1u_24p.glb",
            "status": "draft",
            "render_strategy": "procedural",
        },
        {
            "asset_key": "generic_server_1u",
            "vendor": "generic",
            "family": "server_1u",
            "exact_models": [],
            "device_type": "server",
            "height_u": 1,
            "glb_path": "assets/build/glb/generic_server_1u.glb",
            "public_path": "/assets/3d/generic_server_1u.glb",
            "status": "draft",
            "render_strategy": "procedural",
        },
        {
            "asset_key": "generic_device_unknown",
            "vendor": "generic",
            "family": "unknown",
            "exact_models": [],
            "device_type": "other",
            "height_u": None,
            "glb_path": None,
            "public_path": None,
            "status": "draft",
            "render_strategy": "procedural",
        },
    ]


def _load_json(path: Path, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback
    return value if isinstance(value, list) else fallback


@lru_cache(maxsize=1)
def _catalog() -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    registry = tuple(_load_json(_REGISTRY_FILE, _fallback_registry()))
    mapping = tuple(_load_json(_MAPPING_FILE, []))
    return registry, mapping


def clear_catalog_cache() -> None:
    """Clear the process cache for an operator-triggered catalog refresh."""

    _catalog.cache_clear()


def list_catalog(*, vendor: str = "", device_type: str = "", status: str = "") -> list[dict[str, Any]]:
    """Return the non-secret visual registry for the rack asset picker."""

    vendor_filter = _norm(vendor)
    type_filter = _norm(device_type)
    status_filter = _norm(status)
    registry, _ = _catalog()
    output = []
    for entry in registry:
        if vendor_filter and _norm(entry.get("vendor")) != vendor_filter:
            continue
        if type_filter and _norm(entry.get("device_type")) != type_filter:
            continue
        if status_filter and _norm(entry.get("status")) != status_filter:
            continue
        item = dict(entry)
        item["available"] = _available(item)
        output.append(item)
    return sorted(output, key=lambda item: str(item.get("asset_key") or ""))


def _height_matches(entry: dict[str, Any], height_u: int | None) -> bool:
    if height_u is None or entry.get("height_u") in (None, ""):
        return True
    try:
        return int(entry["height_u"]) == int(height_u)
    except (TypeError, ValueError):
        return False


def _available(entry: dict[str, Any]) -> bool:
    if str(entry.get("status") or "draft").strip().lower() != "approved":
        return False
    glb_path = str(entry.get("glb_path") or "").strip()
    if not glb_path:
        return False
    path = (_ROOT / glb_path).resolve()
    try:
        path.relative_to(_ROOT)
    except ValueError:
        return False
    return path.is_file()


def _result(
    entry: dict[str, Any],
    *,
    level: str,
    requested_vendor: str,
    requested_model: str,
    fallback_reason: str = "",
) -> dict[str, Any]:
    available = _available(entry)
    render_strategy = "glb" if available else str(entry.get("render_strategy") or "procedural")
    return {
        "asset_key": str(entry.get("asset_key") or "generic_device_unknown"),
        "vendor": str(entry.get("vendor") or "generic"),
        "family": str(entry.get("family") or "unknown"),
        "device_type": str(entry.get("device_type") or "other"),
        "height_u": entry.get("height_u"),
        "glb_path": entry.get("glb_path"),
        "asset_url": entry.get("public_path"),
        "thumbnail_path": entry.get("thumbnail_path"),
        "status": str(entry.get("status") or "draft"),
        "available": available,
        "render_strategy": render_strategy,
        "resolution_level": level,
        "fidelity": {"exact": "exact", "family": "family", "vendor_generic": "vendor", "global_generic": "generic"}.get(level, level),
        "fallback_reason": fallback_reason,
        "requested_vendor": requested_vendor,
        "requested_model": requested_model,
    }


def _synthetic_generic(vendor: str, kind: str, height_u: int | None, *, level: str, reason: str) -> dict[str, Any]:
    height_label = f"{int(height_u)}u" if height_u else "unknown"
    key = f"{slug(vendor) or 'vendor'}_generic_{slug(kind) or 'device'}_{height_label}"
    entry = {
        "asset_key": key,
        "vendor": vendor or "generic",
        "family": f"{kind}_{height_label}",
        "device_type": kind or "other",
        "height_u": height_u,
        "glb_path": None,
        "public_path": None,
        "status": "draft",
        "render_strategy": "procedural",
    }
    return _result(entry, level=level, requested_vendor=vendor, requested_model="", fallback_reason=reason)


def slug(value: Any) -> str:
    return "_".join(re.findall(r"[a-z0-9]+", _norm(value)))


def resolve_asset(
    *,
    vendor: str = "",
    model: str = "",
    device_type: str = "other",
    height_u: int | None = None,
    model_key: str = "",
) -> dict[str, Any]:
    """Resolve exact -> family -> vendor generic -> global generic.

    The return value never becomes ``None``.  If no approved GLB exists, the
    caller receives a procedural fallback plus an explicit fidelity level.
    """

    requested_vendor = _norm(vendor) or "generic"
    requested_model = _norm_model(model)
    requested_kind = _norm(device_type) or "other"
    registry, mapping = _catalog()
    by_key = {str(item.get("asset_key")): item for item in registry if item.get("asset_key")}

    if model_key and model_key in by_key:
        return _result(
            by_key[model_key],
            level="exact",
            requested_vendor=requested_vendor,
            requested_model=requested_model,
        )

    mapping_match = next(
        (
            item for item in mapping
            if _norm(item.get("vendor")) == requested_vendor
            and _norm_model(item.get("exact_model")) == requested_model
        ),
        None,
    )
    if mapping_match:
        entry = by_key.get(str(mapping_match.get("asset_key")))
        if entry:
            level = str(mapping_match.get("resolution_level") or "family")
            return _result(
                entry,
                level="exact" if level == "exact" else "family",
                requested_vendor=requested_vendor,
                requested_model=requested_model,
            )

    family_candidates = [
        item for item in registry
        if _norm(item.get("vendor")) == requested_vendor
        and _norm(item.get("device_type")) == requested_kind
        and _height_matches(item, height_u)
        and bool(item.get("exact_models"))
    ]
    if family_candidates:
        entry = sorted(family_candidates, key=lambda item: str(item.get("asset_key")))[0]
        return _result(
            entry,
            level="family",
            requested_vendor=requested_vendor,
            requested_model=requested_model,
            fallback_reason="exact model is not mapped; selected vendor family form factor",
        )

    vendor_generic = next(
        (
            item for item in registry
            if _norm(item.get("vendor")) == requested_vendor
            and _norm(item.get("device_type")) == requested_kind
            and _height_matches(item, height_u)
            and not item.get("exact_models")
        ),
        None,
    )
    if vendor_generic:
        return _result(
            vendor_generic,
            level="vendor_generic",
            requested_vendor=requested_vendor,
            requested_model=requested_model,
            fallback_reason="no exact or family mapping was available",
        )

    global_generic = next(
        (
            item for item in registry
            if _norm(item.get("vendor")) == "generic"
            and _norm(item.get("device_type")) == requested_kind
            and _height_matches(item, height_u)
        ),
        None,
    )
    if global_generic:
        return _result(
            global_generic,
            level="global_generic",
            requested_vendor=requested_vendor,
            requested_model=requested_model,
            fallback_reason="no vendor-specific visual asset was available",
        )

    global_generic = next(
        (
            item for item in registry
            if _norm(item.get("vendor")) == "generic"
            and _norm(item.get("device_type")) in {"other", "switch"}
        ),
        None,
    )
    if global_generic:
        return _result(
            global_generic,
            level="global_generic",
            requested_vendor=requested_vendor,
            requested_model=requested_model,
            fallback_reason="device type is unknown; selected global safe fallback",
        )
    return _synthetic_generic(
        requested_vendor,
        requested_kind,
        height_u,
        level="global_generic",
        reason="catalog seed unavailable; procedural safe fallback",
    )


def resolve_asset_for_device(device: dict[str, Any]) -> dict[str, Any]:
    return resolve_asset(
        vendor=str(device.get("vendor") or ""),
        model=str(device.get("model") or ""),
        device_type=str(device.get("device_type") or device.get("device_role") or "other"),
        height_u=device.get("height_u") or device.get("u_height"),
        model_key=str(device.get("model_key") or ""),
    )


__all__ = ["clear_catalog_cache", "list_catalog", "resolve_asset", "resolve_asset_for_device"]
