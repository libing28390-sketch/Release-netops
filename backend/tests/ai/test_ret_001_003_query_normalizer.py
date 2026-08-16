from ai.services.query_normalizer import NORMALIZER_VERSION, normalize_query
from ai.services.intent_parser import IntentParser


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


def test_legacy_intent_parser_projects_normalizer_fields():
    parser = IntentParser()
    metadata = parser.parse_knowledge_metadata("S5735-L-V2 V600 ARP")

    assert metadata["product_series"] == "S5735-L-V2"
    assert metadata["software_train"] == "V600"
    assert metadata["cli_platform"] is None
    assert metadata["query_normalization"]["normalizer_version"] == NORMALIZER_VERSION

