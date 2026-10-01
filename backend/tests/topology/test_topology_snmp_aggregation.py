import asyncio

import pytest

from services import topology_snmp_aggregation_service as service


DEVICE = {"id": "device-1", "ip_address": "192.0.2.10"}
CREDENTIALS = {
    "snmp": {
        "server": "192.0.2.10",
        "community": "test-read-only",
        "port": 1161,
        "version": "2c",
    }
}


def _base_tables(parent_name="Bridge-Aggregation12", member_names=None):
    member_names = member_names or {
        50: "Ten-GigabitEthernet1/0/1",
        51: "Ten-GigabitEthernet1/0/2",
        52: "Ten-GigabitEthernet1/0/3",
        53: "Ten-GigabitEthernet1/0/4",
    }
    names = [(str(index), name) for index, name in member_names.items()]
    names.append(("5130", parent_name))
    types = [(str(index), "ethernetCsmacd(6)") for index in member_names]
    types.append(("5130", "ieee8023adLag(161)"))
    attached = [(str(index), "5130") for index in member_names]
    statuses = [(str(index), "up(1)") for index in member_names]
    statuses.append(("5130", "up(1)"))
    speeds = [(str(index), "10000") for index in member_names]
    speeds.append(("5130", "40000"))
    return {
        service.IF_NAME_OID: names,
        service.IF_TYPE_OID: types,
        service.IF_DESCR_OID: [],
        service.IF_OPER_STATUS_OID: statuses,
        service.IF_HIGH_SPEED_OID: speeds,
        service.ATTACHED_AGG_ID_OID: attached,
        service.IF_STACK_STATUS_OID: [],
    }


def _install_walk(monkeypatch, tables, *, failures=None):
    failures = failures or {}
    calls = []

    async def fake_walk(ip, community, oid, *, port, version, max_rows=service.MAX_ROWS, timeout=service.WALK_TIMEOUT_SECONDS):
        calls.append((ip, community, oid, port, version, max_rows, timeout))
        failure = failures.get(oid)
        if failure:
            if isinstance(failure, BaseException):
                raise failure
            raise failure()
        return list(tables.get(oid, []))

    monkeypatch.setattr(service, "latebound_snmp_walk", fake_walk)
    return calls


def collect():
    return asyncio.run(service.collect_snmp_aggregation_inventory(DEVICE, CREDENTIALS))


def test_h3c_attached_agg_id_collects_parent_and_four_members(monkeypatch):
    calls = _install_walk(monkeypatch, _base_tables())

    result = collect()

    assert result["status"] == "success"
    assert result["membership_source"] == "dot3adAggPortAttachedAggID"
    assert result["parents"] == [{
        "interface_name": "Bridge-Aggregation12",
        "if_index": 5130,
        "oper_status": "up",
        "speed_mbps": 40000.0,
    }]
    assert [record["member_if_index"] for record in result["records"]] == [50, 51, 52, 53]
    assert all(record["aggregation_protocol"] == "" for record in result["records"])
    assert calls and all(call[3:] == (1161, "2c", service.MAX_ROWS, service.WALK_TIMEOUT_SECONDS) for call in calls)


@pytest.mark.parametrize(
    ("parent_name", "member_name"),
    [
        ("Port-channel34", "TenGigabitEthernet1/0/1"),
        ("Route-Aggregation34", "XGigabitEthernet1/0/1"),
    ],
)
def test_vendor_interface_names_are_preserved_and_protocol_is_unknown(monkeypatch, parent_name, member_name):
    tables = _base_tables(parent_name, {2: member_name})
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "success"
    assert result["parents"][0]["interface_name"] == parent_name
    assert result["records"][0]["member_interface"] == member_name
    assert result["records"][0]["aggregation_protocol"] == ""


def test_all_zero_attached_table_is_authoritative_empty_snapshot(monkeypatch):
    tables = _base_tables()
    tables[service.ATTACHED_AGG_ID_OID] = [(str(index), "0") for index in (50, 51, 52, 53)]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "success"
    assert result["records"] == []
    assert result["parents"]


def test_ifname_can_fall_back_to_ifdescr(monkeypatch):
    tables = _base_tables()
    tables[service.IF_NAME_OID] = []
    tables[service.IF_DESCR_OID] = [
        ("50", "GigabitEthernet1/0/1"),
        ("5130", "Bridge-Aggregation12"),
    ]
    tables[service.ATTACHED_AGG_ID_OID] = [("50", "5130")]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "success"
    assert result["records"][0]["member_interface"] == "GigabitEthernet1/0/1"


def test_missing_optional_status_and_speed_remain_unknown(monkeypatch):
    tables = _base_tables()
    tables.pop(service.IF_OPER_STATUS_OID)
    tables.pop(service.IF_HIGH_SPEED_OID)
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "success"
    assert result["parents"][0]["oper_status"] == "unknown"
    assert result["parents"][0]["speed_mbps"] is None
    assert result["records"][0]["member_oper_status"] == "unknown"
    assert result["records"][0]["member_speed_mbps"] is None


@pytest.mark.parametrize("type_rows", [[], [("50", "6"), ("5130", "161")]])
def test_empty_or_incomplete_type_table_cannot_clear_inventory(monkeypatch, type_rows):
    tables = _base_tables()
    tables[service.IF_TYPE_OID] = type_rows
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "partial"
    assert result["detail"] in {"SNMP_IF_TYPE_TABLE_EMPTY", "SNMP_IF_TYPE_INDEX_MISSING"}


def test_duplicate_attached_rows_are_deduplicated_but_conflicting_parent_is_rejected(monkeypatch):
    tables = _base_tables()
    tables[service.ATTACHED_AGG_ID_OID] = [("50", "0"), ("50", "5130")]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "partial"
    assert result["detail"] == "SNMP_AGGREGATION_INDEX_CONFLICT"


def test_empty_attached_table_uses_active_ifstack_fallback(monkeypatch):
    tables = _base_tables()
    tables[service.ATTACHED_AGG_ID_OID] = []
    tables[service.IF_STACK_STATUS_OID] = [("5130.50", "active(1)")]
    tables[service.IF_NAME_OID] = [("50", "GigabitEthernet1/0/1"), ("5130", "Route-Aggregation34")]
    tables[service.IF_TYPE_OID] = [("50", "6"), ("5130", "161")]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "success"
    assert result["membership_source"] == "ifStackStatus"
    assert result["records"][0]["member_if_index"] == 50


def test_empty_membership_tables_with_lag_parent_are_not_safe_to_clear(monkeypatch):
    tables = _base_tables()
    tables[service.ATTACHED_AGG_ID_OID] = []
    tables[service.IF_STACK_STATUS_OID] = []
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "unavailable"
    assert result["detail"] == "SNMP_MEMBERSHIP_TABLE_EMPTY"


def test_no_lag_parent_and_complete_if_table_is_empty_success(monkeypatch):
    tables = _base_tables()
    tables[service.IF_NAME_OID] = [("50", "GigabitEthernet1/0/1")]
    tables[service.IF_TYPE_OID] = [("50", "6")]
    tables[service.ATTACHED_AGG_ID_OID] = []
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "success"
    assert result["records"] == []
    assert result["membership_source"] == "no_aggregation"


@pytest.mark.parametrize(
    ("failure_oid", "failure", "expected_status", "expected_detail"),
    [
        (service.ATTACHED_AGG_ID_OID, asyncio.TimeoutError, "failed", "SNMP_MEMBERSHIP_WALK_TIMEOUT"),
        (service.ATTACHED_AGG_ID_OID, service._AggregationCollectionError("SNMP_WALK_TRUNCATED"), "failed", "SNMP_WALK_TRUNCATED"),
        (service.ATTACHED_AGG_ID_OID, RuntimeError, "unavailable", "SNMP_ATTACHED_AGG_ID_UNAVAILABLE"),
    ],
)
def test_membership_transport_failures_never_emit_partial_records(
    monkeypatch, failure_oid, failure, expected_status, expected_detail
):
    _install_walk(monkeypatch, _base_tables(), failures={failure_oid: failure})

    result = collect()

    assert result["status"] == expected_status
    assert result["detail"] == expected_detail
    assert result["records"] == []


@pytest.mark.parametrize(
    ("tables_patch", "expected_detail"),
    [
        (lambda tables: tables[service.ATTACHED_AGG_ID_OID].__setitem__(0, ("50", "missing")), "SNMP_ATTACHED_AGG_ID_INDEX_MALFORMED"),
        (lambda tables: tables[service.ATTACHED_AGG_ID_OID].__setitem__(0, ("50", "9999")), "SNMP_AGGREGATION_PARENT_ORPHAN"),
        (lambda tables: tables[service.IF_TYPE_OID].extend([("5130", "6")]), "SNMP_IF_TYPE_INDEX_CONFLICT"),
    ],
)
def test_malformed_or_conflicting_rows_reject_snapshot(monkeypatch, tables_patch, expected_detail):
    tables = _base_tables()
    tables_patch(tables)
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "partial"
    assert result["detail"] == expected_detail


def test_ifstack_requires_8023ad_parent_and_named_physical_lower(monkeypatch):
    tables = _base_tables()
    tables[service.ATTACHED_AGG_ID_OID] = []
    tables[service.IF_STACK_STATUS_OID] = [("9999.50", "1")]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "partial"
    assert result["detail"] == "SNMP_IF_STACK_PARENT_INVALID"


def test_ifstack_skips_zero_endpoints_and_known_non_lag_higher_layers(monkeypatch):
    tables = _base_tables()
    tables[service.ATTACHED_AGG_ID_OID] = []
    tables[service.IF_STACK_STATUS_OID] = [("0.50", "1"), ("50.0", "1"), ("50.5130", "1")]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "unavailable"
    assert result["detail"] == "SNMP_MEMBERSHIP_TABLE_EMPTY"


def test_ifstack_member_cannot_belong_to_two_lags(monkeypatch):
    tables = _base_tables(parent_name="Bridge-Aggregation12", member_names={50: "GigabitEthernet1/0/1"})
    tables[service.IF_NAME_OID].append(("5131", "Bridge-Aggregation13"))
    tables[service.IF_TYPE_OID].append(("5131", "161"))
    tables[service.ATTACHED_AGG_ID_OID] = []
    tables[service.IF_STACK_STATUS_OID] = [("5130.50", "1"), ("5131.50", "1")]
    _install_walk(monkeypatch, tables)

    result = collect()

    assert result["status"] == "partial"
    assert result["detail"] == "SNMP_AGGREGATION_INDEX_CONFLICT"


def test_missing_credentials_is_unavailable_without_cli_or_ssh(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("SNMP walk should not run without resolved credentials")

    monkeypatch.setattr(service, "latebound_snmp_walk", fail_if_called)

    result = asyncio.run(service.collect_snmp_aggregation_inventory(DEVICE, {"ssh": {"username": "x"}}))

    assert result["status"] == "unavailable"
    assert result["detail"] == "SNMP_CREDENTIALS_OR_TARGET_INVALID"
