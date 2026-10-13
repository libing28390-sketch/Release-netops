"""Safely add the IF-MIB interface last-change metric."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog
from database.migrations.m0233_vendor_snmp_oid_catalog import _seed_metric_definitions


VERSION = 253
NAME = "expand_ifmib_last_change"
NEW_METRIC_NAMES = {
    "ifLastChange",
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    item = next(
        (entry for entry in iter_builtin_catalog() if entry.get("module_key") == "generic_ifmib_interface"),
        None,
    )
    if not item:
        return
    variant = item["variant"]
    catalog_config = variant.get("oid_config") or {}
    row = cursor.execute(
        """
        SELECT oid_config_json
          FROM snmp_module_variants
         WHERE id = ? AND module_id = ?
        """,
        (variant["id"], item["id"]),
    ).fetchone()
    if row:
        raw = row[0] if not hasattr(row, "get") else row.get("oid_config_json")
        try:
            existing = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            existing = None

        # A blank built-in row can be seeded completely. For a non-empty row,
        # keep every operator edit and append only the metrics introduced by
        # this migration. In particular, never replace an existing metric
        # with the same name but a customized OID.
        merged = None
        if (isinstance(existing, dict) and not existing) or existing == []:
            merged = dict(catalog_config)
        elif isinstance(existing, dict):
            configured_metrics = existing.get("metrics", [])
            if isinstance(configured_metrics, list):
                present = {
                    str(metric.get("name") or "")
                    for metric in configured_metrics
                    if isinstance(metric, dict)
                }
                additions = [
                    metric
                    for metric in (catalog_config.get("metrics") or [])
                    if isinstance(metric, dict)
                    and str(metric.get("name") or "") in NEW_METRIC_NAMES
                    and str(metric.get("name") or "") not in present
                ]
                if additions:
                    merged = dict(existing)
                    merged["metrics"] = [*configured_metrics, *additions]

        if merged is not None:
            oid_json = _json(merged)
            mib_json = _json(merged.get("mib_sources") or [])
            cursor.execute(
                """
                UPDATE snmp_module_variants
                   SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?, updated_at = ?
                 WHERE id = ? AND module_id = ?
                """,
                (
                    oid_json,
                    hashlib.sha256(oid_json.encode("utf-8")).hexdigest(),
                    hashlib.sha256(mib_json.encode("utf-8")).hexdigest(),
                    now,
                    variant["id"],
                    item["id"],
                ),
            )
    _seed_metric_definitions(cursor, [item], now)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Catalog refreshes are additive. Keeping the additional OID definition
    # prevents an older runtime from generating an incomplete module artifact.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
