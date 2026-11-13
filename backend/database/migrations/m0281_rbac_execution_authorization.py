"""Persist approval bindings and account authorization mode for RBAC hardening."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone


VERSION = 281
NAME = "rbac_execution_authorization"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if not use_pg:
        raise RuntimeError("RBAC execution authorization migration requires PostgreSQL")
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}


def _normalize_legacy_account_profiles(cursor) -> None:
    """Keep historical capability profiles from surviving on ordinary users."""
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS legacy_user_rbac_assignments (
               user_id TEXT PRIMARY KEY,
               previous_role TEXT NOT NULL DEFAULT '',
               previous_role_profile TEXT NOT NULL DEFAULT '',
               previous_scope_mode TEXT NOT NULL DEFAULT '',
               previous_scopes_json TEXT NOT NULL DEFAULT '[]',
               captured_at TEXT NOT NULL
           )"""
    )
    cursor.execute(
        """UPDATE users SET role = 'Administrator'
             WHERE LOWER(TRIM(COALESCE(role, ''))) IN ('administrator', 'admin')"""
    )
    users = cursor.execute(
        """SELECT id, COALESCE(tenant_id, '') AS tenant_id
             FROM users
            WHERE LOWER(TRIM(COALESCE(role, ''))) NOT IN ('administrator', 'admin')"""
    ).fetchall()
    created_at = datetime.now(timezone.utc).isoformat()
    for row in users:
        user_id = str(row[0] or '')
        tenant_id = str(row[1] or '').strip()
        previous = cursor.execute(
            "SELECT role, role_profile, scope_mode FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        previous_scopes = cursor.execute(
            """SELECT id, resource_type, scope_type, scope_id, actions_json, created_at
                 FROM user_resource_scopes WHERE user_id = ? ORDER BY id""",
            (user_id,),
        ).fetchall()
        cursor.execute(
            """INSERT INTO legacy_user_rbac_assignments
               (user_id, previous_role, previous_role_profile, previous_scope_mode,
                previous_scopes_json, captured_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO NOTHING""",
            (
                user_id,
                str(previous[0] or '') if previous else '',
                str(previous[1] or '') if previous else '',
                str(previous[2] or '') if previous else '',
                json.dumps(
                    [
                        {
                            "id": str(scope[0] or ''),
                            "resource_type": str(scope[1] or ''),
                            "scope_type": str(scope[2] or ''),
                            "scope_id": str(scope[3] or ''),
                            "actions_json": str(scope[4] or '[]'),
                            "created_at": str(scope[5] or ''),
                        }
                        for scope in previous_scopes
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                created_at,
            ),
        )
        cursor.execute(
            """UPDATE users
                  SET role = 'Viewer', role_profile = 'Change Requester', scope_mode = 'restricted'
                WHERE id = ?""",
            (user_id,),
        )
        # Replace any legacy capability grants with the narrowly scoped
        # requester workflow. Tenantless users get no scope rows and therefore
        # remain denied until an administrator assigns them to a tenant.
        cursor.execute("DELETE FROM user_resource_scopes WHERE user_id = ?", (user_id,))
        if not tenant_id:
            continue
        for resource_type, actions in (
            ('pam', ['create_change', 'view']),
            ('change_order', ['create', 'update', 'view']),
        ):
            cursor.execute(
                """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                   VALUES (?, ?, ?, 'tenant', ?, ?, ?)""",
                (
                    f"scope-{uuid.uuid4().hex[:16]}",
                    user_id,
                    resource_type,
                    tenant_id,
                    json.dumps(actions, sort_keys=True),
                    created_at,
                ),
            )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("RBAC execution authorization migration requires PostgreSQL")
    user_columns = _columns(cursor, "users", use_pg)
    if "scope_mode" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN scope_mode TEXT NOT NULL DEFAULT 'legacy'")
    _normalize_legacy_account_profiles(cursor)

    job_columns = _columns(cursor, "scheduled_jobs", use_pg)
    for name, declaration in (
        ("created_by_id", "TEXT NOT NULL DEFAULT ''"),
        ("tenant_id", "TEXT NOT NULL DEFAULT ''"),
        ("script_sha256", "TEXT NOT NULL DEFAULT ''"),
        ("authorization_manifest_hash", "TEXT NOT NULL DEFAULT ''"),
        ("authorization_mode", "TEXT NOT NULL DEFAULT 'legacy'"),
    ):
        if name not in job_columns:
            cursor.execute(f"ALTER TABLE scheduled_jobs ADD COLUMN {name} {declaration}")

    script_columns = _columns(cursor, "scripts", use_pg)
    for name, declaration in (
        ("created_by_id", "TEXT NOT NULL DEFAULT ''"),
        ("tenant_id", "TEXT NOT NULL DEFAULT 'tenant-default'"),
        ("approver_id", "TEXT NOT NULL DEFAULT ''"),
        ("approved_by_id", "TEXT NOT NULL DEFAULT ''"),
        ("content_sha256", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in script_columns:
            cursor.execute(f"ALTER TABLE scripts ADD COLUMN {name} {declaration}")
    cursor.execute(
        """UPDATE scripts s
              SET created_by_id = COALESCE((
                      SELECT u.id FROM users u
                       WHERE u.username = COALESCE(NULLIF(s.submitter_name, ''), s.author, '')
                  ), ''),
                  tenant_id = COALESCE((
                      SELECT NULLIF(u.tenant_id, '') FROM users u
                       WHERE u.username = COALESCE(NULLIF(s.submitter_name, ''), s.author, '')
                  ), CASE
                       WHEN LOWER(COALESCE(NULLIF(s.submitter_name, ''), s.author, '')) = 'system'
                       THEN 'tenant-default'
                       ELSE ''
                  END)
            WHERE COALESCE(created_by_id, '') = ''
               OR COALESCE(tenant_id, '') = ''"""
    )
    # Older script rows did not persist an approver subject or freeze the
    # approved content. Keep trusted system seeds, but make user-authored
    # historical submissions drafts so they must pass the new review gate.
    cursor.execute(
        """UPDATE scripts
              SET status = 'draft', approver_username = '', approved_by_id = '',
                  content_sha256 = ''
            WHERE LOWER(COALESCE(submitter_name, author, '')) <> 'system'
              AND LOWER(COALESCE(status, '')) IN ('pending_audit', 'released')"""
    )
    released_rows = cursor.execute(
        "SELECT id, content FROM scripts WHERE LOWER(COALESCE(status, '')) = 'released'"
    ).fetchall()
    for row in released_rows:
        script_id, content = str(row[0]), str(row[1] or '')
        cursor.execute(
            "UPDATE scripts SET content_sha256 = ? WHERE id = ?",
            (hashlib.sha256(content.encode('utf-8')).hexdigest(), script_id),
        )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_scripts_tenant_status ON scripts(tenant_id, status)"
    )

    # Existing scheduled jobs were created before approvals were bound to a
    # frozen operation manifest.  Do not infer a valid approval from their
    # old status fields.  Resolve the historical owner for attribution, then
    # require an operator to review and re-authorize each user job.
    cursor.execute(
        """UPDATE scheduled_jobs
              SET created_by_id = COALESCE((
                      SELECT u.id FROM users u
                       WHERE u.username = scheduled_jobs.created_by
                  ), ''),
                  tenant_id = COALESCE((
                      SELECT NULLIF(u.tenant_id, '') FROM users u
                       WHERE u.username = scheduled_jobs.created_by
                  ), ''),
                  enabled = 0,
                  status = 'reauthorization_required',
                  authorization_mode = 'legacy'
            WHERE COALESCE(authorization_mode, 'legacy') = 'legacy'"""
    )
    # One built-in read-only NSOT collector is a platform service job.  It is
    # allowed through a narrow runtime identity check; no user-owned legacy
    # job receives this mode merely because its action_type is "nsot".
    cursor.execute(
        """UPDATE scheduled_jobs
              SET created_by_id = '', tenant_id = 'tenant-default',
                  enabled = 1, status = 'approved', authorization_mode = 'system'
            WHERE id = 'nsot-daily-collection'
              AND name = 'NSOT 网络事实库每日采集'
              AND job_type = 'cron' AND action_type = 'nsot'
              AND cron_expr = '0 2 * * *' AND device_scope = 'all'
              AND COALESCE(device_filter, '') = ''
              AND COALESCE(commands, '') = ''
              AND COALESCE(script_id, '') = ''
              AND COALESCE(is_config, 0) = 0
              AND COALESCE(use_admin_creds, 0) = 0"""
    )

    change_order_columns = _columns(cursor, "change_orders", use_pg)
    if "tenant_id" not in change_order_columns:
        cursor.execute("ALTER TABLE change_orders ADD COLUMN tenant_id TEXT NOT NULL DEFAULT ''")
    cursor.execute(
        """UPDATE change_orders
              SET tenant_id = COALESCE((
                  SELECT NULLIF(u.tenant_id, '') FROM users u WHERE u.id = change_orders.requester_id
              ), '')
            WHERE COALESCE(tenant_id, '') = ''"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_change_orders_tenant_status "
        "ON change_orders(tenant_id, status, created_at)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_approval_requests (
            token_hash TEXT PRIMARY KEY,
            approval_type TEXT NOT NULL,
            requester_id TEXT NOT NULL,
            requester_username TEXT NOT NULL,
            requester_tenant_id TEXT NOT NULL DEFAULT '',
            approver_id TEXT NOT NULL,
            approver_username TEXT NOT NULL,
            verification_method TEXT NOT NULL,
            code_hash TEXT NOT NULL DEFAULT '',
            binding_hash TEXT NOT NULL DEFAULT '',
            config_reason TEXT NOT NULL DEFAULT '',
            device_hostname TEXT NOT NULL DEFAULT '',
            command_preview TEXT NOT NULL DEFAULT '',
            extra_fields_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            verified_at TEXT NOT NULL DEFAULT '',
            consumed_at TEXT NOT NULL DEFAULT '',
            CHECK (status IN ('pending', 'verified', 'consumed', 'expired', 'revoked'))
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_config_approval_requests_expiry "
        "ON config_approval_requests(status, expires_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_config_approval_requests_requester "
        "ON config_approval_requests(requester_id, created_at)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_approval_mfa_limits (
            approver_id TEXT PRIMARY KEY,
            window_started_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_approval_mfa_steps (
            approver_id TEXT NOT NULL,
            time_step BIGINT NOT NULL,
            used_at TEXT NOT NULL,
            PRIMARY KEY (approver_id, time_step)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_config_approval_mfa_steps_used_at "
        "ON config_approval_mfa_steps(used_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Approval history is security evidence; retain it on downgrade.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
