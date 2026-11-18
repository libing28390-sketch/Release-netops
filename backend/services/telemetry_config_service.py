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
            raise TelemetryServiceError("TELEMETRY_SOURCE_INVALID", "TLS-authenticated sources also require an explicit device source IP allowlist")
        if profile.get("auth_mode") in {"tls_pki", "device_configured"} and bool(payload.enabled):
            if not payload.tls_profile_id:
                raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "This protocol profile requires a TLS profile")
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
    raw_bind_ip = os.environ.get("TELEMETRY_GRPC_BIND_IP", "127.0.0.1").strip() or "127.0.0.1"
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
    return (
        str(profile.get("vendor") or "").casefold() == "h3c"
        and any(re.match(r"R[\dx]{4}", item.strip(), re.IGNORECASE) for item in re.split(r"[,/;]", scope))
        and bool(re.fullmatch(r"(?:Comware\s+)?V?\d+(?:\.\d+)+", version, re.IGNORECASE))
    )


def _version_scope_matches(scope: str, version: str) -> bool:
    """Match documented x wildcards, including H3C versions like R6717Pxx-6W101."""
    scope = scope.strip().casefold()
    if re.match(r"r[\dx]{4}", scope):
        version = re.sub(r"\brelease\s+(?=\d)", "r", version, flags=re.IGNORECASE)
        if scope == "r6717pxx-6w101":
            # The suffix is the manual revision. Match the device's Release field.
            return bool(re.search(r"\br6717(?:p\d{2})?\b", version, re.IGNORECASE))
    escaped_scope = re.escape(scope)
    pattern = re.sub(
        r"x+",
        lambda match: f"[0-9a-z]{{{len(match.group(0))}}}",
        escaped_scope,
    )
    return bool(re.search(pattern, version, flags=re.IGNORECASE))


def _has_profile_version(profile: dict[str, Any], device: dict[str, Any]) -> bool:
    version = str(device.get("version") or "").strip()
    if not _known_device_value(version) or _h3c_release_pending(profile, version):
        return False
    # A VRP core version such as 8.180 does not identify the product release.
    return not (
        str(profile.get("vendor") or "").casefold() == "huawei"
        and re.search(r"\bV\d{3}R", str(profile.get("version_scope") or ""), re.IGNORECASE)
        and re.fullmatch(r"(?:VRP\s+)?V?\d+(?:\.\d+)+", version, re.IGNORECASE)
    )


def _validate_profile_known_scope(profile: dict[str, Any], device: dict[str, Any], *, draft: bool = False) -> str:
    """Reject known model/version mismatches and report missing identity fields."""
    _validate_profile_vendor(profile, device)
    if str(profile.get("support_status") or "UNKNOWN").upper() == "UNSUPPORTED":
        raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Telemetry profile is marked unsupported")
    pending: list[str] = []
    model_scope = str(profile.get("model_scope") or "").casefold()
    model = str(device.get("model") or "").casefold()
    if model_scope:
        def normalized_model(value: str) -> str:
            # Official scope notation such as S6520X-HI[EI][SI] names a
            # documented family. Compare its stable base with inventory model
            # spellings while retaining the explicit family boundary.
            without_variants = re.sub(r"\[[^\]]+\]", "", value)
            return re.sub(r"[^a-z0-9]", "", without_variants.casefold())

        if not _known_device_value(model):
            pending.append("model")
        else:
            model_key = normalized_model(model)
            tokens = [normalized_model(token) for token in re.split(r"[,/;]", model_scope)]
            if not any(token and token in model_key for token in tokens):
                if draft:
                    return "MISMATCH"
                raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Device model is outside the documented profile scope")
    version_scope = str(profile.get("version_scope") or "").strip()
    version = str(device.get("version") or "").strip()
    if version_scope:
        if not _has_profile_version(profile, device):
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
    if profile.get("version_scope") and not _has_profile_version(profile, device):
        missing.append("version")
    return missing


def _validate_profile_device(profile: dict[str, Any], device: dict[str, Any]) -> None:
    match_state = _validate_profile_known_scope(profile, device)
    if match_state == "IDENTIFICATION_PENDING":
        if not _known_device_value(device.get("model")) and profile.get("model_scope"):
            raise TelemetryServiceError("TELEMETRY_PROFILE_UNSUPPORTED", "Device model must be identified before enabling this profile")
        raise TelemetryServiceError("TELEMETRY_VERSION_UNVERIFIED", "Device software version must be identified before enabling this profile")


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


def list_profiles() -> dict[str, Any]:
    _require_postgres()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM telemetry_protocol_profiles
                ORDER BY vendor, model_scope, version_scope, profile_key"""
        ).fetchall()
        items = []
        for row in rows:
            item = _dict(row)
            item["official_sources"] = _json_value(item.get("official_sources"), [])
            item["paths"] = []
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
        elif profile.get("auth_mode") in {"tls_pki", "device_configured"} and bool(payload.enabled):
            raise TelemetryServiceError("TELEMETRY_TLS_INVALID", "This protocol profile requires a TLS profile")
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
    return {
        "collector_id": collector_id,
        "version": int(version_row[0] or 0),
        "limits": {
            "series": int(collector.get("series_limit") or SERIES_LIMIT),
            "samples_per_second": float(collector.get("samples_per_second_limit") or SAMPLES_PER_SECOND_LIMIT),
        },
        "accept_insecure": os.environ.get("TELEMETRY_ALLOW_INSECURE_IP_SOURCES", "0").strip().casefold() in {"1", "true", "yes", "on"},
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
