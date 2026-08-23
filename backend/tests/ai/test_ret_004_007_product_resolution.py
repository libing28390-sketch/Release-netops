from ai.services.product_resolver import product_resolver
from ai.services.query_normalizer import normalize_query


def test_exact_model_match_returns_canonical_series_and_model():
    resolution = product_resolver.resolve_query("Huawei CE6885", metadata={"vendor": "Huawei"})

    assert resolution.match_method == "exact"
    assert resolution.match_score == 1.0
    assert resolution.metadata["product_series"] == "CloudEngine 6800"
    assert resolution.metadata["product_model"] == "ce6885"
    assert resolution.ambiguous is False


def test_canonical_alias_match_is_explicit_and_prefix_is_candidate_only():
    canonical = product_resolver.resolve_query("Catalyst 9300")
    prefix = product_resolver.resolve_query("S57 V600 VLAN config")

    assert canonical.match_method == "canonical"
    assert canonical.metadata["product_series"] == "Catalyst 9300"
    assert canonical.metadata["product_model"] == "c9300"
    assert prefix.match_method == "prefix"
    assert prefix.ambiguous is True
    assert prefix.candidates[0]["product_model"] == "s5735-l-v2"


def test_normalizer_and_resolver_preserve_unknown_product_as_unknown():
    normalized = normalize_query("Huawei unknown-9000 show vlan")
    resolution = product_resolver.resolve_query("Huawei unknown-9000 show vlan")

    assert normalized.model is None
    assert resolution.match_method == "none"
    assert resolution.metadata.get("product_series") is None
    assert resolution.metadata.get("product_model") is None


def test_full_huawei_sku_alias_remains_matchable_to_hardware_registry():
    resolution = product_resolver.resolve_query("Huawei CE6885-48YS8CQ 型号")

    assert resolution.match_method == "canonical"
    assert resolution.metadata["product_series"] == "CloudEngine 6800"
    assert resolution.metadata["product_model"] == "ce6885-48ys8cq"
