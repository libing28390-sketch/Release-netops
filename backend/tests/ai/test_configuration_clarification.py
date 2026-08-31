from __future__ import annotations

from ai.services.config_clarification import assess_configuration_request


def test_vendor_only_configuration_returns_bounded_feature_and_platform_choices():
    decision = assess_configuration_request(
        message="请给我华为交换机配置",
        metadata={"vendor": "Huawei", "document_category": "configuration"},
        resolution={"ambiguous": True, "platform_candidates": []},
    )

    assert decision is not None
    assert decision.required is True
    assert decision.retrieval_allowed is False
    assert decision.missing_fields == ("feature", "platform_or_model")
    assert len(decision.options) <= 12
    assert all(set(option) >= {"field", "value", "label"} for option in decision.options)


def test_exact_configuration_scope_can_retrieve_without_clarification():
    decision = assess_configuration_request(
        message="Huawei S5735-L-V2 V600 VLAN config",
        metadata={
            "vendor": "Huawei",
            "product_series": "S5735-L-V2",
            "software_train": "V600",
            "cli_platform": "huawei_yunshan_v600",
            "feature": "vlan",
            "document_category": "configuration",
        },
        resolution={"ambiguous": False},
    )

    assert decision is not None
    assert decision.required is False
    assert decision.retrieval_allowed is True
    assert decision.missing_fields == ()


def test_full_configuration_export_is_always_device_data_only():
    decision = assess_configuration_request(
        message="请给我设备 sw-core-01 的全量运行配置",
        metadata={
            "vendor": "Huawei",
            "device_identifier": "sw-core-01",
            "document_category": "configuration",
        },
        resolution={"ambiguous": False},
    )

    assert decision is not None
    assert decision.required is True
    assert decision.request_kind == "running_config_export"
    assert decision.retrieval_allowed is False
    assert decision.missing_fields == ()
    assert "设备只读数据源" in decision.question


def test_read_only_cli_command_keeps_cross_platform_explanation_available():
    decision = assess_configuration_request(
        message="display ospf peer meaning",
        metadata={"document_category": "cli_output", "feature": "ospf"},
        resolution={"ambiguous": True},
    )

    assert decision is not None
    assert decision.required is False
    assert decision.allow_generic_reference is True
    assert decision.retrieval_allowed is True
