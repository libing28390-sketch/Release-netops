from __future__ import annotations

import pytest

from services.ingestion_idempotency_service import (
    SourceContentDecision,
    build_source_content_identity,
    build_url_idempotency_key,
    classify_source_content,
)


def _identity(**overrides):
    value = {
        "tenant_id": "tenant-a",
        "source_id": "source-a",
        "canonical_url": "https://docs.example/guide",
        "content_hash": "a" * 64,
        "byte_size": 12,
    }
    value.update(overrides)
    return build_source_content_identity(**value)


def test_ing012_default_url_key_is_stable_without_retaining_url():
    first = build_url_idempotency_key("https://docs.example/guide")
    second = build_url_idempotency_key("https://docs.example/guide")

    assert first == second
    assert "docs.example" not in first


def test_ing012_existing_same_hash_is_replay():
    decision = classify_source_content(
        {
            "id": "version-a",
            "tenant_id": "tenant-a",
            "source_registry_id": "source-a",
            "content_hash": "a" * 64,
        },
        identity=_identity(),
    )

    assert decision.decision is SourceContentDecision.REPLAY
    assert decision.replayed is True
    assert decision.existing_version_id == "version-a"


def test_ing012_changed_hash_is_new_version():
    decision = classify_source_content(
        {
            "id": "version-a",
            "tenant_id": "tenant-a",
            "source_registry_id": "source-a",
            "content_hash": "b" * 64,
        },
        identity=_identity(),
    )

    assert decision.decision is SourceContentDecision.NEW_VERSION
    assert decision.replayed is False


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"content_hash": "bad"}, "IDEMPOTENCY_CONTENT_HASH_INVALID"),
        ({"canonical_url": "http://docs.example/guide"}, "IDEMPOTENCY_URL_INVALID"),
        ({"byte_size": -1}, "IDEMPOTENCY_BYTE_SIZE_INVALID"),
    ],
)
def test_ing012_identity_validation_is_fail_closed(changes, code):
    with pytest.raises(ValueError, match=code):
        _identity(**changes)


def test_ing012_cross_tenant_existing_version_is_conflict():
    decision = classify_source_content(
        {
            "id": "version-a",
            "tenant_id": "tenant-b",
            "source_registry_id": "source-a",
            "content_hash": "a" * 64,
        },
        identity=_identity(),
    )

    assert decision.decision is SourceContentDecision.CONFLICT
    assert decision.replayed is False
