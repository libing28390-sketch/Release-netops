"""PostgreSQL-backed Telemetry configuration, capacity and publish service."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import secrets
import hmac
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.tenant_policy import DEFAULT_TENANT_ID, TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from database import get_db_connection
from database.core import _USE_PG
from services.rack_scope_service import allowed_resource_scope, device_scope_predicate
from services.audit_service import log_audit_event


DEVICE_LIMIT = 50
SERIES_LIMIT = 25_000
SAMPLES_PER_SECOND_LIMIT = 5_000.0
MESSAGE_BYTES_LIMIT = 4 * 1024 * 1024
QUEUE_BYTES_LIMIT = 16 * 1024 * 1024 * 1024
RECEIVER_CONFIG_BYTES_LIMIT = 8 * 1024 * 1024
_TELEMETRY_COLLECTOR_ID = "telemetry-collector-local"
_METRIC_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,159}$")
_MAX_MAPPINGS = 256
logger = logging.getLogger("services.telemetry_config")


def _queue_bytes_limit() -> int:
    """Mirror the dedicated vmagent disk-queue bound from Docker Compose."""
    raw = os.environ.get("TELEMETRY_VMAGENT_MAX_DISK_USAGE", "16GiB").strip()
    match = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?", raw)
    if not match:
        return QUEUE_BYTES_LIMIT
    amount = float(match.group(1))
    unit = (match.group(2) or "B").lower()
    multiplier = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }[unit]
    return max(1, int(amount * multiplier))


def _audit_control_action(user: dict[str, Any], event_type: str, summary: str,
                          target_type: str, target_id: str, details: dict[str, Any] | None = None) -> None:
    try:
        log_audit_event(
            event_type=event_type,
            category="monitoring",
            severity="info",
            status="success",
            summary=summary,
            actor_id=(user or {}).get("id"),
            actor_username=(user or {}).get("username", "system"),
            actor_role=(user or {}).get("role", "system"),
            target_type=target_type,
            target_id=target_id,
            details=details or {},
        )
    except Exception:
        logger.warning("Telemetry audit event could not be persisted", exc_info=True)


def ensure_receiver_status_token() -> str:
    """Create a private collector-to-control-plane status token on first boot."""
    token_path = Path(os.environ.get("TELEMETRY_STATUS_TOKEN_FILE", "/app/data/telemetry-control/status.token"))
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return token_path.read_text(encoding="ascii").strip()
    token = secrets.token_urlsafe(48)
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        output.write(token)
        output.flush()
        os.fsync(output.fileno())
    return token


def validate_receiver_status_token(candidate: str) -> bool:
    try:
        stored = ensure_receiver_status_token()
    except OSError:
        return False
    return bool(candidate) and hmac.compare_digest(stored, str(candidate))


def validate_device_config(device_id: str, payload: Any, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        device = _load_device(conn, device_id, user, "update")
        profile = _profile(conn, payload.profile_id)
        profile_match_state = _validate_profile_known_scope(profile, device, draft=not bool(payload.enabled))
        _require_telemetry_collector(conn, payload.collector_id)
        if bool(payload.enabled):
            _validate_profile_device(profile, device)
            _require_collector_endpoint()
        allowed_sources = _validate_allowed_sources(list(payload.allowed_sources or []))
        device_source_address = _normalize_device_source_address(
            getattr(payload, "device_source_address", None)
        )
        if profile.get("auth_mode") in {"tls_pki", "device_configured"} and not allowed_sources:
            raise TelemetryServiceError("TELEMETRY_SOURCE_INVALID", "TLS or IP-allowlisted Telemetry sources require at least one allowed source IP")
        if payload.tls_profile_id:
            tls = conn.execute(
                "SELECT status, fingerprint FROM telemetry_tls_profiles WHERE id = ? AND tenant_id = ?",
                (payload.tls_profile_id, device["tenant_id"]),
            ).fetchone()
            if not tls or str(_dict(tls).get("status") or "").upper() != "ACTIVE" or not _dict(tls).get("fingerprint"):
                raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "Active TLS credentials and peer fingerprint are required")
        return {
            "valid": True,
            "device_id": device_id,
            "profile_id": profile["id"],
            "support_status": profile["support_status"],
            "estimated_series": 0,
            "estimated_samples_per_second": 0,
            "allowed_source_count": len(allowed_sources),
            "ready_to_collect": False,
            "state": "AWAITING_DEVICE",
            "profile_match_state": profile_match_state,
            "profile_match_fields": _profile_identification_fields(profile, device),
            "version_confirmation_required": "version" in _profile_identification_fields(profile, device),
            "profile_match_message": (
                "设备型号或软件版本待识别；当前配置保持停用，启用前请人工核对。"
                if profile_match_state == "IDENTIFICATION_PENDING"
                else "设备型号或软件版本超出协议档范围；当前仅可登记停用配置。"
                if profile_match_state == "MISMATCH"
                else "设备型号和软件版本符合协议档案范围。"
            ),
            "device_source_address": device_source_address,
            **_collector_endpoint(),
        }
    finally:
        conn.close()


class TelemetryServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _require_postgres() -> None:
    if not _USE_PG:
        raise RuntimeError("Telemetry control-plane operations require PostgreSQL")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return parsed


def _page_args(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    return page, page_size


def _scope_where(conn, user: dict[str, Any], action: str, alias: str = "d") -> tuple[str, tuple[Any, ...]]:
    scope = allowed_resource_scope(conn, user, "asset", action)
    predicate, params = device_scope_predicate(scope, device_alias=alias)
    clauses = [predicate] if predicate else []
    values = list(params)
    if scope.tenant_id:
        clauses.append(f"COALESCE({alias}.tenant_id, 'tenant-default') = ?")
        values.append(scope.tenant_id)
    if not clauses:
        clauses.append("1 = 1")
    return " AND ".join(clauses), tuple(values)


def _load_device(conn, device_id: str, user: dict[str, Any], action: str = "view") -> dict[str, Any]:
    where, params = _scope_where(conn, user, action)
    row = conn.execute(
        f"""SELECT d.id AS device_id, d.asset_id, d.tenant_id, d.hostname,
                   d.ip_address, d.vendor, d.platform, d.version, pa.asset_tag, pa.model,
                   pa.site_id, pa.asset_type
              FROM devices d
              JOIN physical_assets pa ON pa.id = d.asset_id
             WHERE d.id = ? AND d.asset_id IS NOT NULL AND {where}""",
        (str(device_id), *params),
    ).fetchone()
    if not row:
        raise TelemetryServiceError("TELEMETRY_DEVICE_NOT_FOUND", "Device not found in the permitted asset scope", 404)
    device = _dict(row)
    actual_tenant = str(device.get("tenant_id") or DEFAULT_TENANT_ID)
    requested_tenant = tenant_scope_for_user(user)
    if TENANT_ISOLATION_ENABLED and requested_tenant and requested_tenant != actual_tenant:
        raise TelemetryServiceError("TELEMETRY_DEVICE_NOT_FOUND", "Device not found in the permitted asset scope", 404)
    device["tenant_id"] = actual_tenant
    return device


def _profile(conn, profile_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM telemetry_protocol_profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Telemetry profile was not found", 404)
    item = _dict(row)
    item["official_sources"] = _json_value(item.get("official_sources"), [])
    return item


def _require_telemetry_collector(conn, collector_id: str, *, lock: bool = False) -> dict[str, Any]:
    if str(collector_id) != _TELEMETRY_COLLECTOR_ID:
        raise TelemetryServiceError("TELEMETRY_COLLECTOR_UNAVAILABLE", "Only the dedicated local Telemetry receiver is supported in this release", 409)
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute(
        "SELECT * FROM telemetry_collectors WHERE id = ?" + suffix,
        (str(collector_id),),
    ).fetchone()
    item = _dict(row)
    if not item:
        raise TelemetryServiceError("TELEMETRY_COLLECTOR_NOT_FOUND", "Telemetry collector not found", 404)
    if not bool(item.get("enabled")):
        raise TelemetryServiceError("TELEMETRY_COLLECTOR_UNAVAILABLE", "Telemetry collector is disabled", 409)
    if str(item.get("collector_type") or "").upper() != "LOCAL":
        raise TelemetryServiceError("TELEMETRY_COLLECTOR_UNAVAILABLE", "Only the local Telemetry receiver is supported in this release", 409)
    return item


def _collector_endpoint() -> dict[str, Any]:
    """Read the device-reachable endpoint configured for the local receiver."""
    raw_address = os.environ.get("TELEMETRY_DEVICE_TARGET_ADDRESS", "").strip()
    raw_port = os.environ.get("TELEMETRY_GRPC_BIND_PORT", "").strip()
    raw_bind_ip = os.environ.get("TELEMETRY_GRPC_BIND_IP", "0.0.0.0").strip() or "0.0.0.0"
    if not raw_address:
        raw_address = os.environ.get("TELEMETRY_DEFAULT_TARGET_ADDRESS", "192.168.56.1").strip() or "192.168.56.1"
    if not raw_port:
        raw_port = "10051"
    valid_address = False
    if raw_address and len(raw_address) <= 253 and not any(char.isspace() for char in raw_address):
        try:
            parsed_address = ipaddress.ip_address(raw_address)
            valid_address = not (
                parsed_address.is_loopback
                or parsed_address.is_link_local
                or parsed_address.is_unspecified
            )
        except ValueError:
            labels = raw_address.rstrip(".").split(".")
            hostname = raw_address.rstrip(".").casefold()
            valid_address = not (hostname == "localhost" or hostname.endswith(".localhost")) and bool(labels) and all(
                label
                and len(label) <= 63
                and label[0].isalnum()
                and label[-1].isalnum()
                and all(char.isalnum() or char == "-" for char in label)
                for label in labels
            )
    try:
        bind_address = ipaddress.ip_address(raw_bind_ip)
        bind_reachable = bind_address.is_unspecified or not (
            bind_address.is_loopback or bind_address.is_link_local
        )
    except ValueError:
        bind_reachable = False
    try:
        port = int(raw_port)
        valid_port = 1 <= port <= 65535
    except (TypeError, ValueError):
        port = None
        valid_port = False
    configured = valid_address and valid_port and bind_reachable
    return {
        "target_address": raw_address if configured else "",
        "grpc_port": port if configured else None,
        "endpoint_configured": configured,
    }


def _require_collector_endpoint() -> dict[str, Any]:
    endpoint = _collector_endpoint()
    if not endpoint["endpoint_configured"]:
        raise TelemetryServiceError(
            "TELEMETRY_COLLECTOR_ENDPOINT_UNCONFIGURED",
            "Bind gRPC to a device-reachable interface or 0.0.0.0, publish/map that port, and set a reachable TELEMETRY_DEVICE_TARGET_ADDRESS plus TELEMETRY_GRPC_BIND_PORT before enabling Telemetry",
            409,
        )
    return endpoint


def validate_collector_endpoint(collector_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Validate the environment-backed endpoint without attempting to edit it."""
    _require_postgres()
    conn = get_db_connection()
    try:
        _require_telemetry_collector(conn, collector_id)
        endpoint = _collector_endpoint()
        return {
            "collector_id": collector_id,
            "valid": endpoint["endpoint_configured"],
            **endpoint,
            "error_code": "" if endpoint["endpoint_configured"] else "TELEMETRY_COLLECTOR_ENDPOINT_UNCONFIGURED",
            "message": "" if endpoint["endpoint_configured"] else "Bind gRPC to a device-reachable interface or 0.0.0.0, publish/map that port, and set a reachable advertised address and gRPC port.",
        }
    finally:
        conn.close()


def list_telemetry_collectors(user: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
    _require_postgres()
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM telemetry_collectors ORDER BY name, id").fetchall()
        items = []
        for row in rows:
            item = _dict(row)
            items.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "collector_type": item.get("collector_type"),
                "status": item.get("status"),
                "enabled": bool(item.get("enabled")),
                "device_limit": int(item.get("device_limit") or DEVICE_LIMIT),
                "series_limit": int(item.get("series_limit") or SERIES_LIMIT),
                "samples_per_second_limit": float(item.get("samples_per_second_limit") or SAMPLES_PER_SECOND_LIMIT),
                "message_bytes_limit": int(item.get("message_bytes_limit") or MESSAGE_BYTES_LIMIT),
                "queue_bytes_limit": _queue_bytes_limit(),
                **_collector_endpoint(),
            })
        return {"items": items}
    finally:
        conn.close()


def _known_device_value(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    return text not in {"", "unknown", "unrecognized", "未识别", "n/a", "na", "none", "null", "-"}


def _h3c_release_pending(profile: dict[str, Any], version: str) -> bool:
    scope = str(profile.get("version_scope") or "")
    if "7.1" in scope or "comware" in scope.casefold():
        return False
    return (
        str(profile.get("vendor") or "").casefold() == "h3c"
        and any(re.match(r"R[\dx]{4}", item.strip(), re.IGNORECASE) for item in re.split(r"[,/;]", scope))
        and bool(re.fullmatch(r"(?:Comware\s+)?V?\d+(?:\.\d+)+", version, re.IGNORECASE))
    )


def _version_scope_matches(scope: str, version: str) -> bool:
    """Match documented x wildcards, including H3C versions like R6717Pxx-6W101 and Comware 7.1.x."""
    scope = scope.strip().casefold()
    v_clean = version.strip().casefold()
    if scope in {"7.1.x", "comware v7", "cmw710", "vrp", "vrp8"}:
        if scope in {"7.1.x", "comware v7", "cmw710"}:
            return bool(re.search(r"(?:\b7\.1\b|\bcmw710\b|\br6\d{3}\b)", v_clean, re.IGNORECASE))
        return bool(re.search(r"\bv[2368]00r\d{3}", v_clean, re.IGNORECASE))
    if re.match(r"r[\dx]{4}", scope):
        version = re.sub(r"\brelease\s+(?=\d)", "r", version, flags=re.IGNORECASE)
        if scope == "r6717pxx-6w101":
            return bool(re.search(r"(?:\br6717(?:p\d{2})?\b|\b7\.1\.)", version, re.IGNORECASE))
    escaped_scope = re.escape(scope)
    pattern = re.sub(
        r"x+",
        lambda match: f"[0-9a-z]{{{len(match.group(0))}}}",
        escaped_scope,
    )
    return bool(re.search(pattern, version, flags=re.IGNORECASE))


def _normalize_hardware_token(value: str) -> str:
    """Strip marketing/vendor prefixes and non-alphanumeric delimiters."""
    without_variants = re.sub(r"\[[^\]]+\]", "", str(value or ""))
    with_ne = re.sub(r"\bnetengine\s*(?=\d)", "ne", without_variants, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:cloudengine|netengine|hisecengine|airengine|secpath|h3c|huawei)\b",
        "",
        with_ne,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[^a-z0-9]", "", cleaned.casefold())


def _model_scope_token_matches(raw_token: str, raw_model: str) -> bool:
    """Match exact SKU tokens, base family tokens, and 00/000-series wildcards."""
    token = _normalize_hardware_token(raw_token)
    model = _normalize_hardware_token(raw_model)
    if not token or not model:
        return False
    if token in model:
        return True
    if "[" in str(raw_token or ""):
        base_before_dash = _normalize_hardware_token(str(raw_token).split("-")[0])
        if len(base_before_dash) >= 4 and base_before_dash in model:
            return True
    m_series = re.fullmatch(r"([a-z]+\d{1,3})00(?:[a-z]{1,4})?", token)
    if m_series:
        prefix = m_series.group(1)
        if re.search(rf"{re.escape(prefix)}\d{{2}}", model):
            return True
    m_thousand = re.fullmatch(r"([a-z]+\d)000(?:[a-z]{1,4})?", token)
    if m_thousand:
        prefix = m_thousand.group(1)
        if re.search(rf"{re.escape(prefix)}\d{{3}}", model):
            return True
    return False


def _validate_profile_known_scope(profile: dict[str, Any], device: dict[str, Any], *, draft: bool = False) -> str:
    """Reject known model/version mismatches and report missing identity fields."""
    _validate_profile_vendor(profile, device)
    if str(profile.get("support_status") or "UNKNOWN").upper() == "UNSUPPORTED":
        raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Telemetry profile is marked unsupported")
    pending: list[str] = []
    model_scope = str(profile.get("model_scope") or "").casefold()
    model = str(device.get("model") or "").casefold()
    if model_scope:
        if not _known_device_value(model):
            pending.append("model")
        else:
            raw_tokens = [token.strip() for token in re.split(r"[,/;]", model_scope) if token.strip()]
            if not any(_model_scope_token_matches(token, model) for token in raw_tokens):
                if draft:
                    return "MISMATCH"
                raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Device model is outside the documented profile scope")
    version_scope = str(profile.get("version_scope") or "").strip()
    version = str(device.get("version") or "").strip()
    if version_scope:
        if not _known_device_value(version) or _h3c_release_pending(profile, version):
            pending.append("version")
        else:
            version_text = version.casefold()
            tokens = [token.strip().casefold() for token in re.split(r"[,/;]", version_scope) if token.strip()]
            if not any(_version_scope_matches(token, version_text) for token in tokens):
                if draft:
                    return "MISMATCH"
                raise TelemetryServiceError("TELEMETRY_VERSION_UNVERIFIED", "Device software version is outside the documented profile scope")
    return "IDENTIFICATION_PENDING" if pending else "MATCHED"


def _profile_identification_fields(profile: dict[str, Any], device: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if profile.get("model_scope") and not _known_device_value(device.get("model")):
        missing.append("model")
    version = str(device.get("version") or "").strip()
    if profile.get("version_scope") and (not _known_device_value(version) or _h3c_release_pending(profile, version)):
        missing.append("version")
    return missing


def _validate_profile_device(profile: dict[str, Any], device: dict[str, Any]) -> None:
    _validate_profile_vendor(profile, device)
    if str(profile.get("support_status") or "UNKNOWN").upper() == "UNSUPPORTED":
        raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Telemetry profile is marked unsupported")


def _normalize_device_source_address(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError as exc:
        raise TelemetryServiceError("TELEMETRY_SOURCE_INVALID", "Device source address must be an IP address") from exc


def _validate_profile_vendor(profile: dict[str, Any], device: dict[str, Any]) -> None:
    vendor = str(device.get("vendor") or "").casefold()
    expected = str(profile.get("vendor") or "").casefold()
    if vendor != expected:
        raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Telemetry profile vendor does not match the device")


def _mapping_payload(mapping: Any) -> dict[str, Any]:
    if hasattr(mapping, "model_dump"):
        return mapping.model_dump(mode="json")
    if isinstance(mapping, dict):
        return dict(mapping)
    raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Telemetry metric mapping must be an object")


def _validate_template_mappings(mappings: list[Any]) -> list[dict[str, Any]]:
    if len(mappings) > _MAX_MAPPINGS:
        raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Telemetry template contains too many metric mappings")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    rendered_metric_names: set[str] = set()
    for raw in mappings:
        item = _mapping_payload(raw)
        key = str(item.get("metric_key") or "").strip()
        source_path = str(item.get("source_path") or "").strip()
        source_field = str(item.get("source_field") or "").strip()
        if not _METRIC_KEY.fullmatch(key) or not source_path or not source_field:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Each metric mapping needs a valid key, source path and JSON field")
        if key.casefold() in keys:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Metric keys must be unique within a template")
        keys.add(key.casefold())
        normalized_key = re.sub(r"[^a-zA-Z0-9_]", "_", key).lower()
        rendered_name = normalized_key if normalized_key.startswith("nexora_telemetry_") else f"nexora_telemetry_{normalized_key}"
        if rendered_name in rendered_metric_names:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Metric keys must produce unique Prometheus names")
        rendered_metric_names.add(rendered_name)
        support = str(item.get("support_status") or "UNKNOWN").upper()
        if support not in {"DOCUMENTED", "SAMPLE_VERIFIED", "DEVICE_VERIFIED", "UNSUPPORTED", "UNKNOWN"}:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Metric mapping support status is invalid")
        evidence = item.get("evidence") or []
        if support in {"DOCUMENTED", "SAMPLE_VERIFIED", "DEVICE_VERIFIED"} and not evidence:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Supported metric mappings require evidence")
        if item.get("counter_bits") is not None:
            try:
                counter_bits = int(item["counter_bits"])
            except (TypeError, ValueError):
                raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "counter_bits must be between 1 and 64") from None
            if not 1 <= counter_bits <= 64 or str(item.get("value_type") or "").casefold() != "counter":
                raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "counter_bits is valid only for counters and must be between 1 and 64")
        item["metric_key"] = key
        item["source_path"] = source_path
        item["source_field"] = source_field
        item["support_status"] = support
        result.append(item)
    return result


def _official_huawei_mappings(profile_key: str = "") -> list[dict[str, Any]]:
    evidence = [
        "https://info.support.huawei.com/info-finder/encyclopedia/zh/Telemetry.html",
        "Huawei CloudEngine gRPC Dial-out JSON 官方 YANG 传感器路径规范",
    ]
    pkey = str(profile_key or "").casefold()
    mappings: list[dict[str, Any]] = [
        {
            "metric_key": "huawei_cpu_system_usage",
            "source_path": "huawei-devm:devm/cpuInfos/cpuInfo",
            "source_field": "cpuInfos.cpuInfo[*].systemCpuUsage",
            "value_type": "gauge",
            "unit": "percent",
            "primary_key_mapping": {"cpu_position": "position"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_memory_os_usage",
            "source_path": "huawei-devm:devm/memoryInfos/memoryInfo",
            "source_field": "memoryInfos.memoryInfo[*].osMemoryUsage",
            "value_type": "gauge",
            "unit": "percent",
            "primary_key_mapping": {"memory_position": "position"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_interface_rx_bytes",
            "source_path": "huawei-ifm:ifm/interfaces/interface/ifStatistics",
            "source_field": "interfaces.interface[*].ifStatistics.receiveByte",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "bytes",
            "primary_key_mapping": {"interface_name": "ifName"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_interface_tx_bytes",
            "source_path": "huawei-ifm:ifm/interfaces/interface/ifStatistics",
            "source_field": "interfaces.interface[*].ifStatistics.sendByte",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "bytes",
            "primary_key_mapping": {"interface_name": "ifName"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_interface_rx_errors",
            "source_path": "huawei-ifm:ifm/interfaces/interface/ifStatistics",
            "source_field": "interfaces.interface[*].ifStatistics.receiveErrorPacket",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "packets",
            "primary_key_mapping": {"interface_name": "ifName"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_interface_tx_drops",
            "source_path": "huawei-ifm:ifm/interfaces/interface/ifStatistics",
            "source_field": "interfaces.interface[*].ifStatistics.sendDropPacket",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "packets",
            "primary_key_mapping": {"interface_name": "ifName"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_interface_speed_bps",
            "source_path": "huawei-ifm:ifm/interfaces/interface",
            "source_field": "interfaces.interface[*].ifSpeed",
            "value_type": "gauge",
            "unit": "bits_per_second",
            "primary_key_mapping": {"interface_name": "ifName"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_optical_rx_power_dbm",
            "source_path": "huawei-devm:devm/ports/port/opticalInfo",
            "source_field": "ports.port[*].opticalInfo.rxPower",
            "value_type": "gauge",
            "unit": "dbm",
            "primary_key_mapping": {"port_position": "position"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_optical_tx_power_dbm",
            "source_path": "huawei-devm:devm/ports/port/opticalInfo",
            "source_field": "ports.port[*].opticalInfo.txPower",
            "value_type": "gauge",
            "unit": "dbm",
            "primary_key_mapping": {"port_position": "position"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_board_temperature_celsius",
            "source_path": "huawei-devm:devm/temperatureInfos/temperatureInfo",
            "source_field": "temperatureInfos.temperatureInfo[*].currentTemperature",
            "value_type": "gauge",
            "unit": "celsius",
            "primary_key_mapping": {"sensor_position": "position"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "huawei_fan_speed_rpm",
            "source_path": "huawei-devm:devm/fans/fan",
            "source_field": "fans.fan[*].speed",
            "value_type": "gauge",
            "unit": "rpm",
            "primary_key_mapping": {"fan_position": "position"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
    ]
    if not pkey or "ce6800" in pkey:
        mappings.extend([
            {
                "metric_key": "huawei_qos_queue_discarded_packets",
                "source_path": "huawei-qos:qos/qosPortQueueStatInfos/qosPortQueueStatInfo",
                "source_field": "qosPortQueueStatInfos.qosPortQueueStatInfo[*].discardedPackets",
                "value_type": "counter",
                "counter_bits": 64,
                "unit": "packets",
                "primary_key_mapping": {"interface_name": "ifName"},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
            {
                "metric_key": "huawei_pfc_rx_pause_frames",
                "source_path": "huawei-dcb:dcb/pfcPortStatistics/pfcPortStatistic",
                "source_field": "pfcPortStatistics.pfcPortStatistic[*].rxPauseFrames",
                "value_type": "counter",
                "counter_bits": 64,
                "unit": "frames",
                "primary_key_mapping": {"interface_name": "ifName"},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
        ])
    return mappings


def _official_h3c_mappings(profile_key: str = "") -> list[dict[str, Any]]:
    evidence = [
        "https://www.h3c.com/cn/d_202504/2397915_30005_0.htm",
        "https://www.h3c.com/cn/d_202606/2861049_30005_0.htm",
        "H3C Comware V7 gRPC Dial-out JSON 官方传感器路径规范",
    ]
    pkey = str(profile_key or "").casefold()
    mappings: list[dict[str, Any]] = [
        {
            "metric_key": "h3c_cpu_usage_percent",
            "source_path": "device/cpus",
            "source_field": "notification.Device.CPUs[*].CPUUsage",
            "value_type": "gauge",
            "unit": "percent",
            "primary_key_mapping": {"cpu_slot": "Slot"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_memory_usage_percent",
            "source_path": "diagnostic/memories",
            "source_field": "notification.Diagnostic.Memories[*].UsedRatio",
            "value_type": "gauge",
            "unit": "percent",
            "primary_key_mapping": {"memory_slot": "Slot"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_interface_oper_status",
            "source_path": "ifmgr/interfaces",
            "source_field": "notification.Ifmgr.Interfaces[*].OperStatus",
            "value_type": "gauge",
            "unit": "state",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_interface_in_octets",
            "source_path": "ifmgr/statistics",
            "source_field": "notification.Ifmgr.Statistics[*].InOctets",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "bytes",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_interface_out_octets",
            "source_path": "ifmgr/statistics",
            "source_field": "notification.Ifmgr.Statistics[*].OutOctets",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "bytes",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_interface_in_errors",
            "source_path": "ifmgr/statistics",
            "source_field": "notification.Ifmgr.Statistics[*].InErrors",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "packets",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_interface_out_discards",
            "source_path": "ifmgr/statistics",
            "source_field": "notification.Ifmgr.Statistics[*].OutDiscards",
            "value_type": "counter",
            "counter_bits": 64,
            "unit": "packets",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_optical_rx_power_dbm",
            "source_path": "device/transceivers",
            "source_field": "notification.Device.Transceivers[*].RxPower",
            "value_type": "gauge",
            "unit": "dbm",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_optical_tx_power_dbm",
            "source_path": "device/transceivers",
            "source_field": "notification.Device.Transceivers[*].TxPower",
            "value_type": "gauge",
            "unit": "dbm",
            "primary_key_mapping": {"interface_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_board_temperature_celsius",
            "source_path": "device/physicalentities",
            "source_field": "notification.Device.PhysicalEntities[*].Temperature",
            "value_type": "gauge",
            "unit": "celsius",
            "primary_key_mapping": {"entity_name": "Name"},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_device_max_mtu",
            "source_path": "ifmgr/devicecapabilities",
            "source_field": "notification.Ifmgr.DeviceCapabilities.MaxMTU",
            "value_type": "gauge",
            "unit": "bytes",
            "primary_key_mapping": {},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
        {
            "metric_key": "h3c_syslog_buffer_size",
            "source_path": "Syslog/LogBuffer",
            "source_field": "notification.Syslog.LogBuffer.BufferSize",
            "value_type": "gauge",
            "unit": "entries",
            "primary_key_mapping": {},
            "source_timestamp_semantics": "sample",
            "support_status": "DOCUMENTED",
            "evidence": evidence,
        },
    ]
    if "sec_wlan" in pkey:
        mappings.extend([
            {
                "metric_key": "h3c_fw_active_sessions",
                "source_path": "session/statistics",
                "source_field": "notification.Session.Statistics.CurrentSessions",
                "value_type": "gauge",
                "unit": "sessions",
                "primary_key_mapping": {},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
            {
                "metric_key": "h3c_wlan_online_ap_count",
                "source_path": "wlan/apstatistics",
                "source_field": "notification.WLAN.APStatistics.OnlineAPCount",
                "value_type": "gauge",
                "unit": "count",
                "primary_key_mapping": {},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
        ])
    elif not pkey or "s6850" in pkey or pkey == "h3c_grpc_dialout_json_v2":
        mappings.extend([
            {
                "metric_key": "h3c_qos_buffer_used_bytes",
                "source_path": "buffermonitor/bufferusages",
                "source_field": "notification.BufferMonitor.BufferUsages[*].UsedBytes",
                "value_type": "gauge",
                "unit": "bytes",
                "primary_key_mapping": {"interface_name": "InterfaceName"},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
            {
                "metric_key": "h3c_pfc_headroom_used_bytes",
                "source_path": "buffermonitor/headroomusages",
                "source_field": "notification.BufferMonitor.HeadroomUsages[*].UsedBytes",
                "value_type": "gauge",
                "unit": "bytes",
                "primary_key_mapping": {"interface_name": "InterfaceName"},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
            {
                "metric_key": "h3c_qos_egress_drop_packets",
                "source_path": "buffermonitor/egressdrops",
                "source_field": "notification.BufferMonitor.EgressDrops[*].DropPackets",
                "value_type": "counter",
                "counter_bits": 64,
                "unit": "packets",
                "primary_key_mapping": {"interface_name": "InterfaceName"},
                "source_timestamp_semantics": "sample",
                "support_status": "DOCUMENTED",
                "evidence": evidence,
            },
        ])
    return mappings


def _ensure_official_starter_templates(conn, tenant_id: str = DEFAULT_TENANT_ID) -> None:
    """Ensure comprehensive vendor/model scopes and official PUBLISHED starter templates exist."""
    tenant = str(tenant_id or DEFAULT_TENANT_ID)
    now = _now()

    # 1. Seed & enrich comprehensive Huawei and H3C model/version scopes.
    profile_catalog = (
        (
            "70000000-0000-4000-8000-000000000001",
            "h3c_grpc_dialout_json_v2",
            "h3c",
            "switch",
            "S6800, S6805, S6812, S6813, S6820, S6825, S6850, S6860, S6861, S6890, S9820, S9825, S9850, S9855, S12500, S12508G-AF, S12516G-AF, S12508X-AF, S12516X-AF, S12508R",
            "7.1.x, CMW710, R24xx, R54xx, R63xx, R65xx, R66xx, R67xx, R68xx, R69xx, R6628Pxx-6W102",
            "h3c_grpc_dialout_json_v2",
            "json",
            "device_configured",
            ["https://www.h3c.com/cn/d_202504/2397915_30005_0.htm"],
        ),
        (
            "70000000-0000-4000-8000-000000000002",
            "h3c_grpc_dialout_json_v3",
            "h3c",
            "switch",
            "S5135S, S5135S-24P4S-EI, S5135S-48T4S-EI-Q, S5135S-28P-EI, S5135S-52P-EI, S5130S, S5130S-28P-EI, S5130S-52P-EI, S5130S-28S-HI, S5130S-52S-HI, S5170, S5000-EI, S5024PV5-EI, S5048PV5-EI, MS4600, S5560X, S5560X-30C-EI, S5560X-54C-EI, S5560X-HI, S5570S, S5570S-28S-EI, S5570S-36F-EI, S5570S-54S-EI, S5590, S6520X, S6520X-HI[EI][SI], S6520-SI, S7500E, S7503E, S7506E, S7510E, S7500X-G, S7506X-G, S7510X-G, S10500, S10500X, S10508X, S10506X-G, S10512X-G",
            "7.1.x, CMW710, R24xx, R54xx, R63xx, R65xx, R66xx, R67xx, R68xx, R69xx, R68xx-6W102",
            "h3c_grpc_dialout_json_v3",
            "json+telemetry-header",
            "device_configured",
            ["https://www.h3c.com/cn/d_202602/2751840_30005_0.htm"],
        ),
        (
            "70000000-0000-4000-8000-000000000003",
            "huawei_grpc_dialout_json",
            "huawei",
            "switch",
            "CloudEngine S3700, S5700, S5720, S5730, S5731, S5731-H, S5731-S, S5732, S5732-H, S5735, S5735-L, S5735-S, S5735-L-V2, S5735-S-V2, S5736, S5736-S, S5755, S5755-H, S6700, S6720, S6720-EI, S6730, S6730-S, S6730-H, S6730-H-V2, S6750, S6750-H, S6750-S, S7700, S7703, S7706, S7712, S8700, S8700-4, S8700-6, S8700-10, S9700, S12700, S12700E, S12700E-4, S12700E-8, S12700E-12, S16700, S16700-4, S16700-8, NetEngine AR600, AR6100, AR6200, AR6300, AR6700, NE40E, NE8000, USG6000, USG6000E, USG6500E, USG6600E, USG6700E, AirEngine 9700, AC6508, AC6805",
            "VRP, VRP8, V200R019, V200R020, V200R021, V200R022, V200R023, V300R022, V300R023, V300R024, V600R021, V600R022, V600R023, V600R024, V600R024C10, V800R021, V800R022",
            "huawei_grpc_dialout_json",
            "json",
            "device_configured",
            [
                "https://e.huawei.com/en/documents/products/enterprise-network/16746037ed334a73ab8e8c5dc75b6c08",
                "https://info.support.huawei.com/info-finder/encyclopedia/zh/Telemetry.html",
            ],
        ),
        (
            "70000000-0000-4000-8000-000000000004",
            "h3c_grpc_dialout_json_v2_s6850_r6717",
            "h3c",
            "switch",
            "S6850, S6850-56HF, S6850-2C, S6820, S6825, S6825-54HT, S6825-54HF, S6860, S6860-54HF, S6861, S6861-54QF, S6890, S9820, S9825, S9825-64D, S9850, S9855, S9855-48CD8D, S9855-32D",
            "7.1.x, CMW710, R67xx, R68xx, R6717Pxx-6W101",
            "h3c_grpc_dialout_json_v2",
            "json",
            "device_configured",
            ["https://wwwsg.h3c.com/cn/d_202606/2861049_30005_0.htm"],
        ),
        (
            "70000000-0000-4000-8000-000000000005",
            "h3c_grpc_dialout_json_v3_s6850_r6717",
            "h3c",
            "switch",
            "S6850, S6850-56HF, S6850-2C, S6820, S6825, S6825-54HT, S6825-54HF, S6860, S6860-54HF, S6861, S6861-54QF, S6890, S9820, S9825, S9825-64D, S9850, S9855, S9855-48CD8D, S9855-32D",
            "7.1.x, CMW710, R67xx, R68xx, R6717Pxx-6W101",
            "h3c_grpc_dialout_json_v3",
            "json+telemetry-header",
            "device_configured",
            ["https://wwwsg.h3c.com/cn/d_202606/2861049_30005_0.htm"],
        ),
        (
            "70000000-0000-4000-8000-000000000006",
            "huawei_ce6800_v200r005c10_grpc_json",
            "huawei",
            "switch",
            "CE5800, CE5855, CE5881, CE6800, CE6820, CE6850, CE6855, CE6857, CE6860, CE6863, CE6863E, CE6865, CE6866, CE6870, CE6881, CE6881E, CE6885, CE8800, CE8850, CE8851, CE8855, CE8860, CE8861, CE8868, CE9800, CE9860, CE9865, CE9866, CE12800, CE12804, CE12808, CE12812, CE12816, CE16800, CE16804, CE16808, CE16816, XH16800, XH16800-8, XH16800-16",
            "VRP, VRP8, V200R005C10, V200R019, V200R020, V200R021, V200R022, V200R023, V300R022, V300R023, V300R024",
            "huawei_grpc_dialout_json",
            "json",
            "device_configured",
            [
                "https://e.huawei.com/cn/products/switches/data-center-switches/ce6800",
                "https://info.support.huawei.com/info-finder/encyclopedia/zh/Telemetry.html",
            ],
        ),
        (
            "70000000-0000-4000-8000-000000000007",
            "h3c_grpc_dialout_json_v2_campus_s5135s",
            "h3c",
            "switch",
            "S5135S, S5135S-24P4S-EI, S5135S-48T4S-EI-Q, S5135S-28P-EI, S5135S-52P-EI, S5135S-EI, S5130S, S5130S-28P-EI, S5130S-52P-EI, S5130S-28S-HI, S5130S-52S-HI, S5130S-EI, S5130S-HI, S5170, S5170-28S-EI, S5170-54S-EI, S5000-EI, S5024PV5-EI, S5048PV5-EI, MS4600, S5560X, S5560X-30C-EI, S5560X-54C-EI, S5560X-34S-HI, S5560X-54S-HI, S5560X-EI, S5560X-HI, S5570S, S5570S-28S-EI, S5570S-36F-EI, S5570S-54S-EI, S5570S-EI, S5590, S5590-28T4XC-EI, S5590-48T4XC-EI, S6520X, S6520X-26C-SI, S6520X-54XC-UPWR-SI, S6520X-30QC-EI, S6520X-54QC-EI, S6520X-30HF-HI, S6520X-54HF-HI, S6520X-EI, S6520X-SI, S6520X-HI, S7500E, S7503E, S7506E, S7510E, S7500X-G, S7506X-G, S7510X-G, S10500, S10500X, S10508X, S10506X-G, S10512X-G",
            "7.1.x, CMW710, R24xx, R54xx, R63xx, R65xx, R66xx, R67xx, R68xx, R69xx",
            "h3c_grpc_dialout_json_v2",
            "json",
            "device_configured",
            ["https://www.h3c.com/cn/Products_and_Solutions/InterConnect/Switches/Products/Campus_Network/"],
        ),
        (
            "70000000-0000-4000-8000-000000000008",
            "h3c_grpc_dialout_json_v2_sec_wlan",
            "h3c",
            "security_wireless",
            "F1000, F1060, F1070, F1080, F1090, F5000, F5020, F5030, F5040, F5060, F5080, M9000, WX3500H, WX3510H, WX3520H, WX3540H, WX5500E, WX5510E, WX5540H, WX5540H-HCL, WX5560H, WX5580H, SR6600, SR6604, SR6608, CR16000, CR19000, MSR3600, MSR3610, MSR3620, MSR3640, MSR3660, MSR5600, MSR5660, MSR5680",
            "7.1.x, CMW710, R24xx, R54xx, R63xx, R65xx, R66xx, R67xx, R68xx, R69xx",
            "h3c_grpc_dialout_json_v2",
            "json",
            "device_configured",
            ["https://www.h3c.com/cn/d_202504/2397915_30005_0.htm"],
        ),
    )

    for pid, pkey, vendor, platform, m_scope, v_scope, adapter, enc, auth_mode, sources in profile_catalog:
        conn.execute(
            """INSERT INTO telemetry_protocol_profiles (
                   id, profile_key, vendor, platform, model_scope, version_scope,
                   adapter_key, encoding, auth_mode, required_proto_version,
                   min_interval_seconds, official_sources, support_status,
                   is_system, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', 5, ?, 'DOCUMENTED', TRUE, ?, ?)
               ON CONFLICT (id) DO UPDATE SET
                   model_scope = EXCLUDED.model_scope,
                   version_scope = EXCLUDED.version_scope,
                   official_sources = EXCLUDED.official_sources,
                   updated_at = EXCLUDED.updated_at""",
            (pid, pkey, vendor, platform, m_scope, v_scope, adapter, enc, auth_mode, json.dumps(sources, ensure_ascii=False), now, now),
        )

    profiles = [_dict(row) for row in conn.execute("SELECT * FROM telemetry_protocol_profiles").fetchall()]
    if not profiles:
        return
    changed = False
    for profile in profiles:
        pid = str(profile.get("id") or "")
        pkey = str(profile.get("profile_key") or "")
        vendor = str(profile.get("vendor") or "").casefold()
        if vendor not in {"huawei", "h3c"}:
            continue
        mappings = _official_huawei_mappings(pkey) if vendor == "huawei" else _official_h3c_mappings(pkey)
        default_interval = max(10, int(profile.get("min_interval_seconds") or 10))
        template_key = f"{pkey}_official_standard"
        tid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:telemetry:{tenant}:{template_key}:1"))
        conn.execute(
            """INSERT INTO telemetry_subscription_templates (
                   id, tenant_id, profile_id, template_key, version,
                   metric_mappings, estimated_series, default_interval_seconds,
                   status, created_at, updated_at
               ) VALUES (?, ?, ?, ?, 1, ?, 128, ?, 'PUBLISHED', ?, ?)
               ON CONFLICT (tenant_id, template_key, version) DO UPDATE SET
                   metric_mappings = EXCLUDED.metric_mappings,
                   estimated_series = EXCLUDED.estimated_series,
                   status = 'PUBLISHED',
                   updated_at = EXCLUDED.updated_at""",
            (tid, tenant, pid, template_key, json.dumps(mappings, ensure_ascii=False), default_interval, now, now),
        )
        changed = True

    # Also upgrade the two initial starter drafts so they are immediately usable if selected.
    conn.execute(
        """UPDATE telemetry_subscription_templates
              SET metric_mappings = ?, status = 'PUBLISHED', updated_at = ?
            WHERE template_key = 'huawei_ce6800_v200r005c10_basic' AND status = 'DRAFT'""",
        (json.dumps(_official_huawei_mappings(), ensure_ascii=False), now),
    )
    conn.execute(
        """UPDATE telemetry_subscription_templates
              SET status = 'PUBLISHED', updated_at = ?
            WHERE template_key = 'h3c_s6850_v2_syslog_smoke' AND status = 'DRAFT'""",
        (now,),
    )
    if changed:
        conn.commit()
    else:
        conn.commit()


def list_profiles() -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        _ensure_official_starter_templates(conn, DEFAULT_TENANT_ID)
        template_rows = [
            _dict(row)
            for row in conn.execute(
                "SELECT profile_id, metric_mappings FROM telemetry_subscription_templates WHERE status = 'PUBLISHED'"
            ).fetchall()
        ]
        paths_by_profile: dict[str, list[dict[str, Any]]] = {}
        seen_by_profile: dict[str, set[tuple[str, str]]] = {}
        for tpl in template_rows:
            pid = str(tpl.get("profile_id") or "")
            for mapping in _json_value(tpl.get("metric_mappings"), []):
                if not isinstance(mapping, dict):
                    continue
                spath = str(mapping.get("source_path") or "").strip()
                mkey = str(mapping.get("metric_key") or "").strip()
                if not spath:
                    continue
                seen = seen_by_profile.setdefault(pid, set())
                if (spath, mkey) in seen:
                    continue
                seen.add((spath, mkey))
                ev_list = mapping.get("evidence") or []
                paths_by_profile.setdefault(pid, []).append({
                    "path": spath,
                    "metric_key": mkey,
                    "validation_status": str(mapping.get("support_status") or "DOCUMENTED"),
                    "evidence": ev_list[0] if isinstance(ev_list, list) and ev_list else "",
                })
        rows = conn.execute(
            """SELECT * FROM telemetry_protocol_profiles
                ORDER BY vendor, model_scope, version_scope, profile_key"""
        ).fetchall()
        items = []
        for row in rows:
            item = _dict(row)
            item["official_sources"] = _json_value(item.get("official_sources"), [])
            item["paths"] = paths_by_profile.get(str(item.get("id") or ""), [])
            items.append(item)
        return {"items": items, "total": len(items), "page": 1, "page_size": max(1, len(items))}
    finally:
        conn.close()


def list_templates(user: dict[str, Any], page: int = 1, page_size: int = 50) -> dict[str, Any]:
    _require_postgres()
    page, page_size = _page_args(page, page_size)
    tenant = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        _ensure_official_starter_templates(conn, str(tenant or DEFAULT_TENANT_ID))
        clause, params = ("tenant_id = ?", (tenant,)) if tenant else ("1 = 1", ())
        total = int(conn.execute(f"SELECT COUNT(*) FROM telemetry_subscription_templates WHERE {clause}", params).fetchone()[0])
        rows = conn.execute(
            f"""SELECT * FROM telemetry_subscription_templates WHERE {clause}
                 ORDER BY template_key, version DESC LIMIT ? OFFSET ?""",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
        items = []
        for row in rows:
            item = _dict(row)
            item["metric_mappings"] = _json_value(item.get("metric_mappings"), [])
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()


def create_template(payload: Any, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    tenant = str(tenant_scope_for_user(user) or DEFAULT_TENANT_ID)
    mappings = _validate_template_mappings(payload.metric_mappings)
    conn = get_db_connection()
    try:
        profile = _profile(conn, payload.profile_id)
        if str(profile.get("support_status") or "").upper() in {"UNKNOWN", "UNSUPPORTED"}:
            raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Protocol documentation must be reviewed before creating a template")
        if profile.get("is_system") is False:
            raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "User-created profiles are not supported")
        template_id = str(uuid.uuid4())
        now = _now()
        try:
            conn.execute(
                """INSERT INTO telemetry_subscription_templates (
                       id, tenant_id, profile_id, template_key, version,
                       metric_mappings, estimated_series, default_interval_seconds,
                       status, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (template_id, tenant, payload.profile_id, payload.template_key.strip(), payload.version,
                 json.dumps(mappings, ensure_ascii=False), int(payload.estimated_series),
                 int(payload.default_interval_seconds), "DRAFT", now, now),
            )
        except Exception as exc:
            conn.rollback()
            if "unique" in str(exc).casefold() or "duplicate" in str(exc).casefold():
                raise TelemetryServiceError("TELEMETRY_TEMPLATE_CONFLICT", "Template key and version already exist", 409) from exc
            raise
        conn.commit()
        _audit_control_action(user, "TELEMETRY_TEMPLATE_CREATED", "Telemetry template draft created", "telemetry_template", template_id,
                              {"profile_id": payload.profile_id, "template_key": payload.template_key, "version": payload.version})
        return get_template(template_id, user)
    finally:
        conn.close()


def update_template_draft(template_id: str, payload: Any, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    tenant = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        query = "SELECT * FROM telemetry_subscription_templates WHERE id = ? FOR UPDATE"
        params: tuple[Any, ...] = (template_id,)
        if tenant:
            query = "SELECT * FROM telemetry_subscription_templates WHERE id = ? AND tenant_id = ? FOR UPDATE"
            params += (tenant,)
        row = conn.execute(query, params).fetchone()
        if not row:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_NOT_FOUND", "Telemetry template not found", 404)
        current = _dict(row)
        if str(current.get("status") or "").upper() != "DRAFT":
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_IMMUTABLE", "Published template versions are immutable", 409)
        mappings = _validate_template_mappings(payload.metric_mappings) if payload.metric_mappings is not None else _json_value(current.get("metric_mappings"), [])
        estimated = int(payload.estimated_series if payload.estimated_series is not None else current.get("estimated_series") or 0)
        interval = int(payload.default_interval_seconds if payload.default_interval_seconds is not None else current.get("default_interval_seconds") or 0)
        if estimated < 0 or interval <= 0:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Template series estimate or interval is invalid")
        if payload.status not in (None, "DRAFT"):
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_IMMUTABLE", "Use the publish action to publish a template", 409)
        conn.execute(
            """UPDATE telemetry_subscription_templates SET metric_mappings = ?,
                   estimated_series = ?, default_interval_seconds = ?, updated_at = ?
                 WHERE id = ? AND tenant_id = ?""",
            (json.dumps(mappings, ensure_ascii=False), estimated, interval, _now(),
             template_id, current["tenant_id"]),
        )
        conn.commit()
        _audit_control_action(user, "TELEMETRY_TEMPLATE_UPDATED", "Telemetry template draft updated", "telemetry_template", template_id,
                              {"template_key": current.get("template_key"), "version": current.get("version")})
        return get_template(template_id, user)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def publish_template(template_id: str, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    tenant = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        query = "SELECT * FROM telemetry_subscription_templates WHERE id = ? FOR UPDATE"
        params: tuple[Any, ...] = (template_id,)
        if tenant:
            query = "SELECT * FROM telemetry_subscription_templates WHERE id = ? AND tenant_id = ? FOR UPDATE"
            params += (tenant,)
        row = conn.execute(query, params).fetchone()
        if not row:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_NOT_FOUND", "Telemetry template not found", 404)
        current = _dict(row)
        if str(current.get("status") or "").upper() != "DRAFT":
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_IMMUTABLE", "Only a draft template can be published", 409)
        mappings = _validate_template_mappings(_json_value(current.get("metric_mappings"), []))
        if not mappings:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "At least one metric mapping is required")
        invalid = [item for item in mappings if item.get("support_status") in {"UNKNOWN", "UNSUPPORTED"} or not item.get("evidence")]
        if invalid:
            raise TelemetryServiceError("TELEMETRY_PATH_UNVERIFIED", "Every published metric mapping requires evidence and a documented support state")
        conn.execute(
            "UPDATE telemetry_subscription_templates SET status = 'PUBLISHED', updated_at = ? WHERE id = ? AND tenant_id = ?",
            (_now(), template_id, current["tenant_id"]),
        )
        conn.commit()
        _audit_control_action(user, "TELEMETRY_TEMPLATE_PUBLISHED", "Telemetry template published", "telemetry_template", template_id,
                              {"template_key": current.get("template_key"), "version": current.get("version")})
        return get_template(template_id, user)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_template(template_id: str, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    tenant = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        query = "SELECT * FROM telemetry_subscription_templates WHERE id = ?"
        params: tuple[Any, ...] = (template_id,)
        if tenant:
            query += " AND tenant_id = ?"
            params += (tenant,)
        row = conn.execute(query, params).fetchone()
        if not row:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_NOT_FOUND", "Telemetry template not found", 404)
        item = _dict(row)
        item["metric_mappings"] = _json_value(item.get("metric_mappings"), [])
        return item
    finally:
        conn.close()


def create_tls_profile(payload: Any, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    references = (
        str(payload.ca_certificate_ref or "").strip(),
        str(payload.client_certificate_ref or "").strip(),
        str(payload.encrypted_private_key_ref or "").strip(),
    )
    fingerprint = re.sub(r"[:\s]", "", str(payload.fingerprint or "")).lower()
    if not all(references) or any("-----BEGIN" in value.upper() for value in references):
        raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "TLS certificates and private keys must be configured as secret-store references")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "Client certificate fingerprint must be a 64-character SHA-256 value")
    tenant = str(tenant_scope_for_user(user) or DEFAULT_TENANT_ID)
    conn = get_db_connection()
    try:
        profile_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """INSERT INTO telemetry_tls_profiles (
                   id, tenant_id, name, ca_certificate_ref, client_certificate_ref,
                   encrypted_private_key_ref, fingerprint, valid_from, valid_until,
                   version, status, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, tenant, payload.name.strip(), references[0],
             references[1], references[2],
             fingerprint, payload.valid_from, payload.valid_until,
             payload.version, payload.status, now, now),
        )
        conn.commit()
        _audit_control_action(user, "TELEMETRY_TLS_PROFILE_CREATED", "Telemetry TLS reference created", "telemetry_tls_profile", profile_id,
                              {"name": payload.name, "version": payload.version})
        row = conn.execute("SELECT * FROM telemetry_tls_profiles WHERE id = ? AND tenant_id = ?", (profile_id, tenant)).fetchone()
        return _tls_profile_public(_dict(row))
    finally:
        conn.close()


def list_tls_profiles(user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    tenant = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        query = "SELECT * FROM telemetry_tls_profiles"
        params: tuple[Any, ...] = ()
        if tenant:
            query += " WHERE tenant_id = ?"
            params = (tenant,)
        rows = conn.execute(query + " ORDER BY name", params).fetchall()
        return {"items": [_tls_profile_public(_dict(row)) for row in rows]}
    finally:
        conn.close()


def _tls_profile_public(row: dict[str, Any]) -> dict[str, Any]:
    """Return metadata needed by operators without disclosing secret-store paths."""
    allowed = (
        "id", "tenant_id", "name", "fingerprint", "valid_from", "valid_until",
        "version", "status", "created_at", "updated_at",
    )
    return {key: row[key] for key in allowed if key in row}


def get_device_config(device_id: str, user: dict[str, Any]) -> dict[str, Any] | None:
    _require_postgres()
    conn = get_db_connection()
    try:
        device = _load_device(conn, device_id, user, "view")
        row = conn.execute(
            "SELECT * FROM telemetry_device_configs WHERE device_id = ? AND tenant_id = ?",
            (device_id, device["tenant_id"]),
        ).fetchone()
        if not row:
            return None
        item = _dict(row)
        item["allowed_sources"] = _json_value(item.get("allowed_sources"), [])
        item["asset_tag"] = device.get("asset_tag")
        item["hostname"] = device.get("hostname")
        try:
            profile = _profile(conn, str(item.get("profile_id") or ""))
            item["profile_match_state"] = _validate_profile_known_scope(profile, device)
            item["profile_match_fields"] = _profile_identification_fields(profile, device)
        except TelemetryServiceError:
            item["profile_match_state"] = "MISMATCH"
            item["profile_match_fields"] = []
        item["version_confirmation_required"] = "version" in item["profile_match_fields"]
        item["profile_match_message"] = (
            "设备型号或软件版本待识别；当前配置保持停用，启用前请人工核对。"
            if item["profile_match_state"] == "IDENTIFICATION_PENDING"
            else "设备型号和软件版本符合协议档案范围。"
            if item["profile_match_state"] == "MATCHED"
            else "设备型号或软件版本与协议档案范围不匹配。"
        )
        return item
    finally:
        conn.close()


def _validate_allowed_sources(raw: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in raw:
        try:
            address = ipaddress.ip_address(str(value).strip())
        except ValueError as exc:
            raise TelemetryServiceError("TELEMETRY_SOURCE_INVALID", "Allowed source must be an IP address") from exc
        text = str(address)
        if text not in normalized:
            normalized.append(text)
    if len(normalized) > 32:
        raise TelemetryServiceError("TELEMETRY_SOURCE_INVALID", "No more than 32 source addresses may be configured")
    return normalized


def upsert_device_config(device_id: str, payload: Any, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        device = _load_device(conn, device_id, user, "update")
        # Serialize same-device changes so repeated imports cannot create two
        # configs or race the capacity reservation rows.
        conn.execute("SELECT id FROM devices WHERE id = ? FOR UPDATE", (device_id,)).fetchone()
        profile = _profile(conn, payload.profile_id)
        profile_match_state = _validate_profile_known_scope(profile, device, draft=not bool(payload.enabled))
        if str(profile.get("support_status") or "").upper() in {"UNKNOWN", "UNSUPPORTED"}:
            raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Protocol profile is not documented for this device family")
        _require_telemetry_collector(conn, payload.collector_id)
        if bool(payload.enabled):
            _validate_profile_device(profile, device)
            _require_collector_endpoint()
        if payload.credential_id:
            credential = conn.execute("SELECT id FROM credentials WHERE id = ?", (payload.credential_id,)).fetchone()
            if not credential:
                raise TelemetryServiceError("TELEMETRY_CREDENTIAL_NOT_FOUND", "Credential reference does not exist", 404)
        if payload.tls_profile_id:
            tls = conn.execute(
                "SELECT id, status, fingerprint FROM telemetry_tls_profiles WHERE id = ? AND tenant_id = ?",
                (payload.tls_profile_id, device["tenant_id"]),
            ).fetchone()
            if not tls or str(_dict(tls).get("status") or "").upper() != "ACTIVE":
                raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "An active TLS profile for this tenant is required")
            if not str(_dict(tls).get("fingerprint") or "").strip():
                raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "TLS profile must contain the expected client certificate fingerprint")
        allowed_sources = _validate_allowed_sources(list(payload.allowed_sources or []))
        device_source_address = _normalize_device_source_address(
            getattr(payload, "device_source_address", None)
        )
        if profile.get("auth_mode") in {"tls_pki", "device_configured"} and not allowed_sources:
            raise TelemetryServiceError("TELEMETRY_SOURCE_INVALID", "TLS-authenticated sources also require an explicit device source IP allowlist")
        tenant_id = device["tenant_id"]
        existing = conn.execute(
            "SELECT * FROM telemetry_device_configs WHERE device_id = ? AND tenant_id = ? FOR UPDATE",
            (device_id, tenant_id),
        ).fetchone()
        had_enabled_subscriptions = False
        if existing:
            current_id = str(_dict(existing).get("id") or "")
            had_enabled_subscriptions = bool(conn.execute(
                "SELECT 1 FROM telemetry_subscriptions WHERE config_id = ? AND tenant_id = ? AND desired_enabled = TRUE LIMIT 1",
                (current_id, tenant_id),
            ).fetchone())
        now = _now()
        if existing:
            current = _dict(existing)
            if int(payload.revision) != int(current.get("revision") or 1):
                raise TelemetryServiceError("TELEMETRY_CONFIG_CONFLICT", "Device Telemetry configuration changed; reload before saving", 409)
            config_id = str(current["id"])
            revision = int(current.get("revision") or 1) + 1
            conn.execute(
                """UPDATE telemetry_device_configs SET collector_id = ?, profile_id = ?,
                       credential_id = ?, tls_profile_id = ?, device_source_address = ?, allowed_sources = ?,
                       enabled = ?, revision = ?, updated_at = ?
                     WHERE id = ? AND tenant_id = ?""",
                (payload.collector_id, payload.profile_id, payload.credential_id, payload.tls_profile_id,
                 device_source_address, json.dumps(allowed_sources), bool(payload.enabled), revision, now, config_id, tenant_id),
            )
        else:
            if int(payload.revision) != 1:
                raise TelemetryServiceError("TELEMETRY_CONFIG_CONFLICT", "New device configuration must start at revision 1", 409)
            config_id = str(uuid.uuid4())
            revision = 1
            conn.execute(
                """INSERT INTO telemetry_device_configs (
                       id, tenant_id, asset_id, device_id, collector_id, profile_id,
                       credential_id, tls_profile_id, device_source_address, allowed_sources, enabled,
                       revision, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (config_id, tenant_id, device["asset_id"], device_id, payload.collector_id,
                 payload.profile_id, payload.credential_id, payload.tls_profile_id,
                 device_source_address, json.dumps(allowed_sources), bool(payload.enabled), revision, now, now),
            )
        if not bool(payload.enabled):
            conn.execute(
                "UPDATE telemetry_subscriptions SET desired_enabled = FALSE, revision = revision + 1, updated_at = ? WHERE config_id = ? AND tenant_id = ?",
                (now, config_id, tenant_id),
            )
            conn.execute(
                """UPDATE telemetry_subscription_runtime r SET connection_state = 'DISABLED', data_state = 'STALE',
                       updated_at = ? FROM telemetry_subscriptions s
                     WHERE s.id = r.subscription_id AND s.config_id = ? AND r.tenant_id = ?""",
                (now, config_id, tenant_id),
            )
        publish_job: dict[str, Any] | None = None
        if had_enabled_subscriptions:
            _require_telemetry_collector(conn, payload.collector_id, lock=True)
            desired_version = _next_desired_version(conn, payload.collector_id)
            job_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO telemetry_config_jobs (
                       id, tenant_id, collector_id, device_config_id, action,
                       desired_version, idempotency_key, state, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, 'PUBLISH', ?, ?, 'QUEUED', ?, ?)""",
                (job_id, tenant_id, payload.collector_id, config_id, desired_version,
                 f"deviceconfig:{config_id}:{revision}:publish", now, now),
            )
            publish_job = {"job_id": job_id, "desired_version": desired_version, "state": "QUEUED"}
        conn.commit()
        _audit_control_action(user, "TELEMETRY_DEVICE_CONFIGURED", "Telemetry device configuration saved", "device", device_id,
                              {"collector_id": payload.collector_id, "profile_id": payload.profile_id,
                               "enabled": bool(payload.enabled), "publish_job_id": (publish_job or {}).get("job_id")})
        result = get_device_config(device_id, user) or {}
        result["profile_match_state"] = profile_match_state
        if publish_job:
            result["publish_job"] = publish_job
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_subscription(
    device_id: str,
    payload: Any,
    user: dict[str, Any],
    *,
    reuse_identical: bool = False,
) -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        device = _load_device(conn, device_id, user, "update")
        config = conn.execute(
            "SELECT * FROM telemetry_device_configs WHERE device_id = ? AND tenant_id = ? FOR UPDATE",
            (device_id, device["tenant_id"]),
        ).fetchone()
        if not config:
            raise TelemetryServiceError("TELEMETRY_CONFIG_NOT_FOUND", "Save device Telemetry settings before adding subscriptions", 409)
        config_row = _dict(config)
        subscription_name = payload.name.strip()
        existing_subscription = conn.execute(
            """SELECT * FROM telemetry_subscriptions
                 WHERE config_id = ? AND tenant_id = ? AND name = ?
                   AND deleted_at IS NULL FOR UPDATE""",
            (config_row["id"], device["tenant_id"], subscription_name),
        ).fetchone()
        if existing_subscription:
            existing = _dict(existing_subscription)
            same_definition = (
                str(existing.get("template_id")) == str(payload.template_id)
                and int(existing.get("template_version") or 0) == int(payload.template_version)
                and int(existing.get("interval_seconds") or 0) == int(payload.interval_seconds)
                and set(_json_value(existing.get("path_filters"), [])) == set(payload.path_filters or [])
            )
            if reuse_identical and same_definition:
                existing_id = str(existing["id"])
                conn.commit()
                return _subscription_by_id(existing_id, user)
            raise TelemetryServiceError(
                "TELEMETRY_SUBSCRIPTION_EXISTS",
                "A subscription with this name already exists on the device",
                409,
            )
        template_row = conn.execute(
            """SELECT * FROM telemetry_subscription_templates
                WHERE id = ? AND tenant_id = ? AND version = ?""",
            (payload.template_id, device["tenant_id"], payload.template_version),
        ).fetchone()
        if not template_row:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_NOT_FOUND", "Published subscription template version not found", 404)
        template = _dict(template_row)
        if str(template.get("status") or "").upper() != "PUBLISHED":
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_NOT_PUBLISHED", "Only a published template can be assigned", 409)
        if str(template.get("profile_id")) != str(config_row.get("profile_id")):
            raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Template profile does not match the device configuration")
        profile = _profile(conn, str(config_row["profile_id"]))
        _validate_profile_vendor(profile, device)
        mappings = _validate_template_mappings(_json_value(template.get("metric_mappings"), []))
        interval = int(payload.interval_seconds)
        min_interval = profile.get("min_interval_seconds")
        path_intervals = [int(item["min_interval_seconds"]) for item in mappings if item.get("min_interval_seconds")]
        min_intervals = [value for value in [min_interval, *path_intervals] if value is not None]
        if min_intervals and interval < max(min_intervals):
            raise TelemetryServiceError("TELEMETRY_INTERVAL_TOO_SHORT", "Interval is shorter than the documented minimum for this profile or metric")
        if interval < 5:
            raise TelemetryServiceError("TELEMETRY_INTERVAL_TOO_SHORT", "Initial collection interval must be at least five seconds")
        paths = set(payload.path_filters or [])
        available_paths = {str(item.get("source_path") or "") for item in mappings}
        if paths - available_paths:
            raise TelemetryServiceError("TELEMETRY_PATH_UNVERIFIED", "Subscription includes a path absent from its template")
        estimated_series = int(template.get("estimated_series") or 0)
        if estimated_series <= 0:
            raise TelemetryServiceError("TELEMETRY_TEMPLATE_INVALID", "Template must declare a positive estimated series count")
        sample_rate = estimated_series / interval
        subscription_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """INSERT INTO telemetry_subscriptions (
                   id, tenant_id, config_id, name, template_id, template_version,
                   interval_seconds, path_filters, reserved_series,
                   reserved_sample_rate, desired_enabled, revision, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, FALSE, 1, ?, ?)""",
            (subscription_id, device["tenant_id"], config_row["id"], subscription_name,
             payload.template_id, payload.template_version, interval, json.dumps(list(paths), ensure_ascii=False),
             estimated_series, sample_rate, now, now),
        )
        conn.execute(
            """INSERT INTO telemetry_subscription_runtime (
                   subscription_id, tenant_id, connection_state, data_state, updated_at
               ) VALUES (?, ?, 'DISABLED', 'NO_DATA', ?)""",
            (subscription_id, device["tenant_id"], now),
        )
        conn.commit()
        _audit_control_action(user, "TELEMETRY_SUBSCRIPTION_CREATED", "Telemetry subscription created", "telemetry_subscription", subscription_id,
                              {"device_id": device_id, "template_id": payload.template_id, "interval_seconds": interval})
        return _subscription_by_id(subscription_id, user)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _subscription_by_id(subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
    result = list_subscriptions(user, page=1, page_size=1, subscription_id=subscription_id)
    if not result["items"]:
        raise TelemetryServiceError("TELEMETRY_SUBSCRIPTION_NOT_FOUND", "Telemetry subscription not found", 404)
    return result["items"][0]


def list_subscriptions(user: dict[str, Any], page: int = 1, page_size: int = 20,
                       subscription_id: str | None = None) -> dict[str, Any]:
    _require_postgres()
    page, page_size = _page_args(page, page_size)
    conn = get_db_connection()
    try:
        where, scope_params = _scope_where(conn, user, "view")
        clauses = [where, "s.deleted_at IS NULL"]
        values = list(scope_params)
        tenant = tenant_scope_for_user(user)
        if tenant:
            clauses.append("s.tenant_id = ?")
            values.append(tenant)
        if subscription_id:
            clauses.append("s.id = ?")
            values.append(subscription_id)
        clause = " AND ".join(clauses)
        total = int(conn.execute(
            f"""SELECT COUNT(*) FROM telemetry_subscriptions s
                 JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                 JOIN devices d ON d.id = c.device_id
                WHERE {clause}""", tuple(values)
        ).fetchone()[0])
        rows = conn.execute(
            f"""SELECT s.*, d.id AS device_id, d.hostname AS device_name, pa.asset_tag,
                       c.collector_id, co.name AS collector_name, c.profile_id,
                       p.profile_key AS profile_name, t.template_key AS template_name,
                       r.connection_state, r.data_state, r.applied_version,
                       r.last_received_at, r.last_valid_at, r.active_series,
                       r.sample_rate AS samples_per_second, r.clock_skew_ms, r.error_code,
                       r.updated_at AS runtime_updated_at,
                       (SELECT j.state FROM telemetry_config_jobs j
                         WHERE j.subscription_id = s.id OR j.device_config_id = c.id
                         ORDER BY j.created_at DESC LIMIT 1) AS publish_state,
                       (SELECT MAX(j.desired_version) FROM telemetry_config_jobs j
                         WHERE j.subscription_id = s.id OR j.device_config_id = c.id) AS desired_version
                  FROM telemetry_subscriptions s
                  JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                  JOIN devices d ON d.id = c.device_id
                  JOIN physical_assets pa ON pa.id = c.asset_id
                  JOIN telemetry_collectors co ON co.id = c.collector_id
                  JOIN telemetry_protocol_profiles p ON p.id = c.profile_id
                  JOIN telemetry_subscription_templates t ON t.id = s.template_id
                     AND t.tenant_id = s.tenant_id AND t.version = s.template_version
                  LEFT JOIN telemetry_subscription_runtime r ON r.subscription_id = s.id
                 WHERE {clause}
                 ORDER BY s.updated_at DESC, s.id
                 LIMIT ? OFFSET ?""",
            (*values, page_size, (page - 1) * page_size),
        ).fetchall()
        items = []
        for raw in rows:
            row = _dict(raw)
            row["runtime"] = {
                "publish_state": {
                    "SUCCEEDED": "APPLIED", "RUNNING": "PUBLISHING",
                    "QUEUED": "QUEUED", "FAILED": "FAILED",
                }.get(str(row.pop("publish_state", "") or "").upper(), "APPLIED" if row.get("desired_enabled") else "DRAFT"),
                "connection_state": row.pop("connection_state", None) or "DISABLED",
                "data_state": row.pop("data_state", None) or "NO_DATA",
                "desired_version": row.pop("desired_version", None),
                "applied_version": row.pop("applied_version", None),
                "last_received_at": row.pop("last_received_at", None),
                "last_valid_at": row.pop("last_valid_at", None),
                "active_series": int(row.pop("active_series", 0) or 0),
                "samples_per_second": float(row.pop("samples_per_second", 0) or 0),
                "clock_skew_ms": row.pop("clock_skew_ms", None),
                "error": (lambda code: {"code": code, "message": "Telemetry receiver reported an error"} if code else None)(row.pop("error_code", "") or ""),
                "updated_at": row.pop("runtime_updated_at", None),
            }
            row["runtime"]["published_version"] = row["runtime"].get("applied_version")
            items.append(row)
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()


def subscription_status(subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
    item = _subscription_by_id(subscription_id, user)
    return item.get("runtime") or {}


def _capacity(conn, collector_id: str, user: dict[str, Any]) -> dict[str, Any]:
    collector = _require_telemetry_collector(conn, collector_id)
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT c.device_id) AS devices,
                   COUNT(DISTINCT CASE WHEN rt.connection_state = 'CONNECTED' THEN c.device_id END) AS observed_devices,
                   COALESCE(SUM(s.reserved_series), 0) AS series,
                   COALESCE(SUM(s.reserved_sample_rate), 0) AS samples_per_second,
                   COALESCE(SUM(rt.active_series), 0) AS observed_series,
                   COALESCE(SUM(rt.sample_rate), 0) AS observed_samples_per_second,
                   COALESCE(SUM(rt.queue_depth), 0) AS observed_queue_depth
              FROM telemetry_subscriptions s
              JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
              JOIN devices d ON d.id = c.device_id
              LEFT JOIN telemetry_subscription_runtime rt ON rt.subscription_id = s.id
             WHERE c.collector_id = ? AND s.deleted_at IS NULL
               AND s.desired_enabled = TRUE AND c.enabled = TRUE""",
        (collector_id,),
    ).fetchone()
    data = _dict(row)
    limits = {
        "devices": int(collector.get("device_limit") or DEVICE_LIMIT),
        "series": int(collector.get("series_limit") or SERIES_LIMIT),
        "samples_per_second": float(collector.get("samples_per_second_limit") or SAMPLES_PER_SECOND_LIMIT),
        "message_bytes": int(collector.get("message_bytes_limit") or MESSAGE_BYTES_LIMIT),
        "queue_bytes": _queue_bytes_limit(),
    }
    return {
        "collector_id": collector_id,
        "measured_at": _now(),
        "limit": limits,
        "reserved": {"devices": int(data.get("devices") or 0), "series": int(data.get("series") or 0),
                     "samples_per_second": float(data.get("samples_per_second") or 0),
                     "message_bytes": 0, "queue_bytes": 0},
        "observed": {"devices": int(data.get("observed_devices") or 0),
                     "series": int(data.get("observed_series") or 0),
                     "samples_per_second": float(data.get("observed_samples_per_second") or 0),
                     # The receiver does not yet publish observed max-message
                     # or vmagent queue occupancy into the control-plane DB.
                     # Return null so the UI does not report an invented zero.
                     "message_bytes": None, "queue_bytes": None},
    }


def collector_capacity(collector_id: str, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        _require_telemetry_collector(conn, collector_id)
        return {**_capacity(conn, collector_id, user), **_collector_endpoint()}
    finally:
        conn.close()


def _next_desired_version(conn, collector_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(desired_version), 0) FROM telemetry_config_jobs WHERE collector_id = ?",
        (collector_id,),
    ).fetchone()
    return int(row[0] or 0) + 1


def set_subscription_enabled(subscription_id: str, enabled: bool, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        subscription = conn.execute(
            """SELECT s.*, c.collector_id, c.device_id, c.profile_id, c.tls_profile_id,
                       c.allowed_sources, c.enabled AS config_enabled, c.tenant_id AS config_tenant
                  FROM telemetry_subscriptions s
                  JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                 WHERE s.id = ? AND s.deleted_at IS NULL FOR UPDATE""",
            (subscription_id,),
        ).fetchone()
        if not subscription:
            raise TelemetryServiceError("TELEMETRY_SUBSCRIPTION_NOT_FOUND", "Telemetry subscription not found", 404)
        row = _dict(subscription)
        device = _load_device(conn, row["device_id"], user, "update")
        if device["tenant_id"] != str(row["tenant_id"]):
            raise TelemetryServiceError("TELEMETRY_SUBSCRIPTION_NOT_FOUND", "Telemetry subscription not found", 404)
        _require_telemetry_collector(conn, str(row["collector_id"]), lock=True)
        if enabled:
            _require_collector_endpoint()
            if not bool(row.get("config_enabled")):
                raise TelemetryServiceError("TELEMETRY_DEVICE_NOT_READY", "Save and enable the device Telemetry configuration first", 409)
            profile = _profile(conn, str(row["profile_id"]))
            _validate_profile_device(profile, device)
            template = conn.execute(
                """SELECT metric_mappings, estimated_series, status FROM telemetry_subscription_templates
                    WHERE id = ? AND tenant_id = ? AND version = ?""",
                (row["template_id"], row["tenant_id"], row["template_version"]),
            ).fetchone()
            if not template or str(_dict(template).get("status") or "").upper() != "PUBLISHED":
                raise TelemetryServiceError("TELEMETRY_TEMPLATE_NOT_PUBLISHED", "Subscription template is not published", 409)
            mappings = _validate_template_mappings(_json_value(_dict(template).get("metric_mappings"), []))
            unverified = [item for item in mappings if item.get("support_status") in {"UNKNOWN", "UNSUPPORTED"}]
            if unverified:
                raise TelemetryServiceError("TELEMETRY_PATH_UNVERIFIED", "Template contains paths without supporting evidence")
            capacity = _capacity(conn, str(row["collector_id"]), user)
            existing_enabled = bool(row.get("desired_enabled"))
            reserved = capacity["reserved"]
            other_enabled = conn.execute(
                """SELECT 1 FROM telemetry_subscriptions other
                     JOIN telemetry_device_configs cfg ON cfg.id = other.config_id
                    WHERE cfg.device_id = ? AND cfg.collector_id = ?
                      AND other.deleted_at IS NULL AND other.desired_enabled = TRUE AND other.id <> ? LIMIT 1""",
                (row["device_id"], row["collector_id"], subscription_id),
            ).fetchone()
            add_devices = 0 if existing_enabled or other_enabled else 1
            add_series = 0 if existing_enabled else int(row.get("reserved_series") or 0)
            add_rate = 0 if existing_enabled else float(row.get("reserved_sample_rate") or 0)
            limits = capacity["limit"]
            if reserved["devices"] + add_devices > limits["devices"] or reserved["series"] + add_series > limits["series"] or reserved["samples_per_second"] + add_rate > limits["samples_per_second"]:
                raise TelemetryServiceError("TELEMETRY_CAPACITY_EXCEEDED", "Telemetry collector capacity reservation would exceed the configured limit", 409)
        now = _now()
        revision = int(row.get("revision") or 1) + 1
        conn.execute(
            "UPDATE telemetry_subscriptions SET desired_enabled = ?, revision = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
            (bool(enabled), revision, now, subscription_id, row["tenant_id"]),
        )
        desired_version = _next_desired_version(conn, str(row["collector_id"]))
        action = "ENABLE" if enabled else "DISABLE"
        idempotency_key = f"subscription:{subscription_id}:{revision}:{action.lower()}"
        job_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO telemetry_config_jobs (
                   id, tenant_id, collector_id, subscription_id, action,
                   desired_version, idempotency_key, state, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?)""",
            (job_id, row["tenant_id"], row["collector_id"], subscription_id, action,
             desired_version, idempotency_key, now, now),
        )
        conn.execute(
            """INSERT INTO telemetry_subscription_runtime (
                   subscription_id, tenant_id, connection_state, data_state, updated_at
               ) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (subscription_id) DO UPDATE SET
                   connection_state = EXCLUDED.connection_state,
                   data_state = EXCLUDED.data_state,
                   error_code = '', updated_at = EXCLUDED.updated_at""",
            (subscription_id, row["tenant_id"],
             "AWAITING_DEVICE" if enabled else "DISABLED",
             "NO_DATA" if enabled else "STALE", now),
        )
        conn.commit()
        _audit_control_action(user, "TELEMETRY_SUBSCRIPTION_ENABLED" if enabled else "TELEMETRY_SUBSCRIPTION_DISABLED",
                              "Telemetry subscription action queued", "telemetry_subscription", subscription_id,
                              {"enabled": bool(enabled), "job_id": job_id, "desired_version": desired_version})
        return {"job_id": job_id, "desired_version": desired_version, "state": "QUEUED"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def retry_subscription(subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
    current = _subscription_by_id(subscription_id, user)
    return set_subscription_enabled(subscription_id, bool(current.get("desired_enabled")), user)


def delete_subscription(subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Disable and soft-delete a subscription after queueing receiver publication."""
    _require_postgres()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT s.*, c.collector_id, c.device_id
                 FROM telemetry_subscriptions s
                 JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                WHERE s.id = ? AND s.deleted_at IS NULL FOR UPDATE""",
            (subscription_id,),
        ).fetchone()
        if not row:
            raise TelemetryServiceError("TELEMETRY_SUBSCRIPTION_NOT_FOUND", "Telemetry subscription not found", 404)
        item = _dict(row)
        device = _load_device(conn, item["device_id"], user, "delete")
        if device["tenant_id"] != str(item["tenant_id"]):
            raise TelemetryServiceError("TELEMETRY_SUBSCRIPTION_NOT_FOUND", "Telemetry subscription not found", 404)
        _require_telemetry_collector(conn, str(item["collector_id"]), lock=True)
        now = _now()
        desired_version = _next_desired_version(conn, str(item["collector_id"]))
        revision = int(item.get("revision") or 1) + 1
        job_id = str(uuid.uuid4())
        conn.execute(
            """UPDATE telemetry_subscriptions SET desired_enabled = FALSE,
                   deleted_at = ?, revision = ?, updated_at = ? WHERE id = ? AND tenant_id = ?""",
            (now, revision, now, subscription_id, item["tenant_id"]),
        )
        conn.execute(
            """INSERT INTO telemetry_config_jobs (
                   id, tenant_id, collector_id, subscription_id, action,
                   desired_version, idempotency_key, state, created_at, updated_at
               ) VALUES (?, ?, ?, ?, 'DELETE', ?, ?, 'QUEUED', ?, ?)""",
            (job_id, item["tenant_id"], item["collector_id"], subscription_id,
             desired_version, f"subscription:{subscription_id}:{revision}:delete", now, now),
        )
        conn.execute(
            """UPDATE telemetry_subscription_runtime SET connection_state = 'DISABLED',
                   data_state = 'STALE', updated_at = ? WHERE subscription_id = ?""",
            (now, subscription_id),
        )
        conn.commit()
        _audit_control_action(user, "TELEMETRY_SUBSCRIPTION_DELETED", "Telemetry subscription soft-deleted", "telemetry_subscription", subscription_id,
                              {"job_id": job_id, "desired_version": desired_version})
        return {"job_id": job_id, "desired_version": desired_version, "state": "QUEUED"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_receiver_status(collector_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Batch-update PostgreSQL runtime rows from the authenticated receiver."""
    _require_postgres()
    if len(items) > 500:
        raise TelemetryServiceError("TELEMETRY_STATUS_BATCH_TOO_LARGE", "Status update contains too many subscriptions")
    conn = get_db_connection()
    try:
        _require_telemetry_collector(conn, collector_id)
        updated = 0
        now = _now()
        for item in items:
            subscription_id = str(item.get("subscription_id") or "").strip()
            if not subscription_id:
                continue
            active_series = max(0, min(int(item.get("active_series") or 0), SERIES_LIMIT))
            sample_rate = max(0.0, min(float(item.get("sample_rate") or 0), SAMPLES_PER_SECOND_LIMIT))
            dropped = max(0, int(item.get("dropped_samples") or 0))
            error_code = str(item.get("error_code") or "")[:120]
            last_received = item.get("last_received_at") or now
            last_valid = item.get("last_valid_at")
            clock_skew_ms = item.get("clock_skew_ms")
            if clock_skew_ms is not None:
                clock_skew_ms = max(-86_400_000, min(86_400_000, int(clock_skew_ms)))
            requested_state = str(item.get("data_state") or "").upper()
            requested_connection = str(item.get("connection_state") or "").upper()
            data_state = requested_state if requested_state in {"NO_DATA", "FRESH", "PARTIAL", "STALE", "INVALID"} else (
                "FRESH" if last_valid and not error_code else "PARTIAL" if last_received else "NO_DATA"
            )
            connection_state = requested_connection if requested_connection in {"DISABLED", "AWAITING_DEVICE", "CONNECTING", "CONNECTED", "ERROR"} else "CONNECTED"
            cursor = conn.execute(
                """UPDATE telemetry_subscription_runtime r
                      SET connection_state = ?, data_state = ?,
                          last_received_at = ?, last_valid_at = ?, active_series = ?,
                          sample_rate = ?, dropped_samples = ?, clock_skew_ms = ?,
                          error_code = ?, owner_id = ?, updated_at = ?
                     FROM telemetry_subscriptions s
                     JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                    WHERE r.subscription_id = s.id AND s.id = ? AND s.deleted_at IS NULL
                      AND c.collector_id = ? AND s.desired_enabled = TRUE AND c.enabled = TRUE""",
                (connection_state, data_state, last_received, last_valid, active_series, sample_rate,
                 dropped, clock_skew_ms, error_code, collector_id, now, subscription_id, collector_id),
            )
            updated += max(0, int(getattr(cursor, "rowcount", 0) or 0))
        conn.commit()
        return {"updated": updated, "received": len(items)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_job(job_id: str, user: dict[str, Any]) -> dict[str, Any]:
    _require_postgres()
    tenant = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        query = "SELECT * FROM telemetry_config_jobs WHERE id = ?"
        params: tuple[Any, ...] = (job_id,)
        if tenant:
            query += " AND tenant_id = ?"
            params += (tenant,)
        row = conn.execute(query, params).fetchone()
        if not row:
            raise TelemetryServiceError("TELEMETRY_JOB_NOT_FOUND", "Telemetry job not found", 404)
        item = _dict(row)
        if item.get("device_config_id"):
            config = conn.execute(
                "SELECT device_id FROM telemetry_device_configs WHERE id = ? AND tenant_id = ?",
                (item["device_config_id"], item["tenant_id"]),
            ).fetchone()
            if not config:
                raise TelemetryServiceError("TELEMETRY_JOB_NOT_FOUND", "Telemetry job not found", 404)
            _load_device(conn, str(_dict(config)["device_id"]), user, "view")
        elif item.get("subscription_id"):
            sub = conn.execute(
                "SELECT config_id FROM telemetry_subscriptions WHERE id = ? AND tenant_id = ?",
                (item["subscription_id"], item["tenant_id"]),
            ).fetchone()
            if not sub:
                raise TelemetryServiceError("TELEMETRY_JOB_NOT_FOUND", "Telemetry job not found", 404)
            config = conn.execute(
                "SELECT device_id FROM telemetry_device_configs WHERE id = ? AND tenant_id = ?",
                (_dict(sub)["config_id"], item["tenant_id"]),
            ).fetchone()
            if not config:
                raise TelemetryServiceError("TELEMETRY_JOB_NOT_FOUND", "Telemetry job not found", 404)
            _load_device(conn, str(_dict(config)["device_id"]), user, "view")
        return item
    finally:
        conn.close()


def _receiver_config(conn, collector_id: str) -> dict[str, Any]:
    collector = _require_telemetry_collector(conn, collector_id)
    rows = conn.execute(
        """SELECT c.id AS config_id, c.tenant_id, c.asset_id, c.device_id,
                   c.device_source_address, c.allowed_sources, c.tls_profile_id,
                   d.hostname, d.vendor, d.platform, pa.asset_tag, pa.model,
                   p.profile_key, p.adapter_key,
                   tls.fingerprint,
                   s.id AS subscription_id, s.name AS subscription_name,
                   s.interval_seconds, s.path_filters, s.reserved_series,
                   s.reserved_sample_rate,
                   t.metric_mappings
              FROM telemetry_device_configs c
              JOIN devices d ON d.id = c.device_id AND d.asset_id = c.asset_id
              JOIN physical_assets pa ON pa.id = c.asset_id
              JOIN telemetry_protocol_profiles p ON p.id = c.profile_id
              LEFT JOIN telemetry_tls_profiles tls
                ON tls.id = c.tls_profile_id AND tls.tenant_id = c.tenant_id
              JOIN telemetry_subscriptions s ON s.config_id = c.id AND s.tenant_id = c.tenant_id
              JOIN telemetry_subscription_templates t ON t.id = s.template_id
                AND t.tenant_id = s.tenant_id AND t.version = s.template_version
             WHERE c.collector_id = ? AND c.enabled = TRUE
               AND s.deleted_at IS NULL AND s.desired_enabled = TRUE
             ORDER BY c.id, s.id""",
        (collector_id,),
    ).fetchall()
    sources: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = _dict(raw)
        source = sources.setdefault(str(row["config_id"]), {
            "config_id": str(row["config_id"]),
            "tenant_id": str(row["tenant_id"]),
            "asset_id": str(row["asset_id"]),
            "device_id": str(row["device_id"]),
            "hostname": str(row.get("hostname") or ""),
            "asset_tag": str(row.get("asset_tag") or ""),
            "vendor": str(row.get("vendor") or ""),
            "platform": str(row.get("platform") or ""),
            "model": str(row.get("model") or ""),
            "protocol": str(row.get("adapter_key") or ""),
            "device_source_address": row.get("device_source_address"),
            "enabled": True,
            "certificate_ids": [],
            "allowed_source_ips": _json_value(row.get("allowed_sources"), []),
            "subscriptions": [],
        })
        fingerprint = str(row.get("fingerprint") or "").strip().lower().replace(":", "")
        if fingerprint:
            source["certificate_ids"].append("sha256:" + fingerprint)
        mappings = _json_value(row.get("metric_mappings"), [])
        path_filters = _json_value(row.get("path_filters"), [])
        allowed_mappings = [
            item for item in mappings
            if not path_filters or str(item.get("source_path") or "") in path_filters
        ]
        source["subscriptions"].append({
            "id": str(row["subscription_id"]),
            "name": str(row["subscription_name"]),
            "enabled": True,
            "interval_seconds": int(row["interval_seconds"]),
            "reserved_sample_rate": float(row.get("reserved_sample_rate") or 0),
            "reserved_series": int(row.get("reserved_series") or 0),
            "path_filters": path_filters,
            "metric_mappings": allowed_mappings,
        })
    version_row = conn.execute(
        "SELECT COALESCE(MAX(desired_version), 0) FROM telemetry_config_jobs WHERE collector_id = ?",
        (collector_id,),
    ).fetchone()
    has_no_tls_source = any(
        bool(src.get("allowed_source_ips")) and not src.get("certificate_ids")
        for src in sources.values()
    )
    return {
        "collector_id": collector_id,
        "version": int(version_row[0] or 0),
        "limits": {
            "series": int(collector.get("series_limit") or SERIES_LIMIT),
            "samples_per_second": float(collector.get("samples_per_second_limit") or SAMPLES_PER_SECOND_LIMIT),
        },
        "accept_insecure": (
            has_no_tls_source
            or os.environ.get("TELEMETRY_ALLOW_INSECURE_IP_SOURCES", "0").strip().casefold() in {"1", "true", "yes", "on"}
        ),
        "sources": list(sources.values()),
    }


def _publish_receiver_config(collector_id: str) -> tuple[str, int, int]:
    _require_postgres()
    lock_key = int.from_bytes(hashlib.sha256(f"telemetry-publish:{collector_id}".encode()).digest()[:8], "big", signed=True)
    conn = get_db_connection()
    locked = False
    try:
        conn.execute("SELECT pg_advisory_lock(?)", (lock_key,)).fetchone()
        locked = True
        config = _receiver_config(conn, collector_id)
        root = Path(os.environ.get("MONITORING_ARTIFACT_ROOT", "artifacts/monitoring")).resolve()
        target = root / "runtime" / "telemetry" / "receiver.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > RECEIVER_CONFIG_BYTES_LIMIT:
            raise TelemetryServiceError("TELEMETRY_CONFIG_TOO_LARGE", "Receiver configuration exceeds the 8 MiB safety limit", 409)
        temp_fd, temp_name = tempfile.mkstemp(prefix=".receiver-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(temp_fd, "wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o640)
            os.replace(temp_name, target)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass
        return hashlib.sha256(body).hexdigest(), len(config["sources"]), int(config["version"])
    finally:
        if locked:
            try:
                conn.execute("SELECT pg_advisory_unlock(?)", (lock_key,)).fetchone()
                conn.commit()
            except Exception:
                conn.rollback()
        conn.close()


def process_publish_job(job_id: str) -> None:
    """Publish a committed job into the local shared runtime volume."""
    _require_postgres()
    conn = get_db_connection()
    try:
        job = conn.execute("SELECT * FROM telemetry_config_jobs WHERE id = ? FOR UPDATE", (job_id,)).fetchone()
        if not job:
            return
        row = _dict(job)
        if str(row.get("state") or "").upper() not in {"QUEUED", "FAILED"}:
            return
        now = _now()
        conn.execute("UPDATE telemetry_config_jobs SET state = 'RUNNING', attempt = attempt + 1, updated_at = ? WHERE id = ?", (now, job_id))
        conn.commit()
        checksum, source_count, published_version = _publish_receiver_config(str(row["collector_id"]))
        conn.execute("UPDATE telemetry_config_jobs SET state = 'SUCCEEDED', error_code = '', updated_at = ? WHERE id = ?", (_now(), job_id))
        if row.get("subscription_id"):
            current = conn.execute(
                """SELECT s.desired_enabled, c.enabled AS config_enabled
                     FROM telemetry_subscriptions s
                     JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                    WHERE s.id = ?""",
                (row["subscription_id"],),
            ).fetchone()
            current_enabled = bool(_dict(current).get("desired_enabled")) and bool(_dict(current).get("config_enabled"))
            conn.execute(
                """UPDATE telemetry_subscription_runtime SET owner_id = ?, applied_version = ?,
                       connection_state = CASE WHEN ? THEN 'AWAITING_DEVICE' ELSE 'DISABLED' END,
                       data_state = CASE WHEN ? THEN 'NO_DATA' ELSE 'STALE' END,
                       error_code = '', updated_at = ? WHERE subscription_id = ?""",
                (str(row["collector_id"]), published_version, current_enabled,
                 current_enabled, _now(), row["subscription_id"]),
            )
        elif row.get("device_config_id"):
            conn.execute(
                """UPDATE telemetry_subscription_runtime r
                      SET owner_id = ?, applied_version = ?,
                          connection_state = CASE WHEN s.desired_enabled AND c.enabled THEN 'AWAITING_DEVICE' ELSE 'DISABLED' END,
                          data_state = CASE WHEN s.desired_enabled AND c.enabled THEN 'NO_DATA' ELSE 'STALE' END,
                          error_code = '', updated_at = ?
                     FROM telemetry_subscriptions s
                     JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                    WHERE r.subscription_id = s.id AND s.config_id = ?
                      AND s.deleted_at IS NULL""",
                (str(row["collector_id"]), published_version, _now(), row["device_config_id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        try:
            conn.execute(
                "UPDATE telemetry_config_jobs SET state = 'FAILED', error_code = 'PUBLISH_FAILED', updated_at = ? WHERE id = ?",
                (_now(), job_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        raise
    finally:
        conn.close()


def _pb_varint(value: int) -> bytes:
    v = max(0, int(value))
    out = bytearray()
    while v > 0x7F:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)
    return bytes(out)


def _pb_field_varint(field_number: int, value: int) -> bytes:
    return _pb_varint((field_number << 3) | 0) + _pb_varint(value)


def _pb_field_bytes(field_number: int, payload: bytes) -> bytes:
    return _pb_varint((field_number << 3) | 2) + _pb_varint(len(payload)) + payload


def _build_official_sample_document(source_path: str, hostname: str, now_ms: int) -> dict[str, Any]:
    path_lower = source_path.strip().casefold()
    # --- Huawei VRP / VRP8 (CloudEngine) ---
    if "cpuinfo" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "cpuInfos": {"cpuInfo": [{"position": "0", "systemCpuUsage": 21}, {"position": "1", "systemCpuUsage": 17}]},
        }
    if "memoryinfo" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "memoryInfos": {"memoryInfo": [{"position": "0", "osMemoryUsage": 44}]},
        }
    if "ifstatistics" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "interfaces": {
                "interface": [
                    {
                        "ifName": "10GE1/0/1",
                        "ifStatistics": {"receiveByte": 984521000, "sendByte": 541209000, "receiveErrorPacket": 0, "sendDropPacket": 2},
                    },
                    {
                        "ifName": "10GE1/0/2",
                        "ifStatistics": {"receiveByte": 312490000, "sendByte": 209884000, "receiveErrorPacket": 0, "sendDropPacket": 0},
                    },
                ]
            },
        }
    if "huawei-ifm:ifm/interfaces/interface" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "interfaces": {
                "interface": [
                    {"ifName": "10GE1/0/1", "ifSpeed": 10000000000},
                    {"ifName": "10GE1/0/2", "ifSpeed": 10000000000},
                ]
            },
        }
    if "opticalinfo" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "ports": {
                "port": [
                    {"position": "10GE1/0/1", "opticalInfo": {"rxPower": -2.4, "txPower": -1.8, "temperature": 36}},
                    {"position": "10GE1/0/2", "opticalInfo": {"rxPower": -3.1, "txPower": -2.0, "temperature": 37}},
                ]
            },
        }
    if "temperatureinfo" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "temperatureInfos": {"temperatureInfo": [{"position": "Slot1", "currentTemperature": 41}]},
        }
    if "fans/fan" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "fans": {"fan": [{"position": "FAN1", "speed": 6400}]},
        }
    if "qosportqueuestatinfo" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "qosPortQueueStatInfos": {"qosPortQueueStatInfo": [{"ifName": "10GE1/0/1", "discardedPackets": 3}]},
        }
    if "pfcportstatistic" in path_lower:
        return {
            "sensor_path": source_path,
            "msg_timestamp": now_ms,
            "pfcPortStatistics": {"pfcPortStatistic": [{"ifName": "10GE1/0/1", "rxPauseFrames": 12}]},
        }

    # --- H3C Comware V7 ---
    if path_lower == "device/cpus":
        return {
            "Timestamp": now_ms,
            "notification": {"Device": {"CPUs": [{"Slot": "1", "CPUUsage": 18}]}},
        }
    if path_lower == "diagnostic/memories":
        return {
            "Timestamp": now_ms,
            "notification": {"Diagnostic": {"Memories": [{"Slot": "1", "UsedRatio": 42}]}},
        }
    if path_lower == "ifmgr/interfaces":
        return {
            "Timestamp": now_ms,
            "notification": {
                "Ifmgr": {
                    "Interfaces": [
                        {"Name": "FortyGigE1/0/53", "OperStatus": 1},
                        {"Name": "GigabitEthernet1/0/2", "OperStatus": 1},
                    ]
                }
            },
        }
    if path_lower == "ifmgr/statistics":
        return {
            "Timestamp": now_ms,
            "notification": {
                "Ifmgr": {
                    "Statistics": [
                        {"Name": "FortyGigE1/0/53", "InOctets": 1482910400, "OutOctets": 892341200, "InErrors": 0, "OutDiscards": 1},
                        {"Name": "GigabitEthernet1/0/2", "InOctets": 249102400, "OutOctets": 124809100, "InErrors": 0, "OutDiscards": 0},
                    ]
                }
            },
        }
    if path_lower == "device/transceivers":
        return {
            "Timestamp": now_ms,
            "notification": {
                "Device": {
                    "Transceivers": [
                        {"Name": "FortyGigE1/0/53", "RxPower": -2.1, "TxPower": -1.6},
                        {"Name": "Ten-GigabitEthernet1/0/1", "RxPower": -3.4, "TxPower": -2.2},
                    ]
                }
            },
        }
    if path_lower == "device/physicalentities":
        return {
            "Timestamp": now_ms,
            "notification": {"Device": {"PhysicalEntities": [{"Name": "Slot 1 Switchboard", "Temperature": 39}]}},
        }
    if path_lower == "buffermonitor/bufferusages":
        return {
            "Timestamp": now_ms,
            "notification": {"BufferMonitor": {"BufferUsages": [{"InterfaceName": "FortyGigE1/0/53", "UsedBytes": 65536}]}},
        }
    if path_lower == "buffermonitor/headroomusages":
        return {
            "Timestamp": now_ms,
            "notification": {"BufferMonitor": {"HeadroomUsages": [{"InterfaceName": "FortyGigE1/0/53", "UsedBytes": 4096}]}},
        }
    if path_lower == "buffermonitor/egressdrops":
        return {
            "Timestamp": now_ms,
            "notification": {"BufferMonitor": {"EgressDrops": [{"InterfaceName": "FortyGigE1/0/53", "DropPackets": 0}]}},
        }
    if path_lower == "session/statistics":
        return {
            "Timestamp": now_ms,
            "notification": {"Session": {"Statistics": {"CurrentSessions": 18420}}},
        }
    if path_lower == "wlan/apstatistics":
        return {
            "Timestamp": now_ms,
            "notification": {"WLAN": {"APStatistics": {"OnlineAPCount": 64}}},
        }
    if path_lower == "ifmgr/devicecapabilities":
        return {
            "Timestamp": now_ms,
            "notification": {"Ifmgr": {"DeviceCapabilities": {"MinMTU": 46, "MaxMTU": 9216}}},
        }
    if path_lower == "syslog/logbuffer":
        return {
            "Timestamp": now_ms,
            "notification": {"Syslog": {"LogBuffer": {"BufferSize": 512, "LogCount": 24}}},
        }
    return {
        "sensor_path": source_path,
        "Timestamp": now_ms,
        "msg_timestamp": now_ms,
        "hostname": hostname,
        "value": 1,
    }


def simulate_subscription_push(subscription_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Simulate an official Huawei or H3C gRPC Dial-out wire frame push and normalize it end-to-end."""
    from collectors.telemetry.normalizer import normalize_message
    from collectors.telemetry.wire import (
        decode_h3c_v2_dialout,
        decode_h3c_v3_json,
        decode_huawei_service_args,
    )

    _require_postgres()
    conn = get_db_connection()
    try:
        sub_row = conn.execute(
            """SELECT s.*, c.collector_id, c.device_id, c.asset_id, c.profile_id,
                      c.enabled AS config_enabled, d.hostname, d.vendor, d.platform,
                      p.profile_key, p.adapter_key, t.metric_mappings
                 FROM telemetry_subscriptions s
                 JOIN telemetry_device_configs c ON c.id = s.config_id AND c.tenant_id = s.tenant_id
                 JOIN devices d ON d.id = c.device_id
                 JOIN telemetry_protocol_profiles p ON p.id = c.profile_id
                 JOIN telemetry_subscription_templates t ON t.id = s.template_id
                  AND t.tenant_id = s.tenant_id AND t.version = s.template_version
                WHERE s.id = ? AND s.deleted_at IS NULL""",
            (subscription_id,),
        ).fetchone()
        if not sub_row:
            raise TelemetryServiceError("TELEMETRY_SUBSCRIPTION_NOT_FOUND", "Telemetry subscription not found", 404)
        row = _dict(sub_row)
        device = _load_device(conn, str(row["device_id"]), user, "update")
        collector_id = str(row["collector_id"])

        # Auto-enable the config and subscription if not yet enabled so simulation works in 1 click.
        if not bool(row.get("config_enabled")):
            conn.execute(
                "UPDATE telemetry_device_configs SET enabled = TRUE, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (_now(), row["config_id"], row["tenant_id"]),
            )
            conn.commit()
    finally:
        conn.close()

    if not bool(row.get("desired_enabled")):
        job = set_subscription_enabled(subscription_id, True, user)
        process_publish_job(job["job_id"])

    adapter_key = str(row.get("adapter_key") or row.get("profile_key") or "").casefold()
    mappings = _json_value(row.get("metric_mappings"), [])
    path_filters = _json_value(row.get("path_filters"), [])
    allowed_mappings = [
        item for item in mappings
        if isinstance(item, dict) and (not path_filters or str(item.get("source_path") or "") in path_filters)
    ]
    paths = list(dict.fromkeys(str(item.get("source_path") or "").strip() for item in allowed_mappings if item.get("source_path")))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    hostname = str(device.get("hostname") or "switch-sim")

    device_ctx = {
        "tenant_id": device.get("tenant_id"),
        "asset_id": device.get("asset_id"),
        "device_id": device.get("device_id"),
        "hostname": hostname,
        "vendor": device.get("vendor"),
        "platform": device.get("platform"),
    }
    sub_ctx = {
        "id": subscription_id,
        "metric_mappings": allowed_mappings,
    }

    normalized_samples: list[str] = []
    decoded_frames: list[dict[str, Any]] = []

    if "huawei" in adapter_key:
        wire_format = "huawei_dialout.gRPCDataservice / serviceArgs(packed_data_json)"
        records = [_build_official_sample_document(p, hostname, now_ms) for p in paths]
        packed_json = json.dumps({"telemetry": records}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # Official Huawei serviceArgs protobuf: field 1 ReqId (varint), field 6 packed_data_json (bytes)
        raw_pb = _pb_field_varint(1, 1001) + _pb_field_bytes(6, packed_json)
        encoding, decoded_payload = decode_huawei_service_args(raw_pb)
        parsed_doc = json.loads(decoded_payload.decode("utf-8"))
        for rec in parsed_doc.get("telemetry", []):
            spath = str(rec.get("sensor_path") or "")
            rec_bytes = json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            samples = normalize_message(
                payload=rec_bytes,
                source_path=spath,
                source_timestamp=rec.get("msg_timestamp"),
                device=device_ctx,
                subscription=sub_ctx,
            )
            normalized_samples.extend(samples)
            decoded_frames.append({"encoding": encoding, "sensor_path": spath, "wire_bytes": len(raw_pb), "sample_count": len(samples)})
    elif "v3" in adapter_key:
        wire_format = "grpc_dialout_v3.gRPCDialoutV3 / TelemetryPacked(3-layer JSON)"
        packed_records = bytearray()
        for spath in paths:
            doc = _build_official_sample_document(spath, hostname, now_ms)
            doc_bytes = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            # Official H3C v3 Telemetry record: field 16 sensor_path, field 19 timestamp, field 24 data_str
            rec_pb = _pb_field_bytes(16, spath.encode("utf-8")) + _pb_field_varint(19, now_ms) + _pb_field_bytes(24, doc_bytes)
            packed_records.extend(_pb_field_bytes(1, rec_pb))
        # Official H3C v3 DialoutV3Args: field 1 requestId, field 2 TelemetryPacked data
        raw_pb = _pb_field_varint(1, 2001) + _pb_field_bytes(2, bytes(packed_records))
        req_id, _total, decoded_records = decode_h3c_v3_json(raw_pb)
        for spath, ts, rec_bytes in decoded_records:
            samples = normalize_message(
                payload=rec_bytes,
                source_path=spath,
                source_timestamp=ts,
                device=device_ctx,
                subscription=sub_ctx,
            )
            normalized_samples.extend(samples)
            decoded_frames.append({"request_id": req_id, "sensor_path": spath, "wire_bytes": len(raw_pb), "sample_count": len(samples)})
    else:
        wire_format = "grpc_dialout.GRPCDialout / DialoutMsg(2-layer JSON)"
        dev_msg_pb = _pb_field_bytes(1, b"H3C") + _pb_field_bytes(2, hostname.encode("utf-8"))
        for spath in paths:
            doc = _build_official_sample_document(spath, hostname, now_ms)
            doc_bytes = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            # Official H3C v2 DialoutMsg: field 1 deviceMsg, field 2 sensorPath, field 3 jsonData
            raw_pb = _pb_field_bytes(1, dev_msg_pb) + _pb_field_bytes(2, spath.encode("utf-8")) + _pb_field_bytes(3, doc_bytes)
            producer, dev_name, decoded_path, decoded_body = decode_h3c_v2_dialout(raw_pb)
            parsed_body = json.loads(decoded_body.decode("utf-8"))
            samples = normalize_message(
                payload=decoded_body,
                source_path=decoded_path,
                source_timestamp=parsed_body.get("Timestamp"),
                device=device_ctx,
                subscription=sub_ctx,
            )
            normalized_samples.extend(samples)
            decoded_frames.append({"producer": producer, "device": dev_name, "sensor_path": decoded_path, "wire_bytes": len(raw_pb), "sample_count": len(samples)})

    now_iso = _now()
    interval = max(1, int(row.get("interval_seconds") or 10))
    sample_rate = round(len(normalized_samples) / float(interval), 2)

    # Best-effort forward simulated Prometheus samples to VictoriaMetrics so they appear live in Grafana.
    metrics_written_to_vm = False
    vm_import_url = ""
    if normalized_samples:
        try:
            import urllib.request

            remote_write = os.environ.get("TELEMETRY_REMOTE_WRITE_URL", "").strip()
            vm_base = os.environ.get("VICTORIAMETRICS_URL", "http://127.0.0.1:8428").strip().rstrip("/")
            vm_import_url = remote_write or f"{vm_base}/api/v1/import/prometheus"
            # Synthesize a 6-point (5-minute) continuous burst ending at now_ms so
            # Grafana immediately draws smooth waves & rate() traffic curves for every simulated device.
            vm_lines: list[str] = []
            host_seed = sum(ord(ch) for ch in hostname) % 11
            step_offsets = (-300_000, -240_000, -180_000, -120_000, -60_000, 0)
            for sample_line in normalized_samples:
                try:
                    identity, val_str, ts_str = sample_line.rsplit(" ", 2)
                    base_val = float(val_str)
                    base_ts = int(ts_str)
                    metric_name = identity.split("{", 1)[0].lower()
                    is_counter = any(tok in metric_name for tok in ("octets", "bytes", "packets", "errors", "discards", "drop", "pause"))
                    for idx, delta_ms in enumerate(step_offsets):
                        ts_i = base_ts + delta_ms
                        if is_counter:
                            # Monotonically increasing counter so rate() renders realistic bps/pps
                            step_inc = max(125_000.0, abs(base_val) * 0.002) if ("octets" in metric_name or "bytes" in metric_name) else max(1.0, abs(base_val) * 0.05)
                            val_i = max(0.0, base_val - (len(step_offsets) - 1 - idx) * step_inc)
                        else:
                            # Subtle per-device wave variation (+/- 4%) so multiple devices separate cleanly
                            wave = ((idx + host_seed) % 5 - 2) * 0.02
                            val_i = round(base_val * (1.0 + wave), 3)
                        vm_lines.append(f"{identity} {val_i:.15g} {ts_i}")
                except Exception:
                    vm_lines.append(sample_line)
            req = urllib.request.Request(
                vm_import_url,
                data=("\n".join(vm_lines) + "\n").encode("utf-8"),
                headers={"Content-Type": "text/plain; version=0.0.4"},
                method="POST",
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=2.0) as resp:
                metrics_written_to_vm = 200 <= int(getattr(resp, "status", 200)) < 300
        except Exception:
            logger.debug("Simulated telemetry samples were not written to VictoriaMetrics (offline or unreachable)", exc_info=True)

    record_receiver_status(
        collector_id,
        [
            {
                "subscription_id": subscription_id,
                "last_received_at": now_iso,
                "last_valid_at": now_iso,
                "active_series": len(normalized_samples),
                "sample_rate": sample_rate,
                "dropped_samples": 0,
                "clock_skew_ms": 0,
                "error_code": "",
                "connection_state": "CONNECTED",
                "data_state": "FRESH",
            }
        ],
    )
    updated_sub = _subscription_by_id(subscription_id, user)
    return {
        "subscription_id": subscription_id,
        "device_id": str(row["device_id"]),
        "hostname": hostname,
        "vendor": str(device.get("vendor") or ""),
        "protocol_profile": str(row.get("profile_key") or ""),
        "wire_format": wire_format,
        "simulated_paths": paths,
        "decoded_frames": decoded_frames,
        "active_series": len(normalized_samples),
        "sample_rate": sample_rate,
        "metrics_written_to_vm": metrics_written_to_vm,
        "vm_import_url": vm_import_url,
        "normalized_samples": normalized_samples,
        "runtime": updated_sub.get("runtime") or {},
    }
