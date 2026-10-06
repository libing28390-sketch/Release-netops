from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries

from api import assets
from api.devices import _resolve_platform_binding
from core.platform_utils import normalize_device_platform
from services.config_vendor_platform_service import validate_vendor_platform
from services.operational_data_service import _normalize_platform, resolve_device_platform_context
from services.platform_identification_service import _inventory_profile_code, identify_platforms
from services.platform_registry_service import (
    PLATFORM_ACTION_COMMANDS,
    PLATFORM_CATALOG_METADATA,
    SYSTEM_PROFILES,
    get_profile_action_commands,
    normalize_platform_code,
)


ALIASES = (
    "huawei_yunshan",
    "yunshan",
    "yunshanos",
    "yunshan_os",
    "YunShan OS",
    "huawei_yunshan_os",
    "Huawei YunShan OS",
    "华为云杉",
    "华为 YunShan OS（云杉）",
    "华为 YunShan OS (云杉)",
)


@pytest.mark.parametrize("alias", ALIASES)
def test_yunshan_aliases_keep_the_independent_platform_key(alias: str) -> None:
    assert normalize_device_platform("Huawei", alias) == "huawei_yunshan"
    assert assets._normalize_asset_platform("Huawei", alias) == "huawei_yunshan"
    assert normalize_platform_code(alias) == "huawei_yunshan"
    assert _normalize_platform(alias) == "huawei_yunshan"


def test_yunshan_profile_separates_transport_parser_and_catalog() -> None:
    profile = next(item for item in SYSTEM_PROFILES if item["platform_code"] == "huawei_yunshan")
    assert profile["vendor"] == "Huawei"
    assert profile["connection_driver"] == "huawei_vrp"
    assert profile["parser_platform"] == "huawei_yunshan"
    assert PLATFORM_CATALOG_METADATA["huawei_yunshan"] == {
        "catalog_vendor": "huawei",
        "platform_family": "huawei_yunshan",
        "version": "common",
    }
    assert PLATFORM_ACTION_COMMANDS["huawei_yunshan"] == {
        "get_version": "display version",
        "get_interface_brief": "display interface brief",
        "get_ip_interfaces": "display ip interface brief",
        "get_lldp_neighbors": "display lldp neighbor brief",
        "get_arp_table": "display arp",
        "get_mac_table": "display mac-address",
    }
    assert get_profile_action_commands(profile) == PLATFORM_ACTION_COMMANDS["huawei_yunshan"]

    context = resolve_device_platform_context({
        "vendor": "Huawei",
        "platform": "YunShan OS",
        "profile_platform_code": "huawei_yunshan",
        "profile_parser_platform": "huawei_yunshan",
        "profile_connection_driver": "huawei_vrp",
    })
    assert context["public_platform"] == "huawei_yunshan"
    assert context["catalog_platform"] == "huawei_yunshan"
    assert context["parser_platform"] == "huawei_yunshan"
    assert context["connection_driver"] == "huawei_vrp"
    assert _inventory_profile_code("YunShan OS", "1.24.0.1", "Huawei") == (
        "huawei_yunshan", "huawei_yunshan",
    )
    assert _resolve_platform_binding(None, "", "YunShan OS", device_vendor="Huawei")[0] == (
        "huawei_yunshan"
    )


@pytest.mark.parametrize("alias", ALIASES)
def test_config_vendor_platform_accepts_yunshan_aliases(alias: str) -> None:
    assert validate_vendor_platform("Huawei", alias) == ("Huawei", "huawei_yunshan")


def test_dynamic_asset_import_workbook_lists_yunshan_for_huawei_and_networks() -> None:
    content = assets._build_asset_import_template([])
    workbook = load_workbook(BytesIO(content), data_only=False)
    options = workbook["下拉选项"]

    for defined_name in ("Platform_Huawei", "Platform_All_Network"):
        attr_text = workbook.defined_names[defined_name].attr_text
        sheet_name, reference = attr_text.rsplit("!", 1)
        sheet_name = sheet_name.strip("'")
        min_col, min_row, max_col, max_row = range_boundaries(reference)
        values = [
            str(options.cell(row=row, column=column).value or "").strip()
            for row in range(min_row, max_row + 1)
            for column in range(min_col, max_col + 1)
        ]
        assert sheet_name == "下拉选项"
        assert "Huawei YunShan OS" in values


def test_identification_prefers_yunshan_to_the_shared_vrp_title(isolated_db) -> None:
    result = identify_platforms(
        {
            "display version": (
                "Huawei Versatile Routing Platform Software\n"
                "YunShan OS, Version 1.25.1.1 (CE6800 V300R025C10SPC500)"
            ),
        },
        {"role": "Administrator", "tenant_id": ""},
    )
    assert result["success"] is True
    assert result["selected"]["platform_code"] == "huawei_yunshan"
    assert [item["platform_code"] for item in result["suggestions"]] == ["huawei_yunshan"]

\n