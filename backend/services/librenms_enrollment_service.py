"""Enroll imported CMDB network devices in LibreNMS with their assigned profile.

LibreNMS remains the only SNMP discovery and hardware-polling engine. This
module only sends the device identity and configured SNMP credentials to the
documented LibreNMS add-device API, then verifies the returned native device by
its exact management IP before creating Nexora's local binding.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from core.crypto import decrypt_credential
from database import get_db_connection
from services.audit_service import log_audit_event
from services.librenms_binding_service import (
    _canonical_ip,
    _flag_is_true,
    _load_auto_binding_context,
    _load_enabled_instances,
    _instance_matches,
    _persist_auto_binding,
    preflight_auto_binding,
)
from services.librenms_runtime_client import LibreNMSAPIError, LibreNMSRuntimeClient

logger = logging.getLogger(__name__)


def _load_asset_enrollment_context(device_id: str) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT d.id, d.asset_id,
                   COALESCE(NULLIF(pa.management_ip, ''), NULLIF(d.ip_address, ''), '') AS management_ip,
                   COALESCE(NULLIF(pa.snmp_port, 0), 161) AS snmp_port,
                   COALESCE(NULLIF(pa.snmp_credential_id, ''), NULLIF(d.snmp_credential_id, ''), '') AS snmp_credential_id,
                   pa.asset_type, pa.snmp_community AS asset_snmp_community,
                   c.credential_type, c.username, c.snmp_community,
                   c.snmp_security_level, c.snmp_auth_protocol, c.snmp_auth_password,
                   c.snmp_priv_protocol, c.snmp_priv_password, c.snmp_context_name
              FROM devices d
              JOIN physical_assets pa ON pa.id = d.asset_id
              LEFT JOIN credentials c
                ON c.id = COALESCE(NULLIF(pa.snmp_credential_id, ''), NULLIF(d.snmp_credential_id, ''))
             WHERE d.id = ?
             LIMIT 1
            """,
            (device_id,),
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def _snmp_parameters(target: Mapping[str, Any]) -> tuple[dict[str, str], str]:
    """Convert a selected credential row into LibreNMS API fields.

    Secret values are returned only to the in-process API caller. They must
    never be written to logs, audit details, or API responses.
    """
    credential_type = str(target.get("credential_type") or "").strip().casefold()
    if credential_type == "snmpv2":
        raw_community = str(target.get("snmp_community") or "")
        community = decrypt_credential(raw_community)
        if community is None:
            return {}, "snmp_community_unavailable"
        if not str(community).strip():
            return {}, "snmp_community_missing"
        return {"snmpver": "v2c", "community": str(community)}, ""

    if credential_type != "snmpv3":
        if str(target.get("snmp_credential_id") or "").strip():
            # A selected vault profile must never silently fall back to a
            # legacy community when its credential row is missing or invalid.
            return {}, "snmp_profile_unavailable"
        raw_community = str(target.get("asset_snmp_community") or "")
        community = decrypt_credential(raw_community)
        if community is None:
            return {}, "snmp_community_unavailable"
        if str(community).strip():
            return {"snmpver": "v2c", "community": str(community)}, ""
        return {}, "snmp_profile_missing"

    username = str(target.get("username") or "").strip()
    raw_level = str(target.get("snmp_security_level") or "authPriv").strip().casefold()
    levels = {
        "noauthnopriv": "noAuthNoPriv",
        "authnopriv": "authNoPriv",
        "authpriv": "authPriv",
    }
    auth_level = levels.get(raw_level)
    if not username or not auth_level:
        return {}, "snmpv3_profile_invalid"
    if str(target.get("snmp_context_name") or "").strip():
        # The documented add-device endpoint has no context-name field. Do not
        # silently create a device with different SNMP semantics.
        return {}, "snmpv3_context_unsupported"

    parameters = {
        "snmpver": "v3",
        "authlevel": auth_level,
        "authname": username,
    }
    if raw_level != "noauthnopriv":
        auth_password = decrypt_credential(str(target.get("snmp_auth_password") or "")) or ""
        if not auth_password:
            return {}, "snmpv3_auth_password_missing"
        parameters["authpass"] = auth_password
        auth_algorithms = {
            "md5": "MD5",
            "sha": "SHA",
            "sha-224": "SHA-224",
            "sha-256": "SHA-256",
            "sha-384": "SHA-384",
            "sha-512": "SHA-512",
        }
        auth_algorithm = auth_algorithms.get(str(target.get("snmp_auth_protocol") or "SHA").strip().casefold())
        if not auth_algorithm:
            return {}, "snmpv3_auth_algorithm_unsupported"
        parameters["authalgo"] = auth_algorithm
    if raw_level == "authpriv":
        priv_password = decrypt_credential(str(target.get("snmp_priv_password") or "")) or ""
        if not priv_password:
            return {}, "snmpv3_priv_password_missing"
        parameters["cryptopass"] = priv_password
        privacy_algorithms = {"aes": "AES", "des": "DES"}
        privacy_algorithm = privacy_algorithms.get(str(target.get("snmp_priv_protocol") or "AES").strip().casefold())
        if not privacy_algorithm:
            return {}, "snmpv3_priv_algorithm_unsupported"
        parameters["cryptoalgo"] = privacy_algorithm
    return parameters, ""


def _match_from_add_response(
    instance: Mapping[str, Any],
    response: Mapping[str, Any] | None,
    canonical_ip: str,
) -> list[dict[str, Any]]:
    """Use the native ID returned by LibreNMS when it confirms our exact hostname."""
    if not isinstance(response, Mapping) or str(response.get("status") or "").casefold() != "ok":
        return []
    rows = response.get("devices")
    if not isinstance(rows, list):
        device = response.get("device")
        rows = [device] if isinstance(device, Mapping) else []

    matches: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if _flag_is_true(row.get("disabled")) or _flag_is_true(row.get("ignore")):
            continue
        native_id = str(row.get("device_id") or "").strip()
        native_hostname = str(row.get("hostname") or "").strip()
        parsed_hostname = _canonical_ip(native_hostname)
        if not native_id.isdigit() or parsed_hostname is None or parsed_hostname[0] != canonical_ip:
            continue
        matches.append({
            "native_device_id": native_id,
            "native_hostname": native_hostname,
            "poller_group": str(row.get("poller_group") or ""),
            "instance_id": str(instance.get("id") or ""),
            "instance_name": str(instance.get("display_name") or ""),
            "base_url": str(instance.get("base_url") or ""),
            "engine_version": str(instance.get("engine_version") or ""),
            "engine_commit": str(instance.get("engine_commit") or ""),
        })
    return matches


async def _apply_profile_with_retry(
    client: LibreNMSRuntimeClient,
    *,
    native_device_id: str,
    snmp_parameters: Mapping[str, str],
    port: int,
) -> None:
    """Retry an idempotent field update once when its response is uncertain."""
    for attempt in range(2):
        try:
            await client.update_device_snmp_profile(
                native_device_id=native_device_id,
                snmp_parameters=snmp_parameters,
                port=port,
            )
            return
        except LibreNMSAPIError as exc:
            retryable = exc.code in {"timeout", "unreachable"} or (exc.http_status or 0) >= 500
            if attempt == 0 and retryable:
                continue
            raise


def _audit_enrollment(
    *,
    target: Mapping[str, Any],
    actor: Mapping[str, Any] | None,
    status: str,
    reason: str,
    instance_id: str = "",
) -> None:
    try:
        log_audit_event(
            event_type="librenms.device.enrollment",
            category="integration",
            severity="medium",
            status=status,
            summary=f"LibreNMS device enrollment {status} for CMDB device {target.get('id') or ''}",
            actor_username=str((actor or {}).get("username") or "system"),
            actor_role=str((actor or {}).get("role") or "System"),
            target_type="device",
            target_id=str(target.get("id") or ""),
            device_id=str(target.get("id") or ""),
            details={
                "asset_id": str(target.get("asset_id") or ""),
                "instance_id": instance_id,
                "reason": reason,
                "profile_type": str(target.get("credential_type") or ""),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LibreNMS enrollment audit write failed: %s", type(exc).__name__)


def _error_result(code: str) -> dict[str, str]:
    messages = {
        "instance_not_configured": "尚未配置并启用 LibreNMS 实例",
        "instance_unavailable": "LibreNMS 实例或 API Token 不可用",
        "multiple_instances": "启用了多个 LibreNMS 实例，无法判断应纳管到哪一个",
        "not_eligible": "该资产不是可自动纳管的网络设备，或缺少有效管理 IP",
        "snmp_profile_missing": "未为该设备选择有效的 SNMP 凭据 Profile",
        "snmp_profile_unavailable": "资产引用的 SNMP 凭据 Profile 不存在或不可读取；未回退到旧凭据",
        "snmp_community_missing": "所选 SNMPv2 Profile 未配置 Community",
        "snmp_community_unavailable": "SNMP Community 无法解密，请检查加密密钥或重新保存凭据",
        "snmpv3_profile_invalid": "所选 SNMPv3 Profile 缺少有效用户名或安全级别",
        "snmpv3_context_unsupported": "当前 LibreNMS 添加设备 API 不支持该 SNMPv3 Profile 的 Context Name",
        "snmpv3_auth_password_missing": "所选 SNMPv3 Profile 缺少认证密码",
        "snmpv3_priv_password_missing": "所选 SNMPv3 Profile 缺少加密密码",
        "snmpv3_auth_algorithm_unsupported": "所选 SNMPv3 认证算法不受 LibreNMS 支持",
        "snmpv3_priv_algorithm_unsupported": "所选 SNMPv3 加密算法不受 LibreNMS 添加设备 API 支持",
        "api_permission_denied": "LibreNMS API Token 没有添加设备权限",
        "remote_rejected": "LibreNMS 拒绝了添加请求；未建立绑定，请检查设备状态、API 参数和 SNMP Profile",
        "profile_update_permission_denied": "LibreNMS API Token 没有修改设备 SNMP 配置的权限",
        "profile_update_failed": "未能将资产选择的 SNMP Profile 写入 LibreNMS 设备配置，未确认纳管成功",
        "profile_update_uncertain": "LibreNMS Profile 更新请求超时，无法确认是否生效；未建立绑定，重试时会先重新查找设备",
        "binding_lookup_failed": "无法核对现有 LibreNMS 本地绑定，未修改远端设备 Profile",
        "snmp_rejected": "LibreNMS 无法通过该 SNMP Profile 验证设备；请检查版本、凭据、端口和设备 ACL",
        "address_unverified": "LibreNMS 添加请求结果不确定，暂未建立绑定；请等待 LibreNMS 完成一轮 Discovery 后再重试，避免重复添加",
        "ambiguous": "存在多个匹配的 LibreNMS 原生设备，未建立绑定",
        "conflict": "CMDB 或 LibreNMS 设备已有冲突关联，未覆盖现有关联",
        "api_failed": "LibreNMS 添加设备失败；CMDB 资产已保留，可重新导入该行重试",
    }
    return {"status": code, "message": messages.get(code, "LibreNMS 自动纳管失败；CMDB 资产已保留，可重试")}


async def enroll_imported_network_device(
    device_id: str,
    *,
    actor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure an imported network asset exists in LibreNMS and bind it locally.

    Match on exact management IP. Existing native devices receive the selected
    asset SNMP profile through LibreNMS' documented device-field API before the
    local binding is persisted. New devices use the documented add-device API.
    OS detection, discovery, polling, and hardware sampling remain native to
    LibreNMS.
    """
    target = _load_asset_enrollment_context(str(device_id or "").strip())
    if not target or str(target.get("asset_type") or "") != "network_device":
        result = _error_result("not_eligible")
        _audit_enrollment(target=target, actor=actor, status="blocked", reason=result["status"])
        return result

    parsed_ip = _canonical_ip(target.get("management_ip"))
    if parsed_ip is None:
        result = _error_result("not_eligible")
        _audit_enrollment(target=target, actor=actor, status="blocked", reason=result["status"])
        return result
    canonical_ip, _address_type = parsed_ip
    context = _load_auto_binding_context(str(target["id"]), canonical_ip)
    if context.get("status") != "ready":
        result = _error_result("not_eligible")
        _audit_enrollment(target=target, actor=actor, status="blocked", reason=str(context.get("status") or result["status"]))
        return result

    parameters, profile_error = _snmp_parameters(target)
    if profile_error:
        result = _error_result(profile_error)
        _audit_enrollment(target=target, actor=actor, status="blocked", reason=profile_error)
        return result

    try:
        instances = _load_enabled_instances()
    except Exception as exc:  # noqa: BLE001
        logger.warning("LibreNMS enrollment instance lookup failed: %s", type(exc).__name__)
        result = _error_result("instance_unavailable")
        _audit_enrollment(target=target, actor=actor, status="failed", reason="instance_lookup_failed")
        return result
    if not instances:
        result = _error_result("instance_not_configured")
        _audit_enrollment(target=target, actor=actor, status="blocked", reason=result["status"])
        return result
    prepared_instances: list[dict[str, Any]] = []
    for instance in instances:
        instance_id = str(instance.get("id") or "")
        if str(instance.get("health_state") or "").casefold() != "healthy":
            result = _error_result("instance_unavailable")
            _audit_enrollment(target=target, actor=actor, status="failed", reason="instance_unhealthy", instance_id=instance_id)
            return result
        if str(instance.get("credential_type") or "").casefold() != "api_token":
            result = _error_result("instance_unavailable")
            _audit_enrollment(target=target, actor=actor, status="failed", reason="api_token_unavailable", instance_id=instance_id)
            return result
        try:
            token = decrypt_credential(str(instance.get("encrypted_password") or "")) or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("LibreNMS enrollment API token could not be decrypted: %s", type(exc).__name__)
            token = ""
        if not token:
            result = _error_result("instance_unavailable")
            _audit_enrollment(target=target, actor=actor, status="failed", reason="api_token_unavailable", instance_id=instance_id)
            return result
        prepared_instances.append({**instance, "_api_token": token})

    async def _find_exact_matches() -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for instance in prepared_instances:
            matches.extend(await _instance_matches(instance, canonical_ip, _address_type))
        return list({
            (str(item.get("instance_id") or ""), str(item.get("native_device_id") or "")): item
            for item in matches
        }.values())

    def _failed_result(code: str, *, instance_id: str = "", audit_status: str = "failed") -> dict[str, Any]:
        result = _error_result(code)
        _audit_enrollment(target=target, actor=actor, status=audit_status, reason=code, instance_id=instance_id)
        return result

    try:
        candidates = await _find_exact_matches()
    except LibreNMSAPIError as exc:
        logger.warning("LibreNMS enrollment identity lookup failed with code %s", exc.code)
        return _failed_result("instance_unavailable")
    except Exception as exc:  # noqa: BLE001
        logger.warning("LibreNMS enrollment identity lookup failed: %s", type(exc).__name__)
        return _failed_result("instance_unavailable")

    if len(candidates) > 1:
        return _failed_result("ambiguous", audit_status="conflict")

    try:
        port = int(target.get("snmp_port") or 161)
    except (TypeError, ValueError):
        return _failed_result("not_eligible", audit_status="blocked")

    if candidates:
        match = candidates[0]
        instance_id = str(match.get("instance_id") or "")
        instance = next((item for item in prepared_instances if str(item.get("id") or "") == instance_id), None)
        if instance is None:
            return _failed_result("instance_unavailable", instance_id=instance_id)
        preflight = preflight_auto_binding(context, match)
        if preflight.get("status") != "ready":
            code = "conflict" if preflight.get("status") == "conflict" else "binding_lookup_failed"
            return _failed_result(code, instance_id=instance_id, audit_status="conflict")
        try:
            async with LibreNMSRuntimeClient(str(instance.get("base_url") or ""), instance["_api_token"]) as client:
                await _apply_profile_with_retry(
                    client,
                    native_device_id=str(match.get("native_device_id") or ""),
                    snmp_parameters=parameters,
                    port=port,
                )
        except LibreNMSAPIError as exc:
            logger.warning("LibreNMS device profile update failed with code %s", exc.code)
            if exc.http_status == 403:
                code = "profile_update_permission_denied"
            elif exc.http_status == 401:
                code = "instance_unavailable"
            elif exc.code in {"timeout", "unreachable"} or (exc.http_status or 0) >= 500:
                code = "profile_update_uncertain"
            else:
                code = "profile_update_failed"
            return _failed_result(code, instance_id=instance_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LibreNMS device profile update failed: %s", type(exc).__name__)
            return _failed_result("profile_update_failed", instance_id=instance_id)

        binding = _persist_auto_binding(context, match)
        if binding.get("status") not in {"bound", "already_bound"}:
            return _failed_result(str(binding.get("status") or "conflict"), instance_id=instance_id, audit_status="conflict")
        status = "profile_updated_and_bound"
        _audit_enrollment(target=target, actor=actor, status="success", reason=status, instance_id=instance_id)
        return {
            "status": status,
            "message": "已按管理 IP 精确匹配 LibreNMS 设备，并将所选 SNMP Profile 写入其原生配置；OS 识别、Discovery 与 Poller 由 LibreNMS 执行",
            "binding": binding.get("binding"),
            "profile_applied": True,
        }

    if len(prepared_instances) != 1:
        return _failed_result("multiple_instances", audit_status="blocked")

    instance = prepared_instances[0]
    instance_id = str(instance.get("id") or "")
    failure_code = ""
    uncertain_request_outcome = False
    add_response: dict[str, Any] | None = None
    add_response_matches: list[dict[str, Any]] = []
    try:
        async with LibreNMSRuntimeClient(str(instance.get("base_url") or ""), instance["_api_token"]) as client:
            add_response = await client.add_device(hostname=canonical_ip, snmp_parameters=parameters, port=port)
        add_response_matches = _match_from_add_response(instance, add_response, canonical_ip)
    except LibreNMSAPIError as exc:
        logger.warning("LibreNMS enrollment request failed with code %s", exc.code)
        if exc.http_status == 403:
            failure_code = "api_permission_denied"
        elif exc.http_status == 401:
            failure_code = "instance_unavailable"
        elif exc.http_status in {400, 422} or exc.code == "upstream_error":
            failure_code = "remote_rejected"
        elif exc.code in {"timeout", "unreachable"} or (exc.http_status or 0) >= 500:
            failure_code = "address_unverified"
            uncertain_request_outcome = True
        else:
            failure_code = "api_failed"
    except Exception as exc:  # noqa: BLE001
        logger.warning("LibreNMS enrollment request failed: %s", type(exc).__name__)
        failure_code = "address_unverified"
        uncertain_request_outcome = True

    # A timeout or duplicate response may mean LibreNMS accepted a prior
    # request. Re-query the exact IP before returning a failure or retrying.
    try:
        candidates = await _find_exact_matches()
    except Exception as exc:  # noqa: BLE001
        logger.warning("LibreNMS enrollment verification failed: %s", type(exc).__name__)
        candidates = []
        if not add_response_matches and (not failure_code or uncertain_request_outcome):
            failure_code = "address_unverified"

    # The add-device API response already carries the native device ID and
    # hostname. When it confirms the exact IP used in the request, use that
    # identity even if the ports/IP index has not been populated by discovery.
    candidates.extend(add_response_matches)
    candidates = list({
        (str(item.get("instance_id") or ""), str(item.get("native_device_id") or "")): item
        for item in candidates
    }.values())

    if len(candidates) > 1:
        return _failed_result("ambiguous", instance_id=instance_id, audit_status="conflict")
    if candidates:
        match = candidates[0]
        preflight = preflight_auto_binding(context, match)
        if preflight.get("status") != "ready":
            code = "conflict" if preflight.get("status") == "conflict" else "binding_lookup_failed"
            return _failed_result(code, instance_id=instance_id, audit_status="conflict")
        # A read-back after an uncertain POST can safely recover a request
        # whose response was lost. A definite LibreNMS rejection (for example
        # bad SNMP credentials or missing API permission) must never be
        # converted into success just because an address match appeared.
        if failure_code and not uncertain_request_outcome:
            return _failed_result(failure_code, instance_id=instance_id)
        if uncertain_request_outcome:
            try:
                async with LibreNMSRuntimeClient(str(instance.get("base_url") or ""), instance["_api_token"]) as client:
                    await _apply_profile_with_retry(
                        client,
                        native_device_id=str(match.get("native_device_id") or ""),
                        snmp_parameters=parameters,
                        port=port,
                    )
            except LibreNMSAPIError as exc:
                logger.warning("LibreNMS retry profile update failed with code %s", exc.code)
                if exc.http_status == 403:
                    code = "profile_update_permission_denied"
                elif exc.http_status == 401:
                    code = "instance_unavailable"
                elif exc.code in {"timeout", "unreachable"} or (exc.http_status or 0) >= 500:
                    code = "profile_update_uncertain"
                else:
                    code = "profile_update_failed"
                return _failed_result(code, instance_id=instance_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LibreNMS retry profile update failed: %s", type(exc).__name__)
                return _failed_result("profile_update_failed", instance_id=instance_id)

        binding = _persist_auto_binding(context, match)
        if binding.get("status") not in {"bound", "already_bound"}:
            return _failed_result(str(binding.get("status") or "conflict"), instance_id=instance_id, audit_status="conflict")
        status = "added_and_bound" if not failure_code else "profile_updated_after_retry_and_bound"
        _audit_enrollment(target=target, actor=actor, status="success", reason=status, instance_id=instance_id)
        return {
            "status": status,
            "message": "已使用该设备的 SNMP Profile 添加并精确关联到 LibreNMS；后续 OS 识别、Discovery、Poller 与硬件采集由 LibreNMS 原生执行",
            "binding": binding.get("binding"),
            "profile_applied": True,
        }

    if failure_code:
        return _failed_result(failure_code, instance_id=instance_id)
    return _failed_result("address_unverified", instance_id=instance_id)


__all__ = ["enroll_imported_network_device"]
