from __future__ import annotations

from services import snmp_discovery_service
from services import snmp_import_identification_service


def test_librenms_os_display_name_is_not_used_as_device_model(monkeypatch):
    monkeypatch.setattr(snmp_discovery_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(
        snmp_discovery_service,
        "_resolve_optional_identity_rule",
        lambda *_args, **_kwargs: {
            "vendor": "H3C",
            "platform": "h3c_comware",
            "display_name": "HPE Comware",
        },
    )

    identity = snmp_discovery_service.resolve_snmp_vendor_identity(
        object(),
        sys_object_id=".1.3.6.1.4.1.25506.11.1.1",
        sys_descr="H3C Comware Version 7.1.070",
    )

    assert identity["vendor"] == "H3C"
    assert identity["model"] == ""


def test_h3c_comware_sysdescr_extracts_explicit_model_lines():
    assert snmp_discovery_service._model_from_descr(
        "H3C Comware Platform Software, Software Version 7.1.070, Alpha 7170\r\n"
        "H3C S6850\r\nCopyright (c) New H3C Technologies Co., Ltd."
    ) == "S6850"
    assert snmp_discovery_service._model_from_descr(
        "H3C Comware Software. Software Version 7.1.064\n"
        "H3C SecPath F1090\nCopyright (c) New H3C Technologies Co., Ltd."
    ) == "SecPath F1090"
    assert snmp_discovery_service._model_from_descr(
        "H3C Comware Platform Software, Software Version 7.1.064\r\n"
        "H3C WX5540H-HCL\r\nCopyright (c) New H3C Technologies Co., Ltd."
    ) == "WX5540H-HCL"
    assert snmp_discovery_service._model_from_descr(
        "H3C Comware Platform Software, Software Version 7.1.064"
    ) == ""


def test_snmp_identity_returns_h3c_model_without_vendor_prefix(monkeypatch):
    monkeypatch.setattr(snmp_discovery_service, "ensure_rules_available", lambda: {"status": "cached"})
    monkeypatch.setattr(snmp_discovery_service, "_resolve_optional_identity_rule", lambda *_args, **_kwargs: None)

    identity = snmp_discovery_service.resolve_snmp_vendor_identity(
        object(),
        sys_object_id=".1.3.6.1.4.1.25506.11.1.1",
        sys_descr=(
            "H3C Comware Platform Software, Software Version 7.1.070\r\n"
            "H3C S6850\r\nCopyright (c) New H3C Technologies Co., Ltd."
        ),
        asset_vendor="H3C",
    )

    assert identity["vendor"] == "H3C"
    assert identity["model"] == "S6850"


def test_model_name_strips_only_the_exact_canonical_vendor_prefix():
    normalize = snmp_discovery_service.normalize_model_name

    assert normalize("H3C", "H3C S6850") == "S6850"
    assert normalize("Cisco", "Cisco Catalyst 9300") == "Catalyst 9300"
    assert normalize("Huawei", "NE40E") == "NE40E"
    assert normalize("H3C", "SecPath F1090") == "SecPath F1090"
    assert normalize("H3C", "XH3C S6850") == "XH3C S6850"


def test_import_model_prefers_operator_and_chassis_over_stale_sysdescr_values() -> None:
    assert snmp_import_identification_service._select_import_model(
        vendor="H3C",
        declared_model="",
        current_asset_model="H3C Comware Platform Software, Version 7.1.064",
        current_device_model="H3C Comware Platform Software, Version 7.1.064",
        chassis_model="H3C F1060",
        sysdescr_model="H3C Comware Platform Software, Version 7.1.064",
        observed_sysdescr_model="H3C Comware Platform Software, Version 7.1.064",
    ) == "F1060"
    assert snmp_import_identification_service._select_import_model(
        vendor="H3C",
        declared_model="H3C F1060",
        current_asset_model="H3C Comware Platform Software, Version 7.1.064",
        current_device_model="H3C Comware Platform Software, Version 7.1.064",
        chassis_model="H3C WX5540H-HCL",
        sysdescr_model="H3C Comware Platform Software, Version 7.1.064",
        observed_sysdescr_model="H3C Comware Platform Software, Version 7.1.064",
    ) == "F1060"
    assert snmp_import_identification_service._select_import_model(
        vendor="H3C",
        declared_model="",
        current_asset_model="H3C S6850",
        current_device_model="H3C S6850",
        chassis_model="H3C S6850",
        sysdescr_model="S6850",
        observed_sysdescr_model="H3C Comware Platform Software, Version 7.1.070",
    ) == "S6850"
