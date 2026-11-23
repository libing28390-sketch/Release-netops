"""Contract tests for the commitments in ADR-006 and ADR-011 (batch 7).

Each test pins one sentence of an ADR so that the documents and the code
cannot drift apart silently again (review item L7).  When a test here fails,
either the code broke a recorded decision or the decision changed -- in the
second case update the ADR and this file together.

ADR-006  docs/knowledge-engine/adr/ADR-006-ai-egress-gateways.md
ADR-011  docs/knowledge-engine/adr/ADR-011-multi-provider-model-scope.md
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.config import settings

AI_ROOT = Path(__file__).resolve().parents[2] / "ai"

# Modules in backend/ai that may open a network connection, and why.
# Adding a module here is an ADR-006 decision: say which gateway or local
# allowlist protects it.
NETWORK_CLIENT_MODULES = {
    "providers/openai_compatible.py": "LLM provider transport; payload comes from AISecurityGateway.protect",
    "providers/embedding.py": "external embeddings via protect_embedding; bge-m3 sidecar restricted to local hosts",
    "services/retrieval_contract.py": "reranker sidecar restricted to local hosts",
    "services/langfuse_exporter.py": "metadata-only export restricted to local hosts",
}
NETWORK_LIBRARIES = {"httpx", "requests", "aiohttp", "urllib3", "urllib.request", "http.client", "openai", "anthropic"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            if node.module == "urllib":
                names.update(f"urllib.{alias.name}" for alias in node.names)
    return names


def _uses_network_library(imported: set[str]) -> set[str]:
    return {
        name for name in imported
        if any(name == lib or name.startswith(lib + ".") for lib in NETWORK_LIBRARIES)
    }


# ── ADR-006: one egress boundary ─────────────────────────────────────────


def test_adr006_only_reviewed_modules_open_network_connections():
    offenders = {}
    for path in sorted(AI_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(AI_ROOT).as_posix()
        used = _uses_network_library(_imported_modules(path))
        if used and rel not in NETWORK_CLIENT_MODULES:
            offenders[rel] = sorted(used)
    assert not offenders, (
        "backend/ai modules may not create their own HTTP clients (ADR-006); "
        f"route the call through the gateways or register it in NETWORK_CLIENT_MODULES: {offenders}"
    )


def test_adr006_registered_network_modules_still_exist():
    missing = [rel for rel in NETWORK_CLIENT_MODULES if not (AI_ROOT / rel).is_file()]
    assert not missing, f"remove stale entries from NETWORK_CLIENT_MODULES: {missing}"


def test_adr006_provider_transport_never_follows_redirects():
    source = (AI_ROOT / "providers" / "openai_compatible.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    redirect_flags = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "follow_redirects"
    ]
    assert redirect_flags, "the provider HTTP client must set follow_redirects explicitly"
    assert all(isinstance(flag, ast.Constant) and flag.value is False for flag in redirect_flags)


@pytest.mark.parametrize(
    ("ai_enabled", "external", "kill", "expect_external", "expect_kill"),
    [
        (True, True, False, True, False),    # deployment allows, policy allows
        (True, False, False, False, False),  # EXTERNAL_AI_ENABLED=false wins over the stored policy
        (False, True, False, False, False),  # AI_ENABLED=false wins over the stored policy
        (True, True, True, True, True),      # AI_KILL_SWITCH adds a stop the database cannot remove
    ],
)
def test_adr006_deployment_flags_are_a_ceiling_on_the_stored_policy(monkeypatch, ai_enabled, external, kill, expect_external, expect_kill):
    from ai.security.gateway import SecurityPolicy, apply_deployment_limits

    monkeypatch.setattr(settings, "AI_ENABLED", ai_enabled, raising=False)
    monkeypatch.setattr(settings, "EXTERNAL_AI_ENABLED", external, raising=False)
    monkeypatch.setattr(settings, "AI_KILL_SWITCH", kill, raising=False)
    stored = SecurityPolicy(external_ai_enabled=True, kill_switch=False)
    effective = apply_deployment_limits(stored)
    assert effective.external_ai_enabled is expect_external
    assert effective.kill_switch is expect_kill


@pytest.mark.parametrize(
    ("policy_kwargs", "provider_type", "region", "code"),
    [
        ({"external_ai_enabled": True, "kill_switch": True}, "openai", "global", "AI_SECURITY_KILL_SWITCH"),
        ({"external_ai_enabled": False}, "openai", "global", "AI_SECURITY_POLICY_DISABLED"),
        ({"external_ai_enabled": True, "allowed_provider_types": ("deepseek",)}, "openai", "global", "AI_SECURITY_PROVIDER_DENIED"),
        ({"external_ai_enabled": True, "provider_kill_switches": {"openai": True}}, "openai", "global", "AI_SECURITY_KILL_SWITCH"),
        ({"external_ai_enabled": True, "allowed_data_regions": ("cn",)}, "openai", "us", "AI_SECURITY_SCOPE_DENIED"),
    ],
)
def test_adr006_egress_checks_fail_closed_with_stable_codes(policy_kwargs, provider_type, region, code):
    from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy

    with pytest.raises(SecurityBlocked) as caught:
        AISecurityGateway().assert_egress_allowed(
            provider_type=provider_type, data_region=region, policy=SecurityPolicy(**policy_kwargs)
        )
    assert caught.value.reason_code == code


def test_adr006_external_embeddings_are_protected_before_the_transport_runs():
    from ai.providers.embedding import ExternalEmbeddingProvider
    from ai.security.gateway import SecurityBlocked

    sent = []

    class _BlockingGateway:
        def protect_embedding(self, texts, **_kwargs):
            raise SecurityBlocked("blocked", reason_code="AI_SECURITY_DLP_FAILED")

    provider = ExternalEmbeddingProvider(
        lambda texts, meta: sent.append(texts) or [[0.0, 1.0] for _ in texts],
        model_id="contract-embed", dimensions=2, security_gateway=_BlockingGateway(),
    )
    with pytest.raises(SecurityBlocked):
        provider.embed_documents(["password: hunter2"])
    assert sent == [], "the embedding transport must not receive anything the gateway refused"


@pytest.mark.parametrize("env_name", ["AI_EMBEDDING_ALLOWED_HOSTS", "AI_RERANKER_ALLOWED_HOSTS", "LANGFUSE_ALLOWED_HOSTS"])
def test_adr006_local_sidecars_refuse_public_hosts(monkeypatch, env_name):
    from ai.providers.embedding import EmbeddingProviderError, SidecarEmbeddingProvider
    from ai.services.langfuse_exporter import _validate_langfuse_endpoint
    from ai.services.retrieval_contract import RemoteSidecarReranker

    for name in ("AI_EMBEDDING_ALLOWED_HOSTS", "AI_RERANKER_ALLOWED_HOSTS", "LANGFUSE_ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    if env_name == "AI_EMBEDDING_ALLOWED_HOSTS":
        with pytest.raises(EmbeddingProviderError):
            SidecarEmbeddingProvider("https://embeddings.example.com")
    elif env_name == "AI_RERANKER_ALLOWED_HOSTS":
        with pytest.raises(ValueError):
            RemoteSidecarReranker("https://rerank.example.com/v1/rerank")
    else:
        with pytest.raises(ValueError):
            _validate_langfuse_endpoint("https://cloud.langfuse.com/api/public/ingestion")


# ── ADR-006 / ADR-011: fallback cannot widen the boundary ────────────────


def _model(provider_type: str, classification: str) -> dict:
    return {"provider_type": provider_type, "allowed_data_classification": classification, "model_type": "chat"}


def test_fallback_never_downgrades_the_data_classification():
    from ai.gateway.llm_gateway import LLMGateway

    gateway = LLMGateway()
    primary = _model("openai", "CONFIDENTIAL")
    assert not gateway._fallback_is_compatible(primary, _model("openai", "INTERNAL"))
    # CONFIDENTIAL data may only fall back to a local provider.
    assert not gateway._fallback_is_compatible(primary, _model("openai", "CONFIDENTIAL"), data_classification="CONFIDENTIAL")
    assert gateway._fallback_is_compatible(primary, _model("ollama", "CONFIDENTIAL"), data_classification="CONFIDENTIAL")
    # Embedding/rerank models are never chat fallbacks.
    assert not gateway._fallback_is_compatible(_model("openai", "PUBLIC"), {**_model("openai", "PUBLIC"), "model_type": "embedding"})


# ── ADR-011: multiple providers, keys never leave the server ─────────────


def test_adr011_schema_registry_and_default_policy_agree_on_provider_types():
    from ai.providers.registry import ADAPTER_REGISTRY
    from ai.schemas.provider import SUPPORTED_PROVIDER_TYPES
    from ai.security.gateway import SecurityPolicy

    # Not single-vendor: more than one remote vendor is a first-class type.
    assert {"deepseek", "openai", "openai_compatible", "azure_openai", "qwen"} <= SUPPORTED_PROVIDER_TYPES
    assert {"ollama", "local"} <= SUPPORTED_PROVIDER_TYPES
    # Every type an administrator can create has an adapter ...
    assert SUPPORTED_PROVIDER_TYPES <= set(ADAPTER_REGISTRY)
    # ... and is reachable under the default policy (narrowing is the
    # administrator's choice, not a hidden code limit).
    assert set(SecurityPolicy().allowed_provider_types) == SUPPORTED_PROVIDER_TYPES


def test_adr011_unknown_provider_types_are_rejected():
    from pydantic import ValidationError

    from ai.schemas.provider import AIProviderCreate

    with pytest.raises(ValidationError):
        AIProviderCreate(name="x", provider_type="made-up-vendor", base_url="https://api.example.com/v1")


def test_adr011_provider_api_returns_only_the_key_mask():
    from ai.schemas.provider import AIProviderResponse

    fields = set(AIProviderResponse.model_fields)
    assert "api_key_masked" in fields
    assert not {"api_key", "api_key_encrypted"} & fields


def test_adr011_mask_reveals_at_most_four_characters():
    from ai.security.crypto import mask_api_key

    masked = mask_api_key("sk-contract-0123456789wxyz")
    assert masked.endswith("wxyz") and "0123456789" not in masked
    assert sum(ch != "*" for ch in masked) <= 4
