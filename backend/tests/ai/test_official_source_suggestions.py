from types import SimpleNamespace
from urllib.parse import urlsplit

from services.official_source_suggestion_service import suggest_official_sources


def test_suggestions_are_vendor_allowlisted_and_model_aware():
    request = SimpleNamespace(vendor="华为", feature="ospf", product_model="S5700")
    suggestions = suggest_official_sources(request)

    assert suggestions
    assert "S5700" in suggestions[-1]["label"]
    assert all(urlsplit(item["url"]).hostname in {"support.huawei.com", "info.support.huawei.com"} for item in suggestions)
    assert all(item["source_kind"] in {"configuration_guide", "product_support"} for item in suggestions)


def test_unknown_vendor_does_not_get_an_invented_url():
    request = SimpleNamespace(vendor="Juniper", feature="ospf", product_model="EX4300")
    assert suggest_official_sources(request) == []
