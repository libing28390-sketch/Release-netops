from ai.services.query_normalizer import NORMALIZER_VERSION, normalize_query
from ai.services.intent_parser import IntentParser
from ai.schemas.knowledge import KnowledgeQueryPlan


def test_normalizer_contract_extracts_explicit_entities_and_keeps_absent_null():
    normalized = normalize_query("Huawei CE6885 V300 display ospf peer down")

    assert normalized.normalizer_version == NORMALIZER_VERSION
    assert normalized.vendor == "Huawei"
    assert normalized.product == "CloudEngine 6800"
    assert normalized.model == "CE6885"
    assert normalized.version == "V300"
    assert normalized.topic == "ospf"
    assert normalized.command == "display ospf peer down"
    assert normalized.error == "down"
    assert normalized.intent == "cli_output"
    assert normalized.os_family is None
    assert normalized.generation is None
    assert normalized.to_dict()["query_hash"]


def test_normalizer_supports_operator_aliases_without_inventing_platform():
    normalized = normalize_query("Catalyst93 vlan config")

    assert normalized.vendor is None
    assert normalized.product == "Catalyst 9300"
    assert normalized.topic == "vlan"
    assert normalized.document_category == "configuration"
    assert normalized.os_family is None
    assert normalized.generation is None


def test_normalizer_redacts_secret_literals_and_preserves_unknowns_as_null():
    normalized = normalize_query("show vlan token=sk-live-secret unknown-model")

    assert "sk-live-secret" not in normalized.normalized_text
    assert "sensitive_literal_redacted" in normalized.warnings
    assert normalized.vendor is None
    assert normalized.model is None
    assert normalized.os_family is None
    assert normalized.generation is None


def test_normalizer_does_not_treat_ipv4_default_route_as_software_release():
    normalized = normalize_query("Cisco Catalyst ip route 0.0.0.0 0.0.0.0 default gateway")

    assert normalized.version is None
    assert normalized.product is None
    assert normalized.vendor == "Cisco"


def test_legacy_intent_parser_projects_normalizer_fields():
    parser = IntentParser()
    metadata = parser.parse_knowledge_metadata("S5735-L-V2 V600 ARP")

    assert metadata["product_series"] == "S5735-L-V2"
    assert metadata["software_train"] == "V600"
    assert metadata["cli_platform"] is None
    assert metadata["query_normalization"]["normalizer_version"] == NORMALIZER_VERSION


def test_mixed_language_model_tokens_are_detected_without_ascii_word_boundaries():
    query = "我想知道华为交换机S5700的OSPF配置示例"

    normalized = normalize_query(query)
    metadata = IntentParser().parse_knowledge_metadata(query)

    assert normalized.product == "S5700"
    assert metadata["product_series"] == "S5700"
    assert metadata["feature"] == "ospf"
    assert metadata["document_category"] == "configuration"


def test_vendor_model_tokens_cover_h3c_cisco_campus_and_data_center_skus():
    cases = (
        ("H3C S5130S-28P-EI VLAN配置", "S5130S", "S5130S-28P-EI"),
        ("H3C S6850 VLAN配置", "S6850", None),
        ("H3C S9825-64D BGP配置", "S9825", "S9825-64D"),
        ("Cisco Catalyst 3850 trunk配置", "CATALYST3850", None),
        ("Cisco C9200L-24P-4G VLAN配置", "Catalyst 9200", "C9200L-24P-4G"),
        ("Cisco N9K-C93180YC-FX VXLAN配置", "Nexus 9000", "N9K-C93180YC-FX"),
        ("Huawei CE8851-32CQ8DQ-K VXLAN配置", "CloudEngine 8800", "CE8851-32CQ8DQ-K"),
    )
    for query, product, model in cases:
        normalized = normalize_query(query)
        assert normalized.product == product
        assert normalized.model == model


def test_h3c_chinese_alias_projects_the_same_scoped_knowledge_metadata():
    parser = IntentParser()
    for query in ("华三 S5130S OSPF 配置", "新华三 S5130S OSPF 配置"):
        normalized = normalize_query(query)
        metadata = parser.parse_knowledge_metadata(query)

        assert normalized.vendor == "H3C"
        assert metadata["vendor"] == "H3C"
        assert metadata["product_series"] == "S5130S"
        assert metadata["feature"] == "ospf"
        assert metadata["document_category"] == "configuration"
        assert metadata["device_identifier"] is None


def test_explicit_h3c_comware_platform_is_canonicalized():
    metadata = IntentParser().parse_knowledge_metadata("华三 Comware 7 OSPF 配置")

    assert metadata["vendor"] == "H3C"
    assert metadata["cli_platform"] == "h3c_comware"
    assert metadata["os_family"] == "Comware"
    assert metadata["os_generation"] == "COMWARE-7"


def test_explicit_huawei_vrp_v200_alias_uses_reviewed_storage_taxonomy():
    metadata = IntentParser().parse_knowledge_metadata(
        "华为 VRP V200 SSH 安全登录配置"
    )

    assert metadata["vendor"] == "Huawei"
    assert metadata["cli_platform"] == "huawei_vrp_v200"
    assert metadata["os_family"] == "VRP"
    assert metadata["os_generation"] is None


def test_version_qualified_cli_platform_aliases_share_the_storage_taxonomy():
    h3c_plan = KnowledgeQueryPlan.from_sources(
        "H3C Comware v7 VLAN configuration",
        {"vendor": "H3C", "cli_platform": "h3c_comware_v7", "feature": "vlan"},
    )
    huawei_plan = KnowledgeQueryPlan.from_sources(
        "Huawei CE12800 VXLAN configuration",
        {"vendor": "Huawei", "cli_platform": "huawei_vrpv8", "feature": "vxlan"},
    )

    assert h3c_plan.cli_platform == "h3c_comware"
    assert huawei_plan.cli_platform == "huawei_vrp"


def test_specific_eth_trunk_alias_wins_over_generic_trunk():
    metadata = IntentParser().parse_knowledge_metadata(
        "华为交换机 Eth-Trunk 链路聚合 mode lacp-static"
    )

    assert metadata["feature"] == "lacp"


def test_h3c_packet_filter_alias_projects_to_acl_feature():
    metadata = IntentParser().parse_knowledge_metadata(
        "H3C Comware 7 packet-filter 3000 inbound"
    )

    assert metadata["feature"] == "acl"
    assert metadata["feature_domain"] == "security"


def test_cisco_hsrp_is_kept_distinct_from_vrrp():
    metadata = IntentParser().parse_knowledge_metadata(
        "Cisco Catalyst HSRP standby 1 ip 192.0.2.1 配置"
    )

    assert metadata["vendor"] == "Cisco"
    assert metadata["feature"] == "hsrp"
    assert metadata["feature_domain"] == "reliability"


def test_legacy_intent_parser_recognizes_catalyst_3850_series():
    metadata = IntentParser().parse_knowledge_metadata(
        "Cisco Catalyst 3850 switchport mode trunk allowed vlan 配置"
    )

    assert metadata["vendor"] == "Cisco"
    assert metadata["product_series"] == "Catalyst 3850"
    assert metadata["product_model"] is None
    assert metadata["feature"] == "trunk"


def test_explicit_cisco_iosxe_platform_is_scoped_to_cisco_vendor():
    metadata = IntentParser().parse_knowledge_metadata(
        "Cisco IOS-XE show ip arp 192.0.2.10"
    )

    assert metadata["vendor"] == "Cisco"
    assert metadata["cli_platform"] == "cisco_iosxe"
    assert metadata["os_family"] == "IOS XE"
    assert metadata["os_generation"] is None


def test_explicit_cisco_nxos_platform_is_scoped_to_cisco_vendor():
    metadata = IntentParser().parse_knowledge_metadata(
        "Cisco NX-OS show ip bgp summary"
    )

    assert metadata["vendor"] == "Cisco"
    assert metadata["cli_platform"] == "cisco_nxos"
    assert metadata["os_family"] == "NX-OS"
