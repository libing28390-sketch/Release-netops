"""Declarative platform identification and tenant-scoped device binding."""

from __future__ import annotations

import re
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.rbac import authorize_resource
from services.platform_registry_service import (
    PlatformRegistryError,
    _assert_profile_access,
    _assert_profile_active,
    _row_dict,
    platform_codes_match,
)


SUPPORTED_MATCH_TYPES = {"contains", "starts_with", "ends_with", "equals", "regex"}
IDENTIFICATION_COMMANDS: dict[str, tuple[str, ...]] = {
    "cisco_ios": ("show version",),
    "arista_eos": ("show version",),
    "juniper_junos": ("show version",),
    "huawei_vrp": ("display version",),
    "h3c_comware": ("display version",),
    "zte_zxros": ("show version",),
    "ruijie_os": ("show version",),
    "dptech_ios": ("show version",),
    "maipu": ("show version",),
}

_IDENTIFICATION_DRIVER_ALIASES = {
    "h3c_comware": "hp_comware",
    "huawei": "huawei_vrp",
    "huawei_vrpv8": "huawei_vrp",
    "ruijie_rgos": "ruijie_os",
    "zte_5900_v6": "zte_zxros",
    "zte_zsrv2_v3": "zte_zxros",
    "ruijie_s6k_rgos12": "ruijie_os",
    "ruijie_eg_rgos11": "ruijie_os",
    "dptech_fw_s211": "dptech_ios",
    "maipu_s3330_v9": "maipu",
}


def _scope_denied(code: str = "DEVICE_SCOPE_DENIED") -> PlatformRegistryError:
    return PlatformRegistryError(code, "Device or platform is outside the current resource scope", status_code=403)


def _load_device(conn, device_id: str, user: dict[str, Any], *, lock: bool = False) -> dict[str, Any]:
    import database as database_module

    suffix = " FOR UPDATE" if lock and database_module._USE_PG else ""
    # Older upgrade fixtures and some installations do not yet carry the
    # optional vendor/device_type columns. Resolve the projection from the
    # actual table so binding remains compatible while still using those
    # fields when they exist.
    if database_module._USE_PG:
        column_rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'devices'",
        ).fetchall()
        available_columns = {str(row[0]) for row in column_rows}
    else:
        column_rows = conn.execute("PRAGMA table_info(devices)").fetchall()
        available_columns = {str(row[1]) for row in column_rows}
    preferred_columns = [
        "id", "hostname", "tenant_id", "site_id", "site", "device_group_id",
        "vendor", "device_type", "platform", "platform_profile_id", "platform_source", "platform_locked",
    ]
    projection = ", ".join(column for column in preferred_columns if column in available_columns)
    row = _row_dict(conn.execute(
        f"SELECT {projection} FROM devices WHERE id = ?{suffix}",
        (device_id,),
    ).fetchone())
    if not row:
        raise PlatformRegistryError("DEVICE_NOT_FOUND", "Device not found", status_code=404)
    user_tenant = str(user.get("tenant_id") or "")
    device_tenant = str(row.get("tenant_id") or "")
    if user_tenant and device_tenant != user_tenant:
        raise _scope_denied()
    if not authorize_resource(
        user,
        "platform",
        "bind_device",
        tenant_id=device_tenant,
        site_id=row.get("site_id") or row.get("site"),
        device_group_id=row.get("device_group_id"),
    ):
        raise _scope_denied()
    return row


def _assert_device_view(conn, device_id: str, user: dict[str, Any]) -> dict[str, Any]:
    row = _row_dict(conn.execute(
        "SELECT id, tenant_id, site_id, site, device_group_id FROM devices WHERE id = ?",
        (device_id,),
    ).fetchone())
    if not row:
        raise PlatformRegistryError("DEVICE_NOT_FOUND", "Device not found", status_code=404)
    tenant_id = str(row.get("tenant_id") or "")
    user_tenant = str(user.get("tenant_id") or "")
    if user_tenant and tenant_id != user_tenant:
        raise _scope_denied()
    if not authorize_resource(
        user,
        "platform",
        "view",
        tenant_id=tenant_id,
        site_id=row.get("site_id") or row.get("site"),
        device_group_id=row.get("device_group_id"),
    ):
        raise _scope_denied()
    return row


def _binding_compatibility(device: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Return a safe compatibility result before a binding is persisted."""
    warnings: list[dict[str, str]] = []
    device_vendor = str(device.get("vendor") or "").strip().lower()
    profile_vendor = str(profile.get("vendor") or "").strip().lower()
    if device_vendor and profile_vendor and device_vendor != profile_vendor:
        warnings.append({
            "code": "VENDOR_PLATFORM_MISMATCH",
            "message": "Device vendor and target platform vendor differ",
        })
    adaptation_status = str(profile.get("adaptation_status") or "").upper()
    sample_status = str(profile.get("sample_status") or "").upper()
    if adaptation_status in {"UNVERIFIED", "MISSING"} or sample_status == "MISSING":
        warnings.append({
            "code": "PLATFORM_ADAPTATION_UNVERIFIED",
            "message": "Target platform has no production-confirmed sample yet",
        })
    return {
        "status": "WARNING" if warnings else "PASSED",
        "warnings": warnings,
        "high_risk_execution_blocked": bool(warnings),
    }


def _assert_device_profile_platform(device: dict[str, Any], profile: dict[str, Any]) -> None:
    """Require an explicit device platform to match the target Profile.

    Legacy imports may have no platform identity yet; those devices can be
    manually assigned once.  Any explicit platform value, however, must match
    the target Profile or one of its declared aliases.
    """
    device_platform = str(device.get("platform") or "").strip().lower()
    if device_platform in {"", "unknown", "generic"}:
        return
    if not platform_codes_match(
        device_platform,
        profile.get("platform_code"),
        profile.get("parser_platform"),
    ):
        raise PlatformRegistryError(
            "PLATFORM_PROFILE_MISMATCH",
            "设备当前平台与目标平台注册表不一致，请选择同一平台后再绑定",
            status_code=409,
        )


def _match(rule: dict[str, Any], output: str) -> bool:
    match_type = str(rule.get("match_type") or "").strip().lower()
    if match_type not in SUPPORTED_MATCH_TYPES:
        return False
    pattern = str(rule.get("pattern") or "")
    candidate = str(output or "")
    if len(pattern.encode("utf-8")) > 4096 or len(candidate.encode("utf-8")) > 2_000_000:
        return False
    if match_type == "contains":
        matched = pattern in candidate
    elif match_type == "starts_with":
        matched = candidate.startswith(pattern)
    elif match_type == "ends_with":
        matched = candidate.endswith(pattern)
    elif match_type == "equals":
        matched = candidate == pattern
    else:
        try:
            matched = re.search(pattern, candidate, flags=re.MULTILINE) is not None
        except re.error:
            matched = False
    return not matched if bool(rule.get("negate")) else matched


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_conflict_payload(result: dict[str, Any], observations: dict[str, str]) -> tuple[list[dict[str, Any]], list[str], str]:
    """Build a conflict fingerprint without retaining any device output."""
    candidates = []
    for item in result.get("suggestions") or []:
        candidates.append({
            "platform_profile_id": str(item.get("platform_profile_id") or ""),
            "platform_code": str(item.get("platform_code") or ""),
            "name_zh": str(item.get("name_zh") or "")[:128],
            "name_en": str(item.get("name_en") or "")[:128],
            "score": round(float(item.get("score") or 0), 4),
            "matched_rule_count": int(item.get("matched_rule_count") or 0),
            "matched_rule_ids": sorted(str(rule.get("rule_id") or "") for rule in item.get("matched_rules") or []),
        })
    candidates.sort(key=lambda item: (item["platform_profile_id"], item["score"]))
    commands = sorted({str(key).strip() for key in observations if str(key).strip()})
    fingerprint_payload = {"commands": commands, "candidates": candidates}
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return candidates, commands, fingerprint


def _persist_identification_conflict(
    device_id: str,
    observations: dict[str, str],
    result: dict[str, Any],
    user: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> None:
    if result.get("status") != "IDENTIFICATION_CONFLICT":
        return
    candidates, commands, fingerprint = _safe_conflict_payload(result, observations)
    if not candidates:
        return
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO platform_identification_conflicts
               (id, tenant_id, device_id, status, conflict_fingerprint,
                platform_candidates_json, observation_commands_json, created_at, updated_at)
               VALUES (?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)
               ON CONFLICT(device_id, conflict_fingerprint, status) DO UPDATE SET
                 platform_candidates_json = excluded.platform_candidates_json,
                 observation_commands_json = excluded.observation_commands_json,
                 updated_at = excluded.updated_at""",
            (
                f"identification-conflict-{device_id}-{fingerprint}",
                tenant_id or str(user.get("tenant_id") or "") or None,
                device_id,
                fingerprint,
                json.dumps(candidates, ensure_ascii=False, sort_keys=True),
                json.dumps(commands, ensure_ascii=False),
                now,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_identification_conflicts(user: dict[str, Any], *, status: str = "OPEN", limit: int = 100) -> list[dict[str, Any]]:
    normalized_status = str(status or "OPEN").strip().upper()
    if normalized_status not in {"OPEN", "RESOLVED", "IGNORED"}:
        raise PlatformRegistryError("INVALID_CONFLICT_STATUS", "Invalid identification conflict status")
    safe_limit = max(1, min(int(limit or 100), 500))
    conn = get_db_connection()
    try:
        clauses = ["c.status = ?"]
        params: list[Any] = [normalized_status]
        if user.get("role") != "Administrator" or user.get("tenant_id"):
            clauses.append("c.tenant_id = ?")
            params.append(str(user.get("tenant_id") or ""))
        rows = conn.execute(
            """SELECT c.id, c.tenant_id, c.device_id, c.status, c.conflict_fingerprint,
                      c.platform_candidates_json, c.observation_commands_json,
                      c.resolved_profile_id, c.resolved_by, c.resolution_reason,
                      c.created_at, c.updated_at, c.resolved_at,
                      d.hostname, d.ip_address, d.site_id, d.site, d.device_group_id
               FROM platform_identification_conflicts c
               LEFT JOIN devices d ON d.id = c.device_id
               WHERE """ + " AND ".join(clauses) + " ORDER BY c.updated_at DESC LIMIT ?",
            [*params, safe_limit],
        ).fetchall()
        result = []
        for raw_row in rows:
            row = _row_dict(raw_row) or {}
            scope = {
                "tenant_id": row.get("tenant_id"),
                "site_id": row.get("site_id") or row.get("site"),
                "device_group_id": row.get("device_group_id"),
            }
            if user.get("role") != "Administrator" and not authorize_resource(user, "platform", "view", **scope):
                continue
            for key in ("platform_candidates_json", "observation_commands_json"):
                raw_value = row.pop(key, None)
                if isinstance(raw_value, (list, dict)):
                    row[key[:-5]] = raw_value
                    continue
                try:
                    row[key[:-5]] = json.loads(raw_value or "[]")
                except (TypeError, json.JSONDecodeError):
                    row[key[:-5]] = []
            result.append(row)
        return result
    finally:
        conn.close()


def identify_platforms(
    observations: dict[str, str],
    user: dict[str, Any],
    *,
    platform_code: str = "",
) -> dict[str, Any]:
    """Return ranked suggestions without mutating devices or storing output."""
    if not isinstance(observations, dict) or not observations:
        raise PlatformRegistryError("IDENTIFICATION_OUTPUT_REQUIRED", "At least one command observation is required")
    normalized_observations = {str(key).strip(): str(value or "") for key, value in observations.items() if str(key).strip()}
    conn = get_db_connection()
    try:
        tenant_id = str(user.get("tenant_id") or "")
        clauses = ["p.status <> 'ARCHIVED'"]
        params: list[Any] = []
        if user.get("role") != "Administrator" or tenant_id:
            clauses.append("(p.tenant_id IS NULL OR p.tenant_id = ?)")
            params.append(tenant_id)
        if platform_code:
            clauses.append("p.platform_code = ?")
            params.append(str(platform_code).strip().lower())
        rows = conn.execute(
            """SELECT p.id AS profile_id, p.platform_code, p.name_zh, p.name_en,
                      p.tenant_id, r.id AS rule_id, r.command, r.match_type,
                      r.pattern, r.logic_group, r.rule_order, r.confidence, r.negate
               FROM platform_profiles p
               JOIN platform_identification_rules r ON r.platform_profile_id = p.id AND r.enabled = 1
               WHERE """ + " AND ".join(clauses) + " ORDER BY p.platform_code, r.rule_order, r.id",
            params,
        ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for raw_row in rows:
            rule = _row_dict(raw_row) or {}
            profile_id = str(rule["profile_id"])
            item = grouped.setdefault(profile_id, {
                "platform_profile_id": profile_id,
                "platform_code": rule.get("platform_code"),
                "name_zh": rule.get("name_zh"),
                "name_en": rule.get("name_en"),
                "matched_rules": [],
                "_all": [],
                "_any": [],
            })
            matched = _match(rule, normalized_observations.get(str(rule.get("command") or "").strip(), ""))
            group = str(rule.get("logic_group") or "ALL").upper()
            (item["_any"] if group == "ANY" else item["_all"]).append(matched)
            if matched:
                item["matched_rules"].append({
                    "rule_id": rule.get("rule_id"),
                    "command": rule.get("command"),
                    "confidence": float(rule.get("confidence") or 0),
                    "rule_order": int(rule.get("rule_order") or 100),
                })
        suggestions: list[dict[str, Any]] = []
        for item in grouped.values():
            if item["_all"] and not all(item["_all"]):
                continue
            if item["_any"] and not any(item["_any"]):
                continue
            matched = item["matched_rules"]
            if not matched:
                continue
            score = round(sum(float(rule["confidence"]) for rule in matched), 4)
            result = {key: value for key, value in item.items() if not key.startswith("_")}
            result["score"] = score
            result["matched_rule_count"] = len(matched)
            suggestions.append(result)
        suggestions.sort(key=lambda value: (-float(value["score"]), str(value["platform_code"])))
        conflict = len(suggestions) > 1 and float(suggestions[0]["score"]) == float(suggestions[1]["score"])
        return {
            "success": not conflict,
            "status": "IDENTIFICATION_CONFLICT" if conflict else ("MATCHED" if suggestions else "NO_MATCH"),
            "suggestions": suggestions,
            "selected": None if conflict or not suggestions else suggestions[0],
        }
    finally:
        conn.close()


def identify_device(
    device_id: str,
    observations: dict[str, str],
    user: dict[str, Any],
    *,
    platform_code: str = "",
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        device = _assert_device_view(conn, device_id, user)
    finally:
        conn.close()
    result = identify_platforms(observations, user, platform_code=platform_code)
    _persist_identification_conflict(
        device_id,
        observations,
        result,
        user,
        tenant_id=str(device.get("tenant_id") or "") or None,
    )
    return result


def identify_device_live(device_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Collect only driver-provided identification commands in memory."""
    conn = get_db_connection()
    try:
        device_scope = _assert_device_view(conn, device_id, user)
    finally:
        conn.close()

    from services.connectivity_service import _build_device_info, _load_device

    device = _load_device(device_id)
    if not device:
        raise PlatformRegistryError("DEVICE_NOT_FOUND", "Device not found", status_code=404)
    # A bound device stores the tenant-facing platform code in
    # ``devices.platform``. Identification must use the immutable Profile
    # connection driver instead of treating that code as a command key.
    connection_driver = ""
    profile_id = str(device.get("platform_profile_id") or "").strip()
    if profile_id:
        profile_conn = get_db_connection()
        try:
            profile_row = profile_conn.execute(
                "SELECT connection_driver FROM platform_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
            connection_driver = str(profile_row[0] or "").strip().lower() if profile_row else ""
        finally:
            profile_conn.close()
    if not connection_driver:
        connection_driver = str(device.get("platform") or device.get("device_type") or "").strip().lower()
    connection_driver = _IDENTIFICATION_DRIVER_ALIASES.get(connection_driver, connection_driver)
    commands = IDENTIFICATION_COMMANDS.get(connection_driver)
    if not commands:
        raise PlatformRegistryError(
            "IDENTIFICATION_DRIVER_UNSUPPORTED",
            "The base connection driver has no approved identification command",
            status_code=409,
        )
    from services.automation_service import AutomationService

    connection_device = {**device, "platform": connection_driver, "device_type": connection_driver}
    results = AutomationService().execute_commands(_build_device_info(connection_device), list(commands), is_config=False)
    observations: dict[str, str] = {}
    for command, result in zip(commands, results or []):
        if not isinstance(result, dict) or not result.get("success"):
            raise PlatformRegistryError("IDENTIFICATION_COMMAND_FAILED", "Device identification command failed", status_code=502)
        output = str(result.get("output") or result.get("stdout") or "")
        if not output:
            raise PlatformRegistryError("IDENTIFICATION_OUTPUT_EMPTY", "Device identification returned no output", status_code=502)
        observations[command] = output
    if len(observations) != len(commands):
        raise PlatformRegistryError("IDENTIFICATION_COMMAND_FAILED", "Device identification command did not return a result", status_code=502)
    result = identify_platforms(observations, user)
    _persist_identification_conflict(
        device_id,
        observations,
        result,
        user,
        tenant_id=str(device_scope.get("tenant_id") or "") or None,
    )
    # Raw output stays in this process only; the API returns suggestions and
    # approved command names, never the device response itself.
    return {"device_id": device_id, "connection_driver": connection_driver, "commands": list(commands), **result}


def bind_device(device_id: str, platform_profile_id: str, user: dict[str, Any], *, lock: bool = False, force: bool = False) -> dict[str, Any]:
    if not platform_profile_id:
        raise PlatformRegistryError("PLATFORM_REQUIRED", "platform_profile_id is required")
    if force and user.get("role") != "Administrator":
        raise _scope_denied("PLATFORM_BIND_FORCE_FORBIDDEN")
    conn = get_db_connection()
    try:
        import database as database_module
        if database_module._USE_PG:
            conn.execute("SELECT id FROM platform_profiles WHERE id = ? FOR UPDATE", (platform_profile_id,)).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")
        profile = _assert_profile_access(conn, platform_profile_id, user)
        _assert_profile_active(profile)
        profile_tenant = str(profile.get("tenant_id") or "")
        user_tenant = str(user.get("tenant_id") or "")
        if profile_tenant and profile_tenant != user_tenant and user.get("role") != "Administrator":
            raise _scope_denied("PLATFORM_SCOPE_DENIED")
        device = _load_device(conn, device_id, user, lock=True)
        if device.get("platform_locked") and not force:
            raise PlatformRegistryError("PLATFORM_BINDING_LOCKED", "Device platform binding is locked", status_code=409)
        _assert_device_profile_platform(device, profile)
        conn.execute(
            """UPDATE devices SET platform_profile_id = ?, platform = ?, platform_source = ?,
                      platform_locked = ? WHERE id = ?""",
            (
                platform_profile_id,
                profile.get("parser_platform") or profile["platform_code"],
                "MANUAL",
                1 if lock else 0,
                device_id,
            ),
        )
        conn.execute(
            """UPDATE platform_identification_conflicts
               SET status = 'RESOLVED', resolved_profile_id = ?, resolved_by = ?,
                   resolution_reason = 'MANUAL_BINDING', resolved_at = ?, updated_at = ?
               WHERE device_id = ? AND status = 'OPEN'""",
            (
                platform_profile_id,
                str(user.get("id") or user.get("username") or ""),
                _now(),
                _now(),
                device_id,
            ),
        )
        conn.commit()
        result = _load_device(conn, device_id, user)
        result["compatibility"] = _binding_compatibility(device, profile)
        result["platform_profile"] = {
            "id": profile["id"],
            "platform_code": profile["platform_code"],
            "source": profile.get("source"),
        }
        return result
    except (PlatformRegistryError,):
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PLATFORM_BIND_FAILED", "Device platform binding failed") from exc
    finally:
        conn.close()


def bind_devices_batch(
    device_ids: list[str],
    platform_profile_id: str,
    user: dict[str, Any],
    *,
    lock: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Atomically bind a bounded device batch and return old/new scope details."""
    normalized_ids = [str(item or "").strip() for item in device_ids or []]
    if not normalized_ids or len(normalized_ids) > 200 or any(not item for item in normalized_ids):
        raise PlatformRegistryError("INVALID_DEVICE_BATCH", "device_ids must contain 1-200 non-empty values")
    if len(set(normalized_ids)) != len(normalized_ids):
        raise PlatformRegistryError("DUPLICATE_DEVICE_BATCH", "device_ids must not contain duplicates")
    if force and user.get("role") != "Administrator":
        raise _scope_denied("PLATFORM_BIND_FORCE_FORBIDDEN")

    conn = get_db_connection()
    try:
        profile = _assert_profile_access(conn, platform_profile_id, user)
        _assert_profile_active(profile)
        old_and_new: list[dict[str, Any]] = []
        for device_id in normalized_ids:
            device = _load_device(conn, device_id, user, lock=True)
            if device.get("platform_locked") and not force:
                raise PlatformRegistryError("PLATFORM_BINDING_LOCKED", f"Device {device_id} platform binding is locked", status_code=409)
            _assert_device_profile_platform(device, profile)
            old_and_new.append({
                "device": device,
                "compatibility": _binding_compatibility(device, profile),
            })

        for item in old_and_new:
            device = item["device"]
            conn.execute(
                """UPDATE devices SET platform_profile_id = ?, platform = ?, platform_source = ?,
                          platform_locked = ? WHERE id = ?""",
                (
                    platform_profile_id,
                    profile.get("parser_platform") or profile["platform_code"],
                    "MANUAL",
                    1 if lock else 0,
                    device["id"],
                ),
            )
            conn.execute(
                """UPDATE platform_identification_conflicts
                   SET status = 'RESOLVED', resolved_profile_id = ?, resolved_by = ?,
                       resolution_reason = 'MANUAL_BATCH_BINDING', resolved_at = ?, updated_at = ?
                   WHERE device_id = ? AND status = 'OPEN'""",
                (
                    platform_profile_id,
                    str(user.get("id") or user.get("username") or ""),
                    _now(),
                    _now(),
                    device["id"],
                ),
            )
        conn.commit()
        return {
            "success": True,
            "atomic": True,
            "device_count": len(old_and_new),
            "platform_profile_id": platform_profile_id,
            "platform_code": profile.get("platform_code"),
            "locked": bool(lock),
            "items": [
                {
                    "device_id": item["device"]["id"],
                    "hostname": item["device"].get("hostname") or "",
                    "old_platform": item["device"].get("platform") or "",
                    "new_platform": profile.get("platform_code") or "",
                    "old_platform_profile_id": item["device"].get("platform_profile_id"),
                    "compatibility": item["compatibility"],
                }
                for item in old_and_new
            ],
        }
    except PlatformRegistryError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise PlatformRegistryError("PLATFORM_BATCH_BIND_FAILED", "Batch platform binding failed") from exc
    finally:
        conn.close()
