from __future__ import annotations

import asyncio
import time
from collections import Counter

import pytest
from puresnmp.exc import NoSuchOID

from services import snmp_chassis_serial_reader as reader
from services import snmp_service


ENTITY = "1.3.6.1.2.1.47.1.1.1.1"
CLASS_OID = f"{ENTITY}.5"
PARENT_OID = f"{ENTITY}.4"
SERIAL_OID = f"{ENTITY}.11"
NAME_OID = f"{ENTITY}.7"
MODEL_OID = f"{ENTITY}.13"
UPTIME_OID = "1.3.6.1.2.1.1.3.0"
LAST_CHANGE_OID = "1.3.6.1.2.1.47.1.4.1.0"
H3C_FRAMES = (
    "1.3.6.1.4.1.25506.8.35.18.4.2.1.6",
    "1.3.6.1.4.1.2011.10.8.35.18.4.2.1.6",
)


def _settings(**overrides):
    settings = {"version": "2c", "community": "community-for-tests", "port": 1161}
    settings.update(overrides)
    return settings


def _walk(rows=(), *, truncated=False, octets=None):
    result = snmp_service.SnmpWalkResult(
        [(str(index), value) for index, value in rows],
        truncated=truncated,
        octet_values=octets or {},
    )
    return result


def _entity_walks(entities, *, truncated=(), octets=None):
    classes = [(index, entity[0]) for index, entity in entities.items()]
    parents = [(index, entity[1]) for index, entity in entities.items()]
    serials = [(index, entity[2]) for index, entity in entities.items() if entity[2] is not None]
    return {
        CLASS_OID: _walk(classes, truncated="class" in truncated),
        PARENT_OID: _walk(parents, truncated="parent" in truncated),
        SERIAL_OID: _walk(serials, truncated="serial" in truncated, octets=octets),
    }


class _Harness:
    def __init__(self, walks, *, gets=None, walk_delay=0.0, get_delay=0.0):
        self.walks = dict(walks)
        self.gets = dict(gets or {})
        self.walk_delay = walk_delay
        self.get_delay = get_delay
        self.walk_calls = []
        self.get_calls = []
        self.client_builds = []
        self.get_counts = Counter()
        self.active = 0
        self.maximum_active = 0
        self.cancelled_walks = 0
        self.walk_started = asyncio.Event()

    async def _slot(self, delay, *, walk=False):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        try:
            if delay:
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            if walk:
                self.cancelled_walks += 1
            raise
        finally:
            self.active -= 1

    async def walk(self, ip, credential, oid, port, **kwargs):
        self.walk_calls.append((ip, credential, oid, port, kwargs))
        self.walk_started.set()
        await self._slot(self.walk_delay, walk=True)
        result = self.walks.get(oid, _walk())
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return await result()
        return result

    async def get(self, oid):
        self.get_calls.append(oid)
        await self._slot(self.get_delay)
        response = self.gets.get(oid, NoSuchOID(None))
        if isinstance(response, (list, tuple)):
            position = self.get_counts[oid]
            self.get_counts[oid] += 1
            response = response[min(position, len(response) - 1)] if response else NoSuchOID(None)
        if isinstance(response, BaseException) and not isinstance(response, NoSuchOID):
            raise response
        return response

    def install(self, monkeypatch):
        monkeypatch.setattr(snmp_service, "_snmp_walk", self.walk)

        def build(ip, credential, port, version):
            self.client_builds.append((ip, credential, port, version))
            return object()

        monkeypatch.setattr(snmp_service, "_build_versioned_snmp_client", build)
        monkeypatch.setattr("puresnmp.PyWrapper", lambda _client: self)


def _stable_snapshot():
    return {
        UPTIME_OID: ["TimeTicks: (10000) 0:01:40.00", "TimeTicks: (10000) 0:01:40.00"],
        LAST_CHANGE_OID: ["3", "3"],
    }


@pytest.mark.parametrize("vendor", ["Cisco", "Huawei", "H3C"])
def test_standard_class3_discovers_four_high_indexes_across_vendors(monkeypatch, vendor):
    indexes = [101, 70002, 1_200_003, 2_147_483_647]
    entities = {
        index: (3, 0, f"SERIAL-{position + 100}")
        for position, index in enumerate(indexes)
    }
    harness = _Harness(_entity_walks(entities), gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.10", _settings(), vendor=vendor))

    assert result["source"] == "snmp_entity_discovery"
    assert result["status"] == "success"
    assert result["discovered_indices"] == indexes
    assert result["discovery_complete"] is True
    assert result["serial_complete"] is True
    assert [member["entity_index"] for member in result["members"]] == indexes
    assert [member["serial_number"] for member in result["members"]] == [
        "SERIAL-100", "SERIAL-101", "SERIAL-102", "SERIAL-103"
    ]
    assert all(set(member) == {
        "entity_index", "serial_number", "entity_name", "entity_description", "model"
    } for member in result["members"])
    core_calls = {call[2]: call[4] for call in harness.walk_calls if call[2] in {CLASS_OID, PARENT_OID, SERIAL_OID}}
    assert set(core_calls) == {CLASS_OID, PARENT_OID, SERIAL_OID}
    assert all(options["max_rows"] == 2000 and options["raise_on_error"] for options in core_calls.values())
    assert all(options["prefer_bulk"] and options["preserve_octets"] for options in core_calls.values())
    if vendor == "H3C":
        assert set(H3C_FRAMES).issubset({call[2] for call in harness.walk_calls})
    else:
        assert not set(H3C_FRAMES).intersection(call[2] for call in harness.walk_calls)


def test_v3_profile_is_used_by_all_walks_and_gets(monkeypatch):
    harness = _Harness(_entity_walks({501: (3, 0, "V3-SERIAL-501")}), gets=_stable_snapshot())
    harness.install(monkeypatch)
    settings = _settings(
        version="v3",
        username="snmp-user",
        security_level="authPriv",
        auth_method="SHA",
        auth_password="auth-secret-for-test",
        priv_method="AES",
        priv_password="priv-secret-for-test",
        context_name="tenant-a",
    )

    result = asyncio.run(reader.read_chassis_serials("192.0.2.20", settings, vendor="Cisco"))

    assert result["serial_complete"] is True
    assert all(call[4]["version"] == "3" for call in harness.walk_calls)
    assert all(call[2:] == (1161, "3") for call in harness.client_builds)
    assert all(call[1]["username"] == "snmp-user" for call in harness.client_builds)
    assert all(call[1]["context_name"] == "tenant-a" for call in harness.client_builds)


def test_module_board_and_nested_chassis_are_never_promoted(monkeypatch):
    entities = {
        10: (3, 0, "CHASSIS-10"),
        11: (3, 10, "NESTED-CHASSIS-11"),
        20: (9, 0, "ROOT-MODULE-20"),
        21: (9, 20, "BOARD-21"),
    }
    harness = _Harness(_entity_walks(entities), gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.21", _settings(), vendor="Huawei"))

    assert result["discovered_indices"] == [10, 11]
    assert result["members"] == [
        {
            "entity_index": 10,
            "serial_number": "CHASSIS-10",
            "entity_name": "",
            "entity_description": "",
            "model": "",
        }
    ]
    assert result["failed_indices"] == [11]
    assert result["discovery_complete"] is False
    assert result["serial_complete"] is False
    assert [item["entity_index"] for item in result["candidates"]] == [20]
    assert all(index not in {20, 21} for index in result["discovered_indices"])
    assert all(f"{ENTITY}.2.{index}" not in harness.get_calls for index in (20, 21))
    assert {f"{ENTITY}.7.{index}" for index in (20, 21)} <= set(harness.get_calls)
    assert {f"{ENTITY}.13.{index}" for index in (20, 21)} <= set(harness.get_calls)


@pytest.mark.parametrize("second_model", ["S6730-H48X6C-V2", "S6730-H24X6C-V2"])
def test_only_an_explicit_multi_member_huawei_s_model_pattern_creates_candidates(monkeypatch, second_model):
    entities = {
        10: (3, 0, "CHASSIS-SN"),
        101: (9, 10, "MODULE-SN-1"),
        102: (9, 10, "MODULE-SN-2"),
    }
    gets = {
        **_stable_snapshot(),
        f"{NAME_OID}.101": "S6730-H48X6C-V2 1",
        f"{MODEL_OID}.101": "S6730-H48X6C-V2",
        f"{NAME_OID}.102": f"{second_model} 2",
        f"{MODEL_OID}.102": second_model,
    }
    harness = _Harness(_entity_walks(entities), gets=gets)
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.22", _settings(), vendor="Huawei"))

    assert result["discovery_complete"] is True
    assert result["members"][0]["serial_number"] == "CHASSIS-SN"
    assert result["serial_complete"] is False
    assert result["status"] == "partial"
    assert {(item["entity_index"], item["member_id"], item["serial_number"]) for item in result["candidates"]} == {
        (101, "1", "MODULE-SN-1"), (102, "2", "MODULE-SN-2")
    }
    assert all(item["entity_index"] not in {101, 102} for item in result["members"])
    assert all("role" not in item and "mac" not in item for item in result["candidates"])


def test_h3c_private_serial_is_joined_by_unique_serial_not_entity_index(monkeypatch):
    entities = {101: (3, 0, "H3C-CHASSIS-SN")}
    walks = _entity_walks(entities)
    walks[H3C_FRAMES[0]] = _walk([(7, "H3C-CHASSIS-SN")])
    harness = _Harness(walks, gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.30", _settings(), vendor="H3C"))

    assert result["members"][0]["entity_index"] == 101
    assert result["members"][0]["serial_number"] == "H3C-CHASSIS-SN"
    assert result["serial_complete"] is True
    assert "h3c_private_serial_corroborated:101" in result["diagnostics"]
    assert result["candidates"] == []


def test_h3c_explicit_frame_name_with_conflicting_private_serial_blocks_confirmation(monkeypatch):
    entities = {101: (3, 0, "STANDARD-SERIAL")}
    walks = _entity_walks(entities)
    walks[H3C_FRAMES[0]] = _walk([(7, "PRIVATE-SERIAL")])
    gets = {**_stable_snapshot(), f"{NAME_OID}.101": "Frame 7"}
    harness = _Harness(walks, gets=gets)
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.31", _settings(), vendor="H3C"))

    assert result["members"] == []
    assert result["failed_indices"] == [101]
    assert result["absent_indices"] == []
    assert result["serial_complete"] is False
    assert any(item["serial_number"] == "PRIVATE-SERIAL" for item in result["candidates"])


def test_h3c_private_frame_serial_never_fills_an_empty_standard_serial(monkeypatch):
    entities = {101: (3, 0, None)}
    walks = _entity_walks(entities)
    walks[H3C_FRAMES[0]] = _walk([(7, "PRIVATE-SERIAL")])
    gets = {**_stable_snapshot(), f"{NAME_OID}.101": "Frame 7"}
    harness = _Harness(walks, gets=gets)
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.33", _settings(), vendor="H3C"))

    assert result["members"] == []
    assert result["absent_indices"] == []
    assert result["failed_indices"] == [101]
    assert any(item["serial_number"] == "PRIVATE-SERIAL" for item in result["candidates"])


def test_h3c_private_index_mismatch_without_explicit_frame_name_is_not_guessed(monkeypatch):
    entities = {1: (3, 0, "STANDARD-SERIAL")}
    walks = _entity_walks(entities)
    walks[H3C_FRAMES[0]] = _walk([(101, "PRIVATE-SERIAL")])
    harness = _Harness(walks, gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.32", _settings(), vendor="H3C"))

    assert [item["serial_number"] for item in result["members"]] == ["STANDARD-SERIAL"]
    assert result["failed_indices"] == []
    assert result["serial_complete"] is False
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["private_index"] == 101


def test_duplicate_invalid_and_absent_serials_are_distinguished(monkeypatch):
    entities = {
        11: (3, 0, "DUPLICATE-SN"),
        12: (3, 0, "DUPLICATE-SN"),
        13: (3, 0, "NA"),
        14: (3, 0, "FFFF"),
        15: (3, 0, "A1B"),
        16: (3, 0, ""),
        17: (3, 0, None),
    }
    harness = _Harness(_entity_walks(entities), gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.40", _settings(), vendor="Cisco"))

    assert [(item["entity_index"], item["serial_number"]) for item in result["members"]] == [
        (11, "DUPLICATE-SN"),
        (12, "DUPLICATE-SN"),
        (15, "A1B"),
    ]
    assert result["failed_indices"] == [13, 14]
    assert result["absent_indices"] == [16, 17]
    assert result["serial_complete"] is False


@pytest.mark.parametrize("truncated", ["class", "parent", "serial"])
def test_partial_or_row_limited_core_walk_never_confirms_a_member(monkeypatch, truncated):
    harness = _Harness(
        _entity_walks({9001: (3, 0, "SERIAL-9001")}, truncated=(truncated,)),
        gets=_stable_snapshot(),
    )
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.50", _settings(), vendor="Cisco"))

    assert result["members"] == []
    assert result["discovered_indices"] == [9001]
    assert result["serial_complete"] is False
    assert result["absent_indices"] == []
    assert result["failed_indices"] == [9001]


def test_partial_exception_rows_are_retained_as_untrusted_discovery(monkeypatch):
    walks = _entity_walks({123: (3, 0, "SERIAL-123")})
    failure = TimeoutError("walk timeout")
    failure.partial_results = _walk([(123, "3")])
    walks[CLASS_OID] = failure
    harness = _Harness(walks, gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.51", _settings(), vendor="Cisco"))

    assert result["discovered_indices"] == [123]
    assert result["discovery_complete"] is False
    assert result["members"] == []
    assert result["failed_indices"] == [123]


@pytest.mark.parametrize(
    ("uptime", "last_change", "expected"),
    [
        (["TimeTicks: (10000)", "TimeTicks: (10000)"], ["9", "10"], "changed"),
        (["TimeTicks: (10000)", "TimeTicks: (1)"], ["9", "9"], "restarted"),
    ],
)
def test_snapshot_change_or_restart_prevents_confirmation(monkeypatch, uptime, last_change, expected):
    gets = {UPTIME_OID: uptime, LAST_CHANGE_OID: last_change}
    harness = _Harness(_entity_walks({808: (3, 0, "SN-808")}), gets=gets)
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.60", _settings(), vendor="Cisco"))

    assert result["snapshot_consistency"] == expected
    assert result["discovered_indices"] == [808]
    assert result["members"] == []
    assert result["failed_indices"] == [808]
    assert result["serial_complete"] is False


def test_missing_parent_and_parent_cycles_are_untrusted(monkeypatch):
    entities = {
        100: (3, 0, "GOOD-SN"),
        200: (3, 999, "MISSING-PARENT"),
        300: (3, 301, "CYCLE-A"),
        301: (9, 300, "CYCLE-B"),
    }
    harness = _Harness(_entity_walks(entities), gets=_stable_snapshot())
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.61", _settings(), vendor="Cisco"))

    assert [item["entity_index"] for item in result["members"]] == [100]
    assert result["failed_indices"] == [200, 300]
    assert result["discovery_complete"] is False


def test_observed_at_is_utc_and_invalid_input_does_not_walk(monkeypatch):
    harness = _Harness({})
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("invalid-ip", _settings()))

    assert result["status"] == "failed"
    assert result["source"] == "snmp_entity_discovery"
    assert result["observed_at"].endswith("Z")
    assert harness.walk_calls == []


@pytest.mark.parametrize(
    "value",
    [
        "NA", "N/A", "no serial number", "not available yet", "0", "000000", "ffff", "--",
        "AB", "S" * 129, "SN\x00BAD",
    ],
)
def test_script_serial_placeholders_and_invalid_lengths_are_rejected(value):
    assert reader._serial(value)[0] == "invalid"


def test_empty_serial_and_postgres_index_bounds_are_explicit():
    assert reader._serial("")[0] == "absent"
    assert reader._row_index("2147483647") == 2147483647
    assert reader._row_index("2147483648") is None
    assert reader._row_index("0") is None


def test_requests_never_exceed_three_in_flight_and_are_row_bounded(monkeypatch):
    harness = _Harness(
        _entity_walks({1000 + index: (3, 0, f"SERIAL-{index:03d}") for index in range(4)}),
        gets=_stable_snapshot(),
        walk_delay=0.01,
        get_delay=0.01,
    )
    harness.install(monkeypatch)

    result = asyncio.run(reader.read_chassis_serials("192.0.2.70", _settings(), vendor="H3C"))

    assert result["serial_complete"] is True
    assert harness.maximum_active <= 3
    assert harness.maximum_active > 1
    assert all(call[4]["max_rows"] == 2000 for call in harness.walk_calls)
    assert all(call[4]["timeout"] <= 60 for call in harness.walk_calls)


def test_device_deadline_cancels_slow_walks_and_leaves_no_request_running(monkeypatch):
    monkeypatch.setattr(reader, "_MAX_DEVICE_SECONDS", 0.04)
    harness = _Harness(_entity_walks({77: (3, 0, "SERIAL-77")}), walk_delay=2.0)
    harness.install(monkeypatch)
    started = time.monotonic()

    result = asyncio.run(reader.read_chassis_serials("192.0.2.71", _settings(), vendor="Cisco"))

    assert time.monotonic() - started < 0.8
    assert result["serial_complete"] is False
    assert harness.cancelled_walks >= 1
    assert harness.active == 0


def test_caller_cancellation_drains_child_walk_tasks(monkeypatch):
    harness = _Harness(_entity_walks({88: (3, 0, "SERIAL-88")}), walk_delay=1.0)
    harness.install(monkeypatch)

    async def cancel_collection():
        task = asyncio.create_task(reader.read_chassis_serials("192.0.2.72", _settings(), vendor="Cisco"))
        await asyncio.wait_for(harness.walk_started.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    asyncio.run(cancel_collection())

    assert harness.cancelled_walks >= 1
    assert harness.active == 0
