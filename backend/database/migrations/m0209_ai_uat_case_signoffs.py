"""Persist browser UAT case sign-offs and their audit history."""

from __future__ import annotations


VERSION = 209
NAME = "ai_uat_case_signoffs"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_uat_case_signoffs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'partial', 'rejected')),
            reviewer_id TEXT NOT NULL DEFAULT '',
            reviewer_name TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            evidence_ref TEXT NOT NULL DEFAULT '',
            signed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, campaign_id, case_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_uat_case_signoff_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            campaign_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            previous_status TEXT NOT NULL DEFAULT 'pending',
            new_status TEXT NOT NULL
                CHECK (new_status IN ('pending', 'approved', 'partial', 'rejected')),
            reviewer_id TEXT NOT NULL DEFAULT '',
            reviewer_name TEXT NOT NULL DEFAULT '',
            comment TEXT NOT NULL DEFAULT '',
            evidence_ref TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_uat_case_signoffs_tenant_campaign "
        "ON ai_uat_case_signoffs(tenant_id, campaign_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_uat_case_signoff_events_case "
        "ON ai_uat_case_signoff_events(tenant_id, campaign_id, case_id, created_at)"
    )


__all__ = ["VERSION", "NAME", "upgrade"]
