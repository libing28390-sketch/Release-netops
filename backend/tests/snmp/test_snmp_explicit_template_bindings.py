from backend.tests.pg_test_utils import postgresql_test_driver
import pytest

from services.snmp_metric_profile_service import (
    bind_model_metric_profile,
    delete_model_metric_profile,
    get_model_metric_profile_mapping,
    resolve_metric_profiles,
    unbind_model_metric_profile,
)


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        """
        CREATE TABLE snmp_metric_profiles (
            id TEXT PRIMARY KEY,
            vendor_key TEXT NOT NULL,
            vendor_name TEXT NOT NULL DEFAULT '',
            model_key TEXT NOT NULL,
            model_name TEXT NOT NULL DEFAULT '',
            cpu_oid TEXT NOT NULL DEFAULT '',
            memory_oid TEXT NOT NULL DEFAULT '',
            cpu_config_json TEXT NOT NULL DEFAULT '{}',
            memory_config_json TEXT NOT NULL DEFAULT '{}',
            metric_definitions_json TEXT NOT NULL DEFAULT '{}',
            interface_config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            last_test_at TEXT,
            last_test_device_id TEXT NOT NULL DEFAULT '',
            last_test_message TEXT NOT NULL DEFAULT '',
            interface_verification_status TEXT NOT NULL DEFAULT 'unverified',
            interface_last_test_at TEXT,
            interface_last_test_device_id TEXT NOT NULL DEFAULT '',
            interface_last_test_message TEXT NOT NULL DEFAULT '',
            template_name TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'custom',
            official_preset_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT,
            vendor TEXT,
            platform TEXT,
            model TEXT,
            status TEXT,
            snmp_metric_profile_id TEXT DEFAULT ''
        );
        INSERT INTO snmp_metric_profiles
            (id, vendor_key, vendor_name, model_key, model_name,
             metric_definitions_json, template_name, source, created_at, updated_at)
        VALUES (
            'profile-custom', 'h3c', 'H3C', 's6800', 'S6800',
            '{"cpu": {"mode": "direct_percent", "oid": "1.3.6.1.4.1.1"}}',
            'H3C S6800 Custom', 'custom', 'now', 'now'
        );
        INSERT INTO devices
            (id, hostname, ip_address, vendor, platform, model, status)
        VALUES
            ('device-1', 'sw-01', '192.0.2.1', 'H3C', 'h3c_comware', 'S6800', 'online'),
            ('device-2', 'sw-02', '192.0.2.2', 'H3C', 'h3c_comware', 'S6800', 'offline');
        """
    )
    return conn


def test_binding_is_explicit_and_unbind_is_reversible(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _connection()
    monkeypatch.setattr(
        "services.snmp_metric_profile_service._load_profile_cache",
        lambda: {
            "profile-custom": {
                "profile_id": "profile-custom",
                "metrics": {"cpu": {"mode": "direct_percent", "oid": "1.3.6.1.4.1.1"}},
                "interface": {},
                "profile_vendor": "H3C",
                "profile_model": "S6800",
                "template_name": "H3C S6800 Custom",
                "source": "custom",
                "official_preset_id": "",
                "profile_status": "unverified",
                "interface_profile_status": "unverified",
                "configured": True,
                "interface_configured": False,
            },
        },
    )
    try:
        bound = bind_model_metric_profile(conn, "profile-custom", ["device-1"])
        assert bound["bound_device_count"] == 1
        assert resolve_metric_profiles({
            "id": "device-1",
            "vendor": "H3C",
            "platform": "h3c_comware",
            "model": "S6800",
            "snmp_metric_profile_id": "profile-custom",
        })["profile_id"] == "profile-custom"
        assert resolve_metric_profiles({
            "id": "device-2",
            "vendor": "H3C",
            "platform": "h3c_comware",
            "model": "S6800",
            "snmp_metric_profile_id": "",
        })["profile_id"] == ""

        mapping = get_model_metric_profile_mapping(conn, "profile-custom")
        assert mapping["matched_device_count"] == 1
        assert mapping["devices"][0]["device_id"] == "device-1"

        unbound = unbind_model_metric_profile(conn, "profile-custom", ["device-1"])
        assert unbound["bound_device_count"] == 0
        with pytest.raises(ValueError, match="still bound"):
            bind_model_metric_profile(conn, "profile-custom", ["device-1"])
            delete_model_metric_profile(conn, "profile-custom")
    finally:
        conn.close()
