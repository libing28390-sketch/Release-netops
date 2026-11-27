"""End-to-end regression tests for the 12-Module Cross-Linked Zero-Token Entity Bus."""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from ai.services import entity_context, module_bus
from ai.services.assistant import AIAssistantService
from ai.services.local_router import resolve_local_intent
from core.config import settings


@pytest.fixture(autouse=True)
def _use_legacy_deterministic_bus_mode(monkeypatch):
    """Exercise the deterministic 0-token local router fallback mode."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)


class _FakeCursor:
    def __init__(self, rows: List[tuple]):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    """Minimal read-only DB double returning deterministic fixtures per SQL table."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self.saved_entity_json: str | None = None

    def execute(self, sql: str, params: tuple = ()):
        s = " ".join(sql.lower().split())
        if "alter table ai_conversations" in s:
            return _FakeCursor([])
        if "select entity_context_json from ai_conversations" in s:
            return _FakeCursor([(self.saved_entity_json,)] if self.saved_entity_json else [])
        if "update ai_conversations set entity_context_json" in s:
            self.saved_entity_json = str(params[0])
            return _FakeCursor([])
        if "from devices" in s and "select id, hostname, ip_address" in s:
            devs = self._data.get("devices", [])
            key = str(params[0]).lower() if params else ""
            for d in devs:
                if key in {str(d["ip_address"]).lower(), str(d["hostname"]).lower()}:
                    return _FakeCursor([(
                        d["id"], d["hostname"], d["ip_address"], d["vendor"], d["platform"],
                        d["model"], d["version"], d["role"], d["status"], d["site"],
                    )])
            return _FakeCursor([])
        if "from pam_sessions" in s:
            rows = self._data.get("pam_sessions", [])
            if "select count(*)" in s:
                return _FakeCursor([(len(rows), 0)])
            return _FakeCursor(rows)
        if "from physical_assets" in s:
            return _FakeCursor(self._data.get("physical_assets", []))
        if "from racks" in s:
            return _FakeCursor(self._data.get("racks", []))
        if "from change_orders" in s:
            return _FakeCursor(self._data.get("change_orders", []))
        if "from users" in s:
            return _FakeCursor([(self._data.get("user_count", 5),)])
        return _FakeCursor([])

    def commit(self):
        pass

    def rollback(self):
        pass


def _sample_device() -> Dict[str, Any]:
    return {
        "id": "dev-101",
        "hostname": "Core-SW-01",
        "ip_address": "1.1.1.1",
        "vendor": "H3C",
        "platform": "hp_comware",
        "model": "S6850",
        "version": "7.1.070",
        "role": "core",
        "status": "online",
        "site": "WH-DC-01",
    }


def test_cross_module_zero_token_chain_and_scope_isolation():
    """Turn 1..6 chain across CMDB -> PAM -> Alarms -> Config -> Racks -> Tickets -> Global."""
    dev = _sample_device()
    with patch.object(entity_context, "lookup_device_in_db", return_value=dev):
        # Turn 1: explicit IP -> device_profile
        r1 = resolve_local_intent("1.1.1.1 这台设备的信息", history=[], entity_context={})
        assert r1 is not None
        assert r1["intent"] == "module_bus"
        assert r1["filters"]["module"] == "device_profile"
        assert r1["filters"]["entities"]["device"]["hostname"] == "Core-SW-01"
        assert r1["filters"]["entities"]["scope_mode"] == "explicit"

        saved_ctx = {"active_device": dev, "last_module": "device_profile"}

        # Turn 2: follow-up PAM login count inherits 1.1.1.1
        r2 = resolve_local_intent("这台设备最近登录了几次", history=[], entity_context=saved_ctx)
        assert r2 is not None
        assert r2["intent"] == "module_bus"
        assert r2["filters"]["module"] == "pam_sessions"
        assert r2["filters"]["entities"]["device"]["ip_address"] == "1.1.1.1"
        assert r2["filters"]["entities"]["scope_mode"] == "inherited"

        # Turn 3: follow-up alarm check inherits 1.1.1.1 into alarm_search device_id
        r3 = resolve_local_intent("它现在有告警吗", history=[], entity_context=saved_ctx)
        assert r3 is not None
        assert r3["intent"] == "alarm_search"
        assert r3["filters"].get("device_id") == "dev-101"
        assert "vendor" not in r3["filters"]

        # Turn 4: follow-up config changes, racks, change orders inherit 1.1.1.1
        for q, expected_mod in (
            ("最近配置改过吗", "config_changes"),
            ("在哪个机柜", "racks"),
            ("有关联变更工单吗", "change_orders"),
        ):
            res = resolve_local_intent(q, history=[], entity_context=saved_ctx)
            assert res is not None, f"Expected module_bus match for: {q}"
            assert res["intent"] == "module_bus"
            assert res["filters"]["module"] == expected_mod
            assert res["filters"]["entities"]["device"]["id"] == "dev-101"

        # Guardrail 1 (Anti-Cross-Talk): Global query MUST NOT inherit active_device!
        r_global = resolve_local_intent("全网今天有多少严重告警", history=[], entity_context=saved_ctx)
        assert r_global is not None
        assert r_global["intent"] == "alarm_search"
        assert "device_id" not in r_global["filters"]
        assert "device_name" not in r_global["filters"]
        assert r_global["entities"]["scope_mode"] == "global"

        # Vendor-scoped alarm query still routes cleanly to alarm_search with vendor=h3c
        r_h3c = resolve_local_intent("华三的设备有告警没有", history=[], entity_context=saved_ctx)
        assert r_h3c is not None
        assert r_h3c["intent"] == "alarm_search"
        assert str(r_h3c["filters"].get("vendor") or "").lower() == "h3c"


def test_guardrail_2_multi_target_ambiguity_clarifies_at_zero_tokens():
    """Pronoun referring to >1 candidate devices returns 0-token local disambiguation."""
    saved_ctx = {
        "active_device": _sample_device(),
        "candidate_devices": [
            {"id": "dev-201", "hostname": "Leaf-SW-01", "ip_address": "10.0.1.1"},
            {"id": "dev-202", "hostname": "Leaf-SW-02", "ip_address": "10.0.1.2"},
        ],
    }
    res = resolve_local_intent("对端那台设备有告警吗", history=[], entity_context=saved_ctx)
    assert res is not None
    assert res["intent"] == "module_bus"
    assert res["filters"]["module"] == "disambiguate"
    entities = res["filters"]["entities"]
    assert entities["scope_mode"] == "ambiguous"

    out = module_bus.execute_module_bus_query("disambiguate", "对端那台设备有告警吗", entities, roles=["operator"])
    assert "请确认目标设备" in out["summary"]
    assert "Leaf-SW-01" in out["summary"]
    assert "Leaf-SW-02" in out["summary"]
    assert "0 Token" in out["summary"]


def test_guardrail_3_rbac_enforcement_and_zero_secret_columns():
    """Viewer is denied PAM/Platform/Credentials; secret columns never appear in module_bus SQL."""
    # Viewer denied PAM & platform_audit & credentials_meta
    pam_denied = module_bus.execute_module_bus_query(
        "pam_sessions", "这台设备最近登录了几次", {"device": _sample_device(), "scope_label": "Core-SW-01"}, roles=["viewer"]
    )
    assert pam_denied["denied"] is True
    assert "权限提示" in pam_denied["summary"]

    plat_denied = module_bus.execute_module_bus_query(
        "platform_audit", "平台有多少个用户", {"scope_label": "全网"}, roles=["operator"]
    )
    assert plat_denied["denied"] is True

    cred_denied = module_bus.execute_module_bus_query(
        "cmdb_base", "有哪些凭据", {"scope_label": "全网"}, roles=["viewer"]
    )
    assert cred_denied["denied"] is True

    # Verify zero secret column names in executable non-comment lines of module_bus
    non_comment_src = "\n".join(
        line for line in inspect.getsource(module_bus).lower().splitlines()
        if not line.lstrip().startswith("#")
    )
    for forbidden in ("encrypted_password", "enable_password", "private_key", "snmp_community", "password_hash"):
        assert forbidden not in non_comment_src, f"Forbidden secret column referenced in module_bus: {forbidden}"


def test_guardrail_4_and_6_reasoning_and_howto_escalate_to_llm():
    """Reasoning / causal / comparative questions escalate deterministically; How-To goes to KB."""
    saved_ctx = {"active_device": _sample_device()}
    for q in (
        "结合上面的登录和告警分析下为什么闪断",
        "刚才的操作和告警有关联吗",
        "结合上面的信息分析下这台设备目前有没有潜在风险",
        "结合上面情况，这台设备和上一台比哪台更需要关注",
    ):
        r = resolve_local_intent(q, history=[], entity_context=saved_ctx)
        assert r is not None
        assert r["intent"] == "troubleshooting"
        assert r.get("reasoning_escalation") is True
        assert r["parse_status"] == "deterministic"
    # How-To still returns None so Knowledge/RAG pipeline handles it
    assert resolve_local_intent("华为交换机怎么配置 OSPF", history=[], entity_context=saved_ctx) is None


def test_live_42_turn_regressions_ipam_global_reset_and_execution_guard():
    """Regression tests for the 4 defects discovered in the 42-turn live test."""
    saved_ctx = {"active_device": _sample_device()}

    # Defect 1: IPAM must NEVER be hijacked by PAM substring match
    r_ipam = resolve_local_intent("IPAM 网段利用率怎么样", history=[], entity_context=saved_ctx)
    assert r_ipam is not None
    assert r_ipam["intent"] == "module_bus"
    assert r_ipam["filters"]["module"] == "ipam_prefix"

    # Defect 3: Plural list query "最近有哪些待审批变更工单" must be global, NOT sticky to active_device
    r_tickets = resolve_local_intent("最近有哪些待审批变更工单", history=[], entity_context=saved_ctx)
    assert r_tickets is not None
    assert r_tickets["intent"] == "module_bus"
    assert r_tickets["filters"]["module"] == "change_orders"
    assert r_tickets["filters"]["entities"]["device"] is None
    assert r_tickets["filters"]["entities"]["scope_mode"] == "global"

    # Defect 3b: _persist_entity_memory clears active_device when updates has active_device=None
    cleared = AIAssistantService._persist_entity_memory(
        None, {"active_device": _sample_device(), "last_module": "device_profile"}, {"active_device": None, "last_module": "alarm_search"}
    )
    assert "active_device" not in cleared
    assert cleared["last_module"] == "alarm_search"


@pytest.mark.asyncio
async def test_defect_4_execution_refusal_not_bypassed_by_pending_clarification():
    """Turn 40 regression: destructive CLI request must be refused even when pending_clarification is open."""
    svc = AIAssistantService()
    pending = {
        "required": True,
        "request_kind": "configuration_reference",
        "recognized_fields": {"vendor": "huawei", "feature": "ospf"},
    }
    events = []
    async for evt in svc.chat_stream(
        "帮我在这台设备上执行 undo ospf 1 并保存",
        roles=["operator"],
        pending_clarification=pending,
    ):
        events.append(evt)
    joined = "".join(events)
    assert "Copilot 不会在设备上执行命令" in joined
    assert "undo ospf 1" in joined
    assert "local_security_block" in joined


@pytest.mark.asyncio
async def test_assistant_chat_e2e_persists_memory_and_feeds_llm_escalation():
    """End-to-end AIAssistantService.chat(): Turn 1 (0 tok) -> Turn 2 (0 tok) -> Turn 3 (LLM with facts)."""
    dev = _sample_device()
    now_iso = datetime.now(timezone.utc).isoformat()
    fake_conn = _FakeConn({
        "devices": [dev],
        "pam_sessions": [
            (now_iso, "alice", "admin", "ssh", "Core-SW-01", "1.1.1.1", "closed", 12, "low"),
            (now_iso, "bob", "admin", "ssh", "Core-SW-01", "1.1.1.1", "closed", 5, "low"),
        ],
    })

    @contextmanager
    def _fake_db():
        yield fake_conn

    svc = AIAssistantService()
    captured_messages: List[Dict[str, str]] = []

    async def _fake_llm_chat(*args, **kwargs):
        captured_messages.extend(kwargs.get("messages") or [])
        return {
            "content": "结合登录和告警记录，疑似人为变更触发。",
            "provider_id": "prov-test",
            "model_id": "model-test",
            "input_tokens": 120,
            "output_tokens": 30,
        }

    with (
        patch.object(entity_context, "get_db_connection", _fake_db),
        patch.object(module_bus, "get_db_connection", _fake_db),
        patch("ai.services.assistant.llm_gateway.chat", new=AsyncMock(side_effect=_fake_llm_chat)),
        patch("ai.services.assistant.intent_parser.parse_intent", new=AsyncMock(return_value={
            "intent": "troubleshooting", "filters": {}, "confidence": 0.9, "parse_status": "deterministic",
        })),
        patch("ai.services.assistant.rag_retriever.retrieve", return_value=[]),
    ):
        # Turn 1: Device profile (0 Token, persists active_device)
        res1 = await svc.chat(
            "1.1.1.1 这台设备的信息",
            roles=["operator"],
            context={"conversation_id": "conv-e2e-1"},
        )
        assert res1["intent"] == "module_bus"
        assert res1["input_tokens"] == 0
        assert res1["output_tokens"] == 0
        assert res1["token_source"] == "local_zero"
        assert "Core-SW-01" in res1["answer"]
        assert fake_conn.saved_entity_json is not None

        # Turn 2: PAM sessions (0 Token, inherits 1.1.1.1 from persisted entity_context_json!)
        res2 = await svc.chat(
            "这台设备最近登录了几次",
            roles=["operator"],
            context={"conversation_id": "conv-e2e-1"},
        )
        assert res2["intent"] == "module_bus"
        assert res2["input_tokens"] == 0
        assert res2["output_tokens"] == 0
        assert "2" in res2["answer"]
        assert "alice" in res2["answer"]

        # Turn 3: Causal reasoning escalates to LLM with compact recent_local_facts
        res3 = await svc.chat(
            "结合上面的登录和告警分析下为什么闪断",
            roles=["operator"],
            context={"conversation_id": "conv-e2e-1"},
        )
        assert res3["execution_mode"] == "provider_generated"
        assert captured_messages, "Expected LLM call for causal reasoning turn"
        final_user_msg = captured_messages[-1]["content"]
        assert "recent_local_facts" in final_user_msg
        assert "Core-SW-01" in final_user_msg
