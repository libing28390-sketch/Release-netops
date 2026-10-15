from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from api import configs
from database import get_db_connection


def test_snapshot_content_and_download_ignore_tenant_but_enforce_explicit_site_scope(isolated_db, monkeypatch, make_user):
    tenant_a = f"tenant-{uuid.uuid4().hex[:12]}"
    tenant_b = f"tenant-{uuid.uuid4().hex[:12]}"
    site_a = f"site-{uuid.uuid4().hex[:12]}"
    site_b = f"site-{uuid.uuid4().hex[:12]}"
    device_a = f"device-{uuid.uuid4().hex[:12]}"
    device_b = f"device-{uuid.uuid4().hex[:12]}"
    device_mismatched_tenant = f"device-{uuid.uuid4().hex[:12]}"
    device_legacy_site = f"device-{uuid.uuid4().hex[:12]}"
    duplicate_site_a = f"site-{uuid.uuid4().hex[:12]}"
    duplicate_site_b = f"site-{uuid.uuid4().hex[:12]}"
    snapshot_a = f"snapshot-{uuid.uuid4().hex[:12]}"
    snapshot_b = f"snapshot-{uuid.uuid4().hex[:12]}"
    snapshot_mismatched_tenant = f"snapshot-{uuid.uuid4().hex[:12]}"
    snapshot_legacy_site = f"snapshot-{uuid.uuid4().hex[:12]}"
    shared_site_name = f"Shared-{uuid.uuid4().hex[:8]}"

    conn = get_db_connection()
    try:
        for tenant_id in (tenant_a, tenant_b):
            conn.execute(
                "INSERT INTO tenants (id, name, description) VALUES (?, ?, '')",
                (tenant_id, tenant_id),
            )
        for site_id, tenant_id in ((site_a, tenant_a), (site_b, tenant_b)):
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_id, site_id, tenant_id),
            )
        for site_id, site_code, tenant_id in (
            (duplicate_site_a, f"code-{duplicate_site_a}", tenant_a),
            (duplicate_site_b, f"code-{duplicate_site_b}", tenant_b),
        ):
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_code, shared_site_name, tenant_id),
            )
        for device_id, site_id, tenant_id in (
            (device_a, site_a, tenant_a),
            (device_b, site_b, tenant_b),
            (device_mismatched_tenant, site_a, tenant_b),
        ):
            conn.execute(
                """INSERT INTO devices (id, hostname, site_id, site, tenant_id, status)
                   VALUES (?, ?, ?, ?, ?, 'active')""",
                (device_id, device_id, site_id, site_id, tenant_id),
            )
        conn.execute(
            """INSERT INTO devices (id, hostname, site_id, site, tenant_id, status)
               VALUES (?, ?, '', ?, ?, 'active')""",
            (device_legacy_site, device_legacy_site, shared_site_name, tenant_a),
        )
        for snapshot_id, device_id in (
            (snapshot_a, device_a),
            (snapshot_b, device_b),
            (snapshot_mismatched_tenant, device_mismatched_tenant),
            (snapshot_legacy_site, device_legacy_site),
        ):
            conn.execute(
                """INSERT INTO config_snapshots
                   (id, device_id, hostname, vendor, timestamp, trigger, author, file_path, size)
                   VALUES (?, ?, ?, 'cisco', '2026-09-26T00:00:00+00:00', 'manual', 'tester', '', 0)""",
                (snapshot_id, device_id, device_id),
            )
        conn.commit()
    finally:
        conn.close()

    read_ids: list[str] = []

    def read_content(row, *, strict_storage_errors=False):
        read_ids.append(row["id"])
        return f"config for {row['hostname']}"

    monkeypatch.setattr(configs, "read_snapshot_content", read_content)
    user = {"role": "Viewer", "tenant_id": tenant_a}
    tenantless_user = {"role": "Viewer", "tenant_id": ""}

    visible = configs.get_snapshot_content(snapshot_a, user=user)
    assert visible["content"] == f"config for {device_a}"

    for endpoint in (configs.get_snapshot_content, configs.download_snapshot):
        for snapshot_id, reader in (
            (snapshot_b, user),
            (snapshot_mismatched_tenant, user),
            (snapshot_legacy_site, user),
            (snapshot_a, tenantless_user),
        ):
            assert endpoint(snapshot_id, user=reader)
    assert {snapshot_a, snapshot_b, snapshot_mismatched_tenant, snapshot_legacy_site} <= set(read_ids)

    scoped_user = make_user("snapshot-site-viewer", role="Viewer")
    scoped_user["tenant_id"] = tenant_a
    conn = get_db_connection()
    try:
        for authorized_site in (site_a, duplicate_site_a):
            conn.execute(
                """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                   VALUES (?, ?, 'asset', 'site', ?, '[\"view\"]', '2026-09-26T00:00:00+00:00')""",
                (str(uuid.uuid4()), scoped_user["user_id"], authorized_site),
            )
        conn.commit()
    finally:
        conn.close()
    scoped_visible = configs.get_snapshot_content(snapshot_a, user=scoped_user)
    assert scoped_visible["content"] == f"config for {device_a}"
    # Tenant labels no longer limit reads when the device is in an authorized site.
    scoped_historical_tenant_visible = configs.get_snapshot_content(snapshot_mismatched_tenant, user=scoped_user)
    assert scoped_historical_tenant_visible["content"] == f"config for {device_mismatched_tenant}"
    with pytest.raises(HTTPException) as blocked_site:
        configs.get_snapshot_content(snapshot_b, user=scoped_user)
    assert blocked_site.value.status_code == 404
    with pytest.raises(HTTPException) as ambiguous_site:
        configs.get_snapshot_content(snapshot_legacy_site, user=scoped_user)
    assert ambiguous_site.value.status_code == 404
    assert read_ids[-2:] == [snapshot_a, snapshot_mismatched_tenant]
