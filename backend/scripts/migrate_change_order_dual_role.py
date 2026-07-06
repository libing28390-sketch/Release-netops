#!/usr/bin/env python3
"""
Task 20 — One-off migration script for dirty historical data.

Scans `change_orders` for rows where:
  - requester_username == assigned_initial_reviewer_username, OR
  - requester_username == assigned_final_approver_username

Prints a report (order_number, requester, reviewer/approver, status).

With --apply:
  - Nulls out the offending assigned_*_id / assigned_*_username fields
  - Logs an audit event (event_type='change_order.dual_role_migration_cleanup')
  - Preserves original values in result_detail.migration_notes for forensic trace

Dry-run by default; requires explicit --apply flag.

Design_Ref: design.md §Migration / Rollout → 3 对存量脏数据
Validates: Property 6 (no dual-role rows remain post-migration)
Requirements: 2.15
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# Make backend/ importable
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find_dual_role_rows(conn) -> list[dict]:
    """Return all change_orders rows with dual-role violations."""
    rows = conn.execute(
        """
        SELECT id, order_number, status,
               requester_username,
               assigned_initial_reviewer_id, assigned_initial_reviewer_username,
               assigned_final_approver_id, assigned_final_approver_username,
               result_detail_json
        FROM change_orders
        WHERE (
            (assigned_initial_reviewer_username != '' AND
             assigned_initial_reviewer_username = requester_username)
            OR
            (assigned_final_approver_username != '' AND
             assigned_final_approver_username = requester_username)
        )
        ORDER BY created_at
        """
    ).fetchall()
    return [dict(r) for r in rows]


def print_report(dirty_rows: list[dict]) -> None:
    if not dirty_rows:
        print("✅ No dual-role rows found. Database is clean.")
        return

    print(f"\n⚠️  Found {len(dirty_rows)} dual-role row(s):\n")
    print(f"{'Order Number':<20} {'Status':<18} {'Requester':<20} {'Reviewer':<20} {'Approver':<20}")
    print("-" * 100)
    for row in dirty_rows:
        violations = []
        if (row["assigned_initial_reviewer_username"] and
                row["assigned_initial_reviewer_username"] == row["requester_username"]):
            violations.append(f"reviewer={row['assigned_initial_reviewer_username']!r}")
        if (row["assigned_final_approver_username"] and
                row["assigned_final_approver_username"] == row["requester_username"]):
            violations.append(f"approver={row['assigned_final_approver_username']!r}")
        print(
            f"{row['order_number']:<20} {row['status']:<18} "
            f"{row['requester_username']:<20} "
            f"{row.get('assigned_initial_reviewer_username', ''):<20} "
            f"{row.get('assigned_final_approver_username', ''):<20}"
            f"  ← {', '.join(violations)}"
        )
    print()


def apply_migration(conn, dirty_rows: list[dict]) -> int:
    """Apply the migration: null out offending fields, log audit events."""
    from services.audit_service import log_audit_event

    fixed_count = 0
    now = _utc_now()

    for row in dirty_rows:
        updates: dict[str, str] = {}
        migration_notes: dict[str, str] = {}

        # Check initial reviewer violation
        if (row["assigned_initial_reviewer_username"] and
                row["assigned_initial_reviewer_username"] == row["requester_username"]):
            migration_notes["original_assigned_initial_reviewer_id"] = row["assigned_initial_reviewer_id"]
            migration_notes["original_assigned_initial_reviewer_username"] = row["assigned_initial_reviewer_username"]
            updates["assigned_initial_reviewer_id"] = ""
            updates["assigned_initial_reviewer_username"] = ""

        # Check final approver violation
        if (row["assigned_final_approver_username"] and
                row["assigned_final_approver_username"] == row["requester_username"]):
            migration_notes["original_assigned_final_approver_id"] = row["assigned_final_approver_id"]
            migration_notes["original_assigned_final_approver_username"] = row["assigned_final_approver_username"]
            updates["assigned_final_approver_id"] = ""
            updates["assigned_final_approver_username"] = ""

        if not updates:
            continue

        # Preserve original values in result_detail.migration_notes
        try:
            rd = json.loads(row.get("result_detail_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            rd = {}
        rd["migration_notes"] = {
            **migration_notes,
            "migrated_at": now,
            "migration_script": "migrate_change_order_dual_role.py",
        }

        # Build SET clause
        set_parts = [f"{k} = ?" for k in updates]
        set_parts.append("result_detail_json = ?")
        set_parts.append("updated_at = ?")
        values = list(updates.values()) + [json.dumps(rd, ensure_ascii=False), now, row["id"]]

        conn.execute(
            f"UPDATE change_orders SET {', '.join(set_parts)} WHERE id = ?",
            values,
        )

        # Log audit event
        log_audit_event(
            event_type="change_order.dual_role_migration_cleanup",
            category="change_order",
            severity="low",
            status="open",
            summary=(
                f"Dual-role migration: cleared offending assignee fields on "
                f"order {row['order_number']} (requester={row['requester_username']!r})"
            ),
            actor_id="system",
            actor_username="system",
            actor_role="system",
            target_type="change_order",
            target_id=row["id"],
            target_name=row["order_number"],
            details={"migration_notes": migration_notes},
            conn=conn,
        )

        fixed_count += 1
        print(f"  ✓ Fixed {row['order_number']} ({row['status']})")

    conn.commit()
    return fixed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate dual-role change orders (requester == reviewer/approver)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply the migration (default: dry-run only)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Path to SQLite DB (default: uses DATABASE_URL env or data/netops.db)",
    )
    args = parser.parse_args()

    # Set up DB path if provided
    if args.db_path:
        import database
        database.DB_PATH = args.db_path

    from database import get_db_connection

    conn = get_db_connection()
    try:
        dirty_rows = find_dual_role_rows(conn)
        print_report(dirty_rows)

        if not dirty_rows:
            sys.exit(0)

        if not args.apply:
            print("ℹ️  Dry-run mode. Use --apply to fix the rows above.")
            print(f"   Would fix {len(dirty_rows)} row(s).")
            sys.exit(0)

        print(f"Applying migration to {len(dirty_rows)} row(s)...")
        fixed = apply_migration(conn, dirty_rows)
        print(f"\n✅ Migration complete. Fixed {fixed} row(s).")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
