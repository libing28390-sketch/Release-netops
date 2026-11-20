import asyncio
import time
from unittest.mock import patch

import pytest
from puresnmp import ObjectIdentifier
from puresnmp.exc import GenErr, NoAccess, TooBig

from services.snmp_service import (
    SnmpWalkResult,
    SnmpWalkTimeoutError,
    _snmp_walk,
    collect_snmp_lldp_neighbors,
)


LLDP_SYS_NAME = '1.0.8802.1.1.2.1.4.1.1.9'
LLDP_PORT_ID = '1.0.8802.1.1.2.1.4.1.1.7'
LLDP_PORT_ID_SUBTYPE = '1.0.8802.1.1.2.1.4.1.1.6'
LLDP_CHASSIS_ID = '1.0.8802.1.1.2.1.4.1.1.5'
LLDP_CHASSIS_SUBTYPE = '1.0.8802.1.1.2.1.4.1.1.4'
LLDP_LOC_PORT_ID = '1.0.8802.1.1.2.1.3.7.1.3'
IF_NAME = '1.3.6.1.2.1.31.1.1.1.1'


class _Permit:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _Limiter:
    def async_snmp(self):
        return _Permit()


class _VarBind:
    def __init__(self, oid, value):
        self.oid = oid
        self.value = value


@pytest.mark.parametrize('version', ['2c', '3'])
def test_prefer_bulk_uses_getbulk_for_v2c_and_v3_and_keeps_octets(version):
    calls = []
    base_oid = LLDP_PORT_ID
    raw_port_id = b'\x00\x11\x22\x33\x44\x55'

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, oids, bulk_size=10):
            calls.append(('bulk', list(oids), bulk_size))
            yield _VarBind(f'{base_oid}.0.1.1', raw_port_id)

        async def walk(self, _base_oid):
            raise AssertionError('GETNEXT must not run after a complete GETBULK walk')

    profile = {'username': 'snmp-reader'} if version == '3' else 'test-community'
    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.10',
                profile,
                base_oid,
                version=version,
                timeout=1,
                max_rows=10000,
                preserve_octets=True,
                prefer_bulk=True,
                raise_on_error=True,
            )
        )

    assert result == [('0.1.1', '\x11"3DU')]
    assert result.octet_values == {'0.1.1': raw_port_id}
    assert calls == [('bulk', [base_oid], 20)]


def test_prefer_bulk_keeps_snmpv1_on_getnext():
    calls = []

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, *_args, **_kwargs):
            raise AssertionError('SNMPv1 does not support GETBULK')

        async def walk(self, base_oid):
            calls.append(('next', base_oid))
            yield _VarBind(f'{base_oid}.0.1.1', 'value')

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.11',
                'test-community',
                LLDP_SYS_NAME,
                version='v1',
                timeout=1,
                prefer_bulk=True,
                raise_on_error=True,
            )
        )

    assert result == [('0.1.1', 'value')]
    assert calls == [('next', LLDP_SYS_NAME)]


def test_bulk_walk_normalizes_a_leading_dot_and_stops_at_subtree_boundary():
    base_oid = LLDP_SYS_NAME

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, oids, bulk_size=10):
            assert oids == [base_oid]
            yield _VarBind(f'{base_oid}.0.1.1', 'inside')
            yield _VarBind(f'{base_oid}0.1.1', 'outside')

        async def walk(self, _base_oid):
            raise AssertionError('GETNEXT fallback is not expected')
            yield  # pragma: no cover - make this an async generator

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.18',
                'test-community',
                f'.{base_oid}',
                timeout=1,
                prefer_bulk=True,
                raise_on_error=True,
            )
        )

    assert result == [('0.1.1', 'inside')]


def test_default_getnext_keeps_its_legacy_suffix_behavior():
    outside_oid = '1.0.8803.1.1'

    class Wrapper:
        def __init__(self, _client):
            pass

        async def walk(self, _base_oid):
            yield _VarBind(outside_oid, 'legacy-result')

        async def bulkwalk(self, *_args, **_kwargs):
            raise AssertionError('Default walks must remain on GETNEXT')
            yield  # pragma: no cover - make this an async generator

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.19',
                'test-community',
                LLDP_SYS_NAME,
                timeout=1,
                raise_on_error=True,
            )
        )

    assert result == [(outside_oid, 'legacy-result')]


@pytest.mark.parametrize('bulk_error', [GenErr, TooBig])
def test_bulk_protocol_compatibility_error_uses_one_complete_getnext_fallback(bulk_error):
    calls = []
    base_oid = LLDP_PORT_ID
    raw_fallback_value = b'\x00\x11\x22\x33\x44\x55'

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, _oids, bulk_size=10):
            calls.append('bulk')
            yield _VarBind(f'{base_oid}.0.1.1', b'old-attempt-value')
            yield _VarBind(f'{base_oid}.0.1.2', b'old-only-row')
            raise bulk_error(ObjectIdentifier(base_oid), 'bulk compatibility error')

        async def walk(self, walk_oid):
            calls.append('next')
            yield _VarBind(f'{walk_oid}.0.1.1', raw_fallback_value)
            yield _VarBind(f'{walk_oid}.0.1.3', b'new-row')

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.12',
                'test-community',
                base_oid,
                timeout=1,
                max_rows=10000,
                preserve_octets=True,
                prefer_bulk=True,
                raise_on_error=True,
            )
        )

    assert calls == ['bulk', 'next']
    assert result == [('0.1.1', '\x11"3DU'), ('0.1.3', 'new-row')]
    assert result.octet_values == {
        '0.1.1': raw_fallback_value,
        '0.1.3': b'new-row',
    }


def test_auth_or_access_error_does_not_retry_as_getnext():
    calls = []

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, oids, bulk_size=10):
            calls.append('bulk')
            raise NoAccess(ObjectIdentifier(oids[0]), 'access denied')
            yield  # pragma: no cover - make this an async generator

        async def walk(self, _base_oid):
            calls.append('next')
            yield _VarBind(f'{LLDP_SYS_NAME}.0.1.1', 'unexpected')

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        with pytest.raises(NoAccess):
            asyncio.run(
                _snmp_walk(
                    '10.0.0.13',
                    'test-community',
                    LLDP_SYS_NAME,
                    timeout=1,
                    prefer_bulk=True,
                    raise_on_error=True,
                )
            )

    assert calls == ['bulk']


def test_bulk_walk_keeps_lldp_row_budget_above_two_hundred():
    base_oid = LLDP_SYS_NAME

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, oids, bulk_size=10):
            assert oids == [base_oid]
            assert bulk_size == 20
            for index in range(1, 206):
                yield _VarBind(f'{base_oid}.0.1.{index}', f'SW-{index}')

        async def walk(self, _base_oid):
            raise AssertionError('GETNEXT fallback is not expected')
            yield  # pragma: no cover - make this an async generator

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        result = asyncio.run(
            _snmp_walk(
                '10.0.0.14',
                'test-community',
                base_oid,
                timeout=1,
                max_rows=10000,
                prefer_bulk=True,
                raise_on_error=True,
            )
        )

    assert len(result) == 205
    assert result.truncated is False


def test_fallback_shares_one_timeout_budget_and_returns_partial_rows():
    calls = []
    base_oid = LLDP_PORT_ID
    raw_fallback_value = b'\x00\x11\x22\x33\x44\x55'

    class Wrapper:
        def __init__(self, _client):
            pass

        async def bulkwalk(self, _oids, bulk_size=10):
            calls.append('bulk')
            yield _VarBind(f'{base_oid}.0.1.1', b'bulk-prefix')
            raise GenErr(ObjectIdentifier(base_oid), 'unsupported bulk operation')

        async def walk(self, walk_oid):
            calls.append('next')
            yield _VarBind(f'{walk_oid}.0.1.1', raw_fallback_value)
            await asyncio.sleep(1)

    with patch('services.snmp_service.get_network_access_limiter', return_value=_Limiter()), \
         patch('services.snmp_service._build_versioned_snmp_client', return_value=object()), \
         patch('puresnmp.PyWrapper', Wrapper):
        started_at = time.monotonic()
        with pytest.raises(SnmpWalkTimeoutError) as failure:
            asyncio.run(
                _snmp_walk(
                    '10.0.0.15',
                    'test-community',
                    base_oid,
                    timeout=0.04,
                    max_rows=10000,
                    preserve_octets=True,
                    prefer_bulk=True,
                    raise_on_error=True,
                )
            )
        elapsed = time.monotonic() - started_at

    assert elapsed < 0.25
    assert calls == ['bulk', 'next']
    assert failure.value.partial_results == [('0.1.1', '\x11"3DU')]
    assert failure.value.partial_results.octet_values == {'0.1.1': raw_fallback_value}


@pytest.mark.parametrize(('version', 'expected_preference'), [('2c', True), ('v1', False)])
def test_lldp_collector_opts_into_bulk_only_for_v2_and_later(version, expected_preference):
    preferences = []

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
        prefer_bulk=False,
    ):
        preferences.append(prefer_bulk)
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        batch = asyncio.run(
            collect_snmp_lldp_neighbors(
                '10.0.0.16', 'test-community', version=version,
            )
        )

    assert batch.collection_status == 'success'
    assert len(preferences) == 10
    assert set(preferences) == {expected_preference}


def test_lldp_port_id_keeps_binary_nul_as_hex_evidence():
    raw_port_id = b'\x00\x11\x22\x33\x44\x55'

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
        prefer_bulk=False,
    ):
        if oid == LLDP_SYS_NAME:
            return [('0.1.1', 'SW-1')]
        if oid == LLDP_PORT_ID:
            return SnmpWalkResult(
                [('0.1.1', 'untrusted-text-view')],
                octet_values={'0.1.1': raw_port_id},
            )
        if oid == LLDP_PORT_ID_SUBTYPE:
            return [('0.1.1', '3')]
        if oid == LLDP_CHASSIS_ID:
            return [('0.1.1', 'SW-1-chassis')]
        if oid == LLDP_CHASSIS_SUBTYPE:
            return [('0.1.1', '7')]
        if oid == LLDP_LOC_PORT_ID:
            return [('1', 'GigabitEthernet0/0/1')]
        if oid == IF_NAME:
            return [('1', 'GE0/0/1')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        batch = asyncio.run(
            collect_snmp_lldp_neighbors('10.0.0.17', 'test-community')
        )

    assert batch.collection_status == 'success'
    assert batch[0]['neighbor_interface'] == ''
    assert batch[0]['neighbor_port_id_subtype'] == 3
    assert batch[0]['neighbor_port_id'] == '00:11:22:33:44:55'
