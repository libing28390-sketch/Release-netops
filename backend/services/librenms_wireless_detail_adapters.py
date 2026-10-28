"""Pinned LibreNMS wireless detail adapters for Aruba Instant and Extreme EWC.

The adapters intentionally mirror the table indexes and sensor inputs used by
the bundled LibreNMS OS classes.  They only read pinned MIB symbols and never
execute upstream PHP.
"""

from __future__ import annotations

import math
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from database import get_db_connection


_ARUBA_MIB = "mibs/arubaos/AI-AP-MIB"
_EWC_MIB = "mibs/ewc/HIPATH-WIRELESS-HWC-MIB"
_EWC_DOT11_MIB = "mibs/ewc/HIPATH-WIRELESS-DOT11-EXTNS-MIB"

_ARUBA_SYMBOLS: dict[str, tuple[str, str]] = {
    "ap_table": (_ARUBA_MIB, "aiAccessPointTable"),
    "ap_mac": (_ARUBA_MIB, "aiAPMACAddress"),
    "ap_name": (_ARUBA_MIB, "aiAPName"),
    "ap_ip": (_ARUBA_MIB, "aiAPIPAddress"),
    "ap_serial": (_ARUBA_MIB, "aiAPSerialNum"),
    "ap_model": (_ARUBA_MIB, "aiAPModel"),
    "ap_model_name": (_ARUBA_MIB, "aiAPModelName"),
    "radio_clients": (_ARUBA_MIB, "aiRadioClientNum"),
    "radio_channel": (_ARUBA_MIB, "aiRadioChannel"),
    "radio_noise_floor": (_ARUBA_MIB, "aiRadioNoiseFloor"),
    "radio_tx_power": (_ARUBA_MIB, "aiRadioTransmitPower"),
    "radio_utilization": (_ARUBA_MIB, "aiRadioUtilization64"),
}

_EWC_SYMBOLS: dict[str, tuple[str, str]] = {
    "ap_clients": (_EWC_MIB, "apStatsMuCounts"),
    "ap_name": (_EWC_MIB, "apName"),
    # This table is indexed by IF-MIB::ifIndex (one integer).
    "radio_channel": (_EWC_MIB, "apRadioStatusChannel"),
    "radio_noise_floor": (_EWC_DOT11_MIB, "dot11ExtRadioMaxNfCount"),
    # These performance rows are indexed by apIndex, apRadioIndex.
    "radio_rssi": (_EWC_MIB, "apPerfRadioCurrentRSS"),
    "radio_snr": (_EWC_MIB, "apPerfRadioCurrentSNR"),
    "radio_utilization": (_EWC_MIB, "apPerfRadioCurrentChannelUtilization"),
    "radio_retransmits": (_EWC_MIB, "apPerfRadioPktRetx"),
}


def _numeric_suffix(value: Any) -> tuple[int, ...] | None:
    text = str(value or "").strip().strip(".")
    if not text or not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return None
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return None


def _fixed_mac_index(value: Any) -> tuple[tuple[int, ...], str] | None:
    """Decode the fixed-size MacAddress index used by AI-AP-MIB.

    MacAddress is six octets, so its OID index contains exactly six arcs and
    has no leading length arc.  Keeping that distinction matters when the
    first octet itself is 6.
    """
    parts = _numeric_suffix(value)
    if parts is None or len(parts) != 6 or any(part > 255 for part in parts):
        return None
    mac = ":".join(f"{part:02x}" for part in parts)
    return parts, mac


def _aruba_radio_index(value: Any) -> tuple[tuple[int, ...], str, int] | None:
    parts = _numeric_suffix(value)
    if parts is None or len(parts) != 7 or any(part > 255 for part in parts[:6]):
        return None
    if parts[6] <= 0:
        return None
    mac = ":".join(f"{part:02x}" for part in parts[:6])
    return parts, mac, parts[6]


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _version_tuple(value: Any) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:\.\d+)+", str(value or ""))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(0).split("."))
    except ValueError:
        return None


def _version_at_least(value: Any, minimum: str) -> bool | None:
    actual = _version_tuple(value)
    threshold = _version_tuple(minimum)
    if actual is None or threshold is None:
        return None
    width = max(len(actual), len(threshold))
    return actual + (0,) * (width - len(actual)) >= threshold + (0,) * (width - len(threshold))


def _row_map(result: Any) -> dict[str, str]:
    return {
        str(index).strip().strip("."): str(value)
        for index, value in (getattr(result, "rows", []) or [])
    }


def _read_complete(result: Any) -> bool:
    return bool(result is not None and getattr(result, "complete", False) and not getattr(result, "reason", ""))


def _status(sensor_count: int, complete: bool) -> str:
    if sensor_count:
        return "success" if complete else "partial"
    return "not_found" if complete else "failed"


def _resolve_symbols(
    symbols_to_resolve: Mapping[str, tuple[str, str]],
) -> tuple[dict[str, str], set[str]]:
    from services import snmp_hardware_probe_service as probe

    resolved: dict[str, str] = {}
    missing: set[str] = set()
    conn = None
    try:
        conn = get_db_connection()
    except Exception:
        conn = None

    try:
        cache: dict[tuple[str, str], str] = {}
        for key, (mib_path, symbol) in symbols_to_resolve.items():
            oid = probe._resolve_pinned_librenms_mib_symbol(
                conn,
                mib_path,
                symbol,
                cache=cache,
            )
            if oid:
                resolved[key] = str(oid).strip().strip(".")
            else:
                missing.add(key)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return resolved, missing


def _walk_rows(reads: Mapping[str, Any], symbols: Mapping[str, str]) -> tuple[dict[str, dict[str, str]], dict[str, bool]]:
    rows = {key: _row_map(reads.get(oid)) for key, oid in symbols.items()}
    complete = {key: _read_complete(reads.get(oid)) for key, oid in symbols.items()}
    return rows, complete


def _lineage(source_rule: Mapping[str, Any], os_key: str) -> dict[str, Any]:
    from services.librenms_source_policy import PINNED_LIBRENMS_COMMIT

    return {
        **dict(source_rule),
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": f"Python adapter for pinned LibreNMS {os_key} wireless details",
        "identity_os_key": os_key,
    }


def _table_mac_indexes(rows: Mapping[str, str]) -> tuple[set[str], int]:
    indexes: set[str] = set()
    invalid = 0
    for suffix in rows:
        parts = _numeric_suffix(suffix)
        if parts is None or len(parts) < 6:
            invalid += 1
            continue
        mac_index = _fixed_mac_index(".".join(str(part) for part in parts[-6:]))
        if mac_index is None:
            invalid += 1
            continue
        indexes.add(".".join(str(part) for part in mac_index[0]))
    return indexes, invalid


def _identity_at(rows: Mapping[str, str], suffix: str) -> str:
    return str(rows.get(suffix, "") or "").strip()[:160]


def _aruba_channel_frequency(raw: Any) -> float | None:
    # Pinned ArubaInstant.php strips non-digits and masks off channel width
    # information before calling LibreNMS Wireless::channelToFrequency().
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return None
    channel = int(digits) & 255
    frequencies = {
        1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437, 7: 2442,
        8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472,
        14: 2484, 34: 5170, 36: 5180, 38: 5190, 40: 5200, 42: 5210,
        44: 5220, 46: 5230, 48: 5240, 52: 5260, 56: 5280, 60: 5300,
        64: 5320, 100: 5500, 104: 5520, 108: 5540, 112: 5560,
        116: 5580, 120: 5600, 124: 5620, 128: 5640, 132: 5660,
        136: 5680, 140: 5700, 149: 5745, 153: 5765, 157: 5785,
        161: 5805, 165: 5825,
    }
    return float(frequencies.get(channel, 0))


def _emit_sensor(
    make_sensor: Callable[..., dict[str, Any] | None],
    *,
    source_id: str,
    component_class: str,
    sensor_class: str,
    oid: str,
    suffix: str,
    raw: Any,
    value: float,
    unit: str,
    name: str,
    labels: Mapping[str, Any],
    lineage: Mapping[str, Any],
    poll_factor: float = 1.0,
    poll_transform: str = "",
) -> dict[str, Any] | None:
    sensor = make_sensor(
        source_id=source_id,
        component_class=component_class,
        measurement_type="wireless_sensor_value",
        oid=oid,
        suffix=suffix,
        raw_value=raw,
        value=value,
        unit=unit,
        name=name,
        labels=labels,
        metadata={**dict(lineage), "wireless_sensor_class": sensor_class},
        poll_plan={
            "kind": "direct",
            "oid": oid,
            "index": suffix,
            "factor": poll_factor,
            "offset": 0.0,
            **({"value_transform": poll_transform} if poll_transform else {}),
        },
    )
    if sensor:
        sensor["index_labels"].update(dict(labels))
    return sensor


async def _probe_aruba_instant(
    *,
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    source_rule: Mapping[str, Any],
    version: str,
    software_version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    probe: Any,
    make_sensor: Callable[..., dict[str, Any] | None],
    make_category_result: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    supports_radio_client_counts = _version_at_least(software_version, "8.4.0.0")
    symbol_specs = {
        key: value
        for key, value in _ARUBA_SYMBOLS.items()
        if key != "radio_clients" or supports_radio_client_counts is True
    }
    symbols, missing = _resolve_symbols(symbol_specs)
    reads = await probe._walk_many(
        ip,
        community,
        set(symbols.values()),
        port,
        version,
        walk_func=walk_func,
    )
    rows, walk_complete = _walk_rows(reads, symbols)
    lineage = _lineage(source_rule, "aruba-instant")
    sensors: list[dict[str, Any]] = []

    table_macs, invalid_table_indexes = _table_mac_indexes(rows.get("ap_table", {}))
    mac_rows: dict[str, str] = {}
    invalid_mac_indexes = 0
    for suffix, raw in rows.get("ap_mac", {}).items():
        parsed = _fixed_mac_index(suffix)
        if parsed is None:
            invalid_mac_indexes += 1
            continue
        mac_suffix = ".".join(str(part) for part in parsed[0])
        mac_rows[mac_suffix] = raw

    ap_indexes = set(mac_rows) | table_macs
    ap_rows: dict[str, dict[str, str]] = {}
    invalid_identity_indexes = invalid_table_indexes + invalid_mac_indexes
    for key in ("ap_name", "ap_ip", "ap_serial", "ap_model", "ap_model_name"):
        parsed_rows: dict[str, str] = {}
        for suffix, raw in rows.get(key, {}).items():
            parsed = _fixed_mac_index(suffix)
            if parsed is None:
                invalid_identity_indexes += 1
                continue
            normalized_suffix = ".".join(str(part) for part in parsed[0])
            parsed_rows[normalized_suffix] = raw
        ap_rows[key] = parsed_rows
        ap_indexes.update(parsed_rows)

    ap_identity_complete = (
        all(walk_complete.get(key, False) for key in ("ap_table", "ap_mac", "ap_name", "ap_ip", "ap_serial", "ap_model", "ap_model_name"))
        and not any(key in missing for key in ("ap_table", "ap_mac", "ap_name", "ap_ip", "ap_serial", "ap_model", "ap_model_name"))
        and invalid_identity_indexes == 0
    )
    # Table row presence is based on the AP table/index, never on aiAPStatus or
    # a radio admin/oper state.  It remains visible in category coverage even
    # when the AP currently has no radio sample.
    for suffix in sorted(ap_indexes):
        if suffix not in mac_rows or suffix not in table_macs:
            ap_identity_complete = False
        if not all(ap_rows[key].get(suffix, "").strip() for key in ("ap_name", "ap_ip", "ap_serial")):
            ap_identity_complete = False
        if not (ap_rows["ap_model"].get(suffix) or ap_rows["ap_model_name"].get(suffix)):
            ap_identity_complete = False

    ap_category = make_category_result(
        "wireless_access_point",
        status=_status(len(ap_indexes), ap_identity_complete),
        complete=ap_identity_complete,
        reason_code=("aruba_instant_ap_table" if ap_indexes and ap_identity_complete else "invalid_aruba_instant_ap_index" if invalid_identity_indexes else "aruba_instant_ap_identity_incomplete" if ap_indexes else "no_aruba_instant_ap_rows" if ap_identity_complete else "aruba_instant_ap_walk_incomplete"),
        reason=(f"Pinned Aruba Instant AP table returned {len(ap_indexes)} AP row(s) with indexed identity." if ap_indexes and ap_identity_complete else f"Aruba Instant AP tables contained {invalid_identity_indexes} invalid index row(s)." if invalid_identity_indexes else "One or more Aruba Instant AP identities are missing or inconsistent." if ap_indexes else "No Aruba Instant AP rows were returned." if ap_identity_complete else "The Aruba Instant AP table or an exact identity symbol did not complete."),
    )

    identity_by_mac: dict[str, dict[str, str]] = {}
    for suffix in ap_indexes:
        parsed = _fixed_mac_index(suffix)
        if not parsed:
            continue
        mac = parsed[1]
        model = _identity_at(ap_rows["ap_model_name"], suffix) or _identity_at(ap_rows["ap_model"], suffix)
        identity_by_mac[mac] = {
            "ap_name": _identity_at(ap_rows["ap_name"], suffix),
            "ap_ip": _identity_at(ap_rows["ap_ip"], suffix),
            "ap_serial": _identity_at(ap_rows["ap_serial"], suffix),
            "ap_model": model,
            "ap_mac": mac,
        }

    radio_keys = (
        (("radio_clients",) if supports_radio_client_counts is True else ())
        + ("radio_channel", "radio_noise_floor", "radio_tx_power", "radio_utilization")
    )
    radio_suffixes: dict[str, dict[str, str]] = {}
    invalid_radio_indexes = 0
    for key in radio_keys:
        indexed: dict[str, str] = {}
        for suffix, raw in rows.get(key, {}).items():
            parsed = _aruba_radio_index(suffix)
            if parsed is None:
                invalid_radio_indexes += 1
                continue
            normalized_suffix = ".".join(str(part) for part in parsed[0])
            indexed[normalized_suffix] = raw
        radio_suffixes[key] = indexed

    radio_indexes = set().union(*(set(radio_suffixes[key]) for key in radio_keys))
    required_radio_reads_complete = all(
        walk_complete.get(key, False) and key not in missing
        for key in radio_keys
    )
    rows_aligned = all(
        set(radio_suffixes[key]) == radio_indexes
        for key in radio_keys
    )
    invalid_radio_values = 0

    specs = (
        (("radio_clients", "clients", "count", "Clients", "clients") if supports_radio_client_counts is True else None),
        ("radio_channel", "frequency", "MHz", "Frequency", "frequency"),
        ("radio_noise_floor", "noise-floor", "dBm", "Noise Floor", "noise"),
        ("radio_tx_power", "power", "dBm", "Tx Power", "number"),
        ("radio_utilization", "utilization", "percent", "Utilization", "percent"),
    )
    for suffix in sorted(radio_indexes):
        parsed = _aruba_radio_index(suffix)
        if not parsed:
            invalid_radio_indexes += 1
            continue
        _parts, mac, radio_index = parsed
        ap_identity = identity_by_mac.get(mac, {})
        if not ap_identity:
            invalid_radio_values += 1
        labels = {**ap_identity, "radio_index": radio_index}
        ap_label = ap_identity.get("ap_name") or ap_identity.get("ap_serial") or mac

        for spec in specs:
            if spec is None:
                continue
            key, sensor_class, unit, title, transform = spec
            raw = radio_suffixes[key].get(suffix)
            if raw is None:
                continue
            if transform == "frequency":
                value = _aruba_channel_frequency(raw)
            else:
                number = _number(raw)
                if number is None:
                    value = None
                elif transform == "noise":
                    # Pinned ArubaInstant.php passes aiRadioNoiseFloor * -1.
                    value = -number
                else:
                    value = number
                if value is not None and (transform == "clients" and value < 0 or transform == "percent" and not 0 <= value <= 100 or transform == "number" and value < 0):
                    value = None
            if value is None:
                invalid_radio_values += 1
                continue
            oid = symbols.get(key)
            if not oid:
                continue
            sensor = _emit_sensor(
                make_sensor,
                source_id=f"wireless_aruba_instant:radio:{sensor_class}:{mac.replace(':', '')}:{radio_index}",
                component_class="wireless_radio",
                sensor_class=sensor_class,
                oid=oid,
                suffix=suffix,
                raw=raw,
                value=value,
                unit=unit,
                name=f"{ap_label} Radio {radio_index} {title}",
                labels=labels,
                lineage=lineage,
                poll_factor=-1.0 if transform == "noise" else 1.0,
                poll_transform="aruba_instant_channel_to_frequency" if transform == "frequency" else "",
            )
            if sensor:
                sensors.append(sensor)

    radio_complete = (
        supports_radio_client_counts is not None
        and required_radio_reads_complete
        and rows_aligned
        and not invalid_radio_indexes
        and not invalid_radio_values
    )
    if supports_radio_client_counts is None:
        radio_reason_code = "aruba_instant_software_version_unknown"
        radio_reason = "Aruba Instant software version is unavailable, so version-gated client counters cannot be verified."
    elif radio_indexes and radio_complete:
        radio_reason_code = "aruba_instant_radio_details"
        radio_reason = f"Pinned Aruba Instant radio tables returned {len(radio_indexes)} AP/radio row(s)."
    elif invalid_radio_indexes or invalid_radio_values:
        radio_reason_code = "invalid_aruba_instant_radio_row"
        radio_reason = f"Aruba Instant radio tables contained {invalid_radio_indexes + invalid_radio_values} invalid or unjoined row/value(s)."
    elif radio_indexes:
        radio_reason_code = "aruba_instant_radio_rows_incomplete"
        radio_reason = "Aruba Instant radio tables did not contain matching rows for every required metric."
    elif radio_complete:
        radio_reason_code = "no_aruba_instant_radio_rows"
        radio_reason = "No Aruba Instant radio rows were returned."
    else:
        radio_reason_code = "aruba_instant_radio_walk_incomplete"
        radio_reason = "One or more Aruba Instant radio walks or exact symbols did not complete."
    radio_category = make_category_result(
        "wireless_radio",
        status=_status(sum(sensor.get("component_class") == "wireless_radio" for sensor in sensors), radio_complete),
        complete=radio_complete,
        reason_code=radio_reason_code,
        reason=radio_reason,
    )
    return {"sensors": sensors, "category_results": [ap_category, radio_category]}


async def _probe_ewc(
    *,
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    source_rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
    probe: Any,
    make_sensor: Callable[..., dict[str, Any] | None],
    make_category_result: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    symbols, missing = _resolve_symbols(_EWC_SYMBOLS)
    reads = await probe._walk_many(
        ip,
        community,
        set(symbols.values()),
        port,
        version,
        walk_func=walk_func,
    )
    rows, walk_complete = _walk_rows(reads, symbols)
    lineage = _lineage(source_rule, "ewc")
    sensors: list[dict[str, Any]] = []

    ap_names: dict[str, str] = {}
    invalid_ap_indexes = 0
    for suffix, raw in rows.get("ap_name", {}).items():
        parts = _numeric_suffix(suffix)
        if parts is None or len(parts) != 1 or parts[0] <= 0:
            invalid_ap_indexes += 1
            continue
        ap_names[str(parts[0])] = str(raw).strip()[:160]

    ap_client_rows: dict[str, str] = {}
    for suffix, raw in rows.get("ap_clients", {}).items():
        parts = _numeric_suffix(suffix)
        if parts is None or len(parts) != 1 or parts[0] <= 0:
            invalid_ap_indexes += 1
            continue
        ap_client_rows[str(parts[0])] = raw

    ap_indexes = set(ap_names) | set(ap_client_rows)
    invalid_ap_values = 0
    ap_complete = (
        walk_complete.get("ap_name", False)
        and walk_complete.get("ap_clients", False)
        and not (missing & {"ap_name", "ap_clients"})
        and invalid_ap_indexes == 0
    )
    for ap_index in sorted(ap_indexes, key=int):
        raw = ap_client_rows.get(ap_index)
        name = ap_names.get(ap_index, "")
        if raw is None or not name:
            ap_complete = False
        if raw is None:
            continue
        value = _number(raw)
        if value is None or value < 0:
            invalid_ap_values += 1
            ap_complete = False
            continue
        oid = symbols.get("ap_clients")
        if not oid:
            continue
        ap_label = name or f"AP {ap_index}"
        sensor = _emit_sensor(
            make_sensor,
            source_id=f"wireless_ewc:ap:clients:{ap_index}",
            component_class="wireless_access_point",
            sensor_class="clients",
            oid=oid,
            suffix=ap_index,
            raw=raw,
            value=value,
            unit="count",
            name=f"Clients ({ap_label})",
            labels={"ap_index": int(ap_index), "ap_name": name},
            lineage=lineage,
        )
        if sensor:
            sensors.append(sensor)

    ap_category = make_category_result(
        "wireless_access_point",
        status=_status(sum(sensor.get("component_class") == "wireless_access_point" for sensor in sensors), ap_complete),
        complete=ap_complete,
        reason_code=("ewc_ap_client_rows" if ap_client_rows and ap_complete else "invalid_ewc_ap_row" if invalid_ap_indexes or invalid_ap_values else "ewc_ap_identity_incomplete" if ap_indexes else "no_ewc_ap_rows" if ap_complete else "ewc_ap_walk_incomplete"),
        reason=(f"Pinned EWC AP client table returned {len(ap_client_rows)} indexed AP row(s)." if ap_client_rows and ap_complete else f"EWC AP tables contained {invalid_ap_indexes + invalid_ap_values} invalid row/value(s)." if invalid_ap_indexes or invalid_ap_values else "EWC AP client rows are missing matching apName values." if ap_indexes else "No EWC AP rows were returned." if ap_complete else "The EWC AP client/name walk or exact symbol lookup did not complete."),
    )

    radio_specs = (
        # EWC's status/noise tables are indexed by a single IF-MIB ifIndex.
        ("radio_channel", "frequency", "channel", "Channel", "ifindex"),
        ("radio_noise_floor", "noise-floor", "dBm", "Noise Floor", "ifindex"),
        # The EWC performance table is indexed by apIndex.apRadioIndex.
        ("radio_rssi", "rssi", "dBm", "RSSI", "ap_radio"),
        ("radio_snr", "snr", "dB", "SNR", "ap_radio"),
        ("radio_utilization", "utilization", "percent", "Utilization", "ap_radio"),
        ("radio_retransmits", "errors", "count", "Retransmits", "ap_radio"),
    )
    parsed_radio_rows: dict[str, dict[tuple[int, ...], str]] = {}
    invalid_radio_indexes = 0
    invalid_radio_values = 0
    for key, _sensor_class, _unit, _title, index_kind in radio_specs:
        indexed: dict[tuple[int, ...], str] = {}
        for suffix, raw in rows.get(key, {}).items():
            parts = _numeric_suffix(suffix)
            expected_length = 1 if index_kind == "ifindex" else 2
            if parts is None or len(parts) != expected_length or any(part <= 0 for part in parts):
                invalid_radio_indexes += 1
                continue
            if index_kind == "ap_radio" and (parts[0] not in {int(index) for index in ap_indexes} or parts[1] > 2):
                # apRadioIndex is 1..2 in the pinned MIB.  Keep the parent AP
                # index in position 0, as the source OS does when labeling it.
                invalid_radio_indexes += 1
                continue
            indexed[parts] = raw
        parsed_radio_rows[key] = indexed

    radio_index_groups = (
        ("radio_channel", "radio_noise_floor"),
        ("radio_rssi", "radio_snr", "radio_utilization", "radio_retransmits"),
    )
    group_indexes = {
        group[0]: set().union(*(set(parsed_radio_rows[key]) for key in group))
        for group in radio_index_groups
    }
    all_radio_indexes: set[tuple[int, ...]] = set().union(*group_indexes.values())
    radio_reads_complete = all(
        walk_complete.get(key, False) and key not in missing
        for key, _sensor_class, _unit, _title, _index_kind in radio_specs
    )
    radio_rows_aligned = all(
        set(parsed_radio_rows[key]) == group_indexes[group[0]]
        for group in radio_index_groups
        for key in group
    )
    nonempty_group_sizes = [len(indexes) for indexes in group_indexes.values() if indexes]
    if len(nonempty_group_sizes) == 1 and len(group_indexes) > 1:
        radio_rows_aligned = False
    elif len(nonempty_group_sizes) > 1 and len(set(nonempty_group_sizes)) > 1:
        radio_rows_aligned = False

    for key, sensor_class, unit, title, index_kind in radio_specs:
        oid = symbols.get(key)
        if not oid:
            continue
        for parts, raw in sorted(parsed_radio_rows[key].items()):
            suffix = ".".join(str(part) for part in parts)
            number = _number(raw)
            if number is None:
                invalid_radio_values += 1
                continue

            if index_kind == "ifindex":
                index_label = parts[0]
                labels: dict[str, Any] = {"if_index": index_label, "radio_if_index": index_label}
                entity_name = f"Radio ifIndex {index_label}"
                identity = f"ifindex:{index_label}"
            else:
                ap_index, radio_index = parts
                ap_name = ap_names.get(str(ap_index), "")
                if not ap_name:
                    invalid_radio_values += 1
                labels = {"ap_index": ap_index, "ap_name": ap_name, "radio_index": radio_index}
                entity_name = ap_name or f"AP {ap_index}"
                identity = f"ap:{ap_index}:radio:{radio_index}"

            sensor = _emit_sensor(
                make_sensor,
                source_id=f"wireless_ewc:radio:{sensor_class}:{identity}",
                component_class="wireless_radio",
                sensor_class=sensor_class,
                oid=oid,
                suffix=suffix,
                raw=raw,
                value=number,
                unit=unit,
                name=f"{title} ({entity_name})",
                labels=labels,
                lineage=lineage,
            )
            if sensor:
                sensors.append(sensor)

    radio_complete = radio_reads_complete and radio_rows_aligned and not invalid_radio_indexes and not invalid_radio_values
    radio_count = sum(sensor.get("component_class") == "wireless_radio" for sensor in sensors)
    radio_category = make_category_result(
        "wireless_radio",
        status=_status(radio_count, radio_complete),
        complete=radio_complete,
        reason_code=("ewc_radio_detail_rows" if all_radio_indexes and radio_complete else "invalid_ewc_radio_row" if invalid_radio_indexes or invalid_radio_values else "ewc_radio_metric_rows_incomplete" if all_radio_indexes else "no_ewc_radio_rows" if radio_complete else "ewc_radio_walk_incomplete"),
        reason=(f"Pinned EWC radio tables returned {len(all_radio_indexes)} indexed radio row(s)." if all_radio_indexes and radio_complete else f"EWC radio tables contained {invalid_radio_indexes + invalid_radio_values} invalid, unavailable, or unjoined row/value(s)." if invalid_radio_indexes or invalid_radio_values else "EWC radio tables did not contain matching rows for every requested metric." if all_radio_indexes else "No EWC radio rows were returned." if radio_complete else "One or more EWC radio walks or exact symbols did not complete."),
    )
    return {"sensors": sensors, "category_results": [ap_category, radio_category]}


async def probe_wireless_profile_details(
    os_key: str,
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    source_rule: Mapping[str, Any],
    version: str,
    software_version: str = "",
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Collect pinned LibreNMS wireless detail rows for supported OS profiles."""
    normalized_os_key = str(os_key or "").strip().casefold()
    if normalized_os_key not in {"aruba-instant", "ewc"}:
        return {"sensors": [], "category_results": []}

    # Keep these imports local: librenms_wireless_rule_service also dispatches
    # wireless probes and imports this adapter only from the service layer.
    from services import snmp_hardware_probe_service as probe
    from services.librenms_wireless_rule_service import _category_result, _sensor

    kwargs = {
        "ip": ip,
        "community": community,
        "port": port,
        "source_rule": source_rule,
        "version": version,
        "walk_func": walk_func,
        "probe": probe,
        "make_sensor": _sensor,
        "make_category_result": _category_result,
    }
    if normalized_os_key == "aruba-instant":
        return await _probe_aruba_instant(**kwargs, software_version=software_version)
    return await _probe_ewc(**kwargs)
