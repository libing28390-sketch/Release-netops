"""CMDB-only CLI inventory collection.

This module is the explicit CMDB job path. It does not call the monitoring
SNMP refresh functions or write monitoring collection-status records.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from core.interface_utils import normalize_interface_name
from database import get_db_connection


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _collector_user(device: dict[str, Any]) -> dict[str, Any]:
    device_id = str(device.get("id") or "unknown")
    return {
        "id": f"cmdb-collector:{device_id}",
        "username": "cmdb-collector",
        "role": "Operator",
        "tenant_id": device.get("tenant_id") or "",
        "_trusted_service_identity": "collector",
    }


def _action_record_limit(action_code: str) -> int:
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT max_records FROM action_definitions WHERE action_code = ?",
            (str(action_code),),
        ).fetchone()
        return max(1, int(row["max_records"] or 1000)) if row else 1000
    finally:
        conn.close()


def _has_truncation_marker(raw_output: Any) -> bool:
    text = str(raw_output or "").lower()
    return any(marker in text for marker in (
        "--more--", "---- more ----", "press any key", "press <space>",
        "output truncated", "displaying first", "more pages",
    ))


def _is_explicitly_unsupported(category: dict[str, Any]) -> bool:
    return (
        str(category.get("parse_status") or "").strip().lower() == "unsupported_by_platform"
        or str(category.get("error_code") or "").strip().upper() in {
            "UNSUPPORTED_ACTION", "UNSUPPORTED_BY_PLATFORM",
        }
    )


def _validate_cli_category(category: dict[str, Any], action_code: str, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    if category.get("success") is not True or category.get("parse_status") != "matched":
        code = str(category.get("error_code") or category.get("parse_status") or "command_failed")
        raise RuntimeError(f"{action_code} CLI结果不完整 ({code})")
    records = category.get("records") or []
    if not allow_empty and not records:
        raise RuntimeError(f"{action_code} CLI结果没有可确认的记录")
    if len(records) >= _action_record_limit(action_code):
        raise RuntimeError(f"{action_code} CLI结果触及记录上限，不能确认快照完整")
    raw_outputs = category.get("raw_outputs") or []
    if category.get("truncated") or any(
        _has_truncation_marker(item.get("output") if isinstance(item, dict) else item)
        for item in raw_outputs
    ):
        raise RuntimeError(f"{action_code} CLI结果疑似分页或输出截断")
    if any(not isinstance(item, dict) for item in records):
        raise RuntimeError(f"{action_code} CLI记录格式无效")
    return list(records)


def _collect_cli_ip_addresses(
    device: dict[str, Any], session,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from services.interface_collection_service import (
        _looks_like_interface_name,
        _normalize_ip,
        _normalize_prefix_length,
    )
    result = _collect_cli_ip_action_result(device, session)
    if (
        result.get("success") is not True
        or str(result.get("parse_status") or "").strip().lower() != "matched"
    ):
        if _has_prefixless_ip_interface_header(result.get("raw_output")):
            fallback_condition = str(result.get("fallback_condition") or "").strip()
            suffix = f" ({fallback_condition})" if fallback_condition else ""
            raise RuntimeError("接口IP CLI结果只有IP地址，没有掩码或前缀长度" + suffix)
        code = str(result.get("error_code") or result.get("parse_status") or "command_failed")
        raise RuntimeError(f"接口IP CLI采集不完整 ({code})")

    records = result.get("records") or []
    if len(records) >= _action_record_limit("get_ip_interfaces"):
        raise RuntimeError("接口IP CLI结果触及记录上限，不能确认快照完整")
    if result.get("truncated") or _has_truncation_marker(result.get("raw_output")):
        raise RuntimeError("接口IP CLI结果疑似分页或输出截断")

    by_interface: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("接口IP CLI记录格式无效")
        interface_name = _cmdb_record_value(record, "INTERFACE", "IFNAME", "NAME", "PORT")
        raw_address = _cmdb_record_value(record, "IP_ADDRESS", "PRIMARY_IP", "MAIN_IP", "IP", "ADDRESS")
        ip_address = _normalize_ip(raw_address)
        if not ip_address:
            if str(raw_address or "").strip().lower() in {"", "unassigned", "none", "--", "-", "n/a"}:
                continue
            raise RuntimeError("接口IP CLI记录包含无效IP地址")
        # The shared IP-interface template also parses valid interface rows
        # that have no assigned address. They are irrelevant to this IP-only
        # snapshot and must not be rejected by the interface-name guard.
        if not interface_name or not _looks_like_cmdb_ip_interface_name(interface_name):
            raise RuntimeError("接口IP CLI记录缺少有效接口名称")

        raw_prefix = _cmdb_record_value(
            record, "PREFIX_LENGTH", "PREFIX_LEN", "MASK", "NETMASK", "SUBNET_MASK", "PREFIX",
        )
        if not raw_prefix and "/" in raw_address:
            raw_prefix = raw_address.split("/", 1)[1].strip()
        prefix_length = _normalize_prefix_length(raw_prefix)
        if prefix_length is None:
            raise RuntimeError("接口IP CLI记录缺少有效掩码或前缀长度")

        key = normalize_interface_name(interface_name)
        current = by_interface.get(key)
        if current is not None:
            if current["ip_address"] == ip_address and current["prefix_length"] == prefix_length:
                continue
            raise RuntimeError("接口IP CLI快照包含同一接口的多个地址，当前CMDB投影无法无损表示")
        by_interface[key] = {
            "interface": interface_name,
            "ip_address": ip_address,
            "prefix_length": prefix_length,
        }

    if not by_interface:
        raise RuntimeError("接口IP CLI快照没有可确认的地址行")
    action_metadata = {
        key: result.get(key)
        for key in (
            "platform_release_id", "release_number", "release_checksum",
            "command_checksum", "resolved_command_checksum", "parser",
            "parser_platform", "template", "template_source", "template_action_code", "command",
            "command_source", "source", "source_action_code", "ip_action_command", "fallback_condition",
        )
        if result.get(key) not in (None, "")
    }
    return list(by_interface.values()), action_metadata


def _has_prefixless_ip_interface_header(raw_output: Any) -> bool:
    """Identify H3C brief output whose IP column omits mask/prefix data."""
    for line in str(raw_output or "").splitlines():
        if not re.search(r"(?i)^\s*Interface\s+Physical\s+Protocol\s+IP\s+Address\b", line):
            continue
        return not re.search(r"(?i)\bMask\b|/", line)
    return False


def _looks_like_cmdb_ip_interface_name(value: Any) -> bool:
    """Extend the shared interface-name guard for H3C RAGG interfaces."""
    from services.interface_collection_service import _looks_like_interface_name

    normalized = re.sub(r"\s+", "", str(value or "").strip().lower())
    return _looks_like_interface_name(value) or bool(re.fullmatch(r"ragg\d+(?:/\d+)*", normalized))


def _cmdb_record_value(record: dict[str, Any], *keys: str) -> str:
    """Read one scalar parser field without stringifying TextFSM List values.

    NTC templates can return a single-cell ``List`` even when the output has
    one value. Unwrap that case; reject several distinct values instead of
    silently choosing an address that the CMDB row cannot represent.
    """
    normalized = {
        str(record_key).strip().replace("-", "_").upper(): value
        for record_key, value in record.items()
    }
    for key in keys:
        value = normalized.get(str(key).strip().replace("-", "_").upper())
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            distinct = list(dict.fromkeys(
                str(item).strip() for item in value
                if item is not None and str(item).strip()
            ))
            if len(distinct) > 1:
                raise RuntimeError("接口IP CLI字段包含多个值，当前CMDB投影无法无损表示")
            if distinct:
                return distinct[0]
            continue
        raw = str(value).strip()
        if raw:
            return raw
    return ""


def _collect_cli_ip_action_result(device: dict[str, Any], session) -> dict[str, Any]:
    """Run the published IP action, with only exact-version TextFSM recovery.

    Missing registry actions may use the operational-data service's existing
    exact action/template resolver. When a published action runs but its
    parser returns no records, retry parsing that same raw output only when
    the current profile has an exact command/version template. This remains
    inside the CMDB path and reuses the same read-only SSH session.
    """
    from services.operational_data_service import (
        _execute_textfsm_operation_fallback,
        parse_device_cli_output,
        resolve_textfsm_operation_fallback,
        resolve_textfsm_template_for_command,
    )
    from services.platform_registry_service import PlatformRegistryError, execute_platform_action

    action_code = "get_ip_interfaces"
    user = _collector_user(device)
    try:
        result = execute_platform_action(
            str(device.get("id") or ""),
            action_code,
            user=user,
            include_raw_output=True,
            _session=session,
        )
    except PlatformRegistryError as exc:
        if exc.code != "UNSUPPORTED_ACTION":
            raise
        fallback_plan = resolve_textfsm_operation_fallback(
            device,
            # This deliberately has no legacy COMMAND_CATALOG entry. The
            # resolver can use an exact get_ip_interfaces template action,
            # but cannot substitute get_interface_brief and lose prefix data.
            operational_category="ip_interfaces",
            action_code=action_code,
        )
        fallback = next(iter(fallback_plan.get("commands") or []), None)
        if (
            not fallback
            or str(fallback.get("command_source") or "").strip().lower()
            != "textfsm_action_metadata"
            or not str(fallback.get("textfsm_template") or "").strip()
        ):
            condition = str(fallback_plan.get("condition") or exc.message)
            raise RuntimeError(
                "接口IP CLI采集不完整 "
                "(UNSUPPORTED_ACTION: 没有绑定get_ip_interfaces的精确模板; "
                f"{condition})"
            ) from exc
        result = _execute_textfsm_operation_fallback(
            device,
            fallback,
            user=user,
            platform_action_session=session,
        )
        result["command_source"] = fallback.get("command_source")
        result["fallback_condition"] = fallback.get("condition")

    parse_status = str(result.get("parse_status") or "").strip().lower()
    if result.get("success") is True and parse_status != "matched":
        command = str(result.get("command") or "").strip()
        raw_output = result.get("raw_output")
        if command and raw_output is not None:
            exact_template = resolve_textfsm_template_for_command(
                device,
                command,
                action_code=action_code,
            )
            template_name = str((exact_template or {}).get("textfsm_template") or "").strip()
            if template_name:
                parsed = parse_device_cli_output(
                    device,
                    command,
                    str(raw_output),
                    template_filename=template_name,
                )
                if str(parsed.get("parse_status") or "").strip().lower() == "matched":
                    result = {
                        **result,
                        "records": parsed.get("records") or [],
                        "parse_status": parsed.get("parse_status"),
                        "parser": parsed.get("parser"),
                        "parser_platform": parsed.get("parser_platform"),
                        "template": parsed.get("template"),
                        "template_source": parsed.get("template_source"),
                        "template_action_code": parsed.get("template_action_code"),
                    }
        if (
            str(result.get("parse_status") or "").strip().lower() != "matched"
            and _has_prefixless_ip_interface_header(result.get("raw_output"))
        ):
            result = _collect_detailed_interface_ip_fallback(
                device,
                session,
                result,
                execute_platform_action=execute_platform_action,
                platform_registry_error=PlatformRegistryError,
                user=user,
            )
    return result


def _collect_detailed_interface_ip_fallback(
    device: dict[str, Any],
    session,
    original_result: dict[str, Any],
    *,
    execute_platform_action,
    platform_registry_error,
    user: dict[str, Any],
) -> dict[str, Any]:
    """Use the published detailed interface action when brief has no mask.

    Some Comware variants return only a bare IP in ``display ip interface
    brief``. Their already-published read-only ``get_interfaces`` action may
    include the same address with CIDR. Only those explicitly prefix-bearing
    records are passed to the strict CMDB IP validator; the shared parser and
    action selection logic remain unchanged.
    """
    device_id = str(device.get("id") or "")
    try:
        detailed = execute_platform_action(
            device_id,
            "get_interfaces",
            user=user,
            include_raw_output=True,
            _session=session,
        )
    except platform_registry_error as exc:
        return {
            **original_result,
            "error_code": "PREFIX_SOURCE_UNAVAILABLE",
            "fallback_condition": f"get_interfaces action unavailable: {exc.code}",
        }

    raw_output = detailed.get("raw_output")
    records = detailed.get("records") or []
    if detailed.get("success") is not True or str(detailed.get("parse_status") or "").strip().lower() != "matched":
        return {
            **original_result,
            "error_code": "PREFIX_SOURCE_UNAVAILABLE",
            "fallback_condition": "get_interfaces action did not return a matched result",
        }
    if len(records) >= _action_record_limit("get_interfaces"):
        return {
            **original_result,
            "error_code": "PREFIX_SOURCE_INCOMPLETE",
            "fallback_condition": "get_interfaces result reached its record limit",
        }
    if detailed.get("truncated") or _has_truncation_marker(raw_output):
        return {
            **original_result,
            "error_code": "PREFIX_SOURCE_INCOMPLETE",
            "fallback_condition": "get_interfaces result may be truncated",
        }

    from services.interface_collection_service import _normalize_ip

    ip_records: list[dict[str, Any]] = []
    detailed_ip_counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            return {
                **original_result,
                "error_code": "PREFIX_SOURCE_INCOMPLETE",
                "fallback_condition": "get_interfaces returned an invalid record",
            }
        interface_name = _cmdb_record_value(record, "INTERFACE", "IFNAME", "NAME", "PORT")
        raw_address = _cmdb_record_value(record, "IP_ADDRESS", "MAIN_IP", "PRIMARY_IP", "IP", "ADDRESS")
        if str(raw_address or "").strip().lower() in {"", "unassigned", "none", "--", "-", "n/a"}:
            continue
        normalized_ip = _normalize_ip(raw_address)
        if not normalized_ip:
            return {
                **original_result,
                "error_code": "PREFIX_SOURCE_INCOMPLETE",
                "fallback_condition": "get_interfaces returned an invalid IP address",
            }
        detailed_ip_counts[normalized_ip] = detailed_ip_counts.get(normalized_ip, 0) + 1
        ip_records.append({
            "INTERFACE": interface_name,
            "IP_ADDRESS": raw_address,
            "PREFIX_LENGTH": _cmdb_record_value(
                record, "PREFIX_LENGTH", "PREFIX_LEN", "MASK", "NETMASK", "SUBNET_MASK", "PREFIX",
            ),
        })
    if not ip_records:
        return {
            **original_result,
            "error_code": "PREFIX_SOURCE_UNAVAILABLE",
            "fallback_condition": "get_interfaces returned no IP-bearing records",
        }

    # Do not accept the detailed action merely because it parsed. Its
    # address set must account for every address visible in the prefixless
    # brief output, with no extras that would change the CMDB projection.
    brief_ip_counts: dict[str, int] = {}
    for value in re.findall(
        r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}(?:/\d{1,3})?(?![\d.])",
        str(original_result.get("raw_output") or ""),
    ):
        normalized_ip = _normalize_ip(value)
        if normalized_ip:
            brief_ip_counts[normalized_ip] = brief_ip_counts.get(normalized_ip, 0) + 1
    if not brief_ip_counts or brief_ip_counts != detailed_ip_counts:
        return {
            **original_result,
            "error_code": "PREFIX_SOURCE_MISMATCH",
            "fallback_condition": "get_interfaces IP rows did not exactly match the prefixless brief output",
        }

    return {
        **detailed,
        "records": ip_records,
        "source_action_code": "get_interfaces",
        "ip_action_command": original_result.get("command"),
        "fallback_condition": "prefixless get_ip_interfaces output; used published get_interfaces action",
    }


def _persist_interface_snapshot(
    device: dict[str, Any],
    rows: list[dict[str, Any]],
    attempt: dict[str, Any],
    *,
    observed_at: str,
    metadata: dict[str, Any],
) -> int:
    """Replace only the CMDB-owned interface observations and success marker."""
    if str(device.get("id") or "") != str(attempt.get("device_id") or ""):
        raise ValueError("CMDB interface attempt device does not match the target")
    conn = get_db_connection()
    try:
        from services.cmdb_interface_snapshot_service import replace_cmdb_interface_observations

        updated = replace_cmdb_interface_observations(
            conn,
            attempt,
            rows,
            observed_at=observed_at,
            metadata=metadata,
        )

        from services.cmdb_snapshot_service import complete_snapshot

        if not complete_snapshot(
            conn,
            attempt,
            observed_at=observed_at,
            transport="ssh",
            record_count=updated,
            metadata=metadata,
        ):
            raise RuntimeError("CMDB interface snapshot was superseded")
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _persist_vlan_snapshot(
    device_id: str,
    records: list[dict[str, Any]],
    attempt: dict[str, Any],
    *,
    observed_at: str,
    metadata: dict[str, Any],
) -> dict[str, int]:
    """Replace CMDB VLAN/member observations and their success marker."""
    if str(device_id or "") != str(attempt.get("device_id") or ""):
        raise ValueError("CMDB VLAN attempt device does not match the target")
    conn = get_db_connection()
    try:
        device = conn.execute(
            """SELECT COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''),
                              NULLIF(d.site, ''), '') AS site_id,
                      d.platform, d.vendor
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE d.id = ?""",
            (device_id,),
        ).fetchone()
        if not device:
            raise RuntimeError("VLAN CLI快照设备不存在")
        site_id = str(device["site_id"] or "")
        platform = str(device["platform"] or device["vendor"] or "")

        from services.cmdb_interface_snapshot_service import replace_cmdb_vlan_observations

        result = replace_cmdb_vlan_observations(
            conn,
            attempt,
            records,
            site_id=site_id,
            platform=platform,
            observed_at=observed_at,
        )
        from services.cmdb_snapshot_service import complete_snapshot

        if not complete_snapshot(
            conn,
            attempt,
            observed_at=observed_at,
            transport="ssh",
            record_count=result["vlans"],
            metadata={"parser": "textfsm", "raw_vlan_records": len(records), **metadata},
        ):
            raise RuntimeError("CMDB VLAN snapshot was superseded")
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def collect_cmdb_interface_status_target(
    device_id: str,
    *,
    vlan_only: bool = False,
) -> dict[str, Any]:
    """Collect CMDB interfaces and their VLAN inventory in one CLI session."""
    from services.collection_plan_service import should_collect
    from services.cmdb_snapshot_service import begin_snapshot_attempt, fail_snapshot_attempt
    from services.interface_collection_service import _load_device, is_online_network_device_for_interface_collection
    from services.platform_registry_service import PlatformActionSession
    from services.read_only_collection_adapter import collect_read_only_evidence

    attempts: dict[str, dict[str, Any]] = {}
    device = _load_device(device_id)
    if not is_online_network_device_for_interface_collection(device):
        raise RuntimeError("接口采集目标已离线或不再属于网络设备")

    collect_interfaces = not vlan_only and should_collect(device, "interface_status")
    # A manual CMDB interface refresh includes VLAN inventory. Scheduler
    # defaults disable VLAN collection and must not suppress this companion
    # domain (or an explicitly requested VLAN-only refresh).
    collect_vlans = vlan_only or collect_interfaces or should_collect(device, "vlan")
    if not collect_interfaces and not collect_vlans:
        return {
            "success": True,
            "device_id": device_id,
            "skipped": True,
            "skip_reason": "collection_policy_disabled",
            "transport_policy": "cmdb_cli_only",
        }

    try:
        if collect_interfaces:
            attempts["interface_inventory"] = begin_snapshot_attempt(device_id, "interface_inventory")
        if collect_vlans:
            attempts["vlan_inventory"] = begin_snapshot_attempt(device_id, "vlan_inventory")

        categories = []
        if collect_interfaces:
            categories.extend(("interfaces", "interface_description"))
        if collect_vlans:
            categories.append("vlan")

        user = _collector_user(device)
        # BaseDriver owns the local SSH gate and shared lease for this session.
        with PlatformActionSession(device_id, user=user, ssh_capacity_class="cmdb_cli") as session:
            evidence = collect_read_only_evidence(
                device,
                categories=categories,
                auth_role="auto",
                policy_override_categories={"vlan"} if collect_vlans else None,
                _platform_action_session=session,
            )
            evidence_categories = {
                str(item.get("key") or ""): item
                for item in evidence.get("categories") or []
                if isinstance(item, dict)
            }
            status_precheck = evidence_categories.get("interfaces") or {}
            description_precheck = evidence_categories.get("interface_description") or {}
            if collect_interfaces and (
                status_precheck.get("success") is True
                and status_precheck.get("parse_status") == "matched"
                and status_precheck.get("records")
            and (
                (
                    description_precheck.get("success") is True
                    and description_precheck.get("parse_status") == "matched"
                )
                or _is_explicitly_unsupported(description_precheck)
            )
            ):
                addresses, address_action_metadata = _collect_cli_ip_addresses(device, session)
            else:
                addresses, address_action_metadata = None, {}
        observed_at = _now()
        by_category = {
            str(item.get("key") or ""): item
            for item in evidence.get("categories") or []
            if isinstance(item, dict)
        }
        errors: list[str] = []
        results: dict[str, Any] = {}
        prefix_sync: dict[str, Any] = {
            "ok": True,
            "skipped": True,
            "reason": "cmdb_projection_isolated",
        }

        if collect_interfaces:
            interface_category = by_category.get("interfaces") or {}
            description_category = by_category.get("interface_description") or {}
            try:
                interface_records = _validate_cli_category(interface_category, "get_interface_brief")
                description_unsupported = _is_explicitly_unsupported(description_category)
                description_records = (
                    []
                    if description_unsupported
                    else _validate_cli_category(
                        description_category, "get_interface_description", allow_empty=True,
                    )
                )
                from services.interface_collection_service import _description_records
                from services.cmdb_interface_snapshot_service import build_cmdb_interface_observation_rows

                descriptions = _description_records({**description_category, "records": description_records})
                rows = build_cmdb_interface_observation_rows(
                    interface_records,
                    descriptions,
                    addresses,
                )
                updated = _persist_interface_snapshot(
                    device,
                    rows,
                    attempts["interface_inventory"],
                    observed_at=observed_at,
                    metadata={
                        "parser": str(interface_category.get("parser") or "textfsm"),
                        "template": interface_category.get("template"),
                        "action_code": "get_ip_interfaces",
                        "address_action": address_action_metadata,
                        "unsupported_fields": ["interface_description"] if description_unsupported else [],
                        "source_categories": {
                            "interfaces": {
                                "action_code": "get_interface_brief",
                                "parser": interface_category.get("parser"),
                                "template": interface_category.get("template"),
                            },
                            "description": {
                                "action_code": "get_interface_description",
                                "parser": description_category.get("parser"),
                                "template": description_category.get("template"),
                            },
                        },
                    },
                )
                results["interfaces"] = {
                    "record_count": len(rows),
                    "updated_count": updated,
                    "unsupported_fields": ["interface_description"] if description_unsupported else [],
                }
            except Exception as exc:
                errors.append(str(exc) or "接口CLI快照写入失败")
                fail_snapshot_attempt(
                    attempts["interface_inventory"],
                    error_code=type(exc).__name__,
                    metadata={"message": "Interface snapshot transaction failed"},
                )
        if collect_vlans:
            vlan_category = by_category.get("vlan") or {}
            try:
                vlan_records = _validate_cli_category(vlan_category, "get_vlan_table")
                results["vlans"] = _persist_vlan_snapshot(
                    device_id,
                    vlan_records,
                    attempts["vlan_inventory"],
                    observed_at=observed_at,
                    metadata={
                        "action_code": "get_vlan_table",
                        "platform_release_id": vlan_category.get("platform_release_id"),
                        "release_checksum": vlan_category.get("release_checksum"),
                        "command_checksum": vlan_category.get("command_checksum"),
                        "parser_platform": vlan_category.get("parser_platform"),
                        "template": vlan_category.get("template"),
                        "template_source": vlan_category.get("template_source"),
                        "parse_status": vlan_category.get("parse_status"),
                    },
                )
            except Exception as exc:
                errors.append(str(exc) or "VLAN CLI快照写入失败")
                fail_snapshot_attempt(
                    attempts["vlan_inventory"],
                    error_code=type(exc).__name__,
                    metadata={"message": "VLAN snapshot transaction failed"},
                )

        if errors:
            raise RuntimeError("；".join(errors))
        return {
            "success": True,
            "device_id": device_id,
            "transport_policy": "cmdb_cli_only",
            "observed_at": observed_at,
            "domains": results,
            "cli_categories": categories,
            "prefix_sync": prefix_sync,
        }
    except Exception as exc:
        for attempt in attempts.values():
            try:
                fail_snapshot_attempt(
                    attempt,
                    error_code=type(exc).__name__,
                    metadata={"message": "CMDB CLI snapshot did not pass completeness validation"},
                )
            except Exception:
                pass
        raise
