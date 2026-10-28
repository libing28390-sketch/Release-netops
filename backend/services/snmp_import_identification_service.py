"""SNMP identity detection performed after asset import."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from core.crypto import decrypt_credential
from database import get_db_connection
from services.config_vendor_platform_service import (
    VENDOR_PLATFORM_CATALOG,
    canonical_vendor,
    validate_vendor_platform,
)
from services.librenms_rule_service import ensure_rules_available, resolve_rule
from services.snmp_discovery_service import normalize_model_name, resolve_snmp_vendor_identity

logger = logging.getLogger(__name__)

IDENTITY_OIDS = {
    "sys_object_id": "1.3.6.1.2.1.1.2.0",
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
}

_SNMPV3_AUTH_METHODS = {
    "md5": "md5",
    "sha": "sha1",
    "sha1": "sha1",
    "sha-1": "sha1",
    "sha224": "sha224",
    "sha-224": "sha224",
    "sha256": "sha256",
    "sha-256": "sha256",
    "sha384": "sha384",
    "sha-384": "sha384",
    "sha512": "sha512",
    "sha-512": "sha512",
}
_SNMPV3_PRIV_METHODS = {"aes": "aes", "aes-128": "aes", "des": "des"}
_PLATFORM_FAMILY_ALIASES = {
    "huawei": {
        "huawei": "huawei_vrp",
        "vrp": "huawei_vrp",
        "yunshan": "huawei_yunshan",
        "huawei_yunshan": "huawei_yunshan",
        "smartax": "huawei_smartax",
        "usg": "huawei_usg",
    },
    "h3c": {"h3c": "h3c_comware", "comware": "h3c_comware", "hp": "h3c_comware"},
    "cisco": {
        "cisco": "cisco_ios",
        "ios": "cisco_ios",
        "iosxe": "cisco_iosxe",
        "ios_xe": "cisco_iosxe",
        "iosxr": "cisco_iosxr",
        "ios_xr": "cisco_iosxr",
        "nxos": "cisco_nxos",
        "nexus": "cisco_nxos",
        "asa": "cisco_asa",
    },
    "arista": {"arista": "arista_eos", "eos": "arista_eos"},
    "juniper": {"juniper": "juniper_junos", "junos": "juniper_junos"},
    "ruijie": {"ruijie": "ruijie_rgos", "rgos": "ruijie_rgos"},
    "zte": {"zte": "zte_zxros", "zxros": "zte_zxros"},
    "palo alto": {"paloalto": "paloalto_panos", "panos": "paloalto_panos"},
}


def _canonical_detected_platform(vendor: str, platform: Any) -> str:
    """Translate common LibreNMS OS-family values to Nexora platform keys."""
    vendor_name = canonical_vendor(vendor)
    raw = str(platform or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = _PLATFORM_FAMILY_ALIASES.get(vendor_name.casefold(), {})
    candidate = aliases.get(raw, raw)
    allowed = VENDOR_PLATFORM_CATALOG.get(vendor_name, ())
    if candidate in allowed:
        return candidate
    if raw:
        # LibreNMS may store a vendor's generic OS key instead of the CLI
        # dialect. Use the first registered platform only for these known
        # generic keys; never invent a platform for an unrelated vendor.
        generic = aliases.get(raw)
        if generic in allowed:
            return generic
    try:
        _canonical, default_platform = validate_vendor_platform(vendor_name, "")
        return default_platform
    except ValueError:
        return raw


def _select_import_model(
    *,
    declared_model: str,
    current_asset_model: str,
    current_device_model: str,
    chassis_model: str,
    sysdescr_model: str,
    observed_sysdescr_model: str,
    vendor: str = "",
) -> str:
    """Prefer operator/asset identity and ENTITY chassis data over stale sysDescr values."""
    declared = normalize_model_name(vendor, declared_model)
    asset_model = normalize_model_name(vendor, current_asset_model)
    device_model = normalize_model_name(vendor, current_device_model)
    chassis = normalize_model_name(vendor, chassis_model)
    sysdescr = normalize_model_name(vendor, sysdescr_model)
    observed_descr = normalize_model_name(vendor, observed_sysdescr_model)
    low_confidence = {value.casefold() for value in (sysdescr, observed_descr) if value}

    if declared:
        return declared
    for candidate in (asset_model, device_model):
        if candidate and candidate.casefold() not in low_confidence:
            return candidate
    return chassis or sysdescr or asset_model or device_model


def _resolve_probe_settings(
    conn: Any,
    device: Mapping[str, Any],
    configured: bool,
) -> tuple[dict[str, Any] | None, str]:
    """Load decrypted probe credentials only for the duration of the probe."""
    if not configured:
        return None, "missing_credentials"

    credential_id = str(device.get("snmp_credential_id") or "").strip()
    credential = None
    if credential_id:
        row = conn.execute("SELECT * FROM credentials WHERE id = ?", (credential_id,)).fetchone()
        if row:
            credential = dict(row)
        else:
            return None, "credential_missing"

    port = int(device.get("snmp_port") or 161)
    if credential:
        credential_type = str(credential.get("credential_type") or "").strip().casefold()
        if credential_type == "snmpv2":
            community = decrypt_credential(credential.get("snmp_community") or "") or ""
            if not community:
                return None, "credential_incomplete"
            return {
                "version": "2c",
                "community": community,
                "server": str(credential.get("snmp_server") or device.get("snmp_server") or "").strip(),
                "port": port,
            }, ""
        if credential_type == "snmpv3":
            username = str(credential.get("username") or "").strip()
            level = str(credential.get("snmp_security_level") or "authPriv").strip().casefold()
            auth_method = _SNMPV3_AUTH_METHODS.get(
                str(credential.get("snmp_auth_protocol") or "SHA").strip().casefold()
            )
            priv_method = _SNMPV3_PRIV_METHODS.get(
                str(credential.get("snmp_priv_protocol") or "AES").strip().casefold()
            )
            auth_password = decrypt_credential(credential.get("snmp_auth_password") or "") or ""
            priv_password = decrypt_credential(credential.get("snmp_priv_password") or "") or ""
            if not username or level not in {"noauthnopriv", "authnopriv", "authpriv"}:
                return None, "credential_incomplete"
            if level != "noauthnopriv" and (not auth_password or not auth_method):
                return None, "snmpv3_auth_unsupported" if not auth_method else "credential_incomplete"
            if level == "authpriv" and (not priv_password or not priv_method):
                return None, "snmpv3_priv_unsupported" if not priv_method else "credential_incomplete"
            return {
                "version": "3",
                "username": username,
                "auth_password": auth_password,
                "auth_method": auth_method if level != "noauthnopriv" else "",
                "priv_password": priv_password,
                "priv_method": priv_method if level == "authpriv" else "",
                "context_name": str(credential.get("snmp_context_name") or ""),
                "security_level": level,
                "server": str(credential.get("snmp_server") or device.get("snmp_server") or "").strip(),
                "port": port,
            }, ""
        return None, "credential_type_unsupported"

    community = decrypt_credential(device.get("snmp_community") or "") or ""
    if not community:
        return None, "missing_credentials"
    return {
        "version": "2c",
        "community": community,
        "server": str(device.get("snmp_server") or "").strip(),
        "port": port,
    }, ""


async def _read_identity(ip: str, settings: Mapping[str, Any]) -> dict[str, str]:
    from services import snmp_service

    if str(settings.get("version") or "") == "3":
        getter = lambda oid: snmp_service._snmp_get_v3(
            ip,
            str(settings.get("username") or ""),
            oid,
            int(settings.get("port") or 161),
            timeout=3,
            auth_password=str(settings.get("auth_password") or ""),
            auth_protocol=str(settings.get("auth_method") or ""),
            priv_password=str(settings.get("priv_password") or ""),
            priv_protocol=str(settings.get("priv_method") or ""),
            context_name=str(settings.get("context_name") or ""),
            security_level=str(settings.get("security_level") or ""),
        )
    else:
        getter = lambda oid: snmp_service._snmp_get(
            ip,
            str(settings.get("community") or ""),
            oid,
            int(settings.get("port") or 161),
            timeout=3,
        )
    fields = tuple(IDENTITY_OIDS.items())
    values = await asyncio.gather(*(getter(oid) for _field, oid in fields), return_exceptions=True)
    identity: dict[str, str] = {}
    probe_errors = [value for value in values if isinstance(value, BaseException)]
    if probe_errors:
        identity["_probe_error"] = type(probe_errors[0]).__name__
    for (field, _oid), value in zip(fields, values):
        if not isinstance(value, BaseException) and value is not None:
            identity[field] = str(value).strip()
    return identity


def _safe_result(
    item: Mapping[str, Any],
    status: str,
    message: str,
    *,
    hostname_sync: Mapping[str, Any] | None = None,
    **details: Any,
) -> dict[str, Any]:
    result = {
        "device_id": str(item.get("device_id") or ""),
        "row": item.get("row"),
        "asset_tag": str(item.get("asset_tag") or ""),
        "hostname": str(item.get("hostname") or ""),
        "ip": str(item.get("ip") or ""),
        "status": status,
        "message": message,
        **details,
    }
    if hostname_sync is not None:
        result["hostname_sync"] = dict(hostname_sync)
    return result


def _sync_hostname_from_sys_name(item: Mapping[str, Any], raw_sys_name: Any) -> dict[str, str]:
    """Persist the sysName already read for identity detection, without another SNMP GET."""
    from services.hostname_sync_service import (
        clean_system_hostname,
        schedule_monitoring_target_sync_if_hostname_changed,
        sync_device_hostname_metadata,
    )

    clean_name = clean_system_hostname(raw_sys_name)
    if not clean_name:
        return {"status": "failed", "hostname": "", "error": "设备未返回有效的 SNMP sysName.0"}

    device_id = str(item.get("device_id") or "").strip()
    conn = get_db_connection()
    try:
        sync_result = sync_device_hostname_metadata(conn, device_id, raw_sys_name)
        if not sync_result:
            conn.rollback()
            return {"status": "failed", "hostname": "", "error": "主机名无法写回 CMDB：设备记录不存在"}
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning(
            "Asset import hostname write failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        return {"status": "failed", "hostname": "", "error": "SNMP 主机名无法写回 CMDB"}
    finally:
        conn.close()

    schedule_monitoring_target_sync_if_hostname_changed(sync_result)
    return {"status": "synced", "hostname": clean_name, "error": ""}


def _auto_bind_imported_platform(
    *,
    device: Mapping[str, Any],
    device_id: str,
    vendor: str,
    platform: str,
    observed_version: str,
    user: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bind only a visible, active, compatible Profile using this SNMP result."""
    skipped = {
        "platform_binding_status": "skipped",
        "platform_profile_id": None,
        "platform_profile_name": None,
    }
    if not isinstance(user, Mapping):
        return {**skipped, "platform_binding_message": "缺少导入操作者上下文，未执行平台自动绑定"}
    if str(device.get("platform_profile_id") or "").strip() or bool(device.get("platform_locked")):
        return {**skipped, "platform_binding_message": "设备已有平台绑定或锁定标记，已保留现有绑定"}

    from services.platform_identification_service import (
        _assert_device_profile_platform,
        bind_device,
        resolve_inventory_profile_candidate,
    )
    from services.platform_registry_service import PlatformRegistryError

    try:
        candidate = resolve_inventory_profile_candidate(
            platform,
            observed_version,
            vendor,
            dict(user),
        )
    except PlatformRegistryError as exc:
        logger.info(
            "Imported device platform candidate is not visible for device %s (%s)",
            device_id,
            exc.code,
        )
        return {
            "platform_binding_status": "unbound",
            "platform_profile_id": None,
            "platform_profile_name": None,
            "platform_binding_message": "没有可访问的匹配平台 Profile，设备信息已保存",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Imported device platform candidate lookup failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        return {
            "platform_binding_status": "unbound",
            "platform_profile_id": None,
            "platform_profile_name": None,
            "platform_binding_message": "平台 Profile 匹配查询失败，设备信息已保存",
        }

    if not candidate:
        return {
            "platform_binding_status": "unbound",
            "platform_profile_id": None,
            "platform_profile_name": None,
            "platform_binding_message": "未找到可访问的精确平台 Profile 匹配，设备信息已保存",
        }

    profile_id = str(candidate.get("platform_profile_id") or "")
    profile_name = str(candidate.get("name_zh") or candidate.get("name_en") or candidate.get("platform_code") or "")
    suggestion = {
        "platform_binding_status": "suggested",
        "platform_profile_id": profile_id or None,
        "platform_profile_name": profile_name or None,
    }
    if str(candidate.get("status") or "").upper() != "ACTIVE":
        return {
            **suggestion,
            "platform_binding_message": "匹配到的平台 Profile 当前未激活，未自动绑定",
        }

    # Check the fresh SNMP evidence against the mapped Profile before calling
    # the normal binder. The binder repeats these checks against the persisted
    # device row after the latest observed version has been written.
    observed_device = {
        "vendor": vendor,
        "platform": platform,
        "version": observed_version,
    }
    try:
        _assert_device_profile_platform(observed_device, candidate)
    except PlatformRegistryError as exc:
        return {
            **suggestion,
            "platform_binding_message": f"SNMP 识别结果与平台 Profile 不兼容（{exc.code}），需人工确认",
        }

    try:
        bound = bind_device(
            device_id,
            profile_id,
            dict(user),
            binding_source="SNMP_AUTO",
        )
    except PlatformRegistryError as exc:
        if exc.code == "PLATFORM_BINDING_LOCKED":
            return {
                **skipped,
                "platform_binding_message": "设备绑定状态已变化或已锁定，保留现有绑定",
            }
        logger.info(
            "Imported device automatic platform binding was not applied for device %s (%s)",
            device_id,
            exc.code,
        )
        return {
            **suggestion,
            "platform_binding_message": "平台候选已识别，但当前权限或设备状态不允许自动绑定",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Imported device automatic platform binding failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        return {
            **suggestion,
            "platform_binding_message": "平台候选已识别，但绑定保存失败，设备信息已保留",
        }

    bound_profile = bound.get("platform_profile") if isinstance(bound.get("platform_profile"), dict) else {}
    return {
        "platform_binding_status": "auto_bound",
        "platform_profile_id": str(bound_profile.get("id") or profile_id) or None,
        "platform_profile_name": profile_name or None,
        "platform_binding_message": "已根据本次 SNMP 身份识别自动绑定平台 Profile",
    }


async def identify_imported_device(
    item: Mapping[str, Any],
    semaphore: Any,
    model_semaphore: Any | None = None,
    *,
    user: Mapping[str, Any] | None = None,
    auto_bind_platform: bool = False,
) -> dict[str, Any]:
    """Probe one committed device and enrich its LibreNMS-derived identity fields."""
    def result(
        item: Mapping[str, Any],
        status: str,
        message: str,
        *,
        hostname_sync: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        if auto_bind_platform and "platform_binding_status" not in details:
            details.update({
                "platform_binding_status": "skipped",
                "platform_profile_id": None,
                "platform_profile_name": None,
                "platform_binding_message": f"SNMP 身份状态为“{status}”，未执行平台自动绑定",
            })
        return _safe_result(
            item,
            status,
            message,
            hostname_sync=hostname_sync,
            **details,
        )

    device_id = str(item.get("device_id") or "").strip()
    if not device_id:
        return result(
            item,
            "device_missing",
            "导入结果中缺少设备记录",
            hostname_sync={"status": "failed", "hostname": "", "error": "设备记录不存在"},
        )

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not row:
            return result(
                item,
                "device_missing",
                "设备记录不存在",
                hostname_sync={"status": "failed", "hostname": "", "error": "设备记录不存在"},
            )
        device = dict(row)
        from services.snmp_collection_policy_service import is_snmp_collection_enabled

        if not is_snmp_collection_enabled(device):
            return result(
                item,
                "collection_disabled",
                "该设备已关闭 SNMP 采集，未执行自动识别",
                hostname_sync={"status": "skipped", "hostname": "", "error": "SNMP 采集已关闭"},
            )
        settings, settings_error = _resolve_probe_settings(
            conn,
            device,
            bool(item.get("snmp_configured")),
        )
    finally:
        conn.close()

    if settings_error:
        messages = {
            "missing_credentials": "未配置 SNMP 凭据，已保留资产，未执行自动识别",
            "credential_missing": "绑定的 SNMP 凭据已不存在，未执行自动识别",
            "credential_incomplete": "SNMP 凭据字段不完整，未执行自动识别",
            "credential_type_unsupported": "当前凭据类型不支持 SNMP 识别",
            "snmpv3_auth_unsupported": "当前识别探测不支持该 SNMPv3 认证算法",
            "snmpv3_priv_unsupported": "当前识别探测不支持该 SNMPv3 加密算法",
        }
        failure = messages.get(settings_error, "SNMP 凭据不可用于识别")
        return result(
            item,
            settings_error,
            failure,
            hostname_sync={"status": "failed", "hostname": "", "error": failure},
        )

    ip = str(settings.get("server") or device.get("ip_address") or item.get("ip") or "").strip()
    if not ip:
        return result(
            item,
            "missing_ip",
            "缺少管理 IP，未执行自动识别",
            hostname_sync={"status": "failed", "hostname": "", "error": "缺少管理 IP"},
        )

    try:
        async with semaphore:
            observed = await _read_identity(ip, settings or {})
    except Exception as exc:
        logger.warning(
            "Asset import SNMP identity probe failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        failure = f"SNMP 主机名读取失败（{type(exc).__name__}）"
        return result(
            item,
            "probe_failed",
            "SNMP 身份读取失败，请检查管理 IP、端口、凭据及访问控制",
            hostname_sync={"status": "failed", "hostname": "", "error": failure},
        )

    raw_sys_name = str(observed.get("sys_name") or "").strip()
    hostname_sync = _sync_hostname_from_sys_name(item, raw_sys_name) if raw_sys_name else {
        "status": "failed",
        "hostname": "",
        "error": (
            f"SNMP 主机名读取失败（{observed['_probe_error']}）"
            if observed.get("_probe_error")
            else "设备未返回 SNMP sysName.0"
        ),
    }
    if not any(observed.get(field) for field in IDENTITY_OIDS):
        return result(
            item,
            "probe_failed",
            "设备未返回 SNMP 系统身份信息，请检查管理 IP、端口、凭据及访问控制",
            hostname_sync=hostname_sync,
        )

    # Hostname writeback uses the sysName already fetched above. Keep this
    # optional chassis table walk after it so unsupported/slow ENTITY-MIB
    # responses cannot delay the existing hostname synchronization path.
    declared_vendor = str(item.get("declared_vendor", device.get("vendor")) or "")
    declared_model = normalize_model_name(
        declared_vendor,
        item.get("declared_model", device.get("model")),
    )
    chassis_model = ""
    if not declared_model:
        try:
            from services.snmp_entity_model_service import read_chassis_model

            # ENTITY-MIB walks fan out to three tables per device. Keep those
            # model probes on their own, lower-concurrency gate: H3C HCL agents
            # answer sysName in parallel but time out when several table walks
            # for multiple devices run together.
            model_limit = model_semaphore if model_semaphore is not None else semaphore
            async with model_limit:
                chassis_model = normalize_model_name(
                    declared_vendor,
                    await read_chassis_model(ip, settings or {}),
                )
        except Exception as exc:
            logger.warning(
                "Asset import SNMP chassis model probe failed for device %s (%s)",
                device_id,
                type(exc).__name__,
            )

    try:
        await asyncio.to_thread(ensure_rules_available)
    except Exception as exc:
        logger.warning("Local LibreNMS rules unavailable during import identity probe (%s)", type(exc).__name__)

    conn = get_db_connection()
    try:
        identity_probe = {
            "vendor": "",
            "platform": "",
            "sys_object_id": observed.get("sys_object_id", ""),
            "sys_descr": observed.get("sys_descr", ""),
            "sys_name": observed.get("sys_name", ""),
        }
        rule = resolve_rule(conn, identity_probe)
        rule_conflicts = (rule or {}).get("identity_match", {}).get("conflicts") or []
        if rule_conflicts:
            return result(
                item,
                "rule_ambiguous",
                "多条 LibreNMS 识别规则同分匹配，未自动选择设备身份",
                hostname_sync=hostname_sync,
                detected_vendor=str((rule or {}).get("vendor") or ""),
                detected_platform=str((rule or {}).get("platform") or ""),
                identity_source="librenms",
                **({
                    "platform_binding_status": "unbound",
                    "platform_profile_id": None,
                    "platform_profile_name": None,
                    "platform_binding_message": "SNMP 身份规则存在冲突，未自动选择平台 Profile",
                } if auto_bind_platform else {}),
            )

        declared_platform = str(item.get("declared_platform", device.get("platform")) or "")
        identity = resolve_snmp_vendor_identity(
            conn,
            sys_object_id=observed.get("sys_object_id", ""),
            sys_descr=observed.get("sys_descr", ""),
            sys_name=observed.get("sys_name", ""),
            asset_vendor=declared_vendor,
            asset_platform=declared_platform,
            asset_model=declared_model,
        )
        identity_status = str(identity.get("status") or "unidentified")
        detected_vendor = str(identity.get("vendor") or "")
        if identity_status == "conflict":
            return result(
                item,
                "identity_conflict",
                "SNMP 识别到的厂商与导入填写的厂商不一致，未覆盖资产信息",
                hostname_sync=hostname_sync,
                detected_vendor=detected_vendor,
                detected_model=normalize_model_name(detected_vendor, identity.get("model")),
                identity_source=str(identity.get("source") or ""),
                **({
                    "platform_binding_status": "unbound",
                    "platform_profile_id": None,
                    "platform_profile_name": None,
                    "platform_binding_message": "SNMP 识别厂商与导入信息冲突，未自动绑定平台 Profile",
                } if auto_bind_platform else {}),
            )
        if identity_status != "identified" or not detected_vendor:
            return result(
                item,
                "unidentified",
                "已读取 SNMP 信息，但本地 LibreNMS 规则和厂商映射未能识别设备",
                hostname_sync=hostname_sync,
                identity_source=str(identity.get("source") or "none"),
                **({
                    "platform_binding_status": "unbound",
                    "platform_profile_id": None,
                    "platform_profile_name": None,
                    "platform_binding_message": "本次 SNMP 结果未能确定厂商和平台，未自动绑定",
                } if auto_bind_platform else {}),
            )

        detected_platform = _canonical_detected_platform(detected_vendor, identity.get("platform") or declared_platform)
        declared_model = normalize_model_name(detected_vendor or declared_vendor, declared_model)
        identity_model = normalize_model_name(detected_vendor, identity.get("model"))
        sysdescr_model = identity_model if identity_model and identity_model != declared_model else ""
        chassis_model = normalize_model_name(detected_vendor, chassis_model)
        detected_model = normalize_model_name(
            detected_vendor,
            chassis_model or sysdescr_model or declared_model,
        )
        model_source = (
            "entity_mib" if chassis_model
            else "sysDescr" if sysdescr_model
            else "operator" if declared_model
            else ""
        )
        detected_version = str(identity.get("software_version") or "").strip()
        # The importer may fill a default platform before the first probe. Use
        # the explicit input snapshot to distinguish that default from a
        # platform the operator deliberately selected.
        next_vendor = str(device.get("vendor") or detected_vendor)
        next_platform = str(device.get("platform") or detected_platform)
        if not declared_platform:
            next_platform = detected_platform
        current_device_row = conn.execute(
            "SELECT model FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        current_asset_model = ""
        asset_id = str(device.get("asset_id") or "").strip()
        if asset_id:
            current_asset_row = conn.execute(
                "SELECT model FROM physical_assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
            current_asset_model = str((current_asset_row or {}).get("model") or "").strip()
        current_device_model = str((current_device_row or {}).get("model") or "").strip()
        observed_sysdescr_model = str(observed.get("sys_descr") or "").split("\r\n")[0].split("\n")[0].strip()[:80]
        next_model = _select_import_model(
            declared_model=declared_model,
            current_asset_model=current_asset_model,
            current_device_model=current_device_model,
            chassis_model=chassis_model,
            sysdescr_model=sysdescr_model,
            observed_sysdescr_model=observed_sysdescr_model,
            vendor=detected_vendor,
        )
        # The latest SNMP sysDescr observation is fresher than an existing
        # inventory value. Keep the stored version when this probe yields no
        # version, but never let an older value override a current observation.
        next_version = detected_version or str(device.get("version") or "")
        conn.execute(
            "UPDATE devices SET vendor = ?, platform = ?, model = ?, version = ? WHERE id = ?",
            (next_vendor, next_platform, next_model, next_version, device_id),
        )
        if asset_id:
            conn.execute(
                "UPDATE physical_assets SET vendor = ?, platform = ?, model = ? WHERE id = ?",
                (next_vendor, next_platform, next_model, asset_id),
            )

        conn.commit()
        platform_binding = {}
        if auto_bind_platform:
            platform_binding = _auto_bind_imported_platform(
                device=device,
                device_id=device_id,
                vendor=detected_vendor,
                platform=detected_platform,
                observed_version=detected_version,
                user=user,
            )
        return result(
            item,
            "identified",
            "已按 LibreNMS 设备身份规则识别厂商、平台和型号；硬件采集由对应 LibreNMS YAML 规则决定",
            hostname_sync=hostname_sync,
            detected_vendor=detected_vendor,
            detected_platform=detected_platform,
            detected_model=detected_model,
            synced_model=next_model,
            model_source=model_source or ("existing" if next_model else ""),
            identity_source=str(identity.get("source") or ""),
            **platform_binding,
        )
    except Exception as exc:
        conn.rollback()
        logger.warning("Asset import SNMP identity resolution failed for device %s (%s)", device_id, type(exc).__name__)
        return result(
            item,
            "identification_failed",
            "SNMP 身份识别失败，资产数据已保留",
            hostname_sync=hostname_sync,
        )
    finally:
        conn.close()


__all__ = ["IDENTITY_OIDS", "identify_imported_device"]
