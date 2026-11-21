import pytest

from ai.providers.embedding import (
    BaseEmbeddingProvider,
    EmbeddingProviderError,
    ExternalEmbeddingProvider,
    assert_pgvector_column_compatible,
    embed_documents_batch,
)
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy


class TinyLocalProvider(BaseEmbeddingProvider):
    model_id = "tiny-local"
    dimensions = 2
    version = "test-v1"
    mode = "local"

    def embed_text(self, text: str, dimensions=None):
        return [float(len(text)), 1.0]


def test_chk009_provider_contract_distinguishes_local_and_external():
    local = TinyLocalProvider()
    assert local.contract().mode == "local"
    gateway = AISecurityGateway(
        policy=SecurityPolicy(external_ai_enabled=True, allowed_provider_types=("test",), identifiers_must_be_tokenized=False)
    )
    seen = {}

    def transport(texts, metadata):
        seen["texts"] = list(texts)
        seen["metadata"] = dict(metadata)
        return [[1.0, 0.0] for _ in texts]

    external = ExternalEmbeddingProvider(
        transport,
        model_id="managed-test",
        dimensions=2,
        provider_type="test",
        security_gateway=gateway,
    )
    assert external.contract().mode == "external"
    assert external.embed_documents(["display interface"], tenant_id="tenant-a", task_id="chk-009") == [[1.0, 0.0]]
    assert seen["metadata"]["egress_kind"] == "embedding"
    events = gateway.embedding_audit_events()
    assert events and events[-1]["input_count"] == 1
    assert "display interface" not in repr(events[-1])


def test_chk010_external_embedding_is_blocked_before_transport_for_secret():
    gateway = AISecurityGateway(
        policy=SecurityPolicy(external_ai_enabled=True, allowed_provider_types=("test",), identifiers_must_be_tokenized=False)
    )
    called = False

    def transport(texts, metadata):
        nonlocal called
        called = True
        return [[1.0, 0.0] for _ in texts]

    external = ExternalEmbeddingProvider(
        transport,
        model_id="managed-test",
        dimensions=2,
        provider_type="test",
        security_gateway=gateway,
    )
    with pytest.raises(SecurityBlocked):
        external.embed_documents(["api_key=sk-test-secret"], tenant_id="tenant-a", task_id="chk-010")
    assert called is False


def test_chk011_dimension_contract_rejects_silent_mismatch():
    provider = TinyLocalProvider()
    provider.dimensions = 3
    with pytest.raises(EmbeddingProviderError, match="dimension mismatch"):
        embed_documents_batch(["display interface"], provider=provider, cache={}, batch_size=1)

    class VectorCursor:
        def execute(self, *_args):
            return self

        def fetchone(self):
            return ("vector(3)",)

    with pytest.raises(EmbeddingProviderError, match="pgvector column dimension"):
        assert_pgvector_column_compatible(VectorCursor(), expected_dimensions=2)


def test_chk012_batch_retry_rate_limit_and_idempotency():
    class FlakyProvider(TinyLocalProvider):
        def __init__(self):
            self.calls = 0

        def embed_documents(self, texts, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise EmbeddingProviderError("temporary provider error")
            return [[1.0, 0.0] for _ in texts]

    provider = FlakyProvider()
    cache = {}
    sleeps = []
    vectors = embed_documents_batch(
        ["show version", "display version"],
        provider=provider,
        cache=cache,
        batch_size=2,
        max_retries=1,
        sleep_fn=sleeps.append,
        idempotency_namespace="chk-012",
    )
    assert vectors == [[1.0, 0.0], [1.0, 0.0]]
    assert provider.calls == 2
    assert sleeps == [0.5]

    again = embed_documents_batch(
        ["show version", "display version"],
        provider=provider,
        cache=cache,
        batch_size=2,
        idempotency_namespace="chk-012",
    )
    assert again == vectors
    assert provider.calls == 2
