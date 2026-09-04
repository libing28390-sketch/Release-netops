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


def test_cisco_configuration_scope_offers_bounded_cli_platform_choices():
    decision = assess_configuration_request(
        message="那可以提供思科的吗",
        metadata={
            "vendor": "Cisco",
            "feature": "ospf",
            "document_category": "configuration",
        },
        resolution={"ambiguous": True, "platform_candidates": []},
    )

    assert decision is not None
    assert decision.required is True
    assert decision.missing_fields == ("platform_or_model",)
    assert [option["value"] for option in decision.options[:3]] == [
        "cisco_iosxe",
        "cisco_ios",
        "cisco_nxos",
    ]
    assert all(option["field"] == "cli_platform" for option in decision.options)


def test_h3c_configuration_scope_offers_comware_platform_choice():
    decision = assess_configuration_request(
        message="华三交换机 OSPF 配置",
        metadata={
            "vendor": "H3C",
            "feature": "ospf",
            "document_category": "configuration",
        },
        resolution={"ambiguous": True, "platform_candidates": []},
    )

    assert decision is not None
    assert decision.required is True
    assert decision.missing_fields == ("platform_or_model",)
    assert decision.options[0] == {
        "field": "cli_platform",
        "value": "h3c_comware",
        "label": "H3C Comware",
    }


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


def test_explicit_non_execution_guard_is_not_classified_as_configuration_change():
    decision = assess_configuration_request(
        message="请仅基于本地知识库回答：Cisco IOS XE HSRP 基础配置和验证命令；不要执行设备操作。",
        metadata={
            "vendor": "Cisco",
            "cli_platform": "cisco_iosxe",
            "feature_domain": "reliability",
            "feature": "hsrp",
            "document_category": "configuration",
        },
        resolution={"ambiguous": False},
    )

    assert decision is not None
    assert decision.request_kind == "configuration_reference"
    assert decision.risk == "medium"
    assert decision.required is False
    assert decision.retrieval_allowed is True
