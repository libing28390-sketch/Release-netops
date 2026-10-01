from __future__ import annotations

from api import devices
from database import get_db_connection


def _read_devices(**overrides):
    # Supply the same plain values FastAPI resolves from Query defaults.
    # Direct router calls otherwise receive the Query descriptor itself.
    params = {
        'search': None, 'platform': None, 'role': None, 'status': None,
        'mode': 'full', 'sort_key': 'hostname', 'sort_direction': 'asc',
        'page': 1, 'page_size': 10, 'asset_type': 'all',
    }
    params.update(overrides)
    return devices.read_devices(**params)


def _seed_hostname_projection_rows() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO physical_assets (id, asset_type, hostname, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("asset-cmdb-zulu", "network_device", "cmdb-zulu", "2026-10-01", "2026-10-01"),
        )
        conn.execute(
            """
            INSERT INTO physical_assets (id, asset_type, hostname, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("asset-cmdb-alpha", "network_device", "cmdb-alpha", "2026-10-01", "2026-10-01"),
        )
        conn.execute(
            """
            INSERT INTO devices (id, asset_id, hostname, ip_address, platform, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("device-cmdb-zulu", "asset-cmdb-zulu", "stale-zulu", "192.0.2.10", "cisco_ios", "online"),
        )
        conn.execute(
            """
            INSERT INTO devices (id, asset_id, hostname, ip_address, platform, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("device-cmdb-alpha", "asset-cmdb-alpha", "stale-alpha", "192.0.2.11", "cisco_ios", "online"),
        )
        conn.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, platform, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("device-legacy", "legacy-charlie", "192.0.2.12", "cisco_ios", "online"),
        )
        conn.commit()


def test_device_list_projects_linked_hostname_from_cmdb_for_full_light_and_paged_reads(isolated_db):
    _seed_hostname_projection_rows()

    full = _read_devices(sort_key="hostname", page=1, page_size=10)
    assert [item["hostname"] for item in full["items"]] == [
        "cmdb-alpha",
        "cmdb-zulu",
        "legacy-charlie",
    ]

    light = _read_devices(mode="light", sort_key="hostname", page=1, page_size=2)
    assert [item["hostname"] for item in light["items"]] == ["cmdb-alpha", "cmdb-zulu"]

    paged = _read_devices(mode="light", sort_key="hostname", page=2, page_size=2)
    assert [item["hostname"] for item in paged["items"]] == ["legacy-charlie"]

    legacy_array = _read_devices(page=None, page_size=None)
    assert [item['hostname'] for item in legacy_array] == ['cmdb-alpha', 'cmdb-zulu', 'legacy-charlie']


def test_device_list_search_and_sort_use_cmdb_hostname(isolated_db):
    _seed_hostname_projection_rows()

    searched = _read_devices(search="cmdb-alpha", mode="light", page=1, page_size=10)
    assert [item["hostname"] for item in searched["items"]] == ["cmdb-alpha"]
    assert _read_devices(search='stale-alpha', mode='light')['total'] == 0

    descending = _read_devices(
        mode="light",
        sort_key="hostname",
        sort_direction="desc",
        page=1,
        page_size=10,
    )
    assert [item["hostname"] for item in descending["items"]] == [
        "legacy-charlie",
        "cmdb-zulu",
        "cmdb-alpha",
    ]


def test_linked_device_update_keeps_current_cmdb_hostname_when_payload_differs_or_omits_it(isolated_db):
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO physical_assets (id, asset_type, hostname, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("asset-update-cmdb", "network_device", "cmdb-authoritative", "2026-10-01", "2026-10-01"),
        )
        conn.execute(
            """
            INSERT INTO devices (id, asset_id, hostname, ip_address, platform, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("device-update-cmdb", "asset-update-cmdb", "stale-device-name", "192.0.2.20", "cisco_ios", "online"),
        )
        conn.commit()

    devices.update_device(
        "device-update-cmdb",
        {
            "hostname": "payload-name-must-be-ignored",
            "ip_address": "192.0.2.21",
            "platform": "cisco_ios",
        },
    )
    devices.update_device(
        "device-update-cmdb",
        {
            "ip_address": "192.0.2.22",
            "platform": "cisco_ios",
        },
    )

    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT d.hostname AS device_hostname, pa.hostname AS asset_hostname
            FROM devices d
            JOIN physical_assets pa ON pa.id = d.asset_id
            WHERE d.id = ?
            """,
            ("device-update-cmdb",),
        ).fetchone()

    assert row["asset_hostname"] == "cmdb-authoritative"
    assert row["device_hostname"] == "cmdb-authoritative"
