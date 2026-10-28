"""Resolve Nexora devices to devices already managed by LibreNMS.

This module only reads the LibreNMS API and writes Nexora's local identity
mapping. It never scans networks or creates/removes devices in LibreNMS.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from core.crypto import decrypt_credential
from database import get_db_connection
from services.audit_service import log_audit_event
from services.librenms_runtime_client import LibreNMSAPIError, LibreNMSRuntimeClient

logger = logging.getLogger(__name__)


def _canonical_ip(value: Any) -> tuple[str, str] | None:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    return address.compressed.casefold(), "ipv4" if address.version == 4 else "ipv6"


def _flag_is_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _management_ip(device: Mapping[str, Any]) -> str:
    for key in ("_asset_management_ip", "management_ip", "ip_address"):
        value = str(device.get(key) or "").strip()
        if value:
            return value
    return ""


def _load_auto_binding_context(device_id: str, management_ip: str) -> dict[str, Any]:
    """Load canonical asset/tenant identity and reject duplicate local IPs."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT d.id, d.asset_id,
                   COALESCE(NULLIF(d.tenant_id, ''), NULLIF(s.tenant_id, ''), 'tenant-default') AS tenant_id,
                   COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''), '') AS site_id,
                   COALESCE(NULLIF(pa.management_ip, ''), NULLIF(d.ip_address, ''), '') AS management_ip
              FROM devices d
              JOIN physical_assets pa ON pa.id = d.asset_id
              LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
             WHERE COALESCE(NULLIF(pa.asset_type, ''), 'network_device') = 'network_device'
               AND (
                    LOWER(TRIM(COALESCE(pa.management_ip, ''))) = LOWER(TRIM(?))
                 OR LOWER(TRIM(COALESCE(d.ip_address, ''))) = LOWER(TRIM(?))
               )
             ORDER BY d.id
             LIMIT 3
            """,
            (management_ip, management_ip),
        ).fetchall()
        candidates = [dict(row) for row in rows]
        if len(candidates) != 1 or str(candidates[0].get("id") or "") != device_id:
            return {"status": "ambiguous", "message": "CMDB 中该管理 IP 未唯一对应一个网络设备，已跳过自动关联"}

        target = candidates[0]
        if not str(target.get("asset_id") or "").strip():
            return {"status": "not_eligible", "message": "该 CMDB 设备尚未关联资产，无法自动关联 LibreNMS"}
        return {"status": "ready", **target}
    finally:
        conn.close()


def _load_enabled_instances() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT i.id, i.display_name, i.base_url, i.health_state,
                       i.engine_version, i.engine_commit,
                       c.credential_type, c.encrypted_password
                  FROM librenms_instances i
                  LEFT JOIN credentials c ON c.id = i.token_credential_id
                 WHERE i.enabled = TRUE
                 ORDER BY i.id
                """
            ).fetchall()
        ]
    finally:
        conn.close()


async def _instance_matches(instance: Mapping[str, Any], canonical_ip: str, address_type: str) -> list[dict[str, Any]]:
    encrypted = str(instance.get("encrypted_password") or "")
    try:
        token = decrypt_credential(encrypted) or ""
    except Exception as exc:
        logger.warning("LibreNMS auto-binding credential could not be decrypted: %s", type(exc).__name__)
        token = ""
    if not token:
        raise LibreNMSAPIError("credential_unavailable")

    async with LibreNMSRuntimeClient(str(instance.get("base_url") or ""), token) as client:
        devices = await client.get_devices(device_type=address_type, query=canonical_ip, max_rows=200)
        if len(devices) >= 200:
            raise LibreNMSAPIError("device_search_too_broad")

        matches: list[dict[str, Any]] = []
        matched_ids: set[str] = set()

        async def add_exact_matches(rows: list[dict[str, Any]], *, hostname_only: bool = False) -> None:
            for native_device in rows:
                native_id = str(native_device.get("device_id") or "").strip()
                if (
                    not native_id
                    or native_id in matched_ids
                    or _flag_is_true(native_device.get("disabled"))
                    or _flag_is_true(native_device.get("ignore"))
                ):
                    continue

                native_hostname = str(native_device.get("hostname") or "").strip()
                hostname_match = (
                    (normalized_hostname := _canonical_ip(native_hostname)) is not None
                    and normalized_hostname[0] == canonical_ip
                )
                exact_address_match = False
                if hostname_match:
                    exact_address_match = True
                elif not hostname_only:
                    native_addresses = await client.get_device_ip_addresses(native_id)
                    address_values = [
                        row.get("ipv4_address") if address_type == "ipv4" else row.get("ipv6_address")
                        for row in native_addresses
                    ]
                    exact_address_match = any(
                        (normalized := _canonical_ip(value)) is not None and normalized[0] == canonical_ip
                        for value in address_values
                    )

                if not exact_address_match:
                    continue
                matched_ids.add(native_id)
                matches.append({
                    "native_device_id": native_id,
                    "native_hostname": native_hostname,
                    "poller_group": str(native_device.get("poller_group") or ""),
                    "instance_id": str(instance.get("id") or ""),
                    "instance_name": str(instance.get("display_name") or ""),
                    "base_url": str(instance.get("base_url") or ""),
                    "engine_version": str(instance.get("engine_version") or ""),
                    "engine_commit": str(instance.get("engine_commit") or ""),
                })

        await add_exact_matches(devices)

        # LibreNMS type=ipv4/ipv6 filters on discovered port addresses. A new
        # device whose hostname is its management IP may not have port IP rows
        # until its first discovery, so search the hostname field as a fallback.
        if not matches:
            hostname_devices = await client.get_devices(
                device_type="hostname",
                query=canonical_ip,
                max_rows=200,
            )
            if len(hostname_devices) >= 200:
                raise LibreNMSAPIError("device_search_too_broad")
            await add_exact_matches(hostname_devices, hostname_only=True)

        return matches


def preflight_auto_binding(target: Mapping[str, Any], match: Mapping[str, Any]) -> dict[str, str]:
    """Check local binding conflicts before mutating a LibreNMS device profile."""
    conn = get_db_connection()
    try:
        current = conn.execute(
            """
            SELECT instance_id, librenms_device_id, desired_state
              FROM librenms_device_bindings
             WHERE device_id = ?
             LIMIT 1
            """,
            (target.get("id"),),
        ).fetchone()
        if current:
            same_target = (
                str(current["instance_id"] or "") == str(match.get("instance_id") or "")
                and str(current["librenms_device_id"] or "") == str(match.get("native_device_id") or "")
                and str(current["desired_state"] or "").casefold() == "enabled"
            )
            if not same_target:
                return {"status": "conflict"}

        native_binding = conn.execute(
            """
            SELECT device_id
              FROM librenms_device_bindings
             WHERE instance_id = ? AND librenms_device_id = ?
             LIMIT 1
            """,
            (match.get("instance_id"), match.get("native_device_id")),
        ).fetchone()
        if native_binding and str(native_binding["device_id"] or "") != str(target.get("id") or ""):
            return {"status": "conflict"}
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("LibreNMS binding preflight failed: %s", type(exc).__name__)
        return {"status": "lookup_unavailable"}
    finally:
        conn.close()

def _persist_auto_binding(target: Mapping[str, Any], match: Mapping[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    binding_id = f"lnmb-{uuid.uuid4().hex[:16]}"
    conn = get_db_connection()
    try:
        inserted = conn.execute(
            """
            INSERT INTO librenms_device_bindings
                (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id,
                 librenms_hostname, collector_id, poller_group, desired_state, sync_status,
                 last_sync_at, last_error_code, last_error_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, 'enabled', 'pending', NULL, '', '', ?, ?)
            ON CONFLICT DO NOTHING
            RETURNING id, tenant_id, asset_id, device_id, instance_id,
                      librenms_device_id, librenms_hostname, collector_id, poller_group,
                      desired_state, sync_status, last_sync_at, last_error_code
            """,
            (
                binding_id, target["tenant_id"], target["asset_id"], target["id"],
                match["instance_id"], match["native_device_id"], match.get("native_hostname") or "",
                match.get("poller_group") or "", now, now,
            ),
        ).fetchone()
        if inserted:
            row = dict(inserted)
            log_audit_event(
                event_type="librenms.binding.auto",
                category="integration",
                severity="medium",
                status="success",
                summary=f"Automatically matched asset {target['asset_id']} to a LibreNMS device",
                actor_username="system",
                actor_role="System",
                target_type="librenms_binding",
                target_id=str(row["id"]),
                device_id=str(target["id"]),
                details={
                    "asset_id": str(target["asset_id"]),
                    "instance_id": str(match["instance_id"]),
                    "native_device_id": str(match["native_device_id"]),
                    "match_method": "unique_management_ip",
                },
                conn=conn,
            )
            conn.commit()
            return {"status": "bound", "binding": row, "message": "已按唯一管理 IP 自动关联 LibreNMS 设备"}

        existing = conn.execute(
            """
            SELECT id, instance_id, librenms_device_id, desired_state
              FROM librenms_device_bindings
             WHERE device_id = ?
             LIMIT 1
            """,
            (target["id"],),
        ).fetchone()
        if existing:
            row = dict(existing)
            same_target = (
                str(row.get("instance_id") or "") == str(match.get("instance_id") or "")
                and str(row.get("librenms_device_id") or "") == str(match.get("native_device_id") or "")
                and str(row.get("desired_state") or "").casefold() == "enabled"
            )
            conn.rollback()
            if same_target:
                return {"status": "already_bound", "message": "该设备已关联到匹配的 LibreNMS 原生设备"}
            return {"status": "conflict", "message": "该 CMDB 设备已有不同的 LibreNMS 关联，自动匹配未覆盖现有关联"}

        conn.rollback()
        return {"status": "conflict", "message": "该 LibreNMS 原生设备已关联到另一台 CMDB 设备，自动匹配未覆盖现有关联"}
    except Exception as exc:
        conn.rollback()
        logger.warning("LibreNMS auto-binding persistence failed: %s", type(exc).__name__)
        return {"status": "conflict", "message": "LibreNMS 自动关联保存失败，现有关联保持不变"}
    finally:
        conn.close()


async def auto_bind_device_by_management_ip(device: Mapping[str, Any]) -> dict[str, Any]:
    """Create a local binding only for one exact, unambiguous management IP."""
    device_id = str(device.get("id") or "").strip()
    if not device_id:
        return {"status": "not_eligible", "message": "当前选择不是带有设备 ID 的 CMDB 网络设备"}

    parsed_ip = _canonical_ip(_management_ip(device))
    if parsed_ip is None:
        return {"status": "missing_ip", "message": "CMDB 未提供有效管理 IP，无法自动关联 LibreNMS"}
    canonical_ip, address_type = parsed_ip

    try:
        target = _load_auto_binding_context(device_id, canonical_ip)
    except Exception as exc:
        logger.warning("LibreNMS auto-binding CMDB lookup failed: %s", type(exc).__name__)
        return {"status": "lookup_unavailable", "message": "CMDB 设备身份暂不可用，无法自动关联 LibreNMS"}
    if target.get("status") != "ready":
        return target

    try:
        instances = _load_enabled_instances()
    except Exception as exc:
        logger.warning("LibreNMS auto-binding instance lookup failed: %s", type(exc).__name__)
        return {"status": "lookup_unavailable", "message": "LibreNMS 实例配置暂不可用，无法自动关联"}
    if not instances:
        return {"status": "instance_not_configured", "message": "尚未在 Nexora 配置并启用 LibreNMS 实例；请先由管理员配置实例 API 地址和 Token"}

    candidates: list[dict[str, Any]] = []
    for instance in instances:
        if str(instance.get("health_state") or "").casefold() != "healthy":
            return {"status": "instance_unavailable", "message": "有已启用的 LibreNMS 实例健康检查未通过，无法安全完成唯一匹配"}
        if str(instance.get("credential_type") or "").casefold() != "api_token":
            return {"status": "instance_unavailable", "message": "已启用的 LibreNMS 实例缺少有效 API Token 凭据"}
        try:
            candidates.extend(await _instance_matches(instance, canonical_ip, address_type))
        except LibreNMSAPIError as exc:
            logger.warning("LibreNMS auto-binding lookup failed with code %s", exc.code)
            return {"status": "instance_unavailable", "message": "无法通过 LibreNMS API 确认设备地址，请检查实例连接和只读 API 权限"}
        except Exception as exc:
            logger.warning("LibreNMS auto-binding request failed: %s", type(exc).__name__)
            return {"status": "instance_unavailable", "message": "无法通过 LibreNMS API 确认设备地址，请检查实例连接和只读 API 权限"}

    # The same native ID returned by duplicate search rows is one candidate.
    unique_candidates = {
        (str(item.get("instance_id") or ""), str(item.get("native_device_id") or "")): item
        for item in candidates
    }
    if not unique_candidates:
        return {
            "status": "not_discovered",
            "message": "LibreNMS 尚未自动发现或添加该设备。请检查 LibreNMS 的 SNMP 凭据、允许网段和自动发现设置；本页不会主动扫描或添加设备。",
        }
    if len(unique_candidates) != 1:
        return {"status": "ambiguous", "message": "多个 LibreNMS 原生设备与该管理 IP 匹配，已跳过自动关联"}

    match = next(iter(unique_candidates.values()))
    return _persist_auto_binding(target, match)


__all__ = ["auto_bind_device_by_management_ip"]
