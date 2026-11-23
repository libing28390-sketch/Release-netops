from __future__ import annotations

import datetime
import json
import time
import uuid

from ai.agents.runner import _resolve_agent_config
from ai.gateway.router import ModelRouter
from ai.prompts.manager import PromptManager
from ai.prompts.renderer import PromptRenderer
from ai.security.rate_limit import AIRateLimiter
from ai.security.tokenization import ScopedTokenVault
from ai.services.conversation_service import (
    append_message,
    archive_conversation,
    clear_messages,
    create_conversation,
    get_context,
    rename_conversation,
)
from ai.tools.read_only_tools import tool_get_device_neighbors
from ai.tools.registry import StrictToolArgs, ToolRegistry, ToolSpec
from database import get_db_connection
from services import official_product_catalog_service


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def test_conversation_service_preserves_state_and_allows_local_modes():
    owner = f"u_p1_{uuid.uuid4().hex[:8]}"
    tenant = "tenant-default"
    created = create_conversation(
        tenant_id=tenant,
        user_id=owner,
        title="Initial",
        selected_model_id="mdl-keep-1",
    )
    conv_id = created["id"]
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ai_conversations SET clarification_state_json = ? WHERE id = ?",
            (json.dumps({"state_id": "st-1", "required": True}), conv_id),
        )
        conn.commit()

    renamed = rename_conversation(conversation_id=conv_id, tenant_id=tenant, user_id=owner, title="Renamed")
    assert renamed["selected_model_id"] == "mdl-keep-1"

    msg = append_message(
        conversation_id=conv_id,
        tenant_id=tenant,
        user_id=owner,
        role="assistant",
        content="local identifier check",
        execution_mode="local_sensitive_identifier",
    )
    assert msg["execution_mode"] == "local_sensitive_identifier"

    msg2 = append_message(
        conversation_id=conv_id,
        tenant_id=tenant,
        user_id=owner,
        role="assistant",
        content="blocked locally",
        execution_mode="local_security_block",
    )
    assert msg2["execution_mode"] == "local_security_block"

    cleared = clear_messages(conversation_id=conv_id, tenant_id=tenant, user_id=owner)
    assert cleared["selected_model_id"] == "mdl-keep-1"

    archived = archive_conversation(conversation_id=conv_id, tenant_id=tenant, user_id=owner, archived=True)
    assert archived["selected_model_id"] == "mdl-keep-1"

    ctx = get_context(conversation_id=conv_id, tenant_id=tenant, user_id=owner)
    assert ctx["conversation"]["selected_model_id"] == "mdl-keep-1"


def test_tool_registry_timeout_does_not_block_and_releases_semaphore():
    registry = ToolRegistry()

    def slow_tool(**_kwargs):
        time.sleep(1.5)
        return {"ok": True}

    registry._tools["test_slow_tool"] = ToolSpec(
        name="test_slow_tool",
        display_name="Test Slow Tool",
        description="Sleeps longer than timeout",
        category="diagnostics",
        risk_level="R0",
        handler=slow_tool,
        input_model=StrictToolArgs,
        timeout_seconds=0.1,
    )

    started = time.perf_counter()
    res = registry.execute_tool("test_slow_tool", {}, permissions={"ai.assistant"})
    elapsed = time.perf_counter() - started
    assert res["success"] is False
    assert res["error_code"] == "TOOL_TIMEOUT"
    assert elapsed < 0.8


def test_tool_get_device_neighbors_swaps_ports_when_device_is_target():
    src_id = f"dev-src-{uuid.uuid4().hex[:6]}"
    tgt_id = f"dev-tgt-{uuid.uuid4().hex[:6]}"
    link_id = f"lnk-{uuid.uuid4().hex[:8]}"
    now = _now_iso()
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, vendor, status) VALUES (?, ?, ?, ?, ?, ?)",
                (src_id, "CORE-SW1", "10.99.0.1", "huawei_vrp", "Huawei", "online"),
            )
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, vendor, status) VALUES (?, ?, ?, ?, ?, ?)",
                (tgt_id, "ACC-SW2", "10.99.0.2", "huawei_vrp", "Huawei", "online"),
            )
            conn.execute(
                "INSERT INTO topology_links (id, source_device_id, source_port, target_device_id, target_port, status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (link_id, src_id, "XGigabitEthernet0/0/1", tgt_id, "GigabitEthernet0/0/24", "up", now),
            )
            conn.commit()

        res = tool_get_device_neighbors(device_id=tgt_id)
        neighbors = res["neighbors"]
        assert len(neighbors) == 1
        assert neighbors[0]["remote_device"] == src_id
        assert neighbors[0]["local_port"] == "GigabitEthernet0/0/24"
        assert neighbors[0]["remote_port"] == "XGigabitEthernet0/0/1"
    finally:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM topology_links WHERE id = ?", (link_id,))
            conn.execute("DELETE FROM devices WHERE id IN (?, ?)", (src_id, tgt_id))
            conn.commit()


def test_prompt_renderer_single_pass_fallback_prevents_second_order_injection():
    rendered = PromptRenderer.render(
        "Hello {{a}} and {{b}}",
        {"a": "{{b}}", "b": "SECRET_VALUE"},
    )
    assert rendered == "Hello {{b}} and SECRET_VALUE"


def test_prompt_manager_scene_specificity_matching():
    unique_scene = f"p1_scene_{uuid.uuid4().hex[:6]}"
    now = _now_iso()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_prompt (id, code, name, scene, vendor, platform, system_prompt, user_prompt_template, enabled, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (str(uuid.uuid4()), f"{unique_scene}_generic", "Generic", unique_scene, "all", "all", "generic", "{{q}}", now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_prompt (id, code, name, scene, vendor, platform, system_prompt, user_prompt_template, enabled, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            """,
            (str(uuid.uuid4()), f"{unique_scene}_huawei", "Huawei VRP", unique_scene, "Huawei", "huawei_vrp", "huawei-vrp", "{{q}}", now, now),
        )
        conn.commit()

    mgr = PromptManager()
    matched_specific = mgr.get_prompt_for_scene(unique_scene, vendor="Huawei", platform="huawei_vrp")
    assert matched_specific is not None
    assert matched_specific["code"] == f"{unique_scene}_huawei"

    matched_generic = mgr.get_prompt_for_scene(unique_scene, vendor="Cisco", platform="cisco_ios")
    assert matched_generic is not None
    assert matched_generic["code"] == f"{unique_scene}_generic"


def test_token_vault_cleans_reverse_map_on_expiry_and_eviction():
    vault = ScopedTokenVault(ttl_seconds=1, max_entries=2)
    t1 = vault.put("10.0.0.1", kind="IP", tenant_id="t1", task_id="k1")
    t2 = vault.put("10.0.0.2", kind="IP", tenant_id="t1", task_id="k1")
    t3 = vault.put("10.0.0.3", kind="IP", tenant_id="t1", task_id="k1")
    assert len(vault._entries) <= 2
    assert len(vault._reverse) == len(vault._entries)
    assert ("t1", "k1", t1) not in vault._entries
    assert ("t1", "k1", t2) in vault._entries and ("t1", "k1", t3) in vault._entries


def test_rate_limiter_in_memory_thread_safe_and_enforces_limit(monkeypatch):
    import ai.security.rate_limit as rl_mod
    monkeypatch.setattr(rl_mod, "_redis_client", None)
    limiter = AIRateLimiter()
    uid = f"rl_{uuid.uuid4().hex[:6]}"
    allowed1, rem1 = limiter.is_allowed(uid, "chat", max_per_day=2)
    allowed2, rem2 = limiter.is_allowed(uid, "chat", max_per_day=2)
    allowed3, rem3 = limiter.is_allowed(uid, "chat", max_per_day=2)
    assert allowed1 is True and rem1 == 1
    assert allowed2 is True and rem2 == 0
    assert allowed3 is False and rem3 == 0


def test_agent_runner_resolves_registered_agent_config():
    agent_code = f"p1_agent_{uuid.uuid4().hex[:6]}"
    now = _now_iso()
    agent_id = str(uuid.uuid4())
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_agent (id, code, name, description, system_prompt, allowed_tools, max_steps, timeout, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                agent_id,
                agent_code,
                "P1 Test Agent",
                "desc",
                "Custom system prompt",
                json.dumps(["get_device_info", "get_device_neighbors"]),
                4,
                25,
                now,
                now,
            ),
        )
        conn.commit()

    try:
        cfg = _resolve_agent_config(agent_code)
        assert cfg["system_prompt"] == "Custom system prompt"
        assert cfg["allowed_tools"] == ["get_device_info", "get_device_neighbors"]
        assert cfg["max_steps"] == 4
        assert cfg["timeout"] == 25
    finally:
        # This test writes to the shared development database; leaving the
        # row behind adds a "P1 Test Agent" to the Agent registry every run.
        with get_db_connection() as conn:
            conn.execute("DELETE FROM ai_agent WHERE id = ?", (agent_id,))
            conn.commit()


def test_model_router_resolve_route_policy_returns_classification():
    scene = f"p1_route_{uuid.uuid4().hex[:6]}"
    provider_id = str(uuid.uuid4())
    model_id = str(uuid.uuid4())
    route_id = str(uuid.uuid4())
    now = _now_iso()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_provider (id, name, provider_type, base_url, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (provider_id, f"P1Prov-{scene}", "openai_compatible", "https://example.invalid/v1", now, now),
        )
        conn.execute(
            "INSERT INTO ai_model (id, provider_id, name, model_code, model_type, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 'chat', 1, ?, ?)",
            (model_id, provider_id, "P1Model", "p1-model", now, now),
        )
        conn.execute(
            """
            INSERT INTO ai_model_route (id, scene, model_id, fallback_model_id, priority, data_classification, enabled, created_at, updated_at)
            VALUES (?, ?, ?, NULL, 10, 'INTERNAL', 1, ?, ?)
            """,
            (route_id, scene, model_id, now, now),
        )
        conn.commit()

    try:
        resolved_id, fallback_id, reason, classification = ModelRouter().resolve_route_policy(scene)
        assert resolved_id == model_id
        assert fallback_id is None
        assert reason == "scene_route"
        assert classification == "INTERNAL"
    finally:
        # Without this every run leaves a "P1Prov-p1_route_*" provider and an
        # unhealthy "P1Model" in the development database, and they show up
        # in the Copilot model picker.
        with get_db_connection() as conn:
            conn.execute("DELETE FROM ai_model_route WHERE id = ?", (route_id,))
            conn.execute("DELETE FROM ai_model WHERE id = ?", (model_id,))
            conn.execute("DELETE FROM ai_provider WHERE id = ?", (provider_id,))
            conn.commit()


def test_official_product_catalog_enrichment_covers_expanded_vendors_and_models():
    catalog = official_product_catalog_service.MODEL_CATALOG
    all_models: set[str] = set()
    for vendor in ("Huawei", "H3C", "Cisco", "Ruijie", "Juniper", "Fortinet", "Aruba"):
        assert vendor in catalog
        assert len(catalog[vendor]) >= 3
        for item in catalog[vendor]:
            model_name = item[0] if isinstance(item, (list, tuple)) else str(item.get("model") or item)
            all_models.add(model_name)

    refs = official_product_catalog_service.OFFICIAL_MODEL_REFERENCE
    for vendor in ("Huawei", "H3C", "Cisco", "Ruijie", "Juniper", "Fortinet", "Aruba"):
        assert vendor in refs
        assert str(refs[vendor]).startswith("https://")

    for model_code in ("NetEngine AR6280", "HiSecEngine USG6565E", "Aruba 6300M 48G", "Aruba 8325-48Y8C"):
        assert model_code in all_models
    assert len(all_models) >= 60
