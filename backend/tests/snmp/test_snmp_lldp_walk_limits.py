import asyncio
from unittest.mock import patch

import pytest

from services.snmp_service import (
    SnmpWalkResult,
    SnmpWalkTimeoutError,
    _snmp_walk,
    collect_snmp_lldp_neighbors,
)


LLDP_SYS_NAME = '1.0.8802.1.1.2.1.4.1.1.9'
LLDP_PORT_ID = '1.0.8802.1.1.2.1.4.1.1.7'
LLDP_PORT_DESC = '1.0.8802.1.1.2.1.4.1.1.8'
LLDP_CHASSIS_ID = '1.0.8802.1.1.2.1.4.1.1.5'
LLDP_CHASSIS_SUBTYPE = '1.0.8802.1.1.2.1.4.1.1.4'
LLDP_SYS_DESC = '1.0.8802.1.1.2.1.4.1.1.10'
LLDP_LOC_PORT_ID = '1.0.8802.1.1.2.1.3.7.1.3'
IF_NAME = '1.3.6.1.2.1.31.1.1.1.1'


def test_lldp_uses_dedicated_timeout_and_row_budget_for_thirteen_neighbors():
    calls = []

    async def mock_walk(
        ip,
        community,
        oid,
        port=161,
        timeout=5.0,
        max_rows=200,
        version='2c',
        raise_on_error=False,
        preserve_octets=False,
    ):
        calls.append((oid, port, timeout, max_rows, raise_on_error, preserve_octets))
        rows = [(f'0.1.{index}', f'SW-{index}') for index in range(1, 14)]
        if oid == LLDP_SYS_NAME:
            return rows
        if oid == LLDP_PORT_ID:
            return [(suffix, f'GigabitEthernet0/0/{index}') for index, (suffix, _name) in enumerate(rows, 1)]
        if oid == LLDP_CHASSIS_ID:
            return [(suffix, f'00:11:22:33:44:{index:02x}') for index, (suffix, _name) in enumerate(rows, 1)]
        if oid == LLDP_CHASSIS_SUBTYPE:
            return [(suffix, '4') for suffix, _name in rows]
        if oid == LLDP_LOC_PORT_ID:
            return [('1', 'GigabitEthernet0/0/1')]
        if oid == IF_NAME:
            return [('1', 'GE0/0/1')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        batch = asyncio.run(
            collect_snmp_lldp_neighbors('10.0.0.1', 'test-community', port=1161)
        )

    assert len(batch) == 13
    assert batch.collection_status == 'success'
    assert batch.truncated_oids == []
    assert batch.max_rows == 10000
    assert len(calls) == 10
    assert all(port == 1161 for _oid, port, _timeout, _max_rows, _raise, _preserve in calls)
    assert all(timeout == 30.0 for _oid, _port, timeout, _max_rows, _raise, _preserve in calls)
    assert all(max_rows == 10000 for _oid, _port, _timeout, max_rows, _raise, _preserve in calls)
    assert all(raise_on_error for _oid, _port, _timeout, _max_rows, raise_on_error, _preserve in calls)
    assert all(
        preserve is (oid in {LLDP_CHASSIS_ID, LLDP_PORT_ID})
        for oid, _port, _timeout, _max_rows, _raise, preserve in calls
    )
    assert LLDP_CHASSIS_SUBTYPE in [oid for oid, *_rest in calls]


def test_lldp_dedicated_budget_allows_more_than_generic_two_hundred_rows():
    async def mock_walk(
        ip,
        community,
        oid,
        port=161,
        timeout=5.0,
        max_rows=200,
        version='2c',
        raise_on_error=False,
        preserve_octets=False,
    ):
        rows = [(f'0.1.{index}', f'SW-{index}') for index in range(1, 202)]
        if oid == LLDP_SYS_NAME:
            return rows
        if oid == LLDP_PORT_ID:
            return [(suffix, f'Ethernet{index}') for index, (suffix, _name) in enumerate(rows, 1)]
        if oid == LLDP_CHASSIS_ID:
            return [(suffix, f'chassis-{index}') for index, (suffix, _name) in enumerate(rows, 1)]
        if oid == LLDP_CHASSIS_SUBTYPE:
            return [(suffix, '7') for suffix, _name in rows]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        batch = asyncio.run(collect_snmp_lldp_neighbors('10.0.0.2', 'test-community'))

    assert len(batch) == 201
    assert batch.collection_status == 'success'
    assert batch.max_rows == 10000


def test_snmp_walk_marks_boundary_row_limit_and_stops():
    build_calls = []

    class Permit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class Limiter:
        def async_snmp(self):
            return Permit()

    class VarBind:
        def __init__(self, oid, value):
            self.oid = oid
            self.value = value

    class Wrapper:
        def __init__(self, _client):
            pass

        async def walk(self, base_oid):
            for index in range(1, 5):
                yield VarBind(f'{base_oid}.{index}', f'value-{index}')

    with patch('services.snmp_service.get_network_access_limiter', return_value=Limiter()), \
         patch(
             'services.snmp_service._build_snmp_client',
             side_effect=lambda ip, auth, port: (build_calls.append((ip, port)) or object()),
         ), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.3',
                'test-community',
                '1.0.8802',
                port=1161,
                max_rows=3,
                timeout=1,
            )
        )

    assert isinstance(result, SnmpWalkResult)
    assert result == [('1', 'value-1'), ('2', 'value-2'), ('3', 'value-3')]
    assert result.truncated is True
    assert build_calls == [('10.0.0.3', 1161)]


def test_snmp_walk_preserves_chassis_octets_without_changing_string_rows():
    class Permit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class Limiter:
        def async_snmp(self):
            return Permit()

    class VarBind:
        def __init__(self, oid, value):
            self.oid = oid
            self.value = value

    class Wrapper:
        def __init__(self, _client):
            pass

        async def walk(self, base_oid):
            yield VarBind(f'{base_oid}.0.1.1', b'\x00\x11\x22\x33\x44\x55')
            yield VarBind(f'{base_oid}.0.1.2', b'ABCDEF')

    with patch('services.snmp_service.get_network_access_limiter', return_value=Limiter()), \
         patch('services.snmp_service._build_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.7',
                'test-community',
                LLDP_CHASSIS_ID,
                port=1161,
                timeout=1,
                max_rows=10,
                preserve_octets=True,
            )
        )

    assert result[0][0] == '0.1.1'
    assert result[1] == ('0.1.2', 'ABCDEF')
    assert result.octet_values == {
        '0.1.1': b'\x00\x11\x22\x33\x44\x55',
        '0.1.2': b'ABCDEF',
    }


def test_lldp_truncation_with_neighbors_is_partial_and_empty_truncation_is_error():
    async def truncated_walk(
        ip,
        community,
        oid,
        port=161,
        timeout=5.0,
        max_rows=200,
        version='2c',
        raise_on_error=False,
        preserve_octets=False,
    ):
        if oid == LLDP_SYS_NAME:
            return SnmpWalkResult([('0.1.1', 'SW-1')], truncated=True)
        if oid == LLDP_PORT_ID:
            return [('0.1.1', 'GigabitEthernet0/0/2')]
        if oid == LLDP_CHASSIS_ID:
            return [('0.1.1', '00:11:22:33:44:55')]
        if oid == LLDP_CHASSIS_SUBTYPE:
            return [('0.1.1', '4')]
        if oid == LLDP_LOC_PORT_ID:
            return [('1', 'GigabitEthernet0/0/1')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=truncated_walk):
        batch = asyncio.run(collect_snmp_lldp_neighbors('10.0.0.4', 'test-community'))

    assert len(batch) == 1
    assert batch.collection_status == 'partial'
    assert batch.truncated_oids == [LLDP_SYS_NAME]
    assert batch.max_rows == 10000

    async def empty_truncated_walk(
        ip,
        community,
        oid,
        port=161,
        timeout=5.0,
        max_rows=200,
        version='2c',
        raise_on_error=False,
        preserve_octets=False,
    ):
        return SnmpWalkResult([], truncated=True) if oid == LLDP_SYS_NAME else []

    with patch('services.snmp_service._snmp_walk', side_effect=empty_truncated_walk):
        with pytest.raises(RuntimeError, match=r'^snmp_lldp_walk_failed:.*row_limit_exceeded') as failure:
            asyncio.run(collect_snmp_lldp_neighbors('10.0.0.4', 'test-community'))
    assert 'row_limit_exceeded:' + LLDP_SYS_NAME in str(failure.value)


def test_lldp_formats_raw_chassis_by_subtype_and_does_not_use_subtype_as_port():
    calls = []

    async def mock_walk(
        ip,
        community,
        oid,
        port=161,
        timeout=5.0,
        max_rows=200,
        version='2c',
        raise_on_error=False,
        preserve_octets=False,
    ):
        calls.append((oid, port, preserve_octets))
        suffixes = [f'0.1.{index}' for index in range(1, 5)]
        if oid == LLDP_SYS_NAME:
            return list(zip(suffixes, ['SW-CONTROL', 'SW-PRINT-MAC', 'SW-NONMAC', 'SW-LEGACY']))
        if oid == LLDP_PORT_ID:
            return [(suffix, f'Ethernet{index}') for index, suffix in enumerate(suffixes[:3], 1)]
        if oid == LLDP_PORT_DESC:
            return []
        if oid == LLDP_CHASSIS_ID:
            return SnmpWalkResult(
                [
                    ('0.1.1', 'garbled-control-byte-value'),
                    ('0.1.2', 'ABCDEF'),
                    ('0.1.3', 'ABCDEF'),
                    ('0.1.4', 'legacy-six'),
                ],
                octet_values={
                    '0.1.1': b'\x00\x11\x22\x33\x44\x55',
                    '0.1.2': b'ABCDEF',
                    '0.1.3': b'ABCDEF',
                },
            )
        if oid == LLDP_CHASSIS_SUBTYPE:
            return [(suffix, subtype) for suffix, subtype in zip(suffixes, ['4', '4', '7', '7'])]
        if oid == LLDP_LOC_PORT_ID:
            return [('1', 'GigabitEthernet0/0/1')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        batch = asyncio.run(
            collect_snmp_lldp_neighbors('10.0.0.8', 'test-community', port=1161)
        )

    by_name = {neighbor['neighbor_name']: neighbor for neighbor in batch}
    assert by_name['SW-CONTROL']['chassis_id'] == '00:11:22:33:44:55'
    assert by_name['SW-PRINT-MAC']['chassis_id'] == '41:42:43:44:45:46'
    assert by_name['SW-NONMAC']['chassis_id'] == 'ABCDEF'
    assert by_name['SW-LEGACY']['chassis_id'] == 'legacy-six'
    # No port ID/description was collected, so keep the interface unknown
    # as an empty value instead of fabricating a display name.
    assert by_name['SW-LEGACY']['neighbor_interface'] == ''
    assert (LLDP_CHASSIS_SUBTYPE, 1161, False) in calls
    assert (LLDP_CHASSIS_ID, 1161, True) in calls


def test_lldp_timeout_is_error_but_complete_empty_table_is_success_with_old_signature():
    calls = []

    async def old_empty_walk(ip, community, oid, port=161, timeout=4.0, version='2c'):
        calls.append(oid)
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=old_empty_walk):
        batch = asyncio.run(collect_snmp_lldp_neighbors('10.0.0.5', 'test-community'))

    assert batch == []
    assert batch.collection_status == 'success'
    assert LLDP_CHASSIS_SUBTYPE in calls

    async def old_timeout_walk(ip, community, oid, port=161, timeout=4.0, version='2c'):
        raise SnmpWalkTimeoutError([])

    with patch('services.snmp_service._snmp_walk', side_effect=old_timeout_walk):
        with pytest.raises(RuntimeError, match=r'^snmp_lldp_walk_failed:'):
            asyncio.run(collect_snmp_lldp_neighbors('10.0.0.5', 'test-community'))


def test_snmp_walk_timeout_preserves_partial_rows_and_raise_semantics():
    class Permit:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class Limiter:
        def async_snmp(self):
            return Permit()

    class VarBind:
        def __init__(self, oid, value):
            self.oid = oid
            self.value = value

    class SlowWrapper:
        def __init__(self, _client):
            pass

        async def walk(self, base_oid):
            yield VarBind(f'{base_oid}.1', b'first')
            await asyncio.sleep(0.05)
            yield VarBind(f'{base_oid}.2', 'second')

    with patch('services.snmp_service.get_network_access_limiter', return_value=Limiter()), \
         patch('services.snmp_service._build_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', SlowWrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.6',
                'test-community',
                '1.0.8802',
                port=1161,
                timeout=0.001,
                preserve_octets=True,
            )
        )
        assert result == [('1', 'first')]
        assert result.truncated is False
        assert result.octet_values == {'1': b'first'}
        with pytest.raises(SnmpWalkTimeoutError) as exc_info:
            asyncio.run(
                _snmp_walk(
                    '10.0.0.6',
                    'test-community',
                    '1.0.8802',
                    port=1161,
                    timeout=0.001,
                    raise_on_error=True,
                    preserve_octets=True,
                )
            )

    assert exc_info.value.partial_results == [('1', 'first')]
    assert exc_info.value.partial_results.octet_values == {'1': b'first'}
