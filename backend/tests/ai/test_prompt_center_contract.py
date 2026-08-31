from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from backend.tests.pg_test_utils import postgresql_test_driver
from ai.api import prompts as prompts_api
from ai.prompts.manager import SEED_PROMPTS
from ai.schemas.prompt import (
    AIPromptCopyRequest,
    AIPromptCreate,
    AIPromptRestoreRequest,
    AIPromptUpdate,
)


ADMIN = {"username": "prompt-admin", "role": "Administrator"}


def _database(tmp_path, monkeypatch):
    db_path = tmp_path / "prompt-center.db"
    connection = postgresql_test_driver.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE ai_prompt (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            scene TEXT NOT NULL,
            vendor TEXT DEFAULT 'all',
            platform TEXT DEFAULT 'all',
            system_prompt TEXT NOT NULL,
            user_prompt_template TEXT NOT NULL,
            output_schema TEXT DEFAULT '{}',
            temperature REAL DEFAULT 0.2,
            max_tokens INTEGER DEFAULT 2048,
            version INTEGER DEFAULT 1,
            enabled INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ai_prompt_version (
            id TEXT PRIMARY KEY,
            prompt_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            system_prompt TEXT NOT NULL,
            user_prompt_template TEXT NOT NULL,
            output_schema TEXT DEFAULT '{}',
            temperature REAL DEFAULT 0.2,
            max_tokens INTEGER DEFAULT 2048,
            created_by TEXT,
            created_at TEXT NOT NULL,
            change_reason TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL DEFAULT 'update',
            restored_from_version INTEGER
        );
        CREATE TABLE audit_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            actor_id TEXT,
            actor_username TEXT,
            actor_role TEXT,
            source_ip TEXT,
            target_type TEXT,
            target_id TEXT,
            target_name TEXT,
            device_id TEXT,
            job_id TEXT,
            execution_id TEXT,
            snapshot_id TEXT,
            summary TEXT NOT NULL,
            details_json TEXT NOT NULL,
            request_id TEXT,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    connection.close()

    def connect():
        return postgresql_test_driver.connect(db_path)

    monkeypatch.setattr(prompts_api, "get_db_connection", connect)
    return db_path


def _payload(**overrides) -> AIPromptCreate:
    values = {
        "code": "NETWORK_CHANGE_PLAN",
        "name": "网络变更实施计划",
        "scene": "change_plan",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "Return a cautious plan as JSON.",
        "user_prompt_template": "Objective: {{objective}}\nCurrent state: {{current_state}}",
        "output_schema": '{"summary":"string","steps":[]}',
        "temperature": 0.1,
        "max_tokens": 2048,
        "enabled": True,
    }
    values.update(overrides)
    return AIPromptCreate(**values)


def test_prompt_create_update_and_version_history_are_atomic(tmp_path, monkeypatch):
    db_path = _database(tmp_path, monkeypatch)

    created = prompts_api.create_prompt(_payload(), user=ADMIN)
    assert created.version == 1
    assert json.loads(created.output_schema)["steps"] == []

    unchanged = prompts_api.update_prompt(
        created.id,
        AIPromptUpdate(name="更清晰的网络变更实施计划"),
        user=ADMIN,
    )
    assert unchanged.version == 1
    assert unchanged.name == "更清晰的网络变更实施计划"

    updated = prompts_api.update_prompt(
        created.id,
        AIPromptUpdate(
            system_prompt="Return a reversible plan as JSON.",
            user_prompt_template="Objective: {{objective}}\nConstraints: {{constraints}}",
            output_schema='{"summary":"string","rollback":[]}',
            enabled=False,
        ),
        user=ADMIN,
    )
    assert updated.version == 2
    assert updated.enabled is False

    history = prompts_api.list_prompt_versions(created.id, user=ADMIN)
    assert [version.version for version in history] == [2, 1]
    assert json.loads(history[0].output_schema)["rollback"] == []

    connection = postgresql_test_driver.connect(db_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM ai_prompt_version WHERE prompt_id = ?", (created.id,)
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_prompt_lifecycle_copy_compare_restore_and_audit_are_server_side(tmp_path, monkeypatch):
    _database(tmp_path, monkeypatch)

    created = prompts_api.create_prompt(_payload(), user=ADMIN)
    updated = prompts_api.update_prompt(
        created.id,
        AIPromptUpdate(
            name="Evidence-backed network plan",
            system_prompt="Return a reversible plan with evidence.",
            change_reason="Add evidence and rollback guidance",
            expected_version=1,
        ),
        user=ADMIN,
    )
    assert updated.version == 2

    copied = prompts_api.copy_prompt(
        created.id,
        AIPromptCopyRequest(
            code="NETWORK_CHANGE_PLAN_REVIEW",
            name="Network change review",
            change_reason="Create a review-specific variant",
        ),
        user=ADMIN,
    )
    assert copied.version == 1
    assert copied.system_prompt == updated.system_prompt

    page = prompts_api.list_prompts(
        search="evidence-backed",
        scene="",
        enabled=None,
        page=1,
        page_size=1,
        user=ADMIN,
    )
    assert page.total == 1
    assert page.items[0].id == created.id
    assert page.total_pages == 1

    comparison = prompts_api.compare_prompt_versions(
        created.id,
        left_version=1,
        right_version=2,
        user=ADMIN,
    )
    assert comparison.changed_fields == ["system_prompt"]
    assert comparison.diff["system_prompt"]

    restored = prompts_api.restore_prompt_version(
        created.id,
        version=1,
        payload=AIPromptRestoreRequest(
            change_reason="Rollback the evidence change after validation",
            expected_current_version=2,
        ),
        user=ADMIN,
    )
    assert restored.version == 3
    assert restored.system_prompt == _payload().system_prompt

    history = prompts_api.list_prompt_versions(created.id, user=ADMIN)
    assert [version.version for version in history] == [3, 2, 1]
    assert history[0].change_type == "restore"
    assert history[0].restored_from_version == 1
    assert history[0].change_reason == "Rollback the evidence change after validation"

    audit_page = prompts_api.list_prompt_audit(created.id, page=1, page_size=2, search="", user=ADMIN)
    assert audit_page.total == 3
    assert audit_page.total_pages == 2
    audit_page_two = prompts_api.list_prompt_audit(created.id, page=2, page_size=2, search="", user=ADMIN)
    audit_items = [*audit_page.items, *audit_page_two.items]
    assert {item.event_type for item in audit_items} == {"ai_prompt_create", "ai_prompt_restore", "ai_prompt_update"}
    restore_audit = next(item for item in audit_items if item.event_type == "ai_prompt_restore")
    audit_after = json.dumps(restore_audit.after)
    assert updated.system_prompt not in audit_after
    assert _payload().user_prompt_template not in audit_after
    assert audit_page.items[0].after["content_sha256"]["system_prompt"]


def test_prompt_output_contract_and_input_bounds_fail_closed(tmp_path, monkeypatch):
    _database(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as invalid_schema:
        prompts_api.create_prompt(_payload(output_schema="not-json"), user=ADMIN)
    assert invalid_schema.value.status_code == 422

    with pytest.raises(HTTPException) as invalid_object:
        prompts_api.create_prompt(_payload(output_schema="[]"), user=ADMIN)
    assert invalid_object.value.status_code == 422

    with pytest.raises(ValueError):
        _payload(code="bad code")


def test_seed_assets_cover_operational_scenes_with_output_contracts():
    expected_scenes = {
        "topology_analysis",
        "health_summary",
        "compliance_audit",
        "change_plan",
        "rag_answer",
        "capacity_analysis",
    }
    assets = {prompt["scene"]: prompt for prompt in SEED_PROMPTS}
    assert expected_scenes.issubset(assets)
    assert len(assets) == len(SEED_PROMPTS)
    for prompt in SEED_PROMPTS:
        assert json.loads(prompt["output_schema"])
        assert "{{" in prompt["user_prompt_template"]
        assert prompt["system_prompt"]
