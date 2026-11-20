from __future__ import annotations

import database
import api.librenms_native as librenms_native_api
from api.librenms_native import InstanceUpdate


def test_instance_update_changes_enabled_once_and_connection_changes_disable(isolated_db, monkeypatch):
    monkeypatch.setattr(librenms_native_api, "get_db_connection", database.get_db_connection)
    conn = database.get_db_connection()
    try:
        conn.execute(
            """INSERT INTO librenms_instances
                   (id, display_name, base_url, enabled, health_state)
               VALUES (?, ?, ?, FALSE, 'healthy')""",
            ("lnms-api-update", "LibreNMS API update", "https://localhost"),
        )
        conn.commit()
    finally:
        conn.close()

    admin = {"username": "test-admin", "role": "Administrator"}

    enabled = librenms_native_api.update_instance(
        "lnms-api-update", InstanceUpdate(enabled=True), _user=admin
    )
    assert enabled["data"]["enabled"] is True

    disabled = librenms_native_api.update_instance(
        "lnms-api-update", InstanceUpdate(enabled=False), _user=admin
    )
    assert disabled["data"]["enabled"] is False

    librenms_native_api.update_instance(
        "lnms-api-update", InstanceUpdate(enabled=True), _user=admin
    )
    changed_connection = librenms_native_api.update_instance(
        "lnms-api-update",
        InstanceUpdate(base_url="https://127.0.0.1", enabled=True),
        _user=admin,
    )
    assert changed_connection["data"]["enabled"] is False
    assert changed_connection["data"]["health_state"] == "unknown"
