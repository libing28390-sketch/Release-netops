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


class CompileError(ValueError):
    """A configuration cannot safely be applied to a collector."""


class CollectionAssignmentConflict(CompileError):
    """The same asset/module would be scraped with incompatible settings."""


_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$", re.I)

GENERIC_IF_MIB_MODULE = {
    "module_key": "generic_ifmib_interface",
    "display_name": "Generic IF-MIB interface",
    "metric_group": "interface",
    "walk": ["1.3.6.1.2.1.2.2", "1.3.6.1.2.1.31.1.1"],
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
    "ifInDiscards", "ifOutDiscards",
)


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
    assignment_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
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
            "vendor": self.vendor,
            "platform": self.platform,
            "role": self.role,
            "assignment_hash": self.assignment_hash,
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
            module_key = str(entry.get("module") or entry.get("module_key") or "").strip()
            variant_key = str(entry.get("variant") or entry.get("variant_key") or "").strip()
            module = module_map.get(module_key) or module_by_id.get(module_key)
            variant = variant_map.get(variant_key) or variant_by_id.get(variant_key)
            if not module:
                raise CompileError(f"MODULE_NOT_FOUND: {module_key}")
            if not variant:
                raise CompileError(f"MODULE_VARIANT_NOT_FOUND: {variant_key}")
            variant_status = str(variant.get("status") or "PUBLISHED").upper()
            if variant_status not in {"TESTED", "PUBLISHED"}:
                raise CompileError(f"MODULE_VARIANT_NOT_PUBLISHED: {variant_key}")
            module_id = str(module.get("id") or "")
            if str(variant.get("module_id") or "") not in {"", module_id}:
                raise CompileError(f"MODULE_VARIANT_MISMATCH: {variant_key}")
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
            assignment = Assignment(
                id=assignment_id,
                asset_id=asset_id,
                target=target,
                collector_id=collector_id,
                module_variant_id=str(variant.get("id") or ""),
                module_key=str(module.get("module_key") or module_key),
                variant_key=str(variant.get("variant_key") or variant_key),
                credential_id=credential_id,
                auth_alias=auth_alias,
                interval_seconds=interval,
                scrape_timeout_seconds=scrape_timeout,
                enabled=True,
                source_type=str(entry.get("source_type") or "PLAN"),
                source_plan_id=plan_id,
                tenant_id=str(device.get("tenant_id") or ""),
                site_id=str(device.get("site_id") or device.get("site") or ""),
                vendor=str(device.get("vendor") or module.get("vendor") or ""),
                platform=str(device.get("platform") or module.get("cli_platform") or ""),
                role=str(device.get("role") or ""),
                assignment_hash=assignment_hash,
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
        labels = {
            "nexora_asset_id": str(assignment.get("asset_id") or ""),
            "nexora_tenant_id": str(assignment.get("tenant_id") or ""),
            "nexora_site_id": str(assignment.get("site_id") or ""),
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


def render_vmagent_config(snapshot_path: str = "/etc/nexora-collector/targets/snmp_targets.yml") -> dict[str, Any]:
    return {
        "global": {"scrape_interval": "60s", "scrape_timeout": "30s"},
        "scrape_configs": [{
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
                {"source_labels": ["nexora_tenant_id"], "target_label": "tenant_id"},
                {"source_labels": ["nexora_site_id"], "target_label": "site_id"},
                {"source_labels": ["nexora_vendor"], "target_label": "vendor"},
                {"source_labels": ["nexora_platform"], "target_label": "platform"},
                {"source_labels": ["nexora_role"], "target_label": "role"},
                {"action": "labeldrop", "regex": "nexora_auth|nexora_scrape_interval|nexora_scrape_timeout"},
                {"target_label": "__address__", "replacement": "snmp-exporter:9116"},
            ],
        }],
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
        auth: dict[str, Any] = {"version": 3}
        credential_type = str(credential.get("credential_type") or "snmpv2").lower()
        if credential_type in {"snmpv3", "snmp_v3"}:
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
    output_root: str | Path | None = None,
    compiler_version: str = "monitoring-compiler-1.0.0",
) -> dict[str, Any]:
    """Build a versioned artifact; writes atomically only when ``output_root`` is supplied."""
    selected = [a for a in assignments if str(a.get("collector_id")) == collector_id and a.get("enabled", True) is not False]
    credential_rows = list(credentials)
    snapshot = render_target_snapshot(selected, collector_id=collector_id)
    target_yaml = yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False)
    vmagent_yaml = yaml.safe_dump(render_vmagent_config(), allow_unicode=True, sort_keys=False)
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
    manifest = {
        "schema_version": "1.0",
        "collector_id": collector_id,
        "config_version": int(config_version),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "assignment_count": len(selected),
        "module_count": len({str(a.get("variant_key")) for a in selected}),
        "auth_alias_count": len(auth_payload.get("auths") or {}),
        "compiler_version": compiler_version,
    }
    files = {
        "vmagent/scrape.yml": vmagent_yaml,
        "vmagent/targets/snmp_targets.yml": target_yaml,
        "snmp_exporter/modules/generic_ifmib_interface_std.yml": yaml.safe_dump(
            {"modules": {"generic_ifmib_interface_std": {
                "walk": list(GENERIC_IF_MIB_MODULE["walk"]),
                "max_repetitions": GENERIC_IF_MIB_VARIANT["max_repetitions"],
                "retries": GENERIC_IF_MIB_VARIANT["retries"],
                "timeout": f"{GENERIC_IF_MIB_VARIANT['request_timeout_ms'] / 1000:g}s",
            }}}, allow_unicode=True, sort_keys=False,
        ),
        "snmp_exporter/modules/generic_system_std.yml": yaml.safe_dump(
            {"modules": {"generic_system_std": {
                "walk": ["1.3.6.1.2.1.1.3"],
                "max_repetitions": 10,
                "retries": 2,
                "timeout": "3s",
            }}}, allow_unicode=True, sort_keys=False,
        ),
        "snmp_exporter/auth/auth.yml": auth_yaml,
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
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
            if name.endswith("auth.yml"):
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
    for required in ("vmagent/scrape.yml", "vmagent/targets/snmp_targets.yml", "snmp_exporter/auth/auth.yml"):
        if required not in files:
            raise CompileError(f"ARTIFACT_FILE_MISSING:{required}")
    try:
        yaml.safe_load(files["vmagent/scrape.yml"])
        targets = yaml.safe_load(files["vmagent/targets/snmp_targets.yml"])
        yaml.safe_load(files["snmp_exporter/auth/auth.yml"])
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

    def artifact(self, assignments, *, collector_id: str, config_version: int, credentials=(), output_root=None):
        return compile_artifact(assignments, collector_id=collector_id, config_version=config_version, credentials=credentials, output_root=output_root, compiler_version=self.compiler_version)
