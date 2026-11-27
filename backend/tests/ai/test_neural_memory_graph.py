"""Tests for the Three-Tier Ops Neural Memory System (Rolling Summary + Spreading Activation)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from ai.services import memory_graph
from ai.services.assistant import AIAssistantService


@pytest.fixture
def isolated_memory_db(tmp_path):
    """Provide an isolated SQLite DB implementing the same SQL interface for fast unit testing."""
    db_file = tmp_path / "memory_test.db"
    conn = sqlite3.connect(str(db_file))
    memory_graph._MEMORY_TABLES_READY = False

    @contextmanager
    def _fake_conn():
        yield conn

    with patch.object(memory_graph, "get_db_connection", _fake_conn):
        yield conn
    conn.close()
    memory_graph._MEMORY_TABLES_READY = False


def test_short_term_rolling_summary_preserves_evicted_entities_in_long_sessions():
    """Evicted turns beyond the 12-turn sliding window are distilled into a compact rolling summary."""
    long_history = [
        {"role": "user", "content": "查一下 10.254.0.1 这台 S6850_1 在哪个机柜"},
        {"role": "assistant", "content": "S6850_1 (10.254.0.1) 位于机柜 JG-01 U30。"},
    ]
    for i in range(25):
        long_history.append({"role": "user", "content": f"常规追问 {i}"})
        long_history.append({"role": "assistant", "content": f"常规回复 {i}"})

    selected = AIAssistantService._select_agentic_history(long_history)
    assert selected[0]["content"].startswith("[短期工作记忆·早期对话摘要]")
    assert "S6850_1" in selected[0]["content"]
    assert "10.254.0.1" in selected[0]["content"]
    assert "JG-01" in selected[0]["content"]


def test_two_hop_synapse_spreading_activation_and_hebbian_reinforcement(isolated_memory_db):
    """Mentioning S6850_1 activates both its own episodic incident AND its HA peer S6850-2 via synapse edge."""
    m1 = memory_graph.save_memory_node(
        title="S6850_1 光模块衰耗根因案例",
        content="GE1/0/24 反复闪断最终确认为 10G SFP+ 光模块发送光功率过低，更换后恢复。",
        memory_type="episodic",
        entity_key="device:s6850_1",
        tags=["光模块", "闪断"],
        related_entities=[("ha_peer_of", "device:s6850-2")],
    )
    m2 = memory_graph.save_memory_node(
        title="双核心互备变更规范",
        content="S6850-2 与 S6850_1 为双核心互备，变更前须确认 IRF/VRRP 主备状态并在周六 02:00 窗口执行。",
        memory_type="semantic",
        entity_key="device:s6850-2",
        tags=["双核心", "变更窗口"],
    )

    # Query mentions ONLY S6850_1 -> 1-hop activates m1, 2-hop synapse edge activates m2!
    recalled = memory_graph.activate_memories("S6850_1 最近又报端口闪断了，怎么处理？")
    recalled_ids = {n["id"] for n in recalled["nodes"]}
    assert m1["id"] in recalled_ids
    assert m2["id"] in recalled_ids
    assert any(e["relation"] == "ha_peer_of" for e in recalled["edges"])
    assert "历史案例" in recalled["prompt_block"]
    assert "企业常识" in recalled["prompt_block"]

    # Hebbian reinforcement boosts weight and hit_count
    assert memory_graph.reinforce_memory_node(m1["id"], delta=0.5) is True
    nodes = memory_graph.list_memory_nodes()
    m1_row = next(n for n in nodes if n["id"] == m1["id"])
    assert m1_row["weight"] >= 1.5
    assert m1_row["hit_count"] >= 2

    # Clean deletion works
    assert memory_graph.delete_memory_node(m2["id"]) is True


def test_long_term_memory_rejects_secrets_and_credentials(isolated_memory_db):
    """Long-term memory strictly refuses passwords, SNMP communities, and private keys."""
    with pytest.raises(ValueError, match="secret|credential"):
        memory_graph.save_memory_node(
            title="核心密码备忘",
            content="snmp-agent community read SuperSecret123!",
            memory_type="semantic",
        )
    with pytest.raises(ValueError, match="secret|credential"):
        memory_graph.save_memory_node(
            title="SSH 私钥",
            content="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END RSA PRIVATE KEY-----",
            memory_type="semantic",
        )
