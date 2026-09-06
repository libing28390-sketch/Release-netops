"""Add PostgreSQL-only experiment, rollout, and Shadow observation storage.

The tables contain evaluation metadata and ranked document identities only.
They intentionally have no prompt, answer, CLI output, or chunk-body columns.
Rollout updates are serialized by the service with a version check; rollback
changes a pointer/mode and never removes experiment or Shadow evidence.
"""

from __future__ import annotations


VERSION = 202
NAME = "ai_experiment_observability"


def upgrade(cursor, use_pg: bool) -> None:
    """Create the tenant-scoped DATA-001 evidence model."""

    if not use_pg:
        raise RuntimeError("ai_experiment_observability requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_experiment_run (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            git_sha TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            chunker_config_hash TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions >= 0),
            distance_algorithm TEXT NOT NULL,
            reranker_version TEXT NOT NULL,
            provider_model TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned'
                CHECK (status IN ('planned', 'running', 'completed', 'failed', 'cancelled')),
            metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_experiment_case_result (
            id TEXT PRIMARY KEY,
            experiment_run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            expected_outcome TEXT NOT NULL,
            actual_outcome TEXT NOT NULL,
            safety_passed BOOLEAN NOT NULL,
            quality_passed BOOLEAN,
            recall_at_5 DOUBLE PRECISION CHECK (recall_at_5 IS NULL OR recall_at_5 BETWEEN 0 AND 1),
            recall_at_10 DOUBLE PRECISION CHECK (recall_at_10 IS NULL OR recall_at_10 BETWEEN 0 AND 1),
            mrr DOUBLE PRECISION CHECK (mrr IS NULL OR mrr BETWEEN 0 AND 1),
            ndcg DOUBLE PRECISION CHECK (ndcg IS NULL OR ndcg BETWEEN 0 AND 1),
            citation_precision DOUBLE PRECISION CHECK (citation_precision IS NULL OR citation_precision BETWEEN 0 AND 1),
            citation_recall DOUBLE PRECISION CHECK (citation_recall IS NULL OR citation_recall BETWEEN 0 AND 1),
            wrong_vendor_rate DOUBLE PRECISION CHECK (wrong_vendor_rate IS NULL OR wrong_vendor_rate BETWEEN 0 AND 1),
            feature_pollution_rate DOUBLE PRECISION CHECK (feature_pollution_rate IS NULL OR feature_pollution_rate BETWEEN 0 AND 1),
            latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
            error_code TEXT,
            gold_document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            returned_document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            returned_vendors JSONB NOT NULL DEFAULT '[]'::jsonb,
            metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
            UNIQUE (experiment_run_id, case_id),
            FOREIGN KEY (experiment_run_id) REFERENCES ai_experiment_run(id) ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_runtime_rollout (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            component TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'disabled'
                CHECK (mode IN ('disabled', 'shadow', 'active', 'degraded', 'failed')),
            rollout_percent INTEGER NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
            baseline_version TEXT NOT NULL,
            candidate_version TEXT NOT NULL,
            kill_switch BOOLEAN NOT NULL DEFAULT FALSE,
            config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE (tenant_id, component)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_shadow_observation (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            experiment_run_id TEXT,
            component TEXT NOT NULL,
            request_id_hash TEXT NOT NULL,
            baseline_ranked_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            candidate_ranked_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            baseline_latency_ms INTEGER CHECK (baseline_latency_ms IS NULL OR baseline_latency_ms >= 0),
            candidate_latency_ms INTEGER CHECK (candidate_latency_ms IS NULL OR candidate_latency_ms >= 0),
            status TEXT NOT NULL DEFAULT 'observed'
                CHECK (status IN ('observed', 'timeout', 'degraded', 'failed')),
            reason_code TEXT,
            retention_days INTEGER NOT NULL DEFAULT 60 CHECK (retention_days BETWEEN 30 AND 90),
            observed_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            FOREIGN KEY (experiment_run_id) REFERENCES ai_experiment_run(id) ON DELETE RESTRICT,
            CHECK (expires_at > observed_at)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_experiment_run_tenant_status "
        "ON ai_experiment_run(tenant_id, status, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_experiment_case_result_tenant_run "
        "ON ai_experiment_case_result(tenant_id, experiment_run_id, case_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_runtime_rollout_tenant_mode "
        "ON ai_runtime_rollout(tenant_id, mode, updated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_shadow_observation_tenant_component "
        "ON ai_shadow_observation(tenant_id, component, observed_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_shadow_observation_expiry "
        "ON ai_shadow_observation(expires_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    """Keep experiment and audit evidence during release rollback."""

    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
