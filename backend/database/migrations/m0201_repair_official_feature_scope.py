"""Clear legacy feature tags inferred from broad official document bodies.

The first official-URL publisher used the beginning of the normalized body to
infer a document-level feature.  A vendor command reference can mention many
features, so that inference made an unrelated section eligible for a narrow
query (for example, a Smart Licensing section returned for VLAN).  This
migration removes only the unreviewed, document-level binding when the source
identity does not support it.  The source remains searchable for unscoped or
exact-command queries.
"""

from __future__ import annotations

import re
from typing import Any

from ai.services.knowledge_metadata import canonical_feature

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 201
NAME = "repair_official_feature_scope"

_OFFICIAL_SOURCE_TYPES = {
    "official_url",
    "official_local",
    "official_vendor",
    "official_product",
}
_BROAD_SOURCE_KINDS = {"command_reference", "configuration_guide"}

# These expressions are deliberately restricted to source identity fields.
# Content-level evidence belongs in retrieval, where it can be evaluated for
# the individual chunk rather than promoted to the whole document.
_FEATURE_IDENTITY_PATTERNS = {
    "vlan": (r"(?<![a-z0-9])vlan(?![a-z0-9])", r"虚拟局域网"),
    "ospf": (r"(?<![a-z0-9])ospf(?![a-z0-9])", r"开放式最短路径优先"),
    "bgp": (r"(?<![a-z0-9])bgp(?![a-z0-9])", r"边界网关协议"),
    "isis": (r"(?<![a-z0-9])isis(?![a-z0-9])",),
    "arp": (r"(?<![a-z0-9])arp(?![a-z0-9])", r"地址解析"),
    "stp": (r"(?<![a-z0-9])stp(?![a-z0-9])", r"spanning[- ]tree", r"生成树"),
    "mstp": (r"(?<![a-z0-9])mstp(?![a-z0-9])",),
    "access_port": (r"access[- ]port", r"接入口", r"接入端口"),
    "trunk": (r"(?<![a-z0-9])trunk(?![a-z0-9])", r"中继端口", r"trunk端口"),
    "lacp": (
        r"(?<![a-z0-9])lacp(?![a-z0-9])",
        r"eth[- ]trunk",
        r"etherchannel",
        r"bridge[- ]aggregation",
        r"链路聚合",
    ),
    "vrrp": (r"(?<![a-z0-9])vrrp(?![a-z0-9])", r"虚拟路由器冗余"),
    "hsrp": (r"(?<![a-z0-9])hsrp(?![a-z0-9])", r"hot standby router protocol"),
    "vxlan": (r"(?<![a-z0-9])vxlan(?![a-z0-9])",),
    "evpn": (r"(?<![a-z0-9])evpn(?![a-z0-9])",),
    "snmp": (r"(?<![a-z0-9])snmp(?:v3)?(?![a-z0-9])", r"简单网络管理协议"),
    "ntp": (r"(?<![a-z0-9])ntp(?![a-z0-9])", r"网络时间协议"),
    "ssh": (r"(?<![a-z0-9])(?:ssh|stelnet)(?![a-z0-9])", r"secure shell", r"安全登录"),
    "acl": (r"(?<![a-z0-9])acl(?![a-z0-9])", r"access[- ]control list", r"访问控制列表"),
    "loopback": (r"(?<![a-z0-9])loopback(?![a-z0-9])", r"环回接口", r"环回口"),
    "static_route": (r"static[- ]route", r"ip route-static", r"静态路由"),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _identity_supports_feature(feature: Any, identity: str) -> bool:
    canonical = canonical_feature(feature)
    value = _text(identity)
    if not canonical or not value:
        return False
    patterns = _FEATURE_IDENTITY_PATTERNS.get(canonical)
    if patterns:
        return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)
    escaped = re.escape(canonical.replace("_", " "))
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", value, flags=re.IGNORECASE))


def _source_is_broad(row: dict[str, Any], metadata: dict[str, Any]) -> bool:
    source_kind = _text(row.get("source_kind") or metadata.get("source_kind")).lower()
    source_type = _text(
        row.get("knowledge_source_type")
        or metadata.get("source_type")
        or metadata.get("knowledge_source_type")
    ).lower()
    return source_kind in _BROAD_SOURCE_KINDS or source_type in _OFFICIAL_SOURCE_TYPES


def _repair_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(metadata)
    repaired.pop("feature", None)
    repaired["feature_domain"] = "general"
    repaired["feature_source"] = "unclassified"
    repaired["feature_repair"] = "legacy_body_inference_cleared"
    return repaired


def _update_chunk_projection(
    cursor,
    *,
    document_id: str,
    use_pg: bool,
) -> None:
    if not _provenance._table_exists(cursor, "ai_document_chunk", use_pg):
        return
    chunk_columns = _provenance._columns(cursor, "ai_document_chunk", use_pg)
    if not {"id", "document_id", "metadata_json"} <= chunk_columns:
        return

    selected = ["id", "metadata_json"]
    for name in ("feature", "feature_domain"):
        if name in chunk_columns:
            selected.append(name)
    lock_clause = " FOR UPDATE" if use_pg else ""
    cursor.execute(
        f"SELECT {', '.join(selected)} FROM ai_document_chunk "
        f"WHERE document_id = ?{lock_clause}",
        (document_id,),
    )
    for row in cursor.fetchall():
        raw_metadata = row[1]
        metadata = _provenance._json_load(raw_metadata, {})
        if not isinstance(metadata, dict):
            metadata = {}
        repaired = _repair_metadata(metadata)

        assignments = ["metadata_json = ?"]
        values: list[Any] = [_provenance._json_value(repaired, use_pg)]
        if "feature" in chunk_columns:
            assignments.append("feature = NULL")
        if "feature_domain" in chunk_columns:
            assignments.append("feature_domain = ?")
            values.append("general")
        values.append(row[0])
        cursor.execute(
            f"UPDATE ai_document_chunk SET {', '.join(assignments)} WHERE id = ?",
            values,
        )


def upgrade(cursor, use_pg: bool) -> None:
    """Repair inferred feature scope while preserving source content."""

    if not _provenance._table_exists(cursor, "ai_document", use_pg):
        return
    columns = _provenance._columns(cursor, "ai_document", use_pg)
    required = {"id", "name", "source", "metadata_json", "feature", "feature_domain"}
    if not required <= columns:
        return

    selected = ["id", "name", "source", "metadata_json", "feature", "feature_domain"]
    for name in ("source_kind", "knowledge_source_type"):
        if name in columns:
            selected.append(name)
    lock_clause = " FOR UPDATE" if use_pg else ""
    cursor.execute(f"SELECT {', '.join(selected)} FROM ai_document{lock_clause}")
    for raw_row in cursor.fetchall():
        row = dict(zip(selected, raw_row))
        metadata = _provenance._json_load(row.get("metadata_json"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        feature = _text(row.get("feature") or metadata.get("feature"))
        if not feature or not _source_is_broad(row, metadata):
            continue
        # A reviewer-supplied feature binding is intentionally authoritative.
        if _text(metadata.get("feature_source")).lower() == "explicit":
            continue

        identity = " ".join(
            _text(value)
            for value in (
                row.get("name"),
                row.get("source"),
                metadata.get("title"),
                metadata.get("description"),
                metadata.get("canonical_url"),
                metadata.get("source_url"),
                metadata.get("official_reference"),
            )
        )
        if _identity_supports_feature(feature, identity):
            continue

        repaired = _repair_metadata(metadata)
        assignments = ["metadata_json = ?", "feature = NULL", "feature_domain = ?"]
        values: list[Any] = [_provenance._json_value(repaired, use_pg), "general"]
        values.append(row["id"])
        cursor.execute(
            f"UPDATE ai_document SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        _update_chunk_projection(
            cursor,
            document_id=_text(row["id"]),
            use_pg=use_pg,
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Do not restore unsafe inferred scope during rollback."""

    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
