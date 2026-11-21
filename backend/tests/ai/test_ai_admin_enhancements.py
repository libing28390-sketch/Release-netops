from __future__ import annotations

import json

from ai.api.providers import list_providers


def _insert_provider(connection, *, provider_id: str, name: str, provider_type: str,
                     data_region: str, health_status: str, enabled: bool, tags: list[str], created_at: str) -> None:
    connection.execute(
        """
        INSERT INTO ai_provider (
            id, name, provider_type, base_url, api_key_encrypted, api_key_masked,
            timeout, max_retries, proxy_url, enabled, created_by, created_at, updated_at,
            tags_json, health_status, data_region, allowed_data_classification,
            no_training_confirmed, retention_days, data_processing_agreement_ref,
            agreement_reviewed_at, approved_endpoint_patterns_json
        ) VALUES (?, ?, ?, ?, NULL, NULL, 30, 3, NULL, ?, 'test', ?, ?, ?, ?, ?, 'PUBLIC', 0, NULL, NULL, NULL, '[]')
        """,
        (
            provider_id, name, provider_type, "https://example.test/v1", int(enabled),
            created_at, created_at, json.dumps(tags), health_status, data_region,
        ),
    )


def test_provider_registry_uses_server_side_filters_pagination_and_exact_tags(isolated_db):
    from database import get_db_connection

    with get_db_connection() as connection:
        _insert_provider(
            connection, provider_id="prov-global", name="OpenAI Global", provider_type="openai",
            data_region="global", health_status="healthy", enabled=True,
            tags=["production", "chat"], created_at="2026-08-30T00:00:01+00:00",
        )
        _insert_provider(
            connection, provider_id="prov-cn", name="Qwen China", provider_type="qwen",
            data_region="cn", health_status="unhealthy", enabled=True,
            tags=["production", "cn"], created_at="2026-08-30T00:00:02+00:00",
        )
        _insert_provider(
            connection, provider_id="prov-lab", name="Local Lab", provider_type="local",
            data_region="unknown", health_status="unknown", enabled=False,
            tags=["lab"], created_at="2026-08-30T00:00:03+00:00",
        )
        connection.commit()

    user = {"id": "provider-admin", "username": "provider-admin", "role": "Administrator"}
    page = list_providers(
        search="", data_region="", health_status="", enabled=True, provider_type="", tag="",
        page=1, page_size=1, user=user,
    )
    assert page.total == 2
    assert page.total_pages == 2
    assert len(page.items) == 1
    assert page.facets["data_regions"] == ["cn", "global", "unknown"]
    assert page.facets["health_statuses"] == ["healthy", "unhealthy", "unknown"]

    filtered = list_providers(
        search="", data_region="cn", health_status="unhealthy", enabled=None,
        provider_type="qwen", tag="production", page=1, page_size=20, user=user,
    )
    assert filtered.total == 1
    assert filtered.items[0].id == "prov-cn"

    exact_tag = list_providers(
        search="", data_region="", health_status="", enabled=None, provider_type="", tag="prod",
        page=1, page_size=20, user=user,
    )
    assert exact_tag.total == 0

    searched = list_providers(
        search="global", data_region="", health_status="", enabled=None, provider_type="", tag="",
        page=1, page_size=20, user=user,
    )
    assert searched.total == 1
    assert searched.items[0].name == "OpenAI Global"


def test_provider_legacy_array_contract_is_preserved_without_filters(isolated_db):
    from database import get_db_connection

    with get_db_connection() as connection:
        _insert_provider(
            connection, provider_id="prov-legacy", name="Legacy Provider", provider_type="openai_compatible",
            data_region="unknown", health_status="unknown", enabled=True, tags=[],
            created_at="2026-08-30T00:00:01+00:00",
        )
        connection.commit()

    result = list_providers(
        search="", data_region="", health_status="", enabled=None, provider_type="", tag="",
        page=None, page_size=20, user={"role": "Administrator"},
    )
    assert isinstance(result, list)
    assert [item.id for item in result] == ["prov-legacy"]
