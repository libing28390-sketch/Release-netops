"""SNMP identity and metric-profile selection performed after asset import."""

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
from services.snmp_discovery_service import resolve_snmp_vendor_identity
from services.snmp_metric_profile_service import (
    bind_model_metric_profile,
    resolve_metric_profile_candidate,
)

logger = logging.getLogger(__name__)

IDENTITY_OIDS = {
    "sys_object_id": "1.3.6.1.2.1.1.2.0",
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
}

_VERIFIED_PROFILE_STATUSES = {"tested", "published", "verified", "passed", "approved"}
_SNMPV3_AUTH_METHODS = {"md5": "md5", "sha": "sha1"}
_SNMPV3_PRIV_METHODS = {"aes": "aes", "des": "des"}
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
            return {"version": "2c", "community": community, "port": port}, ""
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
            if str(credential.get("snmp_context_name") or "").strip():
                return None, "snmpv3_context_unsupported"
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
                "port": port,
            }, ""
        return None, "credential_type_unsupported"

    community = decrypt_credential(device.get("snmp_community") or "") or ""
    if not community:
        return None, "missing_credentials"
    return {"version": "2c", "community": community, "port": port}, ""


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
    for (field, _oid), value in zip(fields, values):
        if not isinstance(value, BaseException) and value is not None:
            identity[field] = str(value).strip()
    return identity


def _safe_result(item: Mapping[str, Any], status: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "device_id": str(item.get("device_id") or ""),
        "row": item.get("row"),
        "asset_tag": str(item.get("asset_tag") or ""),
        "hostname": str(item.get("hostname") or ""),
        "ip": str(item.get("ip") or ""),
        "status": status,
        "message": message,
        **details,
    }


async def identify_imported_device(item: Mapping[str, Any], semaphore: Any) -> dict[str, Any]:
    """Probe one committed device, enrich only blank identity fields, and bind a safe profile."""
    device_id = str(item.get("device_id") or "").strip()
    if not device_id:
        return _safe_result(item, "device_missing", "导入结果中缺少设备记录")

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not row:
            return _safe_result(item, "device_missing", "设备记录不存在")
        device = dict(row)
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
            "snmpv3_context_unsupported": "当前识别探测不支持 SNMPv3 Context Name",
            "snmpv3_auth_unsupported": "当前识别探测不支持该 SNMPv3 认证算法",
            "snmpv3_priv_unsupported": "当前识别探测不支持该 SNMPv3 加密算法",
        }
        return _safe_result(item, settings_error, messages.get(settings_error, "SNMP 凭据不可用于识别"))

    ip = str(device.get("ip_address") or item.get("ip") or "").strip()
    if not ip:
        return _safe_result(item, "missing_ip", "缺少管理 IP，未执行自动识别")

    try:
        async with semaphore:
            observed = await _read_identity(ip, settings or {})
    except Exception as exc:
        logger.warning(
            "Asset import SNMP identity probe failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        return _safe_result(item, "probe_failed", "SNMP 身份读取失败，请检查管理 IP、端口、凭据及访问控制")
    if not any(observed.get(field) for field in IDENTITY_OIDS):
        return _safe_result(item, "probe_failed", "设备未返回 SNMP 系统身份信息，请检查管理 IP、端口、凭据及访问控制")

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
            return _safe_result(
                item,
                "rule_ambiguous",
                "多条 LibreNMS 识别规则同分匹配，未自动选择 Profile",
                detected_vendor=str((rule or {}).get("vendor") or ""),
                detected_platform=str((rule or {}).get("platform") or ""),
                identity_source="librenms",
            )

        declared_vendor = str(item.get("declared_vendor", device.get("vendor")) or "")
        declared_platform = str(item.get("declared_platform", device.get("platform")) or "")
        declared_model = str(item.get("declared_model", device.get("model")) or "")
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
            return _safe_result(
                item,
                "identity_conflict",
                "SNMP 识别到的厂商与导入填写的厂商不一致，未覆盖资产信息或绑定 Profile",
                detected_vendor=detected_vendor,
                detected_model=str(identity.get("model") or ""),
                identity_source=str(identity.get("source") or ""),
            )
        if identity_status != "identified" or not detected_vendor:
            return _safe_result(
                item,
                "unidentified",
                "已读取 SNMP 信息，但本地 LibreNMS 规则和厂商映射未能识别设备",
                identity_source=str(identity.get("source") or "none"),
            )

        detected_platform = _canonical_detected_platform(detected_vendor, identity.get("platform") or declared_platform)
        detected_model = str(identity.get("model") or declared_model or "").strip()
        detected_version = str(identity.get("software_version") or "").strip()
        match_identity = {
            "id": device_id,
            "vendor": detected_vendor,
            "platform": detected_platform,
            "model": detected_model,
            "version": detected_version or str(device.get("version") or ""),
            "os_version": detected_version or str(device.get("os_version") or ""),
            "firmware_version": detected_version or str(device.get("firmware_version") or ""),
        }

        # The importer may fill a default platform before the first probe. Use
        # the explicit input snapshot to distinguish that default from a
        # platform the operator deliberately selected.
        next_vendor = str(device.get("vendor") or detected_vendor)
        next_platform = str(device.get("platform") or detected_platform)
        if not declared_platform:
            next_platform = detected_platform
        next_model = str(device.get("model") or detected_model)
        next_version = str(device.get("version") or detected_version)
        conn.execute(
            "UPDATE devices SET vendor = ?, platform = ?, model = ?, version = ? WHERE id = ?",
            (next_vendor, next_platform, next_model, next_version, device_id),
        )
        asset_id = str(device.get("asset_id") or "").strip()
        if asset_id:
            conn.execute(
                "UPDATE physical_assets SET vendor = ?, platform = ?, model = ? WHERE id = ?",
                (next_vendor, next_platform, next_model, asset_id),
            )

        existing_profile_id = str(device.get("snmp_metric_profile_id") or "").strip()
        if existing_profile_id:
            conn.commit()
            return _safe_result(
                item,
                "profile_already_bound",
                "设备已有手动绑定的 SNMP 指标 Profile，保留现有绑定",
                detected_vendor=detected_vendor,
                detected_platform=detected_platform,
                detected_model=detected_model,
                identity_source=str(identity.get("source") or ""),
                profile_id=existing_profile_id,
            )

        candidate = resolve_metric_profile_candidate(match_identity)
        candidate_status = str(candidate.get("status") or "no_match")
        base_details = {
            "detected_vendor": detected_vendor,
            "detected_platform": detected_platform,
            "detected_model": detected_model,
            "identity_source": str(identity.get("source") or ""),
        }
        if candidate_status == "ambiguous":
            conn.commit()
            return _safe_result(
                item,
                "profile_ambiguous",
                "设备身份已识别，但有多个同等匹配的 SNMP 指标 Profile，未自动绑定",
                **base_details,
            )
        if candidate_status != "matched":
            conn.commit()
            return _safe_result(item, "profile_no_match", "设备身份已识别，但没有兼容的 SNMP 指标 Profile", **base_details)

        profile = candidate.get("profile") or {}
        profile_name = str(profile.get("template_name") or candidate.get("profile_id") or "")
        profile_status = str(profile.get("profile_status") or "unverified").casefold()
        if profile_status not in _VERIFIED_PROFILE_STATUSES:
            conn.commit()
            return _safe_result(
                item,
                "profile_unverified",
                "唯一匹配的 SNMP 指标 Profile 尚未验证，未自动绑定",
                **base_details,
                profile_name=profile_name,
            )
        metric_keys = {str(key).casefold() for key in (profile.get("metrics") or {})}
        if not {"cpu", "memory"}.issubset(metric_keys):
            conn.commit()
            return _safe_result(
                item,
                "profile_incomplete",
                "唯一匹配的 SNMP 指标 Profile 缺少 CPU 或内存定义，未自动绑定",
                **base_details,
                profile_name=profile_name,
            )

        try:
            bind_model_metric_profile(conn, str(candidate.get("profile_id") or ""), [device_id])
        except ValueError as exc:
            conn.commit()
            logger.info(
                "Automatic SNMP profile binding skipped for device %s (%s)",
                device_id,
                str(exc).split(":", 1)[0],
            )
            return _safe_result(
                item,
                "profile_incompatible",
                "识别结果与资产已有厂商、平台或型号字段不兼容，未自动绑定",
                **base_details,
                profile_name=profile_name,
            )
        conn.commit()
        return _safe_result(
            item,
            "profile_bound",
            "已按 SNMP 身份自动绑定唯一且已验证的 CPU/内存指标 Profile",
            **base_details,
            profile_id=str(candidate.get("profile_id") or ""),
            profile_name=profile_name,
        )
    except Exception as exc:
        conn.rollback()
        logger.warning("Asset import SNMP identity resolution failed for device %s (%s)", device_id, type(exc).__name__)
        return _safe_result(item, "identification_failed", "SNMP 身份识别或 Profile 绑定失败，资产数据已保留")
    finally:
        conn.close()


__all__ = ["IDENTITY_OIDS", "identify_imported_device"]
