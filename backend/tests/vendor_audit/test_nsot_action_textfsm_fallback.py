from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import operational_data_service
from services.platform_registry_service import PlatformRegistryError


def _profile_and_device(
    connection,
    *,
    profile_code: str,
    platform: str,
    parser_platform: str,
    connection_driver: str,
) -> tuple[str, str, str]:
    profile_id = f"profile-{uuid.uuid4().hex}"
    release_id = f"release-{uuid.uuid4().hex}"
    device_id = f"device-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """INSERT INTO platform_profiles (
               id, tenant_id, platform_code, name_zh, name_en, vendor,
               connection_driver, parser_platform, source, status,
               description, current_release_id, created_by, created_at,
               updated_at, lock_version
           ) VALUES (?, 'tenant-default', ?, ?, ?, 'Test', ?, ?, 'CUSTOM',
                     'ACTIVE', '', NULL, 'test', ?, ?, 1)""",
        (
            profile_id,
            profile_code,
            profile_code,
            profile_code,
            connection_driver,
            parser_platform,
            now,
            now,
        ),
    )
    connection.execute(
        """INSERT INTO platform_releases (
               id, profile_id, release_number, status, connection_driver,
               parser_platform, safety_policy_json, checksum, created_by,
               created_at, updated_at, lock_version
           ) VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '', 'test', ?, ?, 1)""",
        (release_id, profile_id, connection_driver, parser_platform, now, now),
    )
    connection.execute(
        "UPDATE platform_profiles SET current_release_id = ? WHERE id = ?",
        (release_id, profile_id),
    )
    connection.execute(
        """INSERT INTO devices (
               id, hostname, ip_address, platform, status, tenant_id,
               platform_profile_id
           ) VALUES (?, ?, '192.0.2.240', ?, 'online', 'tenant-default', ?)""",
        (device_id, device_id, platform, profile_id),
    )
    connection.commit()
    return profile_id, release_id, device_id


def _template(
    *,
    filename: str,
    platform: str,
    command: str,
    version: str = "common",
    action_code: str = "",
    source: str = "builtin",
) -> dict:
    return {
        "filename": filename,
        "platform": platform,
        "platform_family": platform,
        "command": command,
        "version": version,
        "action_code": action_code,
        "source": source,
    }


class _FakeActionSession:
    def __init__(self, output: str = "sample output"):
        self.output = output
        self.commands: list[str] = []

    def send_command(self, command: str):
        self.commands.append(command)
        return SimpleNamespace(success=True, output=self.output, error="")


def test_bound_missing_action_uses_same_version_action_template(isolated_db, monkeypatch):
    connection = isolated_db["module"].get_db_connection()
    try:
        _profile_id, _release_id, device_id = _profile_and_device(
            connection,
            profile_code="nsot_test_h3c_v7",
            platform="h3c_comware",
            parser_platform="h3c_comware_v7",
            connection_driver="hp_comware",
        )
    finally:
        connection.close()

    device = {
        "id": device_id,
        "platform": "h3c_comware",
        "vendor": "h3c",
        "tenant_id": "tenant-default",
        "profile_platform_code": "nsot_test_h3c_v7",
        "profile_parser_platform": "h3c_comware_v7",
        "profile_connection_driver": "hp_comware",
        "platform_profile_id": "profile-present",
    }
    templates = [_template(
        filename="h3c_comware_v7_display_ip_routing_table.textfsm",
        platform="h3c_comware",
        command="display ip routing-table",
        version="v7",
        action_code="get_route_table",
        source="custom",
    )]
    monkeypatch.setattr("core.textfsm.list_templates", lambda: templates)
    observed_parse: list[dict] = []

    def fake_parse(_device, command, output, **kwargs):
        observed_parse.append({"command": command, "output": output, **kwargs})
        return {
            "records": [{"prefix": "10.0.0.0/8"}],
            "parse_status": "matched",
            "parser": "textfsm:h3c_comware_v7_display_ip_routing_table.textfsm",
            "parser_platform": "h3c_comware_v7",
            "template": kwargs.get("template_filename"),
            "template_source": "custom",
            "template_action_code": "get_route_table",
        }

    monkeypatch.setattr(operational_data_service, "parse_device_cli_output", fake_parse)
    session = _FakeActionSession("route output")

    results = operational_data_service._collect_registry_categories(
        device,
        "h3c_comware",
        ["routing_table"],
        platform_action_session=session,
    )

    item = results["routing_table"]
    assert session.commands == ["display ip routing-table"]
    assert item["success"] is True
    assert item["command_source"] == "textfsm_action_metadata"
    assert item["template"] == "h3c_comware_v7_display_ip_routing_table.textfsm"
    assert item["records"] == [{"prefix": "10.0.0.0/8"}]
    assert observed_parse[0]["template_filename"] == "h3c_comware_v7_display_ip_routing_table.textfsm"


def test_bound_missing_action_without_code_uses_exact_category_command(isolated_db, monkeypatch):
    connection = isolated_db["module"].get_db_connection()
    try:
        _profile_id, _release_id, device_id = _profile_and_device(
            connection,
            profile_code="nsot_test_cisco_eigrp",
            platform="cisco_ios",
            parser_platform="cisco_ios",
            connection_driver="cisco_ios",
        )
    finally:
        connection.close()

    device = {
        "id": device_id,
        "platform": "cisco_ios",
        "vendor": "cisco",
        "tenant_id": "tenant-default",
        "profile_platform_code": "nsot_test_cisco_eigrp",
        "profile_parser_platform": "cisco_ios",
        "profile_connection_driver": "cisco_ios",
        "platform_profile_id": "profile-present",
    }
    monkeypatch.setattr("core.textfsm.list_templates", lambda: [_template(
        filename="cisco_ios_show_ip_eigrp_neighbors.textfsm",
        platform="cisco_ios",
        command="show ip eigrp neighbors",
        action_code="",
    )])
    monkeypatch.setattr(
        operational_data_service,
        "parse_device_cli_output",
        lambda _device, command, output, **kwargs: {
            "records": [{"neighbor": "192.0.2.2"}],
            "parse_status": "matched",
            "parser": "textfsm",
            "parser_platform": "cisco_ios",
            "template": kwargs.get("template_filename"),
            "template_source": "builtin",
        },
    )
    session = _FakeActionSession()

    result = operational_data_service._collect_registry_categories(
        device,
        "cisco_ios",
        ["eigrp"],
        platform_action_session=session,
    )["eigrp"]

    assert session.commands == ["show ip eigrp neighbors"]
    assert result["success"] is True
    assert result["command_source"] == "legacy_catalog_textfsm"
    assert result["template_action_code"] is None


def test_bound_missing_action_does_not_cross_parser_version(isolated_db, monkeypatch):
    connection = isolated_db["module"].get_db_connection()
    try:
        _profile_id, _release_id, device_id = _profile_and_device(
            connection,
            profile_code="nsot_test_h3c_v7_no_action",
            platform="h3c_comware",
            parser_platform="h3c_comware_v7",
            connection_driver="hp_comware",
        )
    finally:
        connection.close()

    device = {
        "id": device_id,
        "platform": "h3c_comware",
        "vendor": "h3c",
        "tenant_id": "tenant-default",
        "profile_platform_code": "nsot_test_h3c_v7_no_action",
        "profile_parser_platform": "h3c_comware_v7",
        "profile_connection_driver": "hp_comware",
        "platform_profile_id": "profile-present",
    }
    monkeypatch.setattr("core.textfsm.list_templates", lambda: [_template(
        filename="h3c_comware_v5_display_ip_routing_table.textfsm",
        platform="h3c_comware",
        command="display ip routing-table",
        version="v5",
        action_code="get_route_table",
    )])
    session = _FakeActionSession()

    result = operational_data_service._collect_registry_categories(
        device,
        "h3c_comware",
        ["routing_table"],
        platform_action_session=session,
    )["routing_table"]

    assert session.commands == []
    assert result["success"] is False
    assert result["parse_status"] == "unsupported_by_platform"
    assert result["error_code"] == "UNSUPPORTED_ACTION"
    assert "同 parser/version" in result["fallback_condition"]


def test_unsafe_textfsm_fallback_command_is_rejected(monkeypatch):
    device = {
        "platform": "cisco_ios",
        "vendor": "cisco",
        "profile_platform_code": "cisco_ios",
        "profile_parser_platform": "cisco_ios",
        "profile_connection_driver": "cisco_ios",
    }
    monkeypatch.setattr("core.textfsm.list_templates", lambda: [_template(
        filename="cisco_ios_show_ip_route_unsafe.textfsm",
        platform="cisco_ios",
        command="show ip route | include 10.0.0.0",
        version="common",
        action_code="get_route_table",
    )])

    resolved = operational_data_service.resolve_textfsm_operation_fallback(
        device,
        operational_category="routing_table",
        action_code="get_route_table",
    )

    assert resolved["status"] == "unsupported"
    assert resolved["commands"] == []


def test_current_release_registry_action_does_not_enter_fallback(isolated_db, monkeypatch):
    connection = isolated_db["module"].get_db_connection()
    try:
        profile_id, release_id, device_id = _profile_and_device(
            connection,
            profile_code="nsot_test_registry_precedence",
            platform="cisco_ios",
            parser_platform="cisco_ios",
            connection_driver="cisco_ios",
        )
        connection.execute(
            """INSERT INTO platform_release_actions (
                   id, release_id, action_code, command, parser_template_version_id,
                   field_contract_json, command_checksum, created_at, updated_at
               ) VALUES (?, ?, 'get_route_table', 'show ip route', NULL, '{}', '', ?, ?)""",
            (f"action-{uuid.uuid4().hex}", release_id, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
    finally:
        connection.close()

    device = {
        "id": device_id,
        "platform": "cisco_ios",
        "vendor": "cisco",
        "tenant_id": "tenant-default",
        "platform_profile_id": profile_id,
    }
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "command": "show ip route",
            "records": [{"prefix": "10.0.0.0/8"}],
            "parse_status": "matched",
            "parser": "textfsm",
        },
    )
    monkeypatch.setattr(
        operational_data_service,
        "resolve_textfsm_operation_fallback",
        lambda *_args, **_kwargs: pytest.fail("published Registry actions must retain precedence"),
    )

    result = operational_data_service._collect_registry_categories(
        device,
        "cisco_ios",
        ["routing_table"],
    )["routing_table"]

    assert result["success"] is True
    assert result["command_source"] == "platform_registry"
    assert result["commands"] == ["show ip route"]


def test_collect_operational_data_routes_actionless_category_to_textfsm_fallback(isolated_db, monkeypatch):
    connection = isolated_db["module"].get_db_connection()
    try:
        _profile_id, _release_id, device_id = _profile_and_device(
            connection,
            profile_code="nsot_test_cisco_eigrp_category",
            platform="cisco_ios",
            parser_platform="cisco_ios",
            connection_driver="cisco_ios",
        )
        connection.execute(
            "UPDATE devices SET role = ?, collection_policy_json = ? WHERE id = ?",
            (
                "router",
                '{"template":"custom","collectors":{"eigrp":true}}',
                device_id,
            ),
        )
        connection.commit()
        device = dict(connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone())
    finally:
        connection.close()

    fallback_calls: list[tuple[str, str | None]] = []

    def resolve_fallback(_device, *, operational_category, action_code, **_kwargs):
        fallback_calls.append((operational_category, action_code))
        return {
            "status": "supported",
            "commands": [{
                "action_code": None,
                "command": "show ip eigrp neighbors",
                "command_source": "legacy_catalog_textfsm",
                "textfsm_template": "cisco_ios_show_ip_eigrp_neighbors.textfsm",
                "textfsm_source": "builtin",
                "status": "supported",
            }],
        }

    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PlatformRegistryError("UNSUPPORTED_ACTION", "no release action")
        ),
    )
    monkeypatch.setattr(operational_data_service, "resolve_textfsm_operation_fallback", resolve_fallback)
    monkeypatch.setattr(
        operational_data_service,
        "_execute_textfsm_operation_fallback",
        lambda _device, fallback, **_kwargs: {
            "success": True,
            "action_code": None,
            "command": fallback["command"],
            "command_source": fallback["command_source"],
            "raw_output": "EIGRP neighbor output",
            "records": [{"neighbor": "192.0.2.2"}],
            "parse_status": "matched",
            "parser": "textfsm",
            "parser_platform": "cisco_ios",
            "template": fallback["textfsm_template"],
            "template_source": fallback["textfsm_source"],
        },
    )

    result = operational_data_service.collect_operational_data(device, categories=["eigrp"])
    category = result["categories"][0]

    assert fallback_calls == [("eigrp", None)]
    assert category["success"] is True
    assert category["command_source"] == "legacy_catalog_textfsm"
    assert category["commands"] == ["show ip eigrp neighbors"]
    assert category["records"] == [{"neighbor": "192.0.2.2"}]
