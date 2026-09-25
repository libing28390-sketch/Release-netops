"""Pure Monitoring V1 assignment and collector configuration compiler.

The compiler intentionally accepts plain mappings.  The API/worker can load
records from PostgreSQL while unit tests and offline validation can exercise
the complete Plan -> Assignment -> Snapshot -> Artifact flow without a live
database or device.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .monitoring_oid_catalog import exporter_config_from_variant


class CompileError(ValueError):
    """A configuration cannot safely be applied to a collector."""


class CollectionAssignmentConflict(CompileError):
    """The same asset/module would be scraped with incompatible settings."""


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$", re.I)
_NUMERIC_OID_RE = re.compile(r"^\.?\d+(?:\.\d+)+$")
_MIB_OID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*::[A-Za-z][A-Za-z0-9_-]*(?:\.\d+)*$")
_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LEGACY_LOOKUP_METADATA = {
    "ifName": ("1.3.6.1.2.1.31.1.1.1.1", "DisplayString"),
    "ifDescr": ("1.3.6.1.2.1.2.2.1.2", "DisplayString"),
}


def _valid_oid_token(value: str) -> bool:
    token = str(value or "").strip()
    if _NUMERIC_OID_RE.fullmatch(token):
        parts = [int(part) for part in token.lstrip(".").split(".")]
        # SMIv2 first/second arc constraints; subsequent arcs are bounded to
        # the unsigned 32-bit range accepted by net-snmp/gosnmp.
        return len(parts) >= 2 and parts[0] in {0, 1, 2} and (parts[0] == 2 or parts[1] < 40) and all(0 <= part <= 4_294_967_295 for part in parts)
    return bool(_MIB_OID_RE.fullmatch(token))

GENERIC_IF_MIB_MODULE = {
    "module_key": "generic_ifmib_interface",
    "display_name": "Generic IF-MIB interface",
    "metric_group": "interface",
    "walk": ["1.3.6.1.2.1.2.2", "1.3.6.1.2.1.31.1.1", "1.3.6.1.2.1.10.7.2.1"],
}
GENERIC_IF_MIB_VARIANT = {
    "variant_key": "generic_ifmib_interface_std",
    "max_repetitions": 25,
    "retries": 2,
    "request_timeout_ms": 3000,
    "scrape_timeout_ms": 20000,
}
GENERIC_IF_MIB_METRICS = (
    "sysUpTime", "ifName", "ifAdminStatus", "ifOperStatus", "ifHighSpeed",
    "ifHCInOctets", "ifHCOutOctets", "ifInErrors", "ifOutErrors",
    "ifInDiscards", "ifOutDiscards", "ifHCInUcastPkts", "ifHCInMulticastPkts",
    "ifHCInBroadcastPkts", "ifHCOutUcastPkts", "ifHCOutMulticastPkts",
    "ifHCOutBroadcastPkts", "ifLastChange",
)


def _parse_variant_oid_config(value: Any, *, include_unit: bool = True) -> dict[str, Any]:
    """Parse and validate the persisted generator payload.

    A variant is considered executable only when it contains at least one
    walk/get OID and one metric mapping.  This prevents a UI-created variant
    from looking published while producing an exporter module with no data.
    """

    if isinstance(value, Mapping):
        config = dict(value)
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise CompileError("OID_CONFIG_INVALID_JSON") from exc
        if not isinstance(parsed, Mapping):
            raise CompileError("OID_CONFIG_MUST_BE_OBJECT")
        config = dict(parsed)
    elif not value:
        return {}
    else:
        raise CompileError("OID_CONFIG_MUST_BE_OBJECT")

    for key in ("walk", "get"):
        raw = config.get(key, [])
        if raw is None:
            raw = []
        if not isinstance(raw, list) or len(raw) > 256:
            raise CompileError(f"OID_CONFIG_{key.upper()}_INVALID")
        normalized: list[str] = []
        for oid in raw:
            text = str(oid or "").strip()
            if not _valid_oid_token(text):
                raise CompileError(f"OID_CONFIG_{key.upper()}_INVALID:{text}")
            normalized.append(text.lstrip("."))
        config[key] = normalized

    oid_values = [*config.get("walk", []), *config.get("get", [])]
    if len(oid_values) != len(set(oid_values)):
        raise CompileError("OID_CONFIG_DUPLICATE_OID")

    metrics = config.get("metrics", [])
    if metrics is None:
        metrics = []
    if not isinstance(metrics, list) or len(metrics) > 1024:
        raise CompileError("OID_CONFIG_METRICS_INVALID")
    lookup_metric_metadata: dict[str, tuple[str, str]] = {}
    for candidate in metrics:
        if not isinstance(candidate, Mapping):
            continue
        candidate_name = str(candidate.get("name") or "").strip()
        candidate_oid = str(candidate.get("oid") or "").strip().lstrip(".")
        candidate_type = str(candidate.get("type") or "gauge").strip()
        candidate_type = {"Counter64": "counter", "Counter32": "counter", "Gauge32": "gauge", "Integer32": "gauge"}.get(candidate_type, candidate_type)
        if candidate_name and candidate_oid and _valid_oid_token(candidate_oid):
            lookup_metric_metadata[candidate_name] = (candidate_oid, candidate_type)

    normalized_metrics: list[dict[str, Any]] = []
    metric_oids: set[str] = set()
    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise CompileError("OID_CONFIG_METRIC_INVALID")
        name = str(metric.get("name") or "").strip()
        oid = str(metric.get("oid") or "").strip()
        metric_type = str(metric.get("type") or "gauge").strip()
        metric_type = {"Counter64": "counter", "Counter32": "counter", "Gauge32": "gauge", "Integer32": "gauge"}.get(metric_type, metric_type)
        if not _METRIC_NAME_RE.fullmatch(name):
            raise CompileError(f"OID_CONFIG_METRIC_NAME_INVALID:{name}")
        if not _valid_oid_token(oid):
            raise CompileError(f"OID_CONFIG_METRIC_OID_INVALID:{name}")
        normalized_oid = oid.lstrip(".")
        if normalized_oid in metric_oids:
            raise CompileError(f"OID_CONFIG_DUPLICATE_METRIC_OID:{normalized_oid}")
        metric_oids.add(normalized_oid)
        if metric_type not in {"gauge", "counter", "DisplayString", "OctetString", "EnumAsInfo", "EnumAsStateSet"}:
            raise CompileError(f"OID_CONFIG_METRIC_TYPE_INVALID:{name}")
        item = {str(key): value for key, value in metric.items() if str(key) in {"name", "oid", "type", "help", "unit", "indexes", "lookups", "enum_values", "scale", "offset", "display_hint", "datetime_pattern", "regex_extracts"}}
        item["name"] = name
        item["oid"] = oid.lstrip(".")
        item["type"] = metric_type
        item["help"] = str(item.get("help") or name)
        # ``unit`` is Nexora metadata used by the UI and metric dictionary,
        # but snmp_exporter rejects it from its strict runtime schema. Keep it
        # while validating persisted OID definitions and omit it when the
        # normalized object is being used to render exporter YAML.
        if include_unit:
            item["unit"] = str(item.get("unit") or "")[:64]
        indexes = item.get("indexes")
        if indexes is not None:
            if not isinstance(indexes, list) or len(indexes) > 16:
                raise CompileError(f"OID_CONFIG_INDEXES_INVALID:{name}")
            for index in indexes:
                if not isinstance(index, Mapping) or not _METRIC_NAME_RE.fullmatch(str(index.get("labelname") or "")):
                    raise CompileError(f"OID_CONFIG_INDEX_INVALID:{name}")
                if str(index.get("type") or "gauge") not in {"gauge", "counter", "Integer32", "Integer", "DisplayString", "OctetString", "PhysAddress48", "EnumAsInfo"}:
                    raise CompileError(f"OID_CONFIG_INDEX_TYPE_INVALID:{name}")
        lookups = item.get("lookups")
        if lookups is not None:
            if not isinstance(lookups, list) or len(lookups) > 16:
                raise CompileError(f"OID_CONFIG_LOOKUPS_INVALID:{name}")
            normalized_lookups: list[dict[str, Any]] = []
            for lookup in lookups:
                if not isinstance(lookup, Mapping):
                    raise CompileError(f"OID_CONFIG_LOOKUP_INVALID:{name}")
                is_legacy_lookup = "source_indexes" in lookup or "lookup" in lookup
                if is_legacy_lookup:
                    lookup_target = str(lookup.get("lookup") or "").strip()
                    labels = lookup.get("source_indexes")
                    target_metadata = lookup_metric_metadata.get(lookup_target) or _LEGACY_LOOKUP_METADATA.get(lookup_target)
                    if target_metadata is None:
                        raise CompileError(f"OID_CONFIG_LOOKUP_TARGET_NOT_FOUND:{lookup_target}")
                    lookup_oid = str(lookup.get("oid") or target_metadata[0]).strip()
                    lookup_type = str(lookup.get("type") or target_metadata[1]).strip()
                else:
                    lookup_target = str(lookup.get("labelname") or "").strip()
                    labels = lookup.get("labels")
                    lookup_oid = str(lookup.get("oid") or "").strip()
                    lookup_type = str(lookup.get("type") or "").strip()
                if not _METRIC_NAME_RE.fullmatch(lookup_target):
                    raise CompileError(f"OID_CONFIG_LOOKUP_INVALID:{name}")
                if not isinstance(labels, list) or len(labels) > 16 or any(
                    not _METRIC_NAME_RE.fullmatch(str(label or "").strip()) for label in labels
                ):
                    raise CompileError(f"OID_CONFIG_LOOKUP_LABELS_INVALID:{name}")
                if lookup_oid and not _valid_oid_token(lookup_oid):
                    raise CompileError(f"OID_CONFIG_LOOKUP_OID_INVALID:{name}")
                normalized_lookup = {"labels": [str(label).strip() for label in labels], "labelname": lookup_target}
                if lookup_oid:
                    normalized_lookup["oid"] = lookup_oid.lstrip(".")
                if lookup_type:
                    if lookup_type not in {"gauge", "counter", "DisplayString", "OctetString", "PhysAddress48", "EnumAsInfo", "EnumAsStateSet"}:
                        raise CompileError(f"OID_CONFIG_LOOKUP_TYPE_INVALID:{name}")
                    normalized_lookup["type"] = lookup_type
                for optional_key in ("display_hint", "enum_values"):
                    if optional_key in lookup:
                        normalized_lookup[optional_key] = lookup[optional_key]
                normalized_lookups.append(normalized_lookup)
            item["lookups"] = normalized_lookups
        normalized_metrics.append(item)
    config["metrics"] = normalized_metrics
    if not config.get("walk") and not config.get("get"):
        raise CompileError("OID_CONFIG_HAS_NO_OIDS")
    if not normalized_metrics:
        raise CompileError("OID_CONFIG_HAS_NO_METRICS")
    return config


def _fallback_exporter_modules() -> dict[str, dict[str, Any]]:
    """Compatibility modules for offline callers that pass no catalog rows."""

    _if_lookups = [
        {"labels": ["ifIndex"], "labelname": "ifName", "oid": "1.3.6.1.2.1.31.1.1.1.1", "type": "DisplayString"},
        {"labels": ["ifIndex"], "labelname": "ifDescr", "oid": "1.3.6.1.2.1.2.2.1.2", "type": "DisplayString"},
    ]
    return {
        GENERIC_IF_MIB_VARIANT["variant_key"]: {
            "walk": list(GENERIC_IF_MIB_MODULE["walk"]),
            "max_repetitions": GENERIC_IF_MIB_VARIANT["max_repetitions"],
            "retries": GENERIC_IF_MIB_VARIANT["retries"],
            "timeout": f"{GENERIC_IF_MIB_VARIANT['request_timeout_ms'] / 1000:g}s",
            "metrics": [
                {
                    "name": name,
                    "oid": oid,
                    "type": "DisplayString" if name in {"ifName", "ifAlias"} else ("counter" if any(token in name for token in ("Octets", "Errors", "Discards", "Pkts")) else "gauge"),
                    "help": name,
                    "indexes": [{"labelname": "ifIndex", "type": "gauge"}],
                    **({"lookups": _if_lookups} if name not in {"ifName", "ifAlias"} else {})
                }
                for name, oid in (
                    ("ifMtu", "1.3.6.1.2.1.2.2.1.4"),
                    ("ifSpeed", "1.3.6.1.2.1.2.2.1.5"),
                    ("ifType", "1.3.6.1.2.1.2.2.1.3"),
                    ("ifAdminStatus", "1.3.6.1.2.1.2.2.1.7"),
                    ("ifOperStatus", "1.3.6.1.2.1.2.2.1.8"),
                    ("ifInDiscards", "1.3.6.1.2.1.2.2.1.13"),
                    ("ifInErrors", "1.3.6.1.2.1.2.2.1.14"),
                    ("ifInOctets", "1.3.6.1.2.1.2.2.1.10"),
                    ("ifOutDiscards", "1.3.6.1.2.1.2.2.1.19"),
                    ("ifOutErrors", "1.3.6.1.2.1.2.2.1.20"),
                    ("ifOutOctets", "1.3.6.1.2.1.2.2.1.16"),
                    ("ifName", "1.3.6.1.2.1.31.1.1.1.1"),
                    ("ifHighSpeed", "1.3.6.1.2.1.31.1.1.1.15"),
                    ("ifHCInOctets", "1.3.6.1.2.1.31.1.1.1.6"),
                    ("ifHCInUcastPkts", "1.3.6.1.2.1.31.1.1.1.7"),
                    ("ifHCInMulticastPkts", "1.3.6.1.2.1.31.1.1.1.8"),
                    ("ifHCInBroadcastPkts", "1.3.6.1.2.1.31.1.1.1.9"),
                    ("ifHCOutOctets", "1.3.6.1.2.1.31.1.1.1.10"),
                    ("ifHCOutUcastPkts", "1.3.6.1.2.1.31.1.1.1.11"),
                    ("ifHCOutMulticastPkts", "1.3.6.1.2.1.31.1.1.1.12"),
                    ("ifHCOutBroadcastPkts", "1.3.6.1.2.1.31.1.1.1.13"),
                    ("ifLastChange", "1.3.6.1.2.1.2.2.1.9"),
                    ("ifAlias", "1.3.6.1.2.1.31.1.1.1.18"),
                    ("dot3StatsFCSErrors", "1.3.6.1.2.1.10.7.2.1.3"),
                )
            ],
        },
        "generic_system_std": {
            "walk": ["1.3.6.1.2.1.1"],
            "max_repetitions": 10,
            "retries": 2,
            "timeout": "3s",
            "metrics": [
                {"name": name, "oid": oid, "type": "DisplayString" if name != "sysUpTime" else "gauge", "help": name}
                for name, oid in (
                    ("sysUpTime", "1.3.6.1.2.1.1.3"),
                    ("sysDescr", "1.3.6.1.2.1.1.1"),
                    ("sysName", "1.3.6.1.2.1.1.5"),
                )
            ],
        },
    }


def validate_oid_config(value: Any, *, allow_empty: bool = False) -> dict[str, Any]:
    """Public validation boundary used by the API and offline tests."""

    if allow_empty and not value:
        return {}
    return _parse_variant_oid_config(value)


def render_exporter_modules(
    assignments: Iterable[Mapping[str, Any]],
    *,
    modules: Iterable[Mapping[str, Any]] = (),
    variants: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any]]:
    """Render one strict snmp_exporter module per selected Variant.

    ``oid_config_json`` is the source of truth.  Module metadata only supplies
    a fallback walk for legacy rows, while the row-level timing knobs remain
    authoritative for GETBULK behaviour.
    """

    module_rows: dict[str, dict[str, Any]] = {}
    for item in modules:
        row = _row(item)
        for key in (row.get("module_key"), row.get("id")):
            if key:
                module_rows[str(key)] = row
    variant_rows: dict[str, dict[str, Any]] = {}
    for item in variants:
        row = _row(item)
        for key in (row.get("variant_key"), row.get("id")):
            if key:
                variant_rows[str(key)] = row
    selected_rows = [
        _row(item)
        for item in assignments
        if _row(item).get("enabled", True) is not False
    ]
    selected_keys = {str(item.get("variant_key") or "") for item in selected_rows}
    if not selected_keys:
        return _fallback_exporter_modules()
    output: dict[str, dict[str, Any]] = {}
    fallbacks = _fallback_exporter_modules()
    for variant_key in sorted(selected_keys):
        override_rows = [
            item for item in selected_rows
            if str(item.get("variant_key") or "") == variant_key
            and isinstance(item.get("exporter_override"), Mapping)
            and item.get("exporter_override")
        ]
        if override_rows:
            override = dict(override_rows[0]["exporter_override"])
            override_hash = _hash(override)
            if any(_hash(dict(item["exporter_override"])) != override_hash for item in override_rows[1:]):
                raise CompileError(f"EXPORTER_OVERRIDE_CONFLICT:{variant_key}")
            output[variant_key] = _parse_variant_oid_config(override, include_unit=False)
            output[variant_key]["max_repetitions"] = int(override.get("max_repetitions") or 25)
            output[variant_key]["retries"] = int(override.get("retries") or 2)
            output[variant_key]["timeout"] = str(override.get("timeout") or "5s")
            continue
        variant = variant_rows.get(variant_key) or {}
        module = module_rows.get(str(variant.get("module_key") or "")) or module_rows.get(str(variant.get("module_id") or "")) or {}
        raw = variant.get("oid_config") or variant.get("oid_config_json")
        if not raw and variant_key in fallbacks:
            output[variant_key] = fallbacks[variant_key]
            continue
        config = _parse_variant_oid_config(raw)
        if not config:
            raise CompileError(f"OID_CONFIG_MISSING:{variant_key}")
        exporter_config = exporter_config_from_variant(module, {"oid_config": config})
        exporter_config = _parse_variant_oid_config(exporter_config, include_unit=False)
        exporter_config["max_repetitions"] = int(variant.get("max_repetitions") or 25)
        exporter_config["retries"] = int(variant.get("retries") or 2)
        timeout_ms = int(variant.get("request_timeout_ms") or 3000)
        exporter_config["timeout"] = f"{timeout_ms / 1000:g}s"
        output[variant_key] = exporter_config
    return output


def duration_seconds(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise CompileError(f"{field} must be a positive duration")
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        match = _DURATION_RE.match(str(value or ""))
        if not match:
            raise CompileError(f"{field} has invalid duration: {value!r}")
        number, suffix = match.groups()
        seconds = float(number) * {"": 1, "s": 1, "m": 60, "h": 3600}[suffix.lower()]
    if seconds <= 0 or seconds != int(seconds):
        raise CompileError(f"{field} must be a positive whole number of seconds")
    return int(seconds)


def opaque_auth_alias(credential_id: str, *, salt: str = "nexora-monitoring-v1") -> str:
    """Return a stable opaque alias without leaking credential semantics."""
    digest = hashlib.sha256(f"{salt}:{credential_id}".encode("utf-8")).hexdigest()[:12]
    return f"auth_{digest}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _row(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "keys"):
        return {key: value[key] for key in value.keys()}
    return dict(value)


def _config_json(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise CompileError("collection plan config_json is not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise CompileError("collection plan config_json must be an object")
    return dict(parsed)


@dataclass(frozen=True)
class Assignment:
    id: str
    asset_id: str
    target: str
    collector_id: str
    module_variant_id: str
    module_key: str
    variant_key: str
    credential_id: str
    auth_alias: str
    interval_seconds: int
    scrape_timeout_seconds: int
    enabled: bool
    source_type: str
    source_plan_id: str
    tenant_id: str
    site_id: str
    vendor: str
    platform: str
    role: str
    selection_reason: str
    assignment_hash: str
    hostname: str = ""
    site_name: str = ""
    exporter_override: dict[str, Any] | None = None
    discovery_status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "hostname": self.hostname,
            "target": self.target,
            "collector_id": self.collector_id,
            "module_variant_id": self.module_variant_id,
            "module_key": self.module_key,
            "variant_key": self.variant_key,
            "credential_id": self.credential_id,
            "auth_alias": self.auth_alias,
            "interval_seconds": self.interval_seconds,
            "scrape_timeout_seconds": self.scrape_timeout_seconds,
            "enabled": self.enabled,
            "source_type": self.source_type,
            "source_plan_id": self.source_plan_id,
            "tenant_id": self.tenant_id,
            "site_id": self.site_id,
            "site_name": self.site_name,
            "vendor": self.vendor,
            "platform": self.platform,
            "role": self.role,
            "selection_reason": self.selection_reason,
            "assignment_hash": self.assignment_hash,
            "exporter_override": self.exporter_override,
            "discovery_status": self.discovery_status,
        }


def _index(values: Iterable[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(item.get(key) or ""): _row(item) for item in values if item.get(key)}


def _plan_for_device(device: Mapping[str, Any], plans: Mapping[str, Mapping[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    # Reuse the existing per-device Collection Plan projection when it carries
    # the V1 monitoring extension.  This keeps a device's effective policy in
    # CMDB instead of creating a second manual target/profile inventory.
    device_policy = device.get("collection_policy_json") or device.get("collection_policy")
    if device_policy:
        try:
            policy = _config_json(device_policy)
        except CompileError:
            policy = {}
        monitoring = policy.get("monitoring") or policy.get("monitoring_modules")
        if isinstance(monitoring, Mapping):
            monitoring_config = dict(monitoring)
            if isinstance(monitoring_config.get("modules") or monitoring_config.get("assignments"), list):
                return f"device-collection-plan:{device.get('id') or device.get('asset_id')}", monitoring_config
            monitoring = [monitoring_config]
        if isinstance(monitoring, list):
            return f"device-collection-plan:{device.get('id') or device.get('asset_id')}", {"modules": monitoring}
    platform = str(device.get("platform") or device.get("cli_platform") or "").strip()
    candidates = [platform, str(device.get("platform_key") or "").strip()]
    for key in candidates:
        if key and key in plans:
            plan = _row(plans[key])
            return str(plan.get("id") or key), _config_json(plan.get("config_json") or plan.get("config"))
    wildcard = plans.get("*")
    if wildcard:
        plan = _row(wildcard)
        return str(plan.get("id") or "plan-generic"), _config_json(plan.get("config_json") or plan.get("config"))
    return None


def plan_target_matches_device(device: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    """Apply optional CMDB-backed target selectors from a collection plan.

    ``target_ips`` and ``device_ids`` are filters, not arbitrary destinations:
    the compiler still resolves the final target from the matching CMDB row.
    When neither selector is present, the plan keeps its existing platform or
    wildcard semantics.
    """
    target_scope = plan.get("target_scope") if isinstance(plan.get("target_scope"), Mapping) else {}
    mode = str(target_scope.get("mode") or "").strip().lower()
    if mode in {"ip", "ips"}:
        values = target_scope.get("values") or target_scope.get("ips") or target_scope.get("device_ips") or []
        target_ips = {str(value).strip() for value in values if str(value).strip()}
        current_ip = str(device.get("ip_address") or device.get("management_address") or "").strip()
        return bool(target_ips) and current_ip in target_ips
    if mode == "site":
        value = str(target_scope.get("value") or "").strip()
        return bool(value) and value in {str(device.get("site") or "").strip(), str(device.get("site_id") or "").strip()}
    if mode == "role":
        value = str(target_scope.get("value") or "").strip().lower()
        return bool(value) and value == str(device.get("role") or device.get("device_role") or "").strip().lower()
    if mode == "tag":
        requested = {str(value).strip() for value in (target_scope.get("tag_ids") or target_scope.get("values") or []) if str(value).strip()}
        actual = {str(value).strip() for value in (device.get("tag_ids") or []) if str(value).strip()}
        if not requested:
            return False
        return requested.issubset(actual) if str(target_scope.get("match_mode") or "all").lower() != "or" else bool(requested & actual)
    if mode in {"composite", "filters", "filter"}:
        filters = target_scope.get("filters") if isinstance(target_scope.get("filters"), Mapping) else target_scope
        comparisons = {
            "site": {str(device.get("site") or "").strip(), str(device.get("site_id") or "").strip()},
            "role": {str(device.get("role") or device.get("device_role") or "").strip().lower()},
            "category": {str(device.get("device_category") or "").strip().lower()},
            "platform": {str(device.get("platform") or "").strip().lower()},
        }
        for key, actual in comparisons.items():
            expected = str(filters.get(key) or "").strip()
            if expected and expected.lower() not in {value.lower() for value in actual}:
                return False
        return True

    target_ips = {str(value).strip() for value in (plan.get("target_ips") or []) if str(value).strip()}
    device_ids = {str(value).strip() for value in (plan.get("device_ids") or []) if str(value).strip()}
    if target_ips and str(device.get("ip_address") or device.get("management_address") or "").strip() not in target_ips:
        return False
    if device_ids and str(device.get("id") or device.get("asset_id") or "").strip() not in device_ids:
        return False
    return True


def _selector_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[,;\n]", str(value))
    return [str(item).strip().lower() for item in values if str(item).strip()]


def _selector_matches(actual: str, expected: str) -> bool:
    actual = str(actual or "").strip().lower()
    expected = str(expected or "").strip().lower()
    if not actual or not expected:
        return False
    # CMDB platform values commonly carry a version suffix (for example
    # ``h3c_comware7`` or ``cisco_iosxe``), while the catalog stores the
    # stable family token.  Matching on token boundaries keeps the selector
    # useful without requiring one plan per software release.
    return actual == expected or actual.startswith(f"{expected}_") or actual.startswith(f"{expected}-") or expected in actual


def plan_entry_matches_device(entry: Mapping[str, Any], device: Mapping[str, Any]) -> bool:
    """Apply optional vendor/platform selectors on a single plan entry."""

    vendor_selectors = _selector_values(entry.get("vendor") or entry.get("vendors"))
    platform_selectors = _selector_values(entry.get("platform") or entry.get("platforms"))
    if not vendor_selectors and not platform_selectors:
        return True
    actual_vendor = str(device.get("vendor") or device.get("vendor_name") or device.get("manufacturer") or "").strip().lower()
    actual_platform = str(device.get("platform") or device.get("cli_platform") or device.get("platform_key") or "").strip().lower()
    if vendor_selectors and not any(_selector_matches(actual_vendor, value) or _selector_matches(actual_platform, value) for value in vendor_selectors):
        return False
    if platform_selectors and not any(_selector_matches(actual_platform, value) for value in platform_selectors):
        return False
    return True


def plan_entry_match_reason(entry: Mapping[str, Any], device: Mapping[str, Any]) -> str:
    """Return a human-readable, secret-free explanation for a Variant hit."""

    vendor_selectors = _selector_values(entry.get("vendor") or entry.get("vendors"))
    platform_selectors = _selector_values(entry.get("platform") or entry.get("platforms"))
    if not vendor_selectors and not platform_selectors:
        return "generic baseline"
    actual_vendor = str(device.get("vendor") or device.get("vendor_name") or device.get("manufacturer") or "").strip() or "unknown vendor"
    actual_platform = str(device.get("platform") or device.get("cli_platform") or device.get("platform_key") or "").strip() or "unknown platform"
    selectors = []
    if vendor_selectors:
        selectors.append(f"vendor={actual_vendor}")
    if platform_selectors:
        selectors.append(f"platform={actual_platform}")
    return ", ".join(selectors)


def _scope_values(value: Any) -> list[str]:
    """Return a normalized selector list from JSON/text compatibility data."""

    if value in (None, ""):
        return []
    raw = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = None
        raw = parsed if isinstance(parsed, list) else re.split(r"[,;\n]", value)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        raw = [raw]
    result: list[str] = []
    for item in raw:
        text = " ".join(str(item or "").strip().split())
        if text and text.casefold() not in {existing.casefold() for existing in result}:
            result.append(text)
    return result


def _scope_token(value: Any) -> str:
    return re.sub(r"[\s./-]+", "_", str(value or "").strip().casefold()).strip("_")


def _glob_match(actual: str, selector: str) -> bool:
    """Small, dependency-free glob matcher for platform/model selectors."""

    pattern = re.escape(selector).replace(r"\*", ".*").replace(r"\?", ".")
    return bool(re.fullmatch(pattern, actual, re.IGNORECASE))


def _platform_selector_matches(actual: str, selector: str) -> bool:
    actual_token = _scope_token(actual)
    selector_token = _scope_token(selector)
    if not actual_token or not selector_token or selector_token in {"*", "any", "all"}:
        return selector_token in {"*", "any", "all"}
    if _glob_match(actual_token, selector_token):
        return True
    # Stable family selectors (h3c_comware, huawei_vrp, iosxe) may match a
    # concrete version suffix, but v5/v7/v9 are intentionally not collapsed.
    supported_families = {
        "comware", "vrp", "ios", "iosxe", "nxos", "asa", "rgos", "junos", "fortios",
        "zte", "zxros", "maipu", "mypower", "dptech", "conplat", "hillstone", "stoneos",
        "sangfor", "sangforos", "dcn", "dcos", "wlan", "aruba", "arubaos", "ruckus", "smartzone", "aireos",
    }
    return actual_token.startswith(f"{selector_token}_") or (
        selector_token in supported_families
        and selector_token in actual_token
    )


def _model_selector_matches(actual: str, selector: str) -> bool:
    actual_text = " ".join(str(actual or "").strip().casefold().split())
    selector_text = " ".join(str(selector or "").strip().casefold().split())
    if not selector_text or selector_text in {"*", "any", "all"}:
        return True
    if not actual_text:
        return False
    if _glob_match(actual_text, selector_text):
        return True
    if "x" in selector_text:
        if _glob_match(actual_text, selector_text.replace("x", "*")):
            return True
    # A documented series such as S6800 also covers concrete SKUs such as
    # S6800-54QT, while a series code such as RG-S or QFX covers RG-S6220 or QFX5100.
    return (
        actual_text == selector_text
        or actual_text.startswith(f"{selector_text}-")
        or actual_text.startswith(f"{selector_text} ")
        or (actual_text.startswith(selector_text) and len(actual_text) > len(selector_text) and actual_text[len(selector_text)].isdigit())
    )


def _version_selector_matches(actual: str, selector: str) -> bool:
    actual_text = " ".join(str(actual or "").strip().casefold().split())
    selector_text = " ".join(str(selector or "").strip().casefold().split())
    if not selector_text or selector_text in {"*", "any", "all"}:
        return True
    if not actual_text:
        return False
    if _glob_match(actual_text, selector_text):
        return True
    actual_compact = re.sub(r"[^a-z0-9]+", "", actual_text)
    selector_compact = re.sub(r"[^a-z0-9]+", "", selector_text)
    if selector_compact and selector_compact in actual_compact:
        return True
    # Human-readable scopes such as “Comware 7” / “VRP V8” should match a
    # concrete banner containing the same platform family and major release.
    selector_major = re.search(r"(?:v|version|comware|vrp|ios(?:xe)?|nxos|asa|rgos|junos|fortios|zxros|mypower|conplat|stoneos|sangforos|dcos|smartzone|arubaos)?\s*(\d+)", selector_text)
    if selector_major:
        major = selector_major.group(1)
        actual_majors = re.findall(r"(?:^|[^a-z0-9])v?(\d+)(?:\.|$|[^0-9])", actual_text)
        if major in actual_majors or re.search(rf"(?:^|[^a-z0-9])v?{re.escape(major)}(?:$|[^0-9])", actual_text):
            family_tokens = [
                token for token in (
                    "comware", "vrp", "iosxe", "ios", "nxos", "asa", "rgos", "junos", "fortios",
                    "zxros", "mypower", "conplat", "stoneos", "sangforos", "dcos", "smartzone", "arubaos"
                ) if token in selector_text
            ]
            return not family_tokens or any(token in actual_text for token in family_tokens)
    return False


def _device_platform_values(device: Mapping[str, Any]) -> list[str]:
    values = [
        device.get("platform_code"),
        device.get("platform"),
        device.get("cli_platform"),
        device.get("platform_key"),
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def _device_version_values(device: Mapping[str, Any]) -> list[str]:
    values = [
        device.get("software_version"),
        device.get("version"),
        device.get("os_version"),
        device.get("firmware_version"),
    ]
    return [str(value).strip() for value in values if str(value or "").strip()]


def variant_matches_device(
    variant: Mapping[str, Any],
    device: Mapping[str, Any],
    module: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether a published Variant is applicable to one device.

    Empty scope means wildcard for backward compatibility.  A populated scope
    is enforced only when the device exposes the corresponding identity; an
    unknown model/version remains eligible but is reported in the reason so an
    operator can decide whether to bind it explicitly.
    """

    platforms = _scope_values(variant.get("supported_platforms"))
    models = _scope_values(variant.get("supported_models"))
    versions = _scope_values(variant.get("supported_version_scope"))
    platform_values = _device_platform_values(device)
    version_values = _device_version_values(device)
    model_value = str(device.get("model") or "").strip()

    if platforms and platform_values and not any(
        _platform_selector_matches(actual, selector)
        for actual in platform_values
        for selector in platforms
    ):
        return False
    if models and model_value and not any(_model_selector_matches(model_value, selector) for selector in models):
        return False
    if versions and version_values and not any(
        _version_selector_matches(actual, selector)
        for actual in [*version_values, *platform_values]
        for selector in versions
    ):
        return False
    return True


def variant_match_reason(
    variant: Mapping[str, Any],
    device: Mapping[str, Any],
    module: Mapping[str, Any] | None = None,
) -> str:
    """Explain the scope dimensions used for a Variant assignment."""

    if not any(_scope_values(variant.get(key)) for key in ("supported_platforms", "supported_models", "supported_version_scope")):
        return "variant scope unrestricted"
    parts: list[str] = []
    if _scope_values(variant.get("supported_platforms")):
        parts.append(f"platform={str(device.get('platform') or device.get('cli_platform') or 'unknown')}")
    if _scope_values(variant.get("supported_models")):
        parts.append(f"model={str(device.get('model') or 'unknown')}")
    if _scope_values(variant.get("supported_version_scope")):
        parts.append(f"version={str(device.get('version') or device.get('software_version') or 'unknown')}")
    return "variant " + ", ".join(parts)


def build_assignments(
    devices: Iterable[Mapping[str, Any]],
    plans: Iterable[Mapping[str, Any]],
    modules: Iterable[Mapping[str, Any]],
    variants: Iterable[Mapping[str, Any]],
    collectors: Iterable[Mapping[str, Any]],
    *,
    credential_aliases: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Compile enabled plan entries for CMDB devices into stable assignments."""
    plan_rows = list(plans)
    plan_map: dict[str, dict[str, Any]] = {}
    for plan in plan_rows:
        row = _row(plan)
        for key in (row.get("id"), row.get("name"), row.get("cli_platform")):
            if key:
                plan_map[str(key)] = row
    module_map = _index(modules, "module_key")
    module_by_id = _index(modules, "id")
    variant_map = _index(variants, "variant_key")
    variant_by_id = _index(variants, "id")
    collector_map = _index(collectors, "id")
    aliases = dict(credential_aliases or {})
    aliases_provided = credential_aliases is not None
    result: list[Assignment] = []
    seen: dict[tuple[str, str], Assignment] = {}
    walk_seen: dict[tuple[str, str], str] = {}

    for device_value in devices:
        device = _row(device_value)
        asset_id = str(device.get("asset_id") or device.get("id") or "").strip()
        target = str(device.get("ip_address") or device.get("management_address") or "").strip()
        if not asset_id or not target:
            continue
        plan_result = _plan_for_device(device, plan_map)
        if plan_result is None:
            continue
        plan_id, plan = plan_result
        if not plan_target_matches_device(device, plan):
            continue
        module_entries = plan.get("modules") or plan.get("assignments") or []
        if not isinstance(module_entries, list):
            raise CompileError(f"collection plan {plan_id} modules must be a list")
        collector_id = str(device.get("collector_id") or "collector-local")
        if collector_map and collector_id not in collector_map:
            raise CompileError(f"COLLECTOR_NOT_FOUND: {collector_id}")
        # SNMP collection must resolve an explicitly bound SNMP credential.
        # ``credential_id`` belongs to the SSH/management path and must never
        # be silently reused as an SNMP credential.
        credential_id = str(device.get("snmp_credential_id") or "")
        explicit_alias = str(device.get("auth_alias") or "")
        if credential_id and aliases_provided and not explicit_alias and credential_id not in aliases:
            raise CompileError(f"AUTH_NOT_FOUND: asset={asset_id} credential={credential_id}")
        auth_alias = str(explicit_alias or aliases.get(credential_id) or (opaque_auth_alias(credential_id) if credential_id else ""))
        if not auth_alias:
            raise CompileError(f"AUTH_NOT_CONFIGURED: asset={asset_id}")
        for entry_value in module_entries:
            entry = _row(entry_value)
            if entry.get("enabled", True) is False:
                continue
            if not plan_entry_matches_device(entry, device):
                continue
            module_key = str(entry.get("module") or entry.get("module_key") or "").strip()
            variant_key = str(entry.get("variant") or entry.get("variant_key") or "").strip()
            module = module_map.get(module_key) or module_by_id.get(module_key)
            variant = variant_map.get(variant_key) or variant_by_id.get(variant_key)
            if not module:
                raise CompileError(f"MODULE_NOT_FOUND: {module_key}")
            if not variant:
                raise CompileError(f"MODULE_VARIANT_NOT_FOUND: {variant_key}")
            if not variant_matches_device(variant, device, module):
                # A plan may contain several entries for the same capability,
                # each scoped to a different platform/model/version.  A
                # non-applicable entry is skipped so the next scoped Variant
                # can win without creating a second collection plan.
                continue
            variant_status = str(variant.get("status") or "PUBLISHED").upper()
            if variant_status not in {"TESTED", "PUBLISHED"}:
                raise CompileError(f"MODULE_VARIANT_NOT_PUBLISHED: {variant_key}")
            module_id = str(module.get("id") or "")
            if str(variant.get("module_id") or "") not in {"", module_id}:
                raise CompileError(f"MODULE_VARIANT_MISMATCH: {variant_key}")

            discovery = device.get("snmp_discovery") if isinstance(device.get("snmp_discovery"), Mapping) else {}
            discovery_status = str(discovery.get("status") or "pending").casefold()
            module_vendor = str(module.get("vendor") or "").strip()
            is_vendor_specific = bool(module_vendor and module_vendor.casefold() not in {"generic", "standard", ""})
            profile_verification = str(device.get("snmp_profile_verification_status") or "").casefold()
            discovery_module_available = bool(
                isinstance(discovery.get("exporter_module"), Mapping)
                and discovery.get("exporter_module", {}).get("metrics")
            )
            if is_vendor_specific and not discovery_module_available and profile_verification not in {"tested", "published", "verified", "passed", "approved"}:
                # A family module with no device-level evidence is a guess. Keep
                # generic IF-MIB/system collection, but do not publish a vendor
                # OID module that has not been observed or explicitly verified.
                continue
            exporter_override = None
            effective_variant_key = variant_key
            if is_vendor_specific and discovery_status in {"matched", "partial"} and profile_verification not in {"tested", "published", "verified", "passed", "approved"}:
                candidate_vendor = str((discovery.get("identity") or {}).get("vendor") or device.get("vendor") or "")
                if _selector_matches(candidate_vendor, module_vendor) or _selector_matches(module_vendor, candidate_vendor):
                    candidate_module = discovery.get("exporter_module")
                    if isinstance(candidate_module, Mapping) and candidate_module.get("metrics"):
                        exporter_override = dict(candidate_module)
                        effective_variant_key = f"auto_{module_key}_{_hash(exporter_override)[:12]}"
            walk_fingerprint = str(module.get("walk_fingerprint") or "").strip()
            if walk_fingerprint:
                walk_key = (asset_id, walk_fingerprint)
                previous_walk = walk_seen.get(walk_key)
                if previous_walk and previous_walk != variant_key:
                    raise CompileError(f"DUPLICATE_WALK: asset={asset_id} fingerprint={walk_fingerprint}")
                walk_seen[walk_key] = variant_key
            interval = duration_seconds(entry.get("interval", entry.get("interval_seconds", 60)), field="interval")
            scrape_timeout = duration_seconds(entry.get("scrape_timeout", entry.get("scrape_timeout_seconds", 20)), field="scrape_timeout")
            if scrape_timeout >= interval:
                raise CompileError(f"TIMEOUT_INVALID: scrape_timeout ({scrape_timeout}s) must be less than interval ({interval}s)")
            assignment_payload = {
                "asset_id": asset_id,
                "collector_id": collector_id,
                "module_variant_id": str(variant.get("id") or ""),
                "auth_alias": auth_alias,
                "interval_seconds": interval,
                "scrape_timeout_seconds": scrape_timeout,
                "variant_key": effective_variant_key,
                "exporter_override": exporter_override or {},
            }
            key = (asset_id, str(variant.get("id") or variant_key))
            assignment_hash = _hash(assignment_payload)
            existing = seen.get(key)
            if existing is not None:
                if existing.assignment_hash != assignment_hash:
                    raise CollectionAssignmentConflict(
                        f"CollectionAssignmentConflict: asset={asset_id} variant={variant_key} "
                        f"has incompatible interval/timeout/collector/auth"
                    )
                continue
            assignment_id = f"assignment-{assignment_hash[:16]}"
            hostname = str(device.get("hostname") or device.get("name") or "").strip()
            assignment = Assignment(
                id=assignment_id,
                asset_id=asset_id,
                hostname=hostname,
                target=target,
                collector_id=collector_id,
                module_variant_id=str(variant.get("id") or ""),
                module_key=str(module.get("module_key") or module_key),
                variant_key=effective_variant_key,
                credential_id=credential_id,
                auth_alias=auth_alias,
                interval_seconds=interval,
                scrape_timeout_seconds=scrape_timeout,
                enabled=True,
                source_type=str(entry.get("source_type") or "PLAN"),
                source_plan_id=plan_id,
                tenant_id=str(device.get("tenant_id") or ""),
                site_id=str(device.get("site_id") or device.get("site") or ""),
                site_name=str(device.get("site_name") or device.get("site") or device.get("site_id") or "").strip(),
                vendor=str(device.get("vendor") or module.get("vendor") or ""),
                platform=str(device.get("platform") or module.get("cli_platform") or ""),
                role=str(device.get("role") or ""),
                selection_reason=(
                    plan_entry_match_reason(entry, device)
                    if variant_match_reason(variant, device, module) == "variant scope unrestricted"
                    else f"{plan_entry_match_reason(entry, device)}; {variant_match_reason(variant, device, module)}"
                ),
                assignment_hash=assignment_hash,
                exporter_override=exporter_override,
                discovery_status=discovery_status,
            )
            seen[key] = assignment
            result.append(assignment)
    return [item.as_dict() for item in result]


def render_target_snapshot(assignments: Iterable[Mapping[str, Any]], *, collector_id: str | None = None) -> list[dict[str, Any]]:
    """Render a secret-free file-SD snapshot consumed by vmagent."""
    output = []
    for assignment_value in assignments:
        assignment = _row(assignment_value)
        if assignment.get("enabled", True) is False:
            continue
        if collector_id and str(assignment.get("collector_id")) != collector_id:
            continue
        interval = int(assignment.get("interval_seconds") or 60)
        timeout = int(assignment.get("scrape_timeout_seconds") or 20)
        if timeout >= interval:
            raise CompileError("TIMEOUT_INVALID: scrape timeout must be less than interval")
        hostname = str(assignment.get("hostname") or "").strip()
        target = str(assignment.get("target") or "").strip()
        labels = {
            "nexora_asset_id": str(assignment.get("asset_id") or ""),
            "nexora_hostname": hostname or target,
            "nexora_tenant_id": str(assignment.get("tenant_id") or ""),
            "nexora_site_id": str(assignment.get("site_id") or ""),
            "nexora_site_name": str(assignment.get("site_name") or assignment.get("site") or assignment.get("site_id") or "").strip(),
            "nexora_vendor": str(assignment.get("vendor") or ""),
            "nexora_platform": str(assignment.get("platform") or ""),
            "nexora_role": str(assignment.get("role") or ""),
            "nexora_module": str(assignment.get("variant_key") or ""),
            "nexora_auth": str(assignment.get("auth_alias") or ""),
            "nexora_scrape_interval": f"{interval}s",
            "nexora_scrape_timeout": f"{timeout}s",
        }
        if not labels["nexora_auth"].startswith("auth_"):
            raise CompileError("AUTH_ALIAS_INVALID")
        output.append({"targets": [str(assignment.get("target") or "")], "labels": labels})
    return sorted(output, key=lambda item: (item["labels"].get("nexora_asset_id", ""), item["labels"].get("nexora_module", "")))


def render_server_targets(servers: Iterable[Mapping[str, Any]] = ()) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Render secret-free file-SD targets for Linux (node_exporter) and Windows servers."""
    linux_targets_by_addr: dict[str, tuple[tuple[int, int, str], dict[str, Any]]] = {}
    windows_targets_by_addr: dict[str, tuple[tuple[int, int, str], dict[str, Any]]] = {}

    for server_val in servers:
        server = _row(server_val)
        ip = str(server.get("management_ip") or server.get("ip_address") or server.get("ip") or "").strip()
        if not ip:
            continue
        platform = str(server.get("platform") or server.get("os") or server.get("os_type") or "").strip().lower()
        hostname = str(server.get("hostname") or server.get("name") or ip).strip()
        site_name = str(server.get("site_name") or server.get("site") or "默认站点").strip()
        site_id = str(server.get("site_id") or "").strip()
        tenant_id = str(server.get("tenant_id") or "tenant-default").strip()
        asset_id = str(server.get("id") or server.get("asset_id") or "").strip()

        is_windows = "windows" in platform or "win" in platform
        port = 9182 if is_windows else 9100
        target_addr = f"{ip}:{port}"

        labels: dict[str, str] = {
            "instance": target_addr,
            "hostname": hostname,
            "role": "server",
            "os": "windows" if is_windows else "linux",
            "site_name": site_name,
        }
        if site_id:
            labels["site_id"] = site_id
        if tenant_id:
            labels["tenant_id"] = tenant_id
        if asset_id:
            labels["asset_id"] = asset_id

        entry = {"targets": [target_addr], "labels": labels}
        # A managed server can appear once in physical_assets and again as a
        # linked devices row. Scrape each exporter endpoint once, preferring
        # the live device record's tenant/site metadata when both are present.
        status_rank = 1 if str(server.get("status") or "").strip().lower() == "online" else 0
        tenant_rank = 1 if tenant_id != "tenant-default" else 0
        priority = (status_rank, tenant_rank, asset_id)
        targets_by_addr = windows_targets_by_addr if is_windows else linux_targets_by_addr
        existing = targets_by_addr.get(target_addr)
        if existing is None or priority > existing[0]:
            targets_by_addr[target_addr] = (priority, entry)

    linux_targets = [item for _, item in linux_targets_by_addr.values()]
    windows_targets = [item for _, item in windows_targets_by_addr.values()]
    linux_targets.sort(key=lambda x: (x["labels"].get("hostname", ""), x["targets"][0]))
    windows_targets.sort(key=lambda x: (x["labels"].get("hostname", ""), x["targets"][0]))
    return linux_targets, windows_targets


def validate_assignments(assignments: Iterable[Mapping[str, Any]]) -> list[str]:
    """Validate already-materialized assignments before an Apply operation."""
    errors: list[str] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for assignment_value in assignments:
        assignment = _row(assignment_value)
        asset_id = str(assignment.get("asset_id") or "")
        variant_id = str(assignment.get("module_variant_id") or assignment.get("variant_key") or "")
        if not asset_id or not variant_id:
            errors.append("ASSIGNMENT_IDENTITY_MISSING")
            continue
        if not str(assignment.get("auth_alias") or ""):
            errors.append(f"AUTH_NOT_CONFIGURED:{asset_id}")
        try:
            interval = duration_seconds(assignment.get("interval_seconds", 0), field="interval")
            timeout = duration_seconds(assignment.get("scrape_timeout_seconds", 0), field="scrape_timeout")
            if timeout >= interval:
                errors.append(f"TIMEOUT_INVALID:{asset_id}:{variant_id}")
        except CompileError as exc:
            errors.append(str(exc))
        key = (asset_id, variant_id)
        if key in seen and _hash({k: assignment.get(k) for k in ("collector_id", "auth_alias", "interval_seconds", "scrape_timeout_seconds")}) != _hash({k: seen[key].get(k) for k in ("collector_id", "auth_alias", "interval_seconds", "scrape_timeout_seconds")}):
            errors.append(f"CollectionAssignmentConflict:{asset_id}:{variant_id}")
        seen[key] = assignment
    return sorted(set(errors))


def _profile_metric_relabel_configs(interface_profiles: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Attach CMDB interface profile labels after SNMP exporter lookup labels exist."""
    default_rules = [
        {
            "source_labels": ["ifName"], "regex": ".+", "target_label": "interface_role",
            "replacement": "unclassified", "action": "replace",
        },
        *[
            {
                "source_labels": ["ifName"], "regex": ".+", "target_label": label,
                "replacement": value, "action": "replace",
            }
            for label, value in (
                ("utilization_warn_pct", "60"),
                ("utilization_high_pct", "75"),
                ("utilization_critical_pct", "90"),
            )
        ],
    ]
    grouped: dict[tuple[str, str, str, str], list[tuple[str, str]]] = {}
    for value in interface_profiles:
        profile = _row(value)
        asset_id = str(profile.get("asset_id") or "").strip()
        interface_name = str(profile.get("interface_name") or "").strip()
        if not asset_id or not interface_name:
            continue
        role = str(profile.get("interface_role") or "unclassified").strip().lower() or "unclassified"
        try:
            warn = f"{float(profile.get('utilization_warn_pct', 60)):g}"
            high = f"{float(profile.get('utilization_high_pct', 75)):g}"
            critical = f"{float(profile.get('utilization_critical_pct', 90)):g}"
        except (TypeError, ValueError):
            warn, high, critical = "60", "75", "90"
        grouped.setdefault((role, warn, high, critical), []).append((asset_id, interface_name))

    configured_rules: list[dict[str, Any]] = []
    for (role, warn, high, critical), identities in sorted(grouped.items()):
        alternatives = [
            f"{re.escape(asset_id)};{re.escape(interface_name)}"
            for asset_id, interface_name in sorted(set(identities))
        ]
        # Bound each RE2 expression while reducing relabel rule count for common profiles.
        for offset in range(0, len(alternatives), 128):
            regex = "^(?:" + "|".join(alternatives[offset:offset + 128]) + ")$"
            for label, replacement in (
                ("interface_role", role),
                ("utilization_warn_pct", warn),
                ("utilization_high_pct", high),
                ("utilization_critical_pct", critical),
            ):
                configured_rules.append({
                    "source_labels": ["asset_id", "ifName"],
                    "separator": ";",
                    "regex": regex,
                    "target_label": label,
                    "replacement": replacement,
                    "action": "replace",
                })
    return default_rules + configured_rules


def render_vmagent_config(
    snapshot_path: str = "/etc/nexora-collector/runtime/vmagent/targets/snmp_targets.yml",
    interface_profiles: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "global": {"scrape_interval": "60s", "scrape_timeout": "30s"},
        "scrape_configs": [
            {
                "job_name": "network_snmp",
                "file_sd_configs": [{"files": [snapshot_path]}],
                "metrics_path": "/snmp",
                "relabel_configs": [
                    {"source_labels": ["__address__"], "target_label": "__param_target"},
                    {"source_labels": ["nexora_module"], "target_label": "__param_module"},
                    {"source_labels": ["nexora_auth"], "target_label": "__param_auth"},
                    {"source_labels": ["nexora_scrape_interval"], "target_label": "__scrape_interval__"},
                    {"source_labels": ["nexora_scrape_timeout"], "target_label": "__scrape_timeout__"},
                    {"source_labels": ["__param_target"], "target_label": "instance"},
                    {"source_labels": ["nexora_asset_id"], "target_label": "asset_id"},
                    {"source_labels": ["nexora_hostname"], "target_label": "hostname"},
                    {"source_labels": ["nexora_tenant_id"], "target_label": "tenant_id"},
                    {"source_labels": ["nexora_site_id"], "target_label": "site_id"},
                    {"source_labels": ["nexora_site_name"], "target_label": "site_name"},
                    {"source_labels": ["nexora_vendor"], "target_label": "vendor"},
                    {"source_labels": ["nexora_platform"], "target_label": "platform"},
                    {"source_labels": ["nexora_role"], "target_label": "role"},
                    {"action": "labeldrop", "regex": "nexora_auth|nexora_.*"},
                    {"target_label": "__address__", "replacement": "snmp-exporter:9116"},
                ],
                "metric_relabel_configs": _profile_metric_relabel_configs(interface_profiles),
            },
            {
                "job_name": "linux_servers",
                "scrape_interval": "15s",
                "scrape_timeout": "10s",
                "metrics_path": "/metrics",
                "file_sd_configs": [
                    {"files": [
                        "/etc/nexora-collector/runtime/vmagent/targets/*linux*.yml",
                        "/etc/nexora-collector/runtime/vmagent/targets/*server*.yml"
                    ]}
                ],
            },
            {
                "job_name": "windows_servers",
                "scrape_interval": "15s",
                "scrape_timeout": "10s",
                "metrics_path": "/metrics",
                "file_sd_configs": [
                    {"files": [
                        "/etc/nexora-collector/runtime/vmagent/targets/*windows*.yml"
                    ]}
                ],
            }
        ],
    }



def render_auth_aliases(credentials: Iterable[Mapping[str, Any]], aliases: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Render exporter auth config from internal records without exposing secrets in labels."""
    output: dict[str, Any] = {}
    aliases = dict(aliases or {})
    for credential_value in credentials:
        credential = _row(credential_value)
        credential_id = str(credential.get("id") or "")
        if not credential_id:
            continue
        alias = str(aliases.get(credential_id) or opaque_auth_alias(credential_id))
        if not alias.startswith("auth_"):
            raise CompileError("AUTH_ALIAS_INVALID")
        credential_type = str(credential.get("credential_type") or "snmpv2").lower()
        if credential_type in {"snmpv3", "snmp_v3"}:
            auth: dict[str, Any] = {"version": 3}
            auth.update({
                "username": credential.get("username") or "",
                "security_level": credential.get("security_level") or "authPriv",
                "auth_protocol": credential.get("auth_protocol") or "SHA",
                "password": credential.get("password") or credential.get("decrypted_password") or "",
                "priv_protocol": credential.get("priv_protocol") or "AES",
                "priv_password": credential.get("priv_password") or "",
                "context_name": credential.get("context_name") or "",
            })
            security_level = str(auth["security_level"]).lower()
            if not auth["username"] or security_level not in {"noauthnopriv", "authnopriv", "authpriv"}:
                raise CompileError(f"AUTH_INVALID: {alias} has an invalid SNMPv3 security level or username")
            if security_level != "noauthnopriv" and not auth["password"]:
                raise CompileError(f"AUTH_INVALID: {alias} requires an SNMPv3 auth password")
            if security_level == "authpriv" and not auth["priv_password"]:
                raise CompileError(f"AUTH_INVALID: {alias} requires an SNMPv3 privacy password")
        else:
            auth = {"version": 2}
            auth.update({"community": credential.get("community") or credential.get("snmp_community") or ""})
            if not auth["community"]:
                raise CompileError(f"AUTH_INVALID: {alias} requires an SNMPv2c community")
        output[alias] = auth
    return {"auths": output}


def compile_artifact(
    assignments: Iterable[Mapping[str, Any]],
    *,
    collector_id: str,
    config_version: int,
    credentials: Iterable[Mapping[str, Any]] = (),
    modules: Iterable[Mapping[str, Any]] = (),
    variants: Iterable[Mapping[str, Any]] = (),
    servers: Iterable[Mapping[str, Any]] = (),
    interface_profiles: Iterable[Mapping[str, Any]] = (),
    output_root: str | Path | None = None,
    compiler_version: str = "monitoring-compiler-1.0.0",
) -> dict[str, Any]:
    """Build a versioned artifact; writes atomically only when ``output_root`` is supplied."""
    selected = [a for a in assignments if str(a.get("collector_id")) == collector_id and a.get("enabled", True) is not False]
    credential_rows = list(credentials)
    module_rows = list(modules)
    variant_rows = list(variants)
    snapshot = render_target_snapshot(selected, collector_id=collector_id)
    target_yaml = yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False)
    vmagent_yaml = yaml.safe_dump(render_vmagent_config(interface_profiles=interface_profiles), allow_unicode=True, sort_keys=False)
    exporter_modules = render_exporter_modules(selected, modules=module_rows, variants=variant_rows)
    assignment_aliases = {
        str(a.get("credential_id") or ""): str(a.get("auth_alias") or "")
        for a in selected
        if a.get("credential_id") and a.get("auth_alias")
    }
    auth_payload = render_auth_aliases(credential_rows, assignment_aliases)
    rendered_aliases = set(auth_payload.get("auths") or {})
    required_aliases = {str(a.get("auth_alias") or "") for a in selected}
    missing_aliases = sorted(alias for alias in required_aliases if alias and alias not in rendered_aliases)
    if missing_aliases:
        raise CompileError(f"AUTH_NOT_FOUND: missing collector auth artifact for {','.join(missing_aliases)}")
    auth_yaml = yaml.safe_dump(auth_payload, allow_unicode=True, sort_keys=False)
    variant_index = {}
    for value in variant_rows:
        row = _row(value)
        for key in (row.get("variant_key"), row.get("id")):
            if key:
                variant_index[str(key)] = row
    module_manifest = []
    for variant_key, config in sorted(exporter_modules.items()):
        variant = variant_index.get(variant_key) or {}
        raw_config = variant.get("oid_config") or variant.get("oid_config_json") or {}
        try:
            normalized_config = _parse_variant_oid_config(raw_config)
        except CompileError:
            normalized_config = config
        module_manifest.append({
            "variant_key": variant_key,
            "supported_platforms": _scope_values(variant.get("supported_platforms")),
            "supported_models": _scope_values(variant.get("supported_models")),
            "supported_version_scope": _scope_values(variant.get("supported_version_scope")),
            "mib_bundle_id": str(variant.get("mib_bundle_id") or ""),
            "generator_version": str(variant.get("generator_version") or compiler_version),
            "generator_config_hash": str(variant.get("generator_config_hash") or _hash(normalized_config)),
            "walk_count": len(config.get("walk") or []),
            "get_count": len(config.get("get") or []),
            "metric_count": len(config.get("metrics") or []),
        })
    linux_targets, windows_targets = render_server_targets(servers)
    manifest = {
        "schema_version": "1.0",
        "collector_id": collector_id,
        "config_version": int(config_version),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "assignment_count": len(selected),
        "module_count": len({str(a.get("variant_key")) for a in selected}),
        "auth_alias_count": len(auth_payload.get("auths") or {}),
        "server_target_count": len(linux_targets) + len(windows_targets),
        "modules": module_manifest,
        "compiler_version": compiler_version,
    }
    module_files = {
        f"snmp_exporter/modules/{variant_key}.yml": yaml.safe_dump(
            {"modules": {variant_key: config}}, allow_unicode=True, sort_keys=False,
        )
        for variant_key, config in exporter_modules.items()
    }
    files = {
        "vmagent/scrape.yml": vmagent_yaml,
        "vmagent/targets/snmp_targets.yml": target_yaml,
        "vmagent/targets/linux_targets.yml": yaml.safe_dump(linux_targets, allow_unicode=True, sort_keys=False),
        "vmagent/targets/windows_targets.yml": yaml.safe_dump(windows_targets, allow_unicode=True, sort_keys=False),
        "snmp_exporter/modules/modules.yml": yaml.safe_dump(
            {"modules": exporter_modules}, allow_unicode=True, sort_keys=False,
        ),
        "snmp_exporter/auth/auth.yml": auth_yaml,
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
    files.update(module_files)
    # The Docker snmp-exporter consumes one complete config file.  Keep the
    # split module/auth artifacts above for external collector nodes, and also
    # render a merged file for the shared Compose runtime volume.
    files["snmp_exporter/snmp.yml"] = yaml.safe_dump(
        {
            "auths": auth_payload.get("auths") or {},
            "modules": exporter_modules,
        },
        allow_unicode=True,
        sort_keys=False,
    )
    checksums = []
    # Avoid a self-referential manifest checksum: the manifest records the
    # checksum file, while the checksum file covers all payload files except
    # the manifest itself.
    for name, content in sorted(files.items()):
        if name == "manifest.json":
            continue
        checksums.append(f"{hashlib.sha256(content.encode('utf-8')).hexdigest()}  {name}")
    files["checksums.sha256"] = "\n".join(checksums) + "\n"
    manifest["checksum"] = hashlib.sha256(files["checksums.sha256"].encode("utf-8")).hexdigest()
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    artifact_path = None
    if output_root is not None:
        root = Path(output_root) / f"artifact-v{int(config_version):08d}"
        temp = root.with_name(root.name + ".tmp")
        if temp.exists():
            for child in sorted(temp.rglob("*"), reverse=True):
                if child.is_file(): child.unlink()
                elif child.is_dir(): child.rmdir()
            temp.rmdir()
        for name, content in files.items():
            destination = temp / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            if name.endswith("auth.yml") or name.endswith("snmp.yml"):
                try:
                    destination.chmod(0o600)
                except OSError:
                    # Windows ACLs are managed by the deployment service; do
                    # not make artifact publication fail on chmod semantics.
                    pass
        root.parent.mkdir(parents=True, exist_ok=True)
        if root.exists():
            for child in sorted(root.rglob("*"), reverse=True):
                if child.is_file(): child.unlink()
                elif child.is_dir(): child.rmdir()
            root.rmdir()
        temp.replace(root)
        artifact_path = str(root)
    return {"manifest": manifest, "files": files, "artifact_path": artifact_path, "snapshot": snapshot}


def validate_artifact(artifact: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    """Validate a compiled artifact before it can become Last Known Good."""
    if isinstance(artifact, (str, Path)):
        root = Path(artifact)
        if not root.is_dir():
            raise CompileError("ARTIFACT_NOT_FOUND")
        files: dict[str, str] = {}
        for path in root.rglob("*"):
            if path.is_file():
                files[str(path.relative_to(root)).replace("\\", "/")] = path.read_text(encoding="utf-8")
    else:
        files = {str(name): str(content) for name, content in dict(artifact.get("files") or {}).items()}
    try:
        manifest = json.loads(files.get("manifest.json", "{}"))
    except (TypeError, ValueError) as exc:
        raise CompileError("MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise CompileError("MANIFEST_SCHEMA_INVALID")
    if "modules" in manifest and not isinstance(manifest.get("modules"), list):
        raise CompileError("MANIFEST_MODULES_INVALID")
    checksums_text = files.get("checksums.sha256", "")
    if not checksums_text.strip():
        raise CompileError("CHECKSUMS_MISSING")
    manifest_checksum = str(manifest.get("checksum") or "")
    if manifest_checksum and manifest_checksum != hashlib.sha256(checksums_text.encode("utf-8")).hexdigest():
        raise CompileError("MANIFEST_CHECKSUM_MISMATCH")
    checked = 0
    for line in checksums_text.splitlines():
        if "  " not in line:
            raise CompileError("CHECKSUMS_INVALID")
        expected, name = line.split("  ", 1)
        content = files.get(name)
        if content is None or hashlib.sha256(content.encode("utf-8")).hexdigest() != expected:
            raise CompileError(f"CHECKSUM_MISMATCH:{name}")
        checked += 1
    for required in ("vmagent/scrape.yml", "vmagent/targets/snmp_targets.yml", "snmp_exporter/auth/auth.yml", "snmp_exporter/snmp.yml"):
        if required not in files:
            raise CompileError(f"ARTIFACT_FILE_MISSING:{required}")
    try:
        yaml.safe_load(files["vmagent/scrape.yml"])
        targets = yaml.safe_load(files["vmagent/targets/snmp_targets.yml"])
        yaml.safe_load(files["snmp_exporter/auth/auth.yml"])
        yaml.safe_load(files["snmp_exporter/snmp.yml"])
    except yaml.YAMLError as exc:
        raise CompileError("ARTIFACT_YAML_INVALID") from exc
    if not isinstance(targets, list):
        raise CompileError("TARGET_SNAPSHOT_INVALID")
    return {"valid": True, "checked_files": checked, "manifest": manifest}


class AuthAliasRenderer:
    """Small stateful facade used by workers that compile many collectors."""

    def __init__(self, aliases: Mapping[str, str] | None = None):
        self.aliases = dict(aliases or {})

    def alias_for(self, credential_id: str) -> str:
        credential_id = str(credential_id or "")
        if not credential_id:
            return ""
        alias = str(self.aliases.get(credential_id) or opaque_auth_alias(credential_id))
        if not alias.startswith("auth_"):
            raise CompileError("AUTH_ALIAS_INVALID")
        self.aliases[credential_id] = alias
        return alias

    def render(self, credentials: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        return render_auth_aliases(credentials, self.aliases)


class ConfigCompiler:
    """Object facade around the pure compiler functions."""

    def __init__(self, *, compiler_version: str = "monitoring-compiler-1.0.0"):
        self.compiler_version = compiler_version

    def assignments(self, devices, plans, modules, variants, collectors, *, credential_aliases=None):
        return build_assignments(devices, plans, modules, variants, collectors, credential_aliases=credential_aliases)

    def artifact(self, assignments, *, collector_id: str, config_version: int, credentials=(), modules=(), variants=(), output_root=None):
        return compile_artifact(
            assignments,
            collector_id=collector_id,
            config_version=config_version,
            credentials=credentials,
            modules=modules,
            variants=variants,
            output_root=output_root,
            compiler_version=self.compiler_version,
        )
