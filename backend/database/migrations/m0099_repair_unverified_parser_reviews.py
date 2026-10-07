"""Return legacy parser reviews to draft when no sandbox pass was recorded."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


VERSION = 99
NAME = "repair_unverified_parser_reviews"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _has_sandbox_pass(summary_json: str | None) -> bool:
    try:
        summary = json.loads(summary_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(summary, dict) and summary.get("passed") is True


def upgrade(cursor, use_pg: bool) -> None:
    """Fail closed for review states created before submit-time gating existed.

    Published versions are intentionally excluded: this repair only prevents
    an unverified version from remaining in a state that an approver or
    publisher can advance.  The original lifecycle state is preserved in the
    audit metadata for operator follow-up.
    """
    now = _now()
    rows = cursor.execute(
        """SELECT id, template_id, status, test_summary_json
           FROM parser_template_versions
           WHERE status IN ('IN_REVIEW', 'APPROVED')"""
    ).fetchall()
    for row in rows:
        version_id, template_id, status, summary_json = row[0], row[1], row[2], row[3]
        if _has_sandbox_pass(summary_json):
            continue
        cursor.execute(
            """UPDATE parser_template_versions
               SET status = 'DRAFT', approved_by = '', published_by = '',
                   lock_version = COALESCE(lock_version, 1) + 1,
                   updated_at = ?
               WHERE id = ? AND status IN ('IN_REVIEW', 'APPROVED')""",
            (now, version_id),
        )
        cursor.execute(
            """INSERT INTO parser_template_audit_logs
               (id, template_id, version_id, event_type, actor_id,
                actor_username, metadata_json, created_at)
               VALUES (?, ?, ?, 'VERSION_GATE_REPAIRED', 'system', 'system', ?, ?)""",
            (
                str(uuid.uuid4()),
                template_id,
                version_id,
                json.dumps(
                    {
                        "from": status,
                        "to": "DRAFT",
                        "reason": "sandbox_pass_required_before_submission",
                    },
                    ensure_ascii=False,
                ),
                now,
            ),
        )
