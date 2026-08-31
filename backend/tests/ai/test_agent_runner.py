from __future__ import annotations

import asyncio
import json

import pytest


def test_agent_runner_resolves_code_to_registered_agent_id(isolated_db, monkeypatch) -> None:
    from ai.agents.runner import agent_runner
    from ai.gateway.llm_gateway import llm_gateway

    async def fake_chat(**kwargs):
        return {"content": json.dumps({"action": "final_answer", "result": "排障证据已汇总"})}

    monkeypatch.setattr(llm_gateway, "chat", fake_chat)

    result = asyncio.run(
        agent_runner.run(
            agent_code="troubleshooting_agent",
            question="为什么设备访问掉包？",
            max_steps=1,
            user_id="alice",
            tenant_id="tenant-default",
        )
    )

    assert result["status"] == "finished"
    assert result["final_result"] == "排障证据已汇总"

    with isolated_db["module"].get_db_connection() as conn:
        row = conn.execute(
            "SELECT agent_id FROM ai_agent_run WHERE id = ?",
            (result["run_id"],),
        ).fetchone()
    assert row[0] == "agent_troubleshooting"


def test_agent_runner_rejects_unregistered_agent_before_persisting_run(isolated_db) -> None:
    from ai.agents.runner import AgentNotFoundError, agent_runner

    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM ai_agent WHERE code = ?", ("troubleshooting_agent",))
        conn.commit()

    with pytest.raises(AgentNotFoundError, match="not registered"):
        asyncio.run(
            agent_runner.run(
                agent_code="troubleshooting_agent",
                question="为什么设备访问掉包？",
                user_id="alice",
                tenant_id="tenant-default",
            )
        )

    with database.get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_agent_run").fetchone()[0] == 0
