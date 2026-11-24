"""Persistence helpers for CMDB-owned CLI interface and VLAN observations."""

from __future__ import annotations

import json
import ipaddress
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from core.interface_utils import normalize_interface_name
from services.normalizers.common import interface_type as infer_interface_type
from services.vlan_discovery_service import is_system_default_vlan, parse_vlan_id_from_interface


_VLAN_ID_RE = re.compile(r"\d+")
_PORT_TAG_RE = re.compile(r"^(UT|TG):(.+)$", re.IGNORECASE)
_PORT_STATE_SUFFIX_RE = re.compile(r"\([UD]\)$", re.IGNORECASE)


def _json_metadata(value: dict[str, Any] | None) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"


def _normalized_name(value: Any) -> str:
    return normalize_interface_name(str(value or "")).strip().lower()


def _lock_current_generation(conn, attempt: dict[str, Any], domain: str) -> tuple[str, int, str]:
    actual_domain = str(attempt.get("domain") or "").strip().lower()
    if actual_domain != domain:
        raise ValueError(f"CMDB observation requires a {domain} attempt")
    device_id = str(attempt.get("device_id") or "")
    generation = int(attempt.get("generation") or 0)
    run_id = str(attempt.get("run_id") or "")
    current = conn.execute(
        """SELECT attempt_generation FROM cmdb_collection_snapshots
           WHERE device_id = ? AND domain = ? FOR UPDATE""",
        (device_id, domain),
    ).fetchone()
    if not current or int(current["attempt_generation"] or 0) != generation:
        label = "interface" if domain == "interface_inventory" else "VLAN"
        raise RuntimeError(f"CMDB {label} snapshot was superseded")
    return device_id, generation, run_id


def _interface_rows_from_cli(
    status_records: list[dict[str, Any]],
    descriptions: dict[str, dict[str, str]],
    address_records: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Merge CLI interface status, descriptions and address evidence by key.

    Unlike the historical shared-interface projection, this includes CLI
    interfaces without IP addresses and never consults ``ip_inventory``.
    """
    from services.interface_collection_service import (
        _interface_description,
        _looks_like_interface_name,
        _normalize_ip,
        _normalize_prefix_length,
        _prefer_status,
        _status_record,
    )

    addresses_by_key: dict[str, list[dict[str, Any]]] = {}
    for address in address_records or []:
        if not isinstance(address, dict):
            continue
        interface_name = str(address.get("interface") or "").strip()
        key = _normalized_name(interface_name)
        if not key:
            raise RuntimeError("CMDB接口地址快照包含缺少接口名的记录")
        raw_ip_address = str(address.get("ip_address") or "").strip()
        raw_prefix_length = address.get("prefix_length")
        prefix_length = _normalize_prefix_length(raw_prefix_length)
        if prefix_length is None and "/" in raw_ip_address:
            prefix_length = _normalize_prefix_length(raw_ip_address.rsplit("/", 1)[-1])
        address_row = {
            "interface": interface_name,
            "ip_address": raw_ip_address,
            "prefix_length": prefix_length if prefix_length is not None else raw_prefix_length,
        }
        for field in (
            "context_source", "context_type", "local_context_key", "local_context_name",
        ):
            if field in address:
                address_row[field] = address[field]
        addresses_by_key.setdefault(key, []).append(address_row)

    status_by_key: dict[str, dict[str, Any]] = {}
    for record in status_records:
        if not isinstance(record, dict):
            continue
        interface_name, ip_address, prefix_length, admin_status, oper_status = _status_record(record, {})
        if not _looks_like_interface_name(interface_name):
            continue
        key = _normalized_name(interface_name)
        if not key:
            continue
        current = status_by_key.get(key)
        direct_description = _interface_description(record)
        if current is None:
            status_by_key[key] = {
                "interface_name": str(interface_name),
                "ip_address": _normalize_ip(ip_address),
                "prefix_length": _normalize_prefix_length(prefix_length),
                "admin_status": admin_status,
                "oper_status": oper_status,
                "description": direct_description,
            }
            continue
        current["admin_status"] = _prefer_status(current["admin_status"], admin_status)
        current["oper_status"] = _prefer_status(current["oper_status"], oper_status)
        if not current.get("ip_address") and ip_address:
            current["ip_address"] = _normalize_ip(ip_address)
            current["prefix_length"] = _normalize_prefix_length(prefix_length)
        if direct_description is not None:
            current["description"] = direct_description

    rows: list[dict[str, Any]] = []
    for key in sorted(set(status_by_key) | set(addresses_by_key)):
        status = status_by_key.get(key, {})
        addresses = addresses_by_key.get(key, [])
        # Keep the historical status-output address fallback when the dedicated
        # address action did not return an address for this interface.
        if not addresses and status.get("ip_address"):
            addresses = [{
                "interface": status.get("interface_name") or key,
                "ip_address": status["ip_address"],
                "prefix_length": status.get("prefix_length"),
                "context_source": "cli",
                "context_type": "unknown",
                "local_context_key": "",
                "local_context_name": "",
            }]
        description = status.get("description")
        if description is None:
            description = descriptions.get(key, {}).get("description")
        single_address = addresses[0] if len(addresses) == 1 else {}
        single_ip = _normalize_ip(single_address.get("ip_address"))
        single_prefix = _normalize_prefix_length(single_address.get("prefix_length"))
        rows.append({
            "interface_name": (
                status.get("interface_name")
                or (addresses[0].get("interface") if addresses else "")
                or descriptions.get(key, {}).get("interface_name")
                or key
            ),
            "description": description,
            "admin_status": status.get("admin_status") or "unknown",
            "oper_status": status.get("oper_status") or "unknown",
            # Legacy parent fields are populated only when there is exactly
            # one child address. The full address set is retained below.
            "interface_ip": single_ip,
            "prefix_length": single_prefix,
            "addresses": addresses,
        })
    return rows


def build_cmdb_interface_observation_rows(
    status_records: list[dict[str, Any]],
    descriptions: dict[str, dict[str, str]],
    address_records: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build a complete CMDB CLI interface observation set without DB reads."""
    return _interface_rows_from_cli(status_records, descriptions, address_records)


def replace_cmdb_interface_observations(
    conn,
    attempt: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    observed_at: str,
    metadata: dict[str, Any] | None,
) -> int:
    """Replace one device's CMDB interface observations in the caller txn."""
    if not rows:
        raise RuntimeError("CMDB CLI接口快照没有可提交的有效接口记录")

    device_id, generation, run_id = _lock_current_generation(
        conn, attempt, "interface_inventory",
    )
    normalized_rows: dict[str, dict[str, Any]] = {}
    for item in rows:
        interface_name = str(item.get("interface_name") or "").strip()
        normalized_name = _normalized_name(interface_name)
        if not normalized_name:
            raise RuntimeError("CMDB CLI接口快照包含缺少接口名的记录")

        if normalized_name in normalized_rows:
            raise RuntimeError("CMDB CLI接口快照包含重复接口记录")

        if "addresses" in item:
            raw_addresses = item.get("addresses")
            if not isinstance(raw_addresses, list):
                raise RuntimeError("CMDB CLI接口快照包含无效地址列表")
        else:
            # Preserve compatibility with older internal callers that still
            # pass the former single-address parent fields.
            legacy_ip = str(item.get("interface_ip") or "").strip()
            raw_addresses = ([{
                "interface": interface_name,
                "ip_address": legacy_ip,
                "prefix_length": item.get("prefix_length"),
            }] if legacy_ip else [])

        address_rows: list[dict[str, Any]] = []
        address_rows_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
        for raw_address in raw_addresses:
            if not isinstance(raw_address, dict):
                raise RuntimeError("CMDB CLI接口快照包含无效地址记录")
            address_interface_name = str(raw_address.get("interface") or interface_name).strip()
            if _normalized_name(address_interface_name) != normalized_name:
                raise RuntimeError("CMDB CLI接口地址不属于其父接口")

            raw_ip_address = str(raw_address.get("ip_address") or "").strip()
            if not raw_ip_address or "%" in raw_ip_address:
                raise RuntimeError("CMDB CLI接口快照包含无效IP地址")
            embedded_prefix_length = None
            try:
                if "/" in raw_ip_address:
                    parsed_interface = ipaddress.ip_interface(raw_ip_address)
                    parsed_ip = parsed_interface.ip
                    embedded_prefix_length = parsed_interface.network.prefixlen
                else:
                    parsed_ip = ipaddress.ip_address(raw_ip_address)
            except ValueError as exc:
                raise RuntimeError("CMDB CLI接口快照包含无效IP地址") from exc
            normalized_ip_address = str(parsed_ip)

            raw_prefix_length = raw_address.get("prefix_length")
            if raw_prefix_length is None or str(raw_prefix_length).strip() == "":
                prefix_length = embedded_prefix_length
            else:
                if isinstance(raw_prefix_length, bool):
                    raise RuntimeError("CMDB CLI接口快照包含无效掩码长度")
                prefix_value = str(raw_prefix_length).strip()
                if prefix_value.startswith("/"):
                    prefix_value = prefix_value[1:].strip()
                try:
                    if "." in prefix_value:
                        if parsed_ip.version != 4:
                            raise ValueError("IPv4 netmask supplied for IPv6 address")
                        prefix_length = ipaddress.IPv4Network(
                            f"0.0.0.0/{prefix_value}"
                        ).prefixlen
                    else:
                        prefix_length = int(prefix_value)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("CMDB CLI接口快照包含无效掩码长度") from exc
            max_prefix_length = 32 if parsed_ip.version == 4 else 128
            if (
                prefix_length is None
                or not 0 <= prefix_length <= max_prefix_length
                or (
                    embedded_prefix_length is not None
                    and prefix_length != embedded_prefix_length
                )
            ):
                raise RuntimeError("CMDB CLI接口快照包含与IP版本不匹配的掩码长度")

            context_source = str(raw_address.get("context_source") or "cli").strip().lower()
            context_type = str(raw_address.get("context_type") or "unknown").strip().lower()
            local_context_key = str(raw_address.get("local_context_key") or "").strip()
            local_context_name = str(raw_address.get("local_context_name") or "").strip()
            if context_source not in {"cli", "snmp"}:
                raise RuntimeError("CMDB CLI接口快照包含无效路由上下文来源")
            if context_type not in {"vrf", "global", "unknown"}:
                raise RuntimeError("CMDB CLI接口快照包含无效路由上下文类型")
            if context_type in {"vrf", "global"} and not local_context_key:
                raise RuntimeError("已知路由上下文必须包含本地上下文键")

            normalized_address = {
                "interface_name": address_interface_name,
                "context_source": context_source,
                "context_type": context_type,
                "local_context_key": local_context_key,
                "local_context_name": local_context_name,
                "ip_address": normalized_ip_address,
                "ip_prefix_length": prefix_length,
            }
            identity = (
                normalized_name, context_source, context_type, local_context_key,
                normalized_ip_address, prefix_length,
            )
            # Repeated identical parser rows represent one current address;
            # distinct contexts or masks remain separate observations.
            address_rows_by_identity[identity] = normalized_address

        # Duplicate address records were collapsed by the child-table key.
        address_rows = list(address_rows_by_identity.values())
        if len(address_rows) > 1:
            address_rows.sort(key=lambda address: (
                address["context_source"], address["context_type"],
                address["local_context_key"], address["ip_address"],
                address["ip_prefix_length"],
            ))
        single_address = address_rows[0] if len(address_rows) == 1 else None
        normalized_rows[normalized_name] = {
            "interface_name": interface_name,
            "description": str(item.get("description") or ""),
            "admin_status": str(item.get("admin_status") or "unknown"),
            "oper_status": str(item.get("oper_status") or "unknown"),
            "ip_address": single_address["ip_address"] if single_address else "",
            "ip_prefix_length": single_address["ip_prefix_length"] if single_address else None,
            "interface_type": infer_interface_type(interface_name),
            "addresses": address_rows,
        }

    observed_value = str(observed_at or "").strip()
    if observed_value:
        try:
            parsed_observed_at = datetime.fromisoformat(
                observed_value.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise RuntimeError("CMDB CLI接口快照包含无效观察时间") from exc
        if parsed_observed_at.tzinfo is None:
            parsed_observed_at = parsed_observed_at.replace(tzinfo=timezone.utc)
    else:
        parsed_observed_at = datetime.now(timezone.utc)
    child_observed_at = parsed_observed_at.isoformat()

    conn.execute(
        "DELETE FROM cmdb_device_interface_address_observations WHERE device_id = ?",
        (device_id,),
    )
    conn.execute(
        "DELETE FROM cmdb_device_interface_observations WHERE device_id = ?",
        (device_id,),
    )
    metadata_json = _json_metadata(metadata)
    for normalized_name, item in sorted(normalized_rows.items()):
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id, normalized_name, item["interface_name"], item["description"],
                item["admin_status"], item["oper_status"], item["ip_address"],
                item["ip_prefix_length"], item["interface_type"], generation,
                str(observed_at), run_id, metadata_json,
            ),
        )
        for address in item["addresses"]:
            conn.execute(
                """INSERT INTO cmdb_device_interface_address_observations (
                       device_id, normalized_interface_name, interface_name,
                       context_source, context_type, local_context_key,
                       local_context_name, ip_address, ip_prefix_length,
                       generation, observed_at, run_id, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB))""",
                (
                    device_id, normalized_name, address["interface_name"],
                    address["context_source"], address["context_type"],
                    address["local_context_key"], address["local_context_name"],
                    address["ip_address"], address["ip_prefix_length"],
                    generation, child_observed_at, run_id, metadata_json,
                ),
            )
    try:
        from services.ipam_radix_index_service import invalidate_ipam_radix_index
        invalidate_ipam_radix_index()
    except Exception:
        pass
    return len(normalized_rows)


def _single_record_value(record: dict[str, Any], *keys: str) -> str:
    normalized = {
        str(key).strip().replace("-", "_").upper(): value
        for key, value in record.items()
    }
    for key in keys:
        value = normalized.get(str(key).strip().replace("-", "_").upper())
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            values = list(dict.fromkeys(
                str(item).strip() for item in value
                if item is not None and str(item).strip()
            ))
            if len(values) > 1:
                raise RuntimeError("CMDB VLAN CLI记录包含无法无损表示的多个字段值")
            if values:
                return values[0]
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _field_values(record: dict[str, Any], *keys: str) -> list[Any]:
    normalized = {
        str(key).strip().replace("-", "_").upper(): value
        for key, value in record.items()
    }
    values: list[Any] = []
    for key in keys:
        value = normalized.get(str(key).strip().replace("-", "_").upper())
        if value is None:
            continue
        values.extend(value if isinstance(value, (list, tuple, set)) else [value])
    return values


def _port_tokens(value: Any, *, forced_tagging: str | None = None) -> Iterable[tuple[str, str]]:
    entries = value if isinstance(value, (list, tuple, set)) else [value]
    for entry in entries:
        active_tagging = forced_tagging or "unknown"
        for token in re.split(r"[,;\s]+", str(entry or "").strip()):
            if not token:
                continue
            tag_match = _PORT_TAG_RE.match(token)
            if tag_match:
                active_tagging = "untagged" if tag_match.group(1).upper() == "UT" else "tagged"
                token = tag_match.group(2)
            interface_name = _PORT_STATE_SUFFIX_RE.sub("", token)
            if interface_name:
                yield interface_name, active_tagging


def _explicit_port_mode(record: dict[str, Any]) -> tuple[str, str]:
    raw_mode = _single_record_value(record, "mode", "port_mode")
    normalized = raw_mode.strip().lower().replace("_", "-")
    if normalized in {"access", "access-port"}:
        return "access", raw_mode
    if normalized in {"trunk", "trunk-port"}:
        return "trunk", raw_mode
    return "unknown", raw_mode


def _merge_evidence(current: str, candidate: str) -> str:
    if current == "unknown":
        return candidate
    if candidate == "unknown" or current == candidate:
        return current
    return "unknown"


def _vlan_observations_from_records(
    records: list[dict[str, Any]],
    *,
    site_id: str,
    platform: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from services.interface_collection_service import _looks_like_interface_name

    vlan_by_id: dict[int, dict[str, Any]] = {}
    port_by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("VLAN CLI快照包含格式无效的记录")
        raw_vlan = _single_record_value(record, "vlan_id", "vlan", "vid")
        match = _VLAN_ID_RE.search(raw_vlan)
        if not match:
            raise RuntimeError("VLAN CLI快照包含缺少VLAN ID的记录")
        vlan_id = int(match.group(0))
        if not 1 <= vlan_id <= 4094:
            raise RuntimeError("VLAN CLI快照包含范围外的VLAN ID")
        vlan_name = _single_record_value(record, "vlan_name", "name", "description")
        if not vlan_name:
            raise RuntimeError("VLAN CLI快照包含缺少名称的记录")
        if is_system_default_vlan(
            vlan_id, vlan_name, platform=platform, discovery_source="vlan_command",
        ):
            continue
        vlan_by_id[vlan_id] = {
            "vlan_id": vlan_id,
            "site_id": site_id,
            "vlan_name": vlan_name,
            "vlan_status": _single_record_value(record, "status", "vlan_status") or "active",
        }

        explicit_mode, raw_mode = _explicit_port_mode(record)
        raw_record_metadata = {"raw_port_mode": raw_mode} if raw_mode else {}
        candidates: list[tuple[str, str]] = []
        for field in ("ut", "untagged", "untagged_ports", "untagged_interfaces"):
            candidates.extend((name, tag) for name, tag in _port_tokens(
                _field_values(record, field), forced_tagging="untagged",
            ))
        for field in ("tg", "tagged", "tagged_ports", "tagged_interfaces"):
            candidates.extend((name, tag) for name, tag in _port_tokens(
                _field_values(record, field), forced_tagging="tagged",
            ))
        for field in ("interfaces", "interface", "ports", "port"):
            candidates.extend((name, tag) for name, tag in _port_tokens(
                _field_values(record, field),
            ))

        for interface_name, tagging in candidates:
            if not _looks_like_interface_name(interface_name):
                continue
            if parse_vlan_id_from_interface(interface_name) == vlan_id:
                # An SVI is captured in the interface observation snapshot;
                # it is not a VLAN port member.
                continue
            normalized_name = _normalized_name(interface_name)
            if not normalized_name:
                continue
            key = (vlan_id, normalized_name)
            current = port_by_key.get(key)
            if current is None:
                port_by_key[key] = {
                    "vlan_id": vlan_id,
                    "normalized_interface_name": normalized_name,
                    "interface_name": interface_name,
                    "port_mode": explicit_mode,
                    "tagging": tagging,
                    "metadata": raw_record_metadata,
                }
                continue
            current["port_mode"] = _merge_evidence(current["port_mode"], explicit_mode)
            current["tagging"] = _merge_evidence(current["tagging"], tagging)
            if raw_record_metadata:
                current["metadata"] = raw_record_metadata

    return (
        [vlan_by_id[vlan_id] for vlan_id in sorted(vlan_by_id)],
        [port_by_key[key] for key in sorted(port_by_key)],
    )


def replace_cmdb_vlan_observations(
    conn,
    attempt: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    site_id: str,
    platform: str,
    observed_at: str,
) -> dict[str, int]:
    """Replace a complete CMDB VLAN and port-member snapshot in one txn."""
    vlan_rows, port_rows = _vlan_observations_from_records(
        records, site_id=site_id, platform=platform,
    )
    device_id, generation, run_id = _lock_current_generation(
        conn, attempt, "vlan_inventory",
    )

    # Deleting the parent VLAN observations cascades the prior port membership
    # rows. Both tables are then rebuilt with the locked attempt generation.
    conn.execute(
        "DELETE FROM cmdb_device_vlan_observations WHERE device_id = ?",
        (device_id,),
    )
    for item in vlan_rows:
        conn.execute(
            """INSERT INTO cmdb_device_vlan_observations (
                   device_id, vlan_id, site_id, vlan_name, vlan_status,
                   generation, observed_at, run_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id, item["vlan_id"], item["site_id"], item["vlan_name"],
                item["vlan_status"], generation, str(observed_at), run_id,
            ),
        )
    for item in port_rows:
        conn.execute(
            """INSERT INTO cmdb_device_vlan_port_observations (
                   device_id, vlan_id, normalized_interface_name, interface_name,
                   port_mode, tagging, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id, item["vlan_id"], item["normalized_interface_name"],
                item["interface_name"], item["port_mode"], item["tagging"],
                generation, str(observed_at), run_id, _json_metadata(item["metadata"]),
            ),
        )
    return {"vlans": len(vlan_rows), "interfaces": len(port_rows)}
