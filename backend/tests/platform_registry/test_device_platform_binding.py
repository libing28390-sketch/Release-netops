from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.devices import _resolve_platform_binding


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, row):
        self.row = row

    def execute(self, _sql, _params):
        return _Result(self.row)


def test_concrete_profile_overrides_legacy_platform_code():
    conn = _Connection({'id': 'profile-zsrv2', 'platform_code': 'zte_zsrv2_v3', 'status': 'ACTIVE'})

    assert _resolve_platform_binding(conn, 'profile-zsrv2', 'cisco_ios') == (
        'zte_zsrv2_v3', 'profile-zsrv2', 'MANUAL', 0,
    )


def test_invalid_or_archived_profile_cannot_be_bound():
    with pytest.raises(HTTPException) as missing:
        _resolve_platform_binding(_Connection(None), 'missing-profile', 'cisco_ios')
    assert missing.value.status_code == 400

    with pytest.raises(HTTPException) as archived:
        _resolve_platform_binding(
            _Connection({'id': 'profile-old', 'platform_code': 'zte_5900_v6', 'status': 'ARCHIVED'}),
            'profile-old',
            'cisco_ios',
        )
    assert archived.value.status_code == 400


def test_legacy_update_without_profile_keeps_existing_binding():
    conn = _Connection({'id': 'profile-zsrv2', 'platform_code': 'zte_zsrv2_v3', 'status': 'ACTIVE'})

    assert _resolve_platform_binding(
        conn,
        None,
        'zte_zsrv2_v3',
        existing={
            'platform_profile_id': 'profile-zsrv2',
            'platform_source': 'MANUAL',
            'platform_locked': 0,
        },
    ) == ('zte_zsrv2_v3', 'profile-zsrv2', 'MANUAL', 0)


def test_existing_profile_cannot_be_changed_through_legacy_device_update():
    conn = _Connection({'id': 'profile-zsrv2', 'platform_code': 'zte_zsrv2_v3', 'status': 'ACTIVE'})

    with pytest.raises(HTTPException) as changed:
        _resolve_platform_binding(
            conn,
            'profile-other',
            'cisco_ios',
            existing={
                'platform_profile_id': 'profile-zsrv2',
                'platform_source': 'SYSTEM',
                'platform_locked': 1,
            },
        )
    assert changed.value.status_code == 409


def test_existing_profile_lock_and_source_are_preserved_when_legacy_update_omits_binding():
    conn = _Connection({'id': 'profile-zsrv2', 'platform_code': 'zte_zsrv2_v3', 'status': 'ACTIVE'})

    assert _resolve_platform_binding(
        conn,
        None,
        'cisco_ios',
        existing={
            'platform_profile_id': 'profile-zsrv2',
            'platform_source': 'SYSTEM',
            'platform_locked': 1,
        },
    ) == ('zte_zsrv2_v3', 'profile-zsrv2', 'SYSTEM', 1)


def test_explicit_legacy_selection_clears_existing_binding():
    conn = _Connection({'id': 'profile-zsrv2', 'platform_code': 'zte_zsrv2_v3', 'status': 'ACTIVE'})

    assert _resolve_platform_binding(
        conn,
        None,
        'cisco_ios',
        existing={
            'platform_profile_id': 'profile-zsrv2',
            'platform_source': 'MANUAL',
            'platform_locked': 0,
        },
        clear_existing=True,
    ) == ('cisco_ios', '', 'LEGACY', 0)
