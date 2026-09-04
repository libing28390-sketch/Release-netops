from __future__ import annotations

import uuid

import psycopg2
import pytest
from psycopg2 import sql

import database.core as database_core
from ai.services.ai_experiment_service import (
    ExperimentPersistenceError,
    create_experiment_run,
    get_experiment_observability,
    list_shadow_observations,
    record_experiment_case_result,
    record_shadow_observation,
    runtime_rollout_decision,
    stable_rollout_bucket,
    update_experiment_run,
    upsert_runtime_rollout,
)
from database.migrations.m0202_ai_experiment_observability import downgrade, upgrade


def _create_run() -> dict:
    return create_experiment_run(
        tenant_id="tenant-experiment",
        dataset_id="dataset-anchors-50-v1",
        git_sha="abc1234",
        prompt_version="prompt.v1",
        parser_version="parser.v1",
        chunker_config_hash="chunkerhash",
        embedding_model="local-embedding-v1",
        embedding_dimensions=1536,
        distance_algorithm="cosine",
        reranker_version="baseline-v1",
        provider_model="local-deterministic",
        created_by="test-reviewer",
        config={"top_k": 10, "environment": "isolated-test"},
    )


def test_m0202_persists_metadata_only_experiment_and_shadow_evidence(isolated_db):
    run = _create_run()
    assert run["status"] == "planned"
    assert run["dataset_id"] == "dataset-anchors-50-v1"
    assert run["version"] == 1

    case = record_experiment_case_result(
        run_id=run["id"],
        tenant_id="tenant-experiment",
        case_id="ANCHOR-001",
        expected_outcome="answer",
        actual_outcome="answer",
        safety_passed=True,
        quality_passed=False,
        gold_document_ids=["doc-vlan"],
        returned_document_ids=["doc-other"],
        returned_vendors=["Huawei"],
        metrics={"recall_at_5": 0, "mrr": 0, "latency_ms": 12},
        created_by="test-reviewer",
    )
    assert case["case_id"] == "ANCHOR-001"
    assert case["quality_passed"] is False
    assert case["returned_document_ids"] == ["doc-other"]

    updated = update_experiment_run(
        run_id=run["id"],
        tenant_id="tenant-experiment",
        status="completed",
        metrics={"recall_at_5": 0, "recall_at_10": 0, "mrr": 0},
        updated_by="test-reviewer",
        expected_version=2,
    )
    assert updated["status"] == "completed"
    assert updated["version"] == 3

    observation = record_shadow_observation(
        tenant_id="tenant-experiment",
        component="reranker",
        request_id="req-shadow-001",
        baseline_ranked_ids=["doc-a", "doc-b"],
        candidate_ranked_ids=["doc-b", "doc-a"],
        metrics={"rank_delta": 1, "candidate_count": 2},
        baseline_latency_ms=10,
        candidate_latency_ms=25,
        experiment_run_id=run["id"],
        created_by="test-reviewer",
    )
    assert observation["request_id_hash"] != "req-shadow-001"
    assert observation["retention_days"] == 60
    assert observation["expires_at"] > observation["observed_at"]

    with isolated_db["module"].get_db_connection() as conn:
        table_columns = {
            str(row[1])
            for row in conn.execute(
                """SELECT table_name, column_name
                   FROM information_schema.columns
                   WHERE table_schema = current_schema()
                     AND table_name IN ('ai_experiment_run', 'ai_experiment_case_result', 'ai_runtime_rollout', 'ai_shadow_observation')""",
            ).fetchall()
        }
        assert table_columns
        forbidden_column_names = {"prompt", "answer", "content", "chunk", "cli_output", "tool_args"}
        assert not any(name in table_columns for name in forbidden_column_names)


def test_m0202_rollout_is_deterministic_tenant_scoped_and_optimistic(isolated_db):
    rollout = upsert_runtime_rollout(
        tenant_id="tenant-rollout",
        component="reranker",
        mode="shadow",
        rollout_percent=50,
        baseline_version="baseline-v1",
        candidate_version="bge-v1",
        updated_by="operator-a",
    )
    assert rollout["version"] == 1

    first = runtime_rollout_decision(
        tenant_id="tenant-rollout",
        component="reranker",
        request_id="request-001",
    )
    second = runtime_rollout_decision(
        tenant_id="tenant-rollout",
        component="reranker",
        request_id="request-001",
    )
    assert first == second
    assert first["mode"] == "shadow"
    assert first["production_version"] == "baseline-v1"
    assert first["candidate_enabled"] == (stable_rollout_bucket(tenant_id="tenant-rollout", request_id="request-001") < 50)

    assert runtime_rollout_decision(
        tenant_id="tenant-other",
        component="reranker",
        request_id="request-001",
    )["mode"] == "disabled"

    changed = upsert_runtime_rollout(
        tenant_id="tenant-rollout",
        component="reranker",
        mode="active",
        rollout_percent=100,
        baseline_version="baseline-v1",
        candidate_version="bge-v1",
        updated_by="operator-b",
        expected_version=1,
        kill_switch=False,
    )
    assert changed["version"] == 2
    assert runtime_rollout_decision(
        tenant_id="tenant-rollout",
        component="reranker",
        request_id="request-001",
    )["production_version"] == "bge-v1"

    with pytest.raises(ExperimentPersistenceError):
        upsert_runtime_rollout(
            tenant_id="tenant-rollout",
            component="reranker",
            mode="active",
            rollout_percent=100,
            baseline_version="baseline-v1",
            candidate_version="bge-v2",
            updated_by="operator-c",
            expected_version=1,
        )


def test_m0202_rejects_raw_content_and_invalid_shadow_retention(isolated_db):
    with pytest.raises(ValueError):
        create_experiment_run(
            tenant_id="tenant-invalid",
            dataset_id="dataset-v1",
            git_sha="abc1234",
            prompt_version="prompt.v1",
            parser_version="parser.v1",
            chunker_config_hash="hash",
            embedding_model="local-v1",
            embedding_dimensions=3,
            distance_algorithm="cosine",
            reranker_version="none",
            provider_model="local-v1",
            created_by="operator",
            config={"answer": "must-not-persist"},
        )

    with pytest.raises(ValueError):
        record_shadow_observation(
            tenant_id="tenant-invalid",
            component="reranker",
            request_id="req-1",
            baseline_ranked_ids=[],
            candidate_ranked_ids=[],
            retention_days=7,
            created_by="operator",
        )


def test_m0202_rejects_non_object_metrics_and_keeps_all_required_tables(isolated_db):
    run = _create_run()
    with pytest.raises(ValueError, match="metrics must be an object"):
        update_experiment_run(
            run_id=run["id"],
            tenant_id="tenant-experiment",
            metrics="not-an-object",  # type: ignore[arg-type]
            updated_by="test-reviewer",
        )

    with isolated_db["module"].get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name IN (
                'ai_experiment_run', 'ai_experiment_case_result',
                'ai_runtime_rollout', 'ai_shadow_observation'
              )
            """
        ).fetchall()
    assert {str(row[0]) for row in rows} == {
        "ai_experiment_run",
        "ai_experiment_case_result",
        "ai_runtime_rollout",
        "ai_shadow_observation",
    }


def test_m0202_downgrade_is_non_destructive_and_preserves_evidence(isolated_db):
    run = _create_run()
    with isolated_db["module"].get_db_connection() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM ai_experiment_run WHERE tenant_id = ? AND id = ?",
            ("tenant-experiment", run["id"]),
        ).fetchone()[0]

    downgrade(None, use_pg=True)

    with isolated_db["module"].get_db_connection() as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM ai_experiment_run WHERE tenant_id = ? AND id = ?",
            ("tenant-experiment", run["id"]),
        ).fetchone()[0]
    assert before == after == 1


def test_m0202_failed_upgrade_rolls_back_partial_postgresql_ddl(isolated_db):
    """A failed migration must not leave an earlier CREATE TABLE behind."""

    schema_name = f"test_m0202_txn_{uuid.uuid4().hex[:12]}"
    connection = psycopg2.connect(database_core._DATABASE_URL)

    class _FailingCursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self.calls = 0

        def execute(self, statement, params=None):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("injected migration failure")
            return self._cursor.execute(statement, params)

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema_name)))
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET search_path TO {} ").format(sql.Identifier(schema_name)))
        connection.commit()

        with connection.cursor() as cursor:
            failing_cursor = _FailingCursor(cursor)
            with pytest.raises(RuntimeError, match="injected migration failure"):
                upgrade(failing_cursor, use_pg=True)
            assert failing_cursor.calls == 2
        connection.rollback()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('ai_experiment_run'), to_regclass('ai_experiment_case_result')"
            )
            assert cursor.fetchone() == (None, None)
    finally:
        try:
            connection.rollback()
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
        finally:
            connection.close()


def test_m0202_kill_switch_restores_baseline_without_deleting_shadow_evidence(isolated_db):
    """Turning the candidate off must restore legacy production selection in place."""

    run = _create_run()
    record_shadow_observation(
        tenant_id="tenant-experiment",
        component="reranker",
        request_id="request-before-kill-switch",
        baseline_ranked_ids=["document-a", "document-b"],
        candidate_ranked_ids=["document-b", "document-a"],
        metrics={"rank_delta": 1},
        experiment_run_id=run["id"],
        created_by="test-reviewer",
    )
    upsert_runtime_rollout(
        tenant_id="tenant-experiment",
        component="reranker",
        mode="active",
        rollout_percent=100,
        baseline_version="legacy-v1",
        candidate_version="bge-v1",
        updated_by="operator-a",
    )
    active = runtime_rollout_decision(
        tenant_id="tenant-experiment",
        component="reranker",
        request_id="request-before-kill-switch",
    )
    assert active["candidate_enabled"] is True
    assert active["production_version"] == "bge-v1"

    restored = upsert_runtime_rollout(
        tenant_id="tenant-experiment",
        component="reranker",
        mode="disabled",
        rollout_percent=0,
        baseline_version="legacy-v1",
        candidate_version="bge-v1",
        updated_by="operator-b",
        kill_switch=True,
        expected_version=1,
    )
    assert restored["version"] == 2
    decision = runtime_rollout_decision(
        tenant_id="tenant-experiment",
        component="reranker",
        request_id="request-after-kill-switch",
    )
    assert decision["mode"] == "disabled"
    assert decision["kill_switch"] is True
    assert decision["candidate_enabled"] is False
    assert decision["production_version"] == "legacy-v1"

    with isolated_db["module"].get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM ai_shadow_observation WHERE experiment_run_id = ?",
            (run["id"],),
        ).fetchone()
    assert row[0] == 1


def test_m0202_observability_projection_is_tenant_scoped_and_redacted(isolated_db):
    run = _create_run()
    record_shadow_observation(
        tenant_id="tenant-experiment",
        component="reranker",
        request_id="request-sensitive-001",
        baseline_ranked_ids=["document-a", "document-b"],
        candidate_ranked_ids=["document-b", "document-a"],
        metrics={"rank_delta": 1, "candidate_count": 2},
        baseline_latency_ms=10,
        candidate_latency_ms=25,
        experiment_run_id=run["id"],
        created_by="test-reviewer",
    )

    projection = get_experiment_observability(tenant_id="tenant-experiment", limit=20)
    assert projection["redacted"] is True
    assert projection["contains_prompt_or_answer"] is False
    assert projection["contains_document_or_chunk_identity"] is False
    assert projection["runs"][0]["dataset_id"] == "dataset-anchors-50-v1"
    assert projection["shadow_observations"][0]["order_changed"] is True
    assert projection["shadow_observations"][0]["rank_deltas"]
    rendered = str(projection)
    assert "document-a" not in rendered
    assert "request-sensitive-001" not in rendered
    assert get_experiment_observability(tenant_id="tenant-other", limit=20)["runs"] == []
    assert list_shadow_observations(tenant_id="tenant-other", limit=20) == []
