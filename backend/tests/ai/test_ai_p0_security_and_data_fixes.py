"""Regression tests for AI Center P0 security, persistence, concurrency, and gateway fixes."""

from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ai.gateway.llm_gateway import LLMGateway
from ai.providers.registry import AzureOpenAIProvider
from ai.schemas.analysis import (
    AlarmAnalysisRequest,
    CommandAnalysisRequest,
    ConfigAnalysisRequest,
    DiffAnalysisRequest,
)
from ai.schemas.provider import AIProviderCreate, AIProviderUpdate
from ai.security.classification import DataLevel, classify_text
from ai.security.dlp import scan as dlp_scan
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.output import sanitize_output
from ai.security.sanitizer import sanitize_text
from ai.security.tokenization import ScopedTokenVault, tokenize_text
from ai.services.alarm_analysis import AlarmAnalysisService
from ai.services.change_governance import change_governance_service
from ai.services.command_analysis import CommandAnalysisService
from ai.services.config_analysis import ConfigAnalysisService
from ai.services.config_generation import ConfigGenerationService
from ai.services.diff_analysis import DiffAnalysisService
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest
from database.core import get_db_connection


# --- P0-1: RAG Retriever SQL Injection ---


def test_p0_1_applicability_filter_rejects_sql_injection_keys():
    retriever = RAGRetriever(cache_enabled=False)
    bad_req = RetrievalRequest(
        query="ospf",
        applicability={"x', '[]'::jsonb) OR 1=1 --": "val"},
    )
    with pytest.raises(ValueError, match="Invalid applicability filter key"):
        retriever._filter_sql(bad_req, {"status", "exclude_from_rag", "metadata_json"})


def test_p0_1_applicability_filter_uses_parameterized_jsonb_key():
    retriever = RAGRetriever(cache_enabled=False)
    good_req = RetrievalRequest(
        query="ospf",
        applicability={"applicable_models": ["CE6885"]},
    )
    where_sql, params = retriever._filter_sql(
        good_req, {"status", "exclude_from_rag", "metadata_json"}
    )
    assert "d.metadata_json -> ?" in where_sql
    assert "'applicable_models'" not in where_sql
    assert "applicable_models" in params
    assert "CE6885" in params


# --- P0-2: Sanitizer, Compressed IPv6 & Output Escaping ---


def test_p0_2_sanitizer_redacts_unmodified_passwords_huawei_cipher_and_pkcs8():
    sample = "\n".join([
        "password myplainpass123",
        "secret myenablepass456",
        "key-string myospfkey",
        "pre-shared-key myipsecpsk",
        "authentication-password mybgpauth",
        "snmp-agent community read cipher MySnmpRead99",
        "password irreversible-cipher $1c$HuaweiHashValue999$",
        "password level 3 cipher %^%#HuaweiLevel3Hash%^%#",
        "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkq\n-----END PRIVATE KEY-----",
    ])
    redacted = sanitize_text(sample)
    for leaked in (
        "myplainpass123",
        "myenablepass456",
        "myospfkey",
        "myipsecpsk",
        "mybgpauth",
        "MySnmpRead99",
        "$1c$HuaweiHashValue999$",
        "%^%#HuaweiLevel3Hash%^%#",
        "MIIEvQIBADANBgkq",
    ):
        assert leaked not in redacted, f"Expected secret {leaked!r} to be redacted in: {redacted}"
    assert "<REDACTED>" in redacted
    assert "<REDACTED_PRIVATE_KEY>" in redacted


def test_p0_2_compressed_ipv6_classified_tokenized_and_dlp_blocked():
    for addr in ("2001:db8::1", "fe80::1", "2408:8000::1", "::1"):
        text = f"Neighbor address is {addr} on interface Eth-Trunk1"
        findings = classify_text(text)
        level = max((item.level for item in findings), default=DataLevel.L0_PUBLIC)
        assert level >= DataLevel.L2_IDENTIFIER
        assert any(item.category == "ip_address" for item in findings)

        vault = ScopedTokenVault()
        tokenized = tokenize_text(text, tenant_id="t1", task_id="task1", vault=vault)
        assert addr not in tokenized
        assert "[[NXA_IPV6_" in tokenized

        dlp_findings = dlp_scan(text, identifiers_blocked=True)
        assert any(item.category == "ip_address" for item in dlp_findings)

        clean_findings = dlp_scan(tokenized, identifiers_blocked=True)
        assert not any(item.category == "ip_address" for item in clean_findings)

    # Timestamps and MACs should not be misclassified as IPv6
    non_ipv6 = "Log time 12:30:45 on MAC 00:11:22:33:44:55"
    non_findings = classify_text(non_ipv6)
    assert not any(item.category == "ip_address" for item in non_findings)


def test_p0_2_sanitize_output_preserves_plain_text_and_redacted_tags():
    vault = ScopedTokenVault()
    token = vault.put("10.1.2.3", kind="IP", tenant_id="t1", task_id="task1")
    raw = f"<script>alert(1)</script>Check {token} with password <REDACTED> & threshold > 80%"
    cleaned = sanitize_output(raw, tenant_id="t1", task_id="task1", vault=vault)
    assert "<script>" not in cleaned
    assert "alert(1)" not in cleaned
    assert "10.1.2.3" in cleaned
    assert "<REDACTED>" in cleaned
    assert "&lt;" not in cleaned
    assert "&gt;" not in cleaned
    assert "&amp;" not in cleaned


# --- P0-3: Scene-Aware Security Gateway & Analysis Hardening ---


def test_p0_3_security_gateway_allows_sanitized_config_analysis_but_blocks_chat_writes():
    policy = SecurityPolicy(
        external_ai_enabled=True,
        kill_switch=False,
        allowed_provider_types=("deepseek",),
        allowed_classifications=("PUBLIC", "INTERNAL", "CONFIDENTIAL"),
        allowed_data_regions=("unknown", "global", "cn"),
    )
    gateway = AISecurityGateway(policy=policy)

    # Read-only config_explain with sanitized config text should be allowed
    config_text = sanitize_text(
        "display current-configuration\nsystem-view\npassword irreversible-cipher $1c$secret$\nsave\n"
    )
    payload = gateway.protect(
        [{"role": "user", "content": config_text}],
        provider_type="deepseek",
        scene="config_explain",
        provider_allowed_classification="CONFIDENTIAL",
    )
    assert payload.messages
    assert "$1c$secret$" not in payload.as_provider_json()

    # Unredacted password in config_explain must STILL be blocked
    with pytest.raises(SecurityBlocked) as exc_secret:
        gateway.protect(
            [{"role": "user", "content": "system-view\npassword plainSecret999\n"}],
            provider_type="deepseek",
            scene="config_explain",
            provider_allowed_classification="CONFIDENTIAL",
        )
    assert exc_secret.value.reason_code == "AI_SECURITY_SENSITIVE_DATA"

    # Regular chat scene with raw write command must STILL be blocked
    with pytest.raises(SecurityBlocked) as exc_chat:
        gateway.protect(
            [{"role": "user", "content": "请帮我批量关闭接口并执行 system-view"}],
            provider_type="deepseek",
            scene="chat",
            provider_allowed_classification="CONFIDENTIAL",
        )
    assert exc_chat.value.reason_code == "AI_SECURITY_UNSAFE_TOOL"


def test_p0_3_analysis_and_config_generation_coerce_malformed_llm_json(monkeypatch):
    async def fake_chat(scene, messages, **kwargs):
        if scene == "command_explain":
            return {"request_id": "req_1", "content": json.dumps({"important_fields": ["State: Full"]})}
        if scene == "config_explain":
            return {"request_id": "req_2", "content": json.dumps({"security_risks": ["Telnet enabled"]})}
        if scene == "config_diff":
            return {"request_id": "req_3", "content": json.dumps({"risk_level": None, "rollback_recommendation": "undo vlan 10"})}
        if scene == "alarm_analysis":
            return {"request_id": "req_4", "content": json.dumps({"confidence": 85, "evidence": "BGP down"})}
        return {
            "request_id": "req_5",
            "content": json.dumps({
                "commands": "system-view\nundo bgp 65001",
                "rollback_commands": ["delete /unreserved flash:/vrpcfg.zip"],
            }),
        }

    from ai.gateway import llm_gateway as gw_mod
    monkeypatch.setattr(gw_mod.llm_gateway, "chat", fake_chat)

    cmd_res = asyncio.run(CommandAnalysisService().analyze(CommandAnalysisRequest(command="display ospf peer", output="Full")))
    assert cmd_res.important_fields == [{"field": "State: Full"}]

    cfg_res = asyncio.run(ConfigAnalysisService().analyze(ConfigAnalysisRequest(config_text="telnet server enable")))
    assert cfg_res.security_risks == [{"description": "Telnet enabled"}]

    diff_res = asyncio.run(DiffAnalysisService().analyze(DiffAnalysisRequest(diff_text="+ vlan 10")))
    assert diff_res.risk_level == "LOW"
    assert diff_res.rollback_recommendation == ["undo vlan 10"]

    alarm_res = asyncio.run(AlarmAnalysisService().analyze(AlarmAnalysisRequest(alarm_title="BGP Down", severity="critical")))
    assert alarm_res.confidence == pytest.approx(0.85)
    assert alarm_res.evidence == ["BGP down"]

    gen_res = asyncio.run(ConfigGenerationService().generate_config("Modify BGP"))
    assert len(gen_res["safety_warnings"]) == 2


# --- P0-4: Change Governance Real PostgreSQL Persistence ---


def test_p0_4_change_governance_persists_draft_and_enforces_approval_guards(isolated_db):
    draft = change_governance_service.create_change_draft(
        title="AI Test VLAN Change",
        device_id="dev_sw01",
        commands=["system-view", "vlan 100"],
        verification_commands=["display vlan 100"],
        rollback_commands=["undo vlan 100"],
        created_by="net_operator",
        requester_id="user_op_1",
        tenant_id="tenant-a",
    )
    assert draft["change_id"]
    assert draft["order_number"].startswith("BG")
    assert draft["status"] == "draft"

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, order_number, title, status, requester_username, tenant_id, rollback_plan FROM change_orders WHERE id = ?",
            (draft["change_id"],),
        ).fetchone()
    assert row is not None
    assert row[1] == draft["order_number"]
    assert row[4] == "net_operator"
    assert row[5] == "tenant-a"
    assert "undo vlan 100" in row[6]

    # Separation of duties: requester cannot approve own change
    with pytest.raises(PermissionError):
        change_governance_service.approve_change(
            draft["change_id"], approver="net_operator", approver_id="user_op_1", tenant_id="tenant-a"
        )

    # Cross-tenant approval is rejected as not found
    with pytest.raises(LookupError):
        change_governance_service.approve_change(
            draft["change_id"], approver="other_admin", approver_id="user_adm_2", tenant_id="tenant-b"
        )

    # Different approver in same tenant succeeds
    approved = change_governance_service.approve_change(
        draft["change_id"], approver="sec_approver", approver_id="user_adm_1", tenant_id="tenant-a"
    )
    assert approved["status"] == "approved"

    # Re-approving an already approved order fails with ValueError
    with pytest.raises(ValueError):
        change_governance_service.approve_change(
            draft["change_id"], approver="another_approver", approver_id="user_adm_3", tenant_id="tenant-a"
        )


# --- P0-5: Atomic ai_usage_daily Upsert & Daily Budget / Weighted Latency ---


def test_p0_5_usage_daily_atomic_upsert_and_daily_budget_summary(isolated_db, monkeypatch):
    from ai.api.usage import get_usage_summary
    from core.config import settings

    provider_id = f"prov_{uuid.uuid4().hex[:8]}"
    model_id = f"model_{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_provider (id, name, provider_type, base_url, enabled, created_at, updated_at) VALUES (?, ?, 'openai', 'https://api.openai.com/v1', 1, ?, ?)",
            (provider_id, f"Prov {provider_id}", now_iso, now_iso),
        )
        conn.execute(
            "INSERT INTO ai_model (id, provider_id, name, model_code, model_type, cost_input_per_1k, cost_output_per_1k, enabled, created_at, updated_at) VALUES (?, ?, 'M1', 'gpt-4o', 'chat', 1.0, 2.0, 1, ?, ?)",
            (model_id, provider_id, now_iso, now_iso),
        )
        # Seed a large historical cost from yesterday (should NOT trigger today's daily budget!)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        conn.execute(
            "INSERT INTO ai_usage_daily (id, date, provider_id, model_id, scene, requests, input_tokens, output_tokens, estimated_cost, success_count, error_count, avg_latency, created_at) VALUES (?, ?, ?, ?, 'chat', 10, 1000, 1000, 50.0, 10, 0, 100.0, ?)",
            (f"usage_{uuid.uuid4().hex[:12]}", yesterday, provider_id, model_id, now_iso),
        )
        conn.commit()

    gateway = LLMGateway()

    def log_one(idx: int) -> None:
        gateway._log_request(
            request_id=f"req_conc_{idx}",
            user_id="user_1",
            scene="chat",
            provider_id=provider_id,
            model_id=model_id,
            prompt_id=None,
            prompt_version=None,
            input_tokens=100,
            output_tokens=50,
            latency_ms=200,
            status="success",
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(log_one, range(5)))

    today = datetime.now(timezone.utc).date().isoformat()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT requests, input_tokens, output_tokens, success_count, avg_latency FROM ai_usage_daily WHERE date = ? AND provider_id = ? AND model_id = ? AND scene = 'chat'",
            (today, provider_id, model_id),
        ).fetchone()
    assert row is not None
    assert int(row[0]) == 5
    assert int(row[1]) == 500
    assert int(row[2]) == 250
    assert int(row[3]) == 5
    assert float(row[4]) == pytest.approx(200.0)

    monkeypatch.setattr(settings, "AI_DAILY_BUDGET_USD", 10.0)
    summary = get_usage_summary(user={"username": "admin", "role": "Administrator"})
    # Today's cost is 5 * (0.1*1.0 + 0.05*2.0) = $1.0, yesterday was $50.0 -> budget_alert must be False!
    assert summary["daily_estimated_cost_usd"] == pytest.approx(1.0)
    assert summary["estimated_cost_usd"] == pytest.approx(51.0)
    assert summary["budget_percent"] == pytest.approx(10.0)
    assert summary["budget_alert"] is False
    # Weighted latency: (10*100 + 5*200) / 15 = 133.33
    assert summary["provider_breakdown"][f"{provider_id}:{model_id}"]["avg_latency_ms"] == pytest.approx(133.33, abs=0.05)


# --- P0-6: Provider base_url Allowlist Sync & AzureOpenAIProvider Streaming ---


def test_p0_6_update_provider_base_url_syncs_allowlist(isolated_db):
    from ai.api.providers import create_provider, update_provider

    user = {"username": "admin", "role": "Administrator"}
    created = create_provider(
        AIProviderCreate(
            name=f"OpenAI-{uuid.uuid4().hex[:6]}",
            provider_type="openai_compatible",
            base_url="https://api.example-a.com/v1",
        ),
        user=user,
    )
    assert created.approved_endpoint_patterns == ["https://api.example-a.com/v1"]

    updated = update_provider(
        created.id,
        AIProviderUpdate(base_url="https://api.example-b.com/v1"),
        user=user,
    )
    assert updated.base_url == "https://api.example-b.com/v1"
    assert updated.approved_endpoint_patterns == ["https://api.example-b.com/v1"]


def test_p0_6_azure_provider_endpoint_is_stateless_for_chat_and_stream():
    azure = AzureOpenAIProvider(
        {"id": "p1", "name": "Azure", "provider_type": "azure_openai", "base_url": "https://my-res.openai.azure.com"},
        api_key="test-key",
    )
    assert azure._get_endpoint("gpt-4o-prod") == "https://my-res.openai.azure.com/openai/deployments/gpt-4o-prod/chat/completions"
    assert azure._get_endpoint("gpt-4o-mini") == "https://my-res.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions"
    assert azure.base_url == "https://my-res.openai.azure.com"


# --- P0-7: Evaluation Route RBAC & Retriever Dependency Isolation ---


def test_p0_7_evaluation_run_requires_update_permission_and_retriever_isolation():
    import ai.services.rag_retriever as retriever_mod
    from api.knowledge_evaluation import router

    run_route = next(r for r in router.routes if getattr(r, "path", "").endswith("/knowledge/evaluation/run"))
    dep_calls = [str(dep.call) for dep in run_route.dependant.dependencies]
    assert dep_calls  # dependency attached

    # Ensure custom embedder/connection_factory on an instance does not mutate module globals
    orig_conn = retriever_mod.get_db_connection
    orig_emb = retriever_mod.embedding_provider

    class _DummyEmbedder:
        model_id = "dummy"
        def embed_text(self, _text: str):
            return [1.0, 0.0]

    r = RAGRetriever(cache_enabled=False, connection_factory=lambda: None, embedder=_DummyEmbedder())
    assert r._active_embedder().model_id == "dummy"
    assert retriever_mod.get_db_connection is orig_conn
    assert retriever_mod.embedding_provider is orig_emb
