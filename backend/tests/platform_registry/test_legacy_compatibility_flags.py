"""Regression coverage for the explicitly temporary legacy compatibility gates."""


def test_textfsm_filename_fallback_is_disabled_without_legacy_gate(monkeypatch):
    from core import textfsm

    monkeypatch.setenv("LEGACY_TEXTFSM_FILE_FALLBACK_ENABLED", "0")
    names = textfsm._template_filename_variants("cisco_ios", "show mac-address-table")

    assert names == ["cisco_ios_show_mac_address_table.textfsm"]

    monkeypatch.setenv("LEGACY_TEXTFSM_FILE_FALLBACK_ENABLED", "1")
    names_with_fallback = textfsm._template_filename_variants("cisco_ios", "show mac-address-table")
    assert names_with_fallback == [
        "cisco_ios_show_mac_address_table.textfsm",
        "cisco_ios_show_mac-address-table.textfsm",
    ]


def test_command_catalog_fallback_is_empty_when_legacy_gate_is_disabled(monkeypatch):
    from services import operational_data_service

    monkeypatch.setitem(
        operational_data_service.COMMAND_CATALOG,
        "legacy_test",
        {"interfaces": ["legacy interface command"]},
    )
    monkeypatch.setenv("LEGACY_COMMAND_CATALOG_ENABLED", "0")
    assert operational_data_service._resolve_commands("legacy_test", ["interfaces"]) == {
        "interfaces": []
    }

    monkeypatch.setenv("LEGACY_COMMAND_CATALOG_ENABLED", "1")
    assert operational_data_service._resolve_commands("legacy_test", ["interfaces"]) == {
        "interfaces": ["legacy interface command"]
    }

