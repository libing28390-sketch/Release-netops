from __future__ import annotations

import asyncio

import pytest

from services import snmp_entity_model_service as service


def run(coro):
    return asyncio.run(coro)


def h3c_entity_rows():
    # Walk responses are deliberately ordered differently across columns.
    # Entity index 101 is the chassis; 201 and 301 are its MPU/SPU modules.
    return (
        [("201", "MPU 1"), ("301", "SPU 1"), ("101", "MSR56-60")],
        [("101", "chassis(3)"), ("301", "module(9)"), ("201", "module(9)")],
        [("301", "101"), ("201", "101"), ("101", "0")],
    )


def test_h3c_msr_chassis_is_selected_over_mpu_and_spu_modules():
    assert service._select_chassis_model(*h3c_entity_rows()) == "MSR56-60"


def test_h3c_s6850_is_selected_when_entity_table_exceeds_legacy_200_row_limit():
    model_rows = [(str(index), "H3C S6850") for index in range(1, 260)]
    class_rows = [("1", "stack(11)"), ("2", "chassis(3)")]
    class_rows.extend((str(index), "module(9)") for index in range(3, 260))
    contained_rows = [("1", "0"), ("2", "1")]
    contained_rows.extend((str(index), "2") for index in range(3, 260))

    assert service._select_chassis_model(model_rows, class_rows, contained_rows) == "H3C S6850"


@pytest.mark.parametrize("version", ["2c", "3"])
def test_import_model_reads_chassis_after_row_200_without_using_partial_tables(monkeypatch, version):
    from services import snmp_service

    # The chassis is deliberately the last entity, after 258 non-chassis rows.
    columns = {
        "1.3.6.1.2.1.47.1.1.1.1.13": [(str(i), "line-card") for i in range(1, 259)] + [("259", "H3C S6850")],
        "1.3.6.1.2.1.47.1.1.1.1.5": [(str(i), "module(9)") for i in range(1, 259)] + [("259", "chassis(3)")],
        "1.3.6.1.2.1.47.1.1.1.1.4": [(str(i), "259") for i in range(1, 259)] + [("259", "0")],
    }
    limits = []

    async def fake_walk(_ip, _credential, oid, **kwargs):
        limit = kwargs.get("max_rows", 200)
        limits.append(limit)
        rows = columns[oid]
        return WalkRows(rows[:limit], truncated=len(rows) >= limit)

    monkeypatch.setattr(snmp_service, "_snmp_walk", fake_walk)
    settings = {"version": version, "community": "fixture-only", "username": "fixture-user"}
    assert run(service.read_chassis_model("192.0.2.10", settings)) == "S6850"
    assert limits == [2000, 2000, 2000]


def test_entity_columns_are_joined_by_index_not_list_position():
    model_rows = [("80", "line-card-model"), ("9", "MSR56-60"), ("3", "power-module")]
    class_rows = [("3", "module(9)"), ("80", "module(9)"), ("9", "3")]
    contained_rows = [("9", "0"), ("80", "9"), ("3", "9")]

    assert service._select_chassis_model(model_rows, class_rows, contained_rows) == "MSR56-60"


def test_different_root_chassis_models_are_ambiguous():
    assert service._select_chassis_model(
        [("1", "MSR56-60"), ("2", "MSR36-20")],
        [("2", "chassis(3)"), ("1", "chassis(3)")],
        [("1", "0"), ("2", "0")],
    ) == ""


@pytest.mark.parametrize(
    "columns",
    [
        ([], [("1", "3")], [("1", "0")]),
        ([("1", "MSR56-60")], [], [("1", "0")]),
        ([("1", "MSR56-60")], [("1", "3")], []),
    ],
)
def test_empty_or_unsupported_entity_table_returns_empty(columns):
    assert service._select_chassis_model(*columns) == ""


def test_single_non_root_chassis_is_allowed_but_multiple_are_not():
    assert service._select_chassis_model(
        [("8", "MSR56-60")], [("8", "chassis(3)")], [("8", "2")]
    ) == "MSR56-60"
    assert service._select_chassis_model(
        [("8", "MSR56-60"), ("9", "MSR36-20")],
        [("8", "chassis(3)"), ("9", "chassis(3)")],
        [("8", "2"), ("9", "2")],
    ) == ""


def test_root_stack_is_used_only_when_no_chassis_rows_exist_and_model_is_unambiguous():
    assert service._select_chassis_model(
        [("12", "Stack-48")], [("12", "stack(11)")], [("12", "0")]
    ) == "Stack-48"
    assert service._select_chassis_model(
        [("12", "Stack-48"), ("13", "Stack-24")],
        [("12", "stack(11)"), ("13", "stack(11)")],
        [("12", "0"), ("13", "0")],
    ) == ""
    assert service._select_chassis_model(
        [("12", "Stack-48"), ("13", "MSR56-60")],
        [("12", "stack(11)"), ("13", "chassis(3)")],
        [("12", "0"), ("13", "0")],
    ) == "MSR56-60"


class WalkRows(list):
    def __init__(self, values, *, truncated=False):
        super().__init__(values)
        self.truncated = truncated


def test_v3_profile_fields_are_adapted_and_walk_limits_are_bounded(monkeypatch):
    from services import snmp_service

    observed = []
    columns = h3c_entity_rows()
    by_oid = dict(zip(
        (
            "1.3.6.1.2.1.47.1.1.1.1.13",
            "1.3.6.1.2.1.47.1.1.1.1.5",
            "1.3.6.1.2.1.47.1.1.1.1.4",
        ),
        columns,
    ))

    async def fake_walk(ip, credential, oid, **kwargs):
        observed.append((ip, credential, oid, kwargs))
        return WalkRows(by_oid[oid])

    monkeypatch.setattr(snmp_service, "_snmp_walk", fake_walk)
    settings = {
        "version": "3",
        "username": "probe-user",
        "auth_password": "auth-secret",
        "auth_method": "sha1",
        "priv_password": "priv-secret",
        "priv_method": "aes",
        "context_name": "system",
        "security_level": "authpriv",
        "port": 1161,
    }

    assert run(service.read_chassis_model("192.0.2.10", settings)) == "MSR56-60"
    assert len(observed) == 3
    for ip, profile, _oid, kwargs in observed:
        assert ip == "192.0.2.10"
        assert profile == {
            "username": "probe-user",
            "security_level": "authpriv",
            "auth_password": "auth-secret",
            "auth_protocol": "sha1",
            "priv_password": "priv-secret",
            "priv_protocol": "aes",
            "context_name": "system",
        }
        assert kwargs == {
            "port": 1161,
            "timeout": 3,
            "max_rows": 2000,
            "version": "3",
            "raise_on_error": True,
        }


def test_v2c_community_is_passed_to_bounded_walks(monkeypatch):
    from services import snmp_service

    observed = []
    columns = h3c_entity_rows()
    oids = (
        "1.3.6.1.2.1.47.1.1.1.1.13",
        "1.3.6.1.2.1.47.1.1.1.1.5",
        "1.3.6.1.2.1.47.1.1.1.1.4",
    )
    by_oid = dict(zip(oids, columns))

    async def fake_walk(ip, credential, oid, **kwargs):
        observed.append((credential, kwargs))
        return by_oid[oid]

    monkeypatch.setattr(snmp_service, "_snmp_walk", fake_walk)

    assert run(service.read_chassis_model(
        "192.0.2.10", {"version": "2c", "community": "read-only", "port": 161}
    )) == "MSR56-60"
    assert len(observed) == 3
    assert all(credential == "read-only" for credential, _kwargs in observed)
    assert all(kwargs["timeout"] == 3 and kwargs["max_rows"] == 2000 for _, kwargs in observed)
    assert all(kwargs["raise_on_error"] is True for _, kwargs in observed)


def test_entity_model_result_omits_manufacturer_prefix(monkeypatch):
    from services import snmp_service

    by_oid = {
        "1.3.6.1.2.1.47.1.1.1.1.13": [("1", "H3C S6850")],
        "1.3.6.1.2.1.47.1.1.1.1.5": [("1", "chassis(3)")],
        "1.3.6.1.2.1.47.1.1.1.1.4": [("1", "0")],
    }

    async def fake_walk(_ip, _credential, oid, **_kwargs):
        return by_oid[oid]

    monkeypatch.setattr(snmp_service, "_snmp_walk", fake_walk)

    assert run(service.read_chassis_model(
        "192.0.2.10", {"version": "2c", "community": "read-only", "port": 161}
    )) == "S6850"


@pytest.mark.parametrize("failure_mode", ["exception", "truncated", "row_limit", "empty"])
def test_walk_error_truncation_or_empty_result_returns_empty(monkeypatch, failure_mode):
    from services import snmp_service

    call_count = 0

    async def fake_walk(_ip, _credential, oid, **_kwargs):
        nonlocal call_count
        current = call_count
        call_count += 1
        if failure_mode == "exception" and current == 1:
            raise RuntimeError("walk failed")
        if failure_mode == "empty" and current == 1:
            return []
        if failure_mode == "truncated" and current == 1:
            return WalkRows([("1", "3")], truncated=True)
        if failure_mode == "row_limit" and current == 1:
            return [(str(index + 1), "3") for index in range(service._WALK_MAX_ROWS)]
        column = {
            "1.3.6.1.2.1.47.1.1.1.1.13": [("1", "MSR56-60")],
            "1.3.6.1.2.1.47.1.1.1.1.5": [("1", "chassis(3)")],
            "1.3.6.1.2.1.47.1.1.1.1.4": [("1", "0")],
        }
        return column[oid]

    monkeypatch.setattr(snmp_service, "_snmp_walk", fake_walk)

    assert run(service.read_chassis_model(
        "192.0.2.10", {"version": "2c", "community": "read-only", "port": 161}
    )) == ""
