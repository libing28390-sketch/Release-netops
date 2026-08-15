"""Read-only database consistency and orphan patrols.

The patrol deliberately inspects the database's declared foreign keys instead
of maintaining a second, slowly drifting list of relationships.  It is safe
to run against V1 databases, partially upgraded databases, and the V2 shadow
schema: missing tables/columns are reported as ``not_applicable`` and never
cause an ad-hoc DDL migration.  The queries return counts and one-way
fingerprints only; document content, credentials, and primary-key values are
never returned to callers or logs.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from .core import _USE_PG, get_db_connection


logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_DEFAULT_SAMPLE_LIMIT = 5
_DEFAULT_MAX_CHECKS = 200


def _identifier(value: str) -> str:
    """Quote a database identifier after validating its introspected shape."""
    value = str(value)
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe database identifier returned by catalog: {value!r}")
    return f'"{value}"'


def _qualified(item: dict[str, Any], prefix: str) -> str:
    schema = str(item.get(f"{prefix}_schema") or "").strip()
    table = _identifier(str(item[f"{prefix}_table"]))
    if schema and schema.lower() not in {"main", "public"}:
        return f"{_identifier(schema)}.{table}"
    return table


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _table_columns(conn: Any, table: str, *, use_pg: bool) -> set[str]:
    if not _IDENTIFIER.fullmatch(table):
        return set()
    try:
        if use_pg:
            rows = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchall()
            return {str(_row_value(row, "column_name", 0)) for row in rows}
        rows = conn.execute(f"PRAGMA table_info({_identifier(table)})").fetchall()
        return {str(_row_value(row, "name", 1)) for row in rows}
    except Exception:
        return set()


def _sqlite_foreign_keys(conn: Any) -> list[dict[str, Any]]:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    relationships: list[dict[str, Any]] = []
    for row in tables:
        table = str(_row_value(row, "name", 0))
        if not _IDENTIFIER.fullmatch(table):
            continue
        try:
            fk_rows = conn.execute(f"PRAGMA foreign_key_list({_identifier(table)})").fetchall()
        except Exception:
            continue
        counts_by_id: dict[Any, int] = {}
        for fk in fk_rows:
            fk_id = _row_value(fk, "id", 0)
            counts_by_id[fk_id] = counts_by_id.get(fk_id, 0) + 1
        for fk in fk_rows:
            # SQLite exposes (id, seq, table, from, to, on_update, ...).
            # Composite constraints are intentionally skipped: a partial
            # check would report false orphans and hide the real constraint.
            if str(_row_value(fk, "seq", 1)) != "0":
                continue
            fk_id = _row_value(fk, "id", 0)
            relationships.append({
                "constraint": f"sqlite:{table}:{fk_id}",
                "child_schema": "main",
                "child_table": table,
                "child_column": str(_row_value(fk, "from", 3)),
                "parent_schema": "main",
                "parent_table": str(_row_value(fk, "table", 2)),
                "parent_column": str(_row_value(fk, "to", 4)),
                "column_count": counts_by_id.get(fk_id, 1),
            })
    return relationships


def _postgres_foreign_keys(conn: Any) -> list[dict[str, Any]]:
    # Composite FKs are recorded as skipped by the caller; single-column FKs
    # are sufficient for deterministic orphan counts and tenant checks.
    rows = conn.execute(
        """
        SELECT child_ns.nspname, child.relname, child_col.attname,
               parent_ns.nspname, parent.relname, parent_col.attname,
               con.conname, COALESCE(array_length(con.conkey, 1), 0)
        FROM pg_constraint con
        JOIN pg_class child ON child.oid = con.conrelid
        JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
        JOIN pg_class parent ON parent.oid = con.confrelid
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
        JOIN pg_attribute child_col
          ON child_col.attrelid = con.conrelid AND child_col.attnum = con.conkey[1]
        JOIN pg_attribute parent_col
          ON parent_col.attrelid = con.confrelid AND parent_col.attnum = con.confkey[1]
        WHERE con.contype = 'f'
          AND child_ns.nspname = current_schema()
        ORDER BY child.relname, con.conname
        """
    ).fetchall()
    relationships: list[dict[str, Any]] = []
    for row in rows:
        relationships.append({
            "constraint": str(_row_value(row, "conname", 6)),
            "child_schema": str(_row_value(row, "nspname", 0)),
            "child_table": str(_row_value(row, "relname", 1)),
            "child_column": str(_row_value(row, "attname", 2)),
            "parent_schema": str(_row_value(row, "nspname", 3)),
            "parent_table": str(_row_value(row, "relname", 4)),
            "parent_column": str(_row_value(row, "attname", 5)),
            "column_count": int(_row_value(row, "array_length", 7) or 0),
        })
    return relationships


def discover_foreign_keys(conn: Any, *, use_pg: bool | None = None) -> list[dict[str, Any]]:
    """Return declared single-column and composite foreign-key metadata."""
    backend = _USE_PG if use_pg is None else bool(use_pg)
    return _postgres_foreign_keys(conn) if backend else _sqlite_foreign_keys(conn)


def _fingerprint(*parts: Any) -> str:
    value = "|".join(str(part) for part in parts)
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]


def _count(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    try:
        return int(row["cnt"] or 0)
    except (KeyError, TypeError, IndexError):
        return int(row[0] or 0)


def _foreign_key_enforcement(conn: Any, *, use_pg: bool) -> dict[str, Any]:
    if use_pg:
        return {"name": "foreign_key_enforcement", "status": "PASS", "enforced": True}
    try:
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        enforced = bool(_row_value(row, "foreign_keys", 0)) if row is not None else False
    except Exception as exc:
        return {
            "name": "foreign_key_enforcement", "status": "WARN", "enforced": None,
            "error_class": type(exc).__name__,
        }
    return {
        "name": "foreign_key_enforcement",
        "status": "PASS" if enforced else "WARN",
        "enforced": enforced,
        "remediation": None if enforced else "Enable PRAGMA foreign_keys=ON for write paths; patrol remains read-only.",
    }


def _run_fk_check(
    conn: Any,
    relationship: dict[str, Any],
    *,
    use_pg: bool,
    tenant_id: str | None,
    sample_limit: int,
) -> dict[str, Any]:
    child_table = str(relationship.get("child_table") or "")
    parent_table = str(relationship.get("parent_table") or "")
    child_column = str(relationship.get("child_column") or "")
    parent_column = str(relationship.get("parent_column") or "")
    base = {
        "name": f"orphan:{child_table}.{child_column}->{parent_table}.{parent_column}",
        "kind": "orphan",
        "child_table": child_table,
        "child_column": child_column,
        "parent_table": parent_table,
        "parent_column": parent_column,
        "constraint": relationship.get("constraint"),
    }
    if relationship.get("column_count", 1) not in (0, 1):
        return {**base, "status": "NOT_APPLICABLE", "reason": "composite_foreign_key"}
    child_columns = _table_columns(conn, child_table, use_pg=use_pg)
    parent_columns = _table_columns(conn, parent_table, use_pg=use_pg)
    if child_column not in child_columns or parent_column not in parent_columns:
        return {**base, "status": "NOT_APPLICABLE", "reason": "table_or_column_missing"}
    child_ref = f"{_qualified(relationship, 'child')} c"
    parent_ref = f"{_qualified(relationship, 'parent')} p"
    child_col = f"c.{_identifier(child_column)}"
    parent_col = f"p.{_identifier(parent_column)}"
    filters = [f"{child_col} IS NOT NULL", f"{parent_col} IS NULL"]
    params: list[Any] = []
    if tenant_id is not None and "tenant_id" in child_columns:
        filters.append(f"c.{_identifier('tenant_id')} = ?")
        params.append(str(tenant_id))
    where = " AND ".join(filters)
    try:
        count = _count(
            conn,
            f"SELECT COUNT(*) AS cnt FROM {child_ref} LEFT JOIN {parent_ref} "
            f"ON {child_col} = {parent_col} WHERE {where}",
            tuple(params),
        )
        # Fingerprints are stable enough for two patrols to be compared but do
        # not disclose the offending primary-key value.
        sample_rows = conn.execute(
            f"SELECT {child_col} AS child_key FROM {child_ref} LEFT JOIN {parent_ref} "
            f"ON {child_col} = {parent_col} WHERE {where} "
            f"LIMIT {max(1, int(sample_limit))}",
            tuple(params),
        ).fetchall()
        fingerprints = [
            _fingerprint(child_table, child_column, _row_value(row, "child_key", 0))
            for row in sample_rows
        ]
    except Exception as exc:
        return {
            **base, "status": "ERROR", "count": None,
            "error_class": type(exc).__name__,
        }
    return {
        **base,
        "status": "FAIL" if count else "PASS",
        "count": count,
        "sample_fingerprints": fingerprints,
        "sample_truncated": count > len(fingerprints),
    }


def _run_tenant_scope_check(
    conn: Any,
    relationship: dict[str, Any],
    *,
    use_pg: bool,
    tenant_id: str | None,
) -> dict[str, Any] | None:
    child_table = str(relationship.get("child_table") or "")
    parent_table = str(relationship.get("parent_table") or "")
    child_columns = _table_columns(conn, child_table, use_pg=use_pg)
    parent_columns = _table_columns(conn, parent_table, use_pg=use_pg)
    if "tenant_id" not in child_columns or "tenant_id" not in parent_columns:
        return None
    child_ref = f"{_qualified(relationship, 'child')} c"
    parent_ref = f"{_qualified(relationship, 'parent')} p"
    child_col = f"c.{_identifier(str(relationship['child_column']))}"
    parent_col = f"p.{_identifier(str(relationship['parent_column']))}"
    filters = [
        f"{child_col} IS NOT NULL",
        f"{child_col} = {parent_col}",
        f"COALESCE(c.{_identifier('tenant_id')}, '') != COALESCE(p.{_identifier('tenant_id')}, '')",
    ]
    params: list[Any] = []
    if tenant_id is not None:
        filters.append(f"c.{_identifier('tenant_id')} = ?")
        params.append(str(tenant_id))
    try:
        count = _count(
            conn,
            f"SELECT COUNT(*) AS cnt FROM {child_ref} JOIN {parent_ref} "
            f"ON {child_col} = {parent_col} WHERE {' AND '.join(filters)}",
            tuple(params),
        )
    except Exception as exc:
        return {
            "name": f"tenant-scope:{child_table}->{parent_table}",
            "kind": "tenant_scope", "status": "ERROR", "count": None,
            "error_class": type(exc).__name__,
        }
    return {
        "name": f"tenant-scope:{child_table}->{parent_table}",
        "kind": "tenant_scope", "status": "FAIL" if count else "PASS",
        "count": count,
        "child_table": child_table, "parent_table": parent_table,
    }


def run_consistency_patrol(
    conn: Any | None = None,
    *,
    use_pg: bool | None = None,
    tenant_id: str | None = None,
    max_checks: int = _DEFAULT_MAX_CHECKS,
    sample_limit: int = _DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Run bounded, read-only orphan and tenant-scope checks.

    ``conn`` is optional for scheduled callers.  The function never commits,
    mutates rows, creates tables, or performs automatic repair.
    """
    own_conn = conn is None
    connection = conn or get_db_connection()
    backend_pg = _USE_PG if use_pg is None else bool(use_pg)
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        relationships = discover_foreign_keys(connection, use_pg=backend_pg)
        checks: list[dict[str, Any]] = [_foreign_key_enforcement(connection, use_pg=backend_pg)]
        skipped = 0
        for relationship in relationships:
            if len(checks) >= max(1, int(max_checks)):
                break
            check = _run_fk_check(
                connection, relationship, use_pg=backend_pg,
                tenant_id=tenant_id, sample_limit=max(1, int(sample_limit)),
            )
            checks.append(check)
            if check.get("status") == "NOT_APPLICABLE":
                skipped += 1
            if len(checks) >= max(1, int(max_checks)):
                break
            scope_check = _run_tenant_scope_check(
                connection, relationship, use_pg=backend_pg, tenant_id=tenant_id,
            )
            if scope_check is not None:
                checks.append(scope_check)
        truncated = len(checks) < len(relationships) + 1
        failures = sum(1 for check in checks if check.get("status") in {"FAIL", "ERROR"})
        warnings = sum(1 for check in checks if check.get("status") == "WARN")
        status = "FAIL" if failures else ("WARN" if warnings else "PASS")
        return {
            "scope": "database_consistency",
            "status": status,
            "checked_at": started,
            "backend": "postgresql" if backend_pg else "sqlite",
            "tenant_id": str(tenant_id) if tenant_id is not None else None,
            "relationship_count": len(relationships),
            "check_count": len(checks),
            "failure_count": failures,
            "warning_count": warnings,
            "not_applicable_count": skipped,
            "truncated": truncated,
            "read_only": True,
            "checks": checks,
            "remediation": (
                "Investigate orphan fingerprints and repair through an approved migration or reconciliation action; "
                "this patrol never deletes or rewrites data."
            ) if failures else None,
        }
    finally:
        if own_conn:
            connection.close()


def run_scheduled_consistency_patrol() -> dict[str, Any]:
    """Scheduler entrypoint; failures are logged without hiding the report."""
    try:
        report = run_consistency_patrol()
        logger.info(
            "[DB consistency] status=%s checks=%s failures=%s warnings=%s",
            report["status"], report["check_count"], report["failure_count"], report["warning_count"],
        )
        return report
    except Exception as exc:
        logger.error("[DB consistency] patrol failed: %s", type(exc).__name__, exc_info=True)
        return {
            "scope": "database_consistency", "status": "ERROR", "read_only": True,
            "error_class": type(exc).__name__, "checks": [],
        }


__all__ = [
    "discover_foreign_keys", "run_consistency_patrol", "run_scheduled_consistency_patrol",
]
