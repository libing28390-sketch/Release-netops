from __future__ import annotations

import json

from ai.api.providers import _row_to_provider


def _row(tags):
    return [
        "provider-1", "Provider", "deepseek", "https://api.deepseek.com", "sk-****1234",
        30, 3, None, 1, "admin", "2026-08-17T00:00:00Z", "2026-08-17T00:00:00Z",
        tags, "unknown", None, None, None, "unknown", "PUBLIC",
    ]


def test_provider_response_normalizes_legacy_object_tags_to_empty_list():
    response = _row_to_provider(_row({}))

    assert response.tags == []


def test_provider_response_accepts_decoded_and_json_tag_lists():
    assert _row_to_provider(_row(["network", "prod"])).tags == ["network", "prod"]
    assert _row_to_provider(_row(json.dumps(["network", "prod"]))).tags == ["network", "prod"]


def test_provider_response_drops_malformed_and_non_string_tags():
    response = _row_to_provider(_row('{"scope": "internal"}'))
    assert response.tags == []
    response = _row_to_provider(_row(json.dumps(["network", 3, "", " prod "])))
    assert response.tags == ["network", "prod"]
