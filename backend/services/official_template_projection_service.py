"""Project reviewed switch templates into the searchable knowledge corpus.

The configuration-template center and the RAG document store are deliberately
separate bounded contexts.  A reviewed template is useful in both places, but
it must carry the same vendor/platform/version/source metadata when it is
projected into ``ai_document``.  This service provides the idempotent bridge;
it never promotes tenant-authored or unreviewed templates.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ai.services.knowledge_service import knowledge_service
from database import _USE_PG, get_db_connection
from services.official_product_catalog_service import model_aliases, vendor_models


TARGET_VENDORS = ("Huawei", "H3C", "Cisco", "Ruijie")

_FEATURES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("vxlan", ("vxlan", "evpn"), "overlay"),
    ("ospf", ("ospf",), "routing"),
    ("bgp", ("bgp",), "routing"),
    ("static_route", ("static route", "static-route", "static routing", "静态路由", "ip route-static"), "routing"),
    ("vrrp", ("vrrp",), "reliability"),
    ("lacp", ("lacp", "eth-trunk", "bridge-aggregation", "port-channel"), "switching"),
    ("lldp", ("lldp", "link layer discovery", "链路层发现"), "switching"),
    ("stp", ("stp", "mstp", "rstp", "spanning-tree"), "switching"),
    ("hsrp", ("hsrp", "hot standby router protocol"), "reliability"),
    ("access_port", ("access-port", "access port", "接入口"), "switching"),
    ("port_security", ("port-security", "port security", "端口安全"), "security"),
    ("trunk", ("trunk",), "switching"),
    ("vlan", ("vlan", "vlanif", "svi"), "switching"),
    ("ntp", ("ntp",), "management"),
    ("loopback", ("loopback",), "routing"),
    ("snmp", ("snmp",), "management"),
    ("ssh", ("ssh", "stelnet", "secure shell", "安全登录"), "management"),
    ("acl", ("acl", "访问控制列表"), "security"),
    ("qos", ("qos", "quality of service", "traffic policy", "traffic-policy", "服务质量"), "management"),
    ("aaa", ("aaa", "authentication", "authorization", "accounting", "认证", "授权"), "security"),
    ("mlag", ("mlag", "m-lag", "s-mlag", "smlag", "vpc", "多机箱", "跨设备链路聚合"), "reliability"),
)

# These six rows are the reviewed identities used by the current Ruijie
# anchors.  Identity-based classification is deliberately explicit here:
# command bodies contain both configuration and verification commands, and a
# broad substring scan would otherwise classify VLAN/access or show-route
# entries under the wrong feature.
_EXPLICIT_FEATURES: dict[str, tuple[str, str]] = {
    "official-huawei-ce12800-vxlan-evpn-basic": ("vxlan", "overlay"),
    "official-huawei-port-security-basic": ("port_security", "security"),
    "official-huawei-cpu-memory-diagnostic": ("system_monitoring", "operations"),
    "official-huawei-ospf-bfd-basic": ("bfd", "routing"),
    "official-huawei-super-password-basic": ("pam", "security"),
    "official-huawei-ce6885-interface-status-diagnostic": ("interface", "operations"),
    # Interface status/switchport evidence belongs to the operations facet,
    # matching the parser's interface intent.  The command body still carries
    # the access/trunk configuration details in its explicit feature scope.
    "official-cisco-interface-switchport-basic": ("interface", "operations"),
    "official-cisco-arp-mac-diagnostic": ("arp", "routing"),
    "official-cisco-aaa-authentication-basic": ("pam", "security"),
    "official-h3c-interface-brief-diagnostic": ("interface", "operations"),
    "official-h3c-arp-mac-diagnostic": ("arp", "routing"),
    "ruijie-rgos-vlan-access": ("vlan", "switching"),
    "ruijie-rgos-aggregateport": ("lacp", "switching"),
    "ruijie-rgos-show-route": ("static_route", "routing"),
    "ruijie-rgos-ospf": ("ospf", "routing"),
    "ruijie-rgos-show-lldp": ("lldp", "switching"),
    "ruijie-rgos-acl": ("acl", "security"),
}

_CLI_OUTPUT_TEMPLATES = {
    "official-huawei-cpu-memory-diagnostic",
    "official-cisco-arp-mac-diagnostic",
    "official-h3c-interface-brief-diagnostic",
    "official-h3c-arp-mac-diagnostic",
    "ruijie-rgos-show-route",
    "ruijie-rgos-show-lldp",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _projection_document_id(row: dict[str, Any]) -> str:
    """Return the semantic ID exposed to retrieval/evaluation consumers.

    The existing Huawei/H3C/Cisco template IDs historically carry the
    ``official-template-`` namespace.  Ruijie Gold IDs were established from
    the official-source corpus before template projection and intentionally
    use the bare template ID.  Preserve both contracts explicitly instead of
    making the evaluator guess how a source was ingested.
    """

    template_id = _text(row.get("id"))
    vendor = _text(row.get("vendor"))
    return template_id if vendor == "Ruijie" else f"official-template-{template_id}"


def _render(content: str) -> str:
    """Render safe defaults while preserving secret inputs as explicit hints."""

    try:
        from jinja2 import Environment, Undefined

        rendered = Environment(undefined=Undefined, autoescape=False).from_string(content).render(
            snmp_auth_key="<from-secret-vault:snmp_auth_key>",
            snmp_priv_key="<from-secret-vault:snmp_priv_key>",
        )
    except Exception:
        rendered = content
    # Secret-bearing variables must never become a blank command argument.
    for variable in ("snmp_auth_key", "snmp_priv_key"):
        rendered = re.sub(rf"\{{\{{\s*{variable}\s*\}}\}}", f"<from-secret-vault:{variable}>", rendered)
    return rendered.strip()


def _feature(row: dict[str, Any]) -> tuple[str, str]:
    # Prefer the reviewed template identity and description over the command
    # body.  A legitimate access-port template often contains a rollback
    # command such as ``no spanning-tree portfast``; scanning the whole body
    # first incorrectly classified that template as STP and made the access
    # Gold anchor fail the feature hard filter.
    template_id = _text(row.get("id")).lower()
    if template_id in _EXPLICIT_FEATURES:
        return _EXPLICIT_FEATURES[template_id]
    identity = " ".join(_text(row.get(key)) for key in ("id", "name", "category", "description")).lower()
    for feature, aliases, domain in _FEATURES:
        if any(alias in identity for alias in aliases):
            return feature, domain
    content = _text(row.get("content")).lower()
    for feature, aliases, domain in _FEATURES:
        if any(alias in content for alias in aliases):
            return feature, domain
    return "", _text(row.get("category")) or "general"


def _product_scope(row: dict[str, Any]) -> tuple[str, str, str]:
    template_id = _text(row.get("id")).lower()
    vendor = _text(row.get("vendor"))
    platform = _text(row.get("platform_family"))
    if vendor == "Huawei":
        if "ce6885" in template_id:
            return "CloudEngine 6800", "CE6885-48YS8CQ", "VRP8"
        if "ce12800" in template_id:
            return "CloudEngine 12800", "CE12800", "VRP8"
        if "ce6800" in template_id:
            return "CloudEngine 6800", "CE6800", "VRP8"
        return "S5700/S6700", "S5700/S6700", "VRP"
    if vendor == "H3C":
        if "s6800" in template_id or "s9825" in template_id:
            return "Comware 7 Data Center Switches", "S6800/S9825/S9855", "Comware 7"
        return "Comware 7 Switches", "S5130/S6520X/S6800", "Comware 7"
    if vendor == "Cisco":
        if "nexus" in template_id:
            return "Nexus 3000/9000", "Nexus 3000/9000", "NX-OS"
        return "Catalyst 9300", "Catalyst 9300", "IOS-XE"
    if vendor == "Ruijie":
        return "RGOS switches", "RG-S/RGOS", "RGOS"
    return platform or vendor, platform, ""


def _catalog_applicability(row: dict[str, Any], vendor: str) -> tuple[list[str], list[str], list[str], str]:
    """Return reviewed model aliases that a template may serve.

    Generic campus templates (VLAN, SSH, ACL, NTP, etc.) are valid for both
    campus and data-center models of the same CLI family.  The three overlay
    templates are intentionally narrowed to their data-center families so a
    Nexus/CE/S6800 VXLAN answer cannot be selected for an unrelated access
    switch.  A bare model token and its official ``CloudEngine`` spelling are
    aliases of one catalog row, never extra unverified SKUs.
    """

    template_id = _text(row.get("id")).lower()
    scope: str | None = None
    if vendor == "Huawei" and "ce6800" in template_id:
        scope = "datacenter"
    elif vendor == "Huawei" and "ce12800" in template_id:
        scope = "datacenter"
    elif vendor == "H3C" and any(token in template_id for token in ("s6800", "s9825")):
        scope = "datacenter"
    elif vendor == "Cisco" and "nexus" in template_id:
        scope = "datacenter"
    rows = vendor_models(vendor, scope=scope)
    if vendor == "Ruijie":
        # RG-S6220 is the concrete family covered by the official Ruijie
        # document-center evidence used for these anchors.  Keep the generic
        # RG-S/RGOS aliases as applicability values, not as additional SKUs.
        return (
            ["RG-S6220", "RG-S", "rg-s6220", "rg-s"],
            ["RG-S/RGOS", "RG-S", "RG-S6220", "RGOS"],
            ["ruijie_rgos"],
            "datacenter",
        )
    platform_rows = rows
    if vendor == "Cisco":
        # Catalyst IOS-XE and Nexus NX-OS are different CLI families.  A
        # generic Cisco campus template must not become eligible for a Nexus
        # query merely because the model catalog contains both vendors' model
        # records.
        platform_rows = vendor_models(vendor, scope="datacenter" if scope == "datacenter" else "campus")
    models: list[str] = []
    series: list[str] = []
    platforms: list[str] = []
    for item in rows:
        models.extend(model_aliases(item))
        if item.get("series"):
            series.append(str(item["series"]))
    for item in platform_rows:
        if item.get("platform"):
            platforms.append(str(item["platform"]))
    # Preserve the template's broad CLI family as an explicit compatibility
    # value.  For example, Huawei VRP V200/V600 model rows can use the same
    # reviewed VRP command skeleton even though their registry platform is
    # more specific.
    template_platform = _text(row.get("platform_family"))
    if template_platform:
        platforms.append(template_platform)
    template_series = _text(_product_scope(row)[1])
    if template_series:
        # Keep the human-readable composite scope (for example
        # ``Nexus 3000/9000``) alongside its individual catalog series.  This
        # lets both a family query and a concrete Nexus 9000 model pass the
        # same hard gate.
        series.append(template_series)
    if vendor == "Huawei" and scope is None:
        # Legacy official Huawei registry rows include these V200/V600
        # family labels even when the newer catalog records a concrete
        # CloudEngine SKU.  They are compatibility series, not additional
        # unverified models, and keep the long-standing S5700/S5735 queries
        # on the same reviewed VRP template path.
        series.extend(("S5700", "S6700", "S5735-L-V2"))
    return (
        list(dict.fromkeys(models)),
        list(dict.fromkeys(series)),
        list(dict.fromkeys(platforms)),
        scope or "all",
    )


def _metadata(row: dict[str, Any], *, document_id: str) -> dict[str, Any]:
    vendor = _text(row.get("vendor"))
    product_family, product_series, os_family = _product_scope(row)
    feature, feature_domain = _feature(row)
    version = _text(row.get("software_version"))
    source = _text(row.get("official_reference"))
    product_model = product_series
    applicable_models, applicable_series, applicable_platforms, model_scope = _catalog_applicability(row, vendor)
    if vendor == "Cisco" and product_series == "Catalyst 9300":
        # The intent parser keeps ``C9300`` as a concrete model token while
        # the catalog uses the human-readable series name.  Store both forms
        # so either query style satisfies the product hard gate.
        product_model = "C9300"
        applicable_models = list(dict.fromkeys(["C9300", "Catalyst 9300", *applicable_models]))
    return {
        "schema_version": "1.0",
        "document_id": document_id,
        "title": _text(row.get("name")),
        "vendor": vendor,
        "product_type": "network_switch",
        "document_category": "cli_output" if _text(row.get("id")).lower() in _CLI_OUTPUT_TEMPLATES else "configuration",
        "source_type": "official_template",
        "official_only": True,
        # ``templates.status`` is the catalog lifecycle state.  RAG parent
        # rows use ``active`` as their retrieval state; keeping those two
        # concepts separate is what makes a published catalog entry searchable.
        "status": "active",
        "product_family": product_family,
        "product_series": product_series,
        "product_model": product_model,
        "applicable_product_models": applicable_models,
        "applicable_product_series": applicable_series,
        "applicable_cli_platforms": applicable_platforms,
        "model_scope": model_scope,
        "os_family": os_family,
        "software_train": version,
        "software_release": version,
        "cli_platform": _text(row.get("platform_family")),
        "feature_domain": feature_domain,
        "feature": feature,
        "risk_level": _text(row.get("risk_level")) or "low",
        "verification_level": "official",
        "rag_priority": 100,
        "official_reference": source,
        "canonical_url": source,
        "source_url": source,
        "template_id": _text(row.get("id")),
        "source_trust_level": "official",
        "document_status": _text(row.get("status")) or "published",
        "description": _text(row.get("description")),
        "rollback": _text(row.get("rollback")),
    }


def _row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = ("id", "name", "type", "category", "vendor", "content", "rollback", "description", "platform_family", "software_version", "official_reference", "validation_status", "source_type", "risk_level", "status", "is_official", "current_version", "updated_at")
    return {key: row[index] for index, key in enumerate(columns) if index < len(row)}


def _existing_template_ids(tenant_id: str) -> set[str]:
    existing: set[str] = set()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT metadata_json FROM ai_document WHERE tenant_id = ? AND knowledge_source_type = 'official_template'",
            (tenant_id,),
        ).fetchall()
    for row in rows:
        raw = row[0] if not hasattr(row, "keys") else row["metadata_json"]
        try:
            metadata = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        template_id = _text(metadata.get("template_id")) if isinstance(metadata, dict) else ""
        if template_id:
            existing.add(template_id)
    return existing


def _json_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _refresh_existing_template_projection(tenant_id: str) -> int:
    """Reconcile scalar/indexed metadata for already projected templates.

    The first projection release ran before nullable Front Matter defaults
    were fixed, so those rows can have ``cli_platform``/feature labels that
    are stale even though the command content is correct.  Refreshing the
    server-owned metadata is cheap, does not recompute embeddings, and keeps
    retrieval filters aligned with the catalog after every startup.
    """

    with get_db_connection() as conn:
        template_rows = conn.execute(
            """
            SELECT id, name, type, category, vendor, content, rollback,
                   description, platform_family, software_version,
                   official_reference, validation_status, source_type,
                   risk_level, status, is_official, current_version, updated_at
            FROM templates
            WHERE COALESCE(is_official, 0) = 1
              AND LOWER(COALESCE(status, 'published')) = 'published'
              AND LOWER(COALESCE(vendor, '')) IN ('huawei', 'h3c', 'cisco', 'ruijie')
            """
        ).fetchall()
        templates = {_text((_row_dict(row)).get("id")): _row_dict(row) for row in template_rows}
        docs = conn.execute(
            """
            SELECT id, metadata_json FROM ai_document
            WHERE tenant_id = ? AND knowledge_source_type = 'official_template'
            """,
            (tenant_id,),
        ).fetchall()

        refreshed = 0
        for raw_doc in docs:
            doc_id = raw_doc[0] if not hasattr(raw_doc, "keys") else raw_doc["id"]
            raw_metadata = raw_doc[1] if not hasattr(raw_doc, "keys") else raw_doc["metadata_json"]
            old_metadata = _json_mapping(raw_metadata)
            template_id = _text(old_metadata.get("template_id"))
            row = templates.get(template_id)
            if not row:
                continue
            metadata = _metadata(row, document_id=_projection_document_id(row))
            metadata_json = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), default=str)
            json_expression = "CAST(? AS JSONB)" if _USE_PG else "?"
            now = metadata.get("updated_at") or row.get("updated_at") or ""
            conn.execute(
                f"""
                UPDATE ai_document
                SET document_id = ?, name = ?, source = ?, platform = ?, version = ?,
                    status = 'active', source_trust_level = 'official', knowledge_source_type = 'official_template',
                    metadata_json = {json_expression}, document_category = ?,
                    product_family = ?, product_series = ?, product_model = ?, os_family = ?,
                    software_train = ?, software_release = ?, cli_platform = ?,
                    feature_domain = ?, feature = ?, risk_level = ?, verification_level = ?,
                    rag_priority = ?, updated_at = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    metadata.get("document_id"), _text(row.get("name")) or template_id,
                    _text(row.get("official_reference")) or None,
                    _text(row.get("platform_family")) or None,
                    _text(row.get("software_version")) or None,
                    metadata_json,
                    metadata.get("document_category"), metadata.get("product_family"),
                    metadata.get("product_series"), metadata.get("product_model"),
                    metadata.get("os_family"), metadata.get("software_train"),
                    metadata.get("software_release"), metadata.get("cli_platform"),
                    metadata.get("feature_domain"), metadata.get("feature"),
                    metadata.get("risk_level"), metadata.get("verification_level"),
                    metadata.get("rag_priority"), now, doc_id, tenant_id,
                ),
            )
            conn.execute(
                f"""
                UPDATE ai_document_chunk
                SET metadata_json = {json_expression}, document_category = ?,
                    vendor = ?, product_series = ?, product_model = ?,
                    software_train = ?, software_release = ?, cli_platform = ?,
                    feature_domain = ?, feature = ?, risk_level = ?, verification_level = ?,
                    rag_priority = ?
                WHERE document_id = ?
                """,
                (
                    metadata_json, metadata.get("document_category"), metadata.get("vendor"),
                    metadata.get("product_series"), metadata.get("product_model"),
                    metadata.get("software_train"),
                    metadata.get("software_release"), metadata.get("cli_platform"),
                    metadata.get("feature_domain"), metadata.get("feature"),
                    metadata.get("risk_level"), metadata.get("verification_level"),
                    metadata.get("rag_priority"), doc_id,
                ),
            )
            refreshed += 1
        if refreshed:
            conn.commit()
        return refreshed


def project_official_templates_to_knowledge(
    *,
    tenant_id: str = "tenant-default",
    created_by: str = "system",
    vendors: Iterable[str] = TARGET_VENDORS,
    limit: int = 100,
) -> dict[str, Any]:
    """Publish reviewed system templates into the local RAG projection.

    The operation is safe to repeat. Existing template projections are left
    untouched so an operator can review a changed template before replacing a
    published knowledge document.
    """

    vendor_set = {vendor.strip().lower() for vendor in vendors if _text(vendor)}
    bounded_limit = max(1, min(200, int(limit)))
    knowledge_base = knowledge_service.get_or_create_default_knowledge_base(
        tenant_id=tenant_id,
        created_by=created_by,
    )
    existing = _existing_template_ids(tenant_id)
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, type, category, vendor, content, rollback,
                   description, platform_family, software_version,
                   official_reference, validation_status, source_type,
                   risk_level, status, is_official, current_version, updated_at
            FROM templates
            WHERE COALESCE(is_official, 0) = 1
              AND LOWER(COALESCE(status, 'published')) = 'published'
            ORDER BY vendor, id
            LIMIT ?
            """,
            (bounded_limit,),
        ).fetchall()

    published: list[dict[str, Any]] = []
    skipped: list[str] = []
    for raw_row in rows:
        row = _row_dict(raw_row)
        vendor = _text(row.get("vendor"))
        template_id = _text(row.get("id"))
        if vendor.lower() not in vendor_set:
            continue
        if not template_id or template_id in existing:
            skipped.append(template_id)
            continue
        content = _render(_text(row.get("content")))
        if not content:
            skipped.append(template_id)
            continue
        document_id = _projection_document_id(row)
        metadata = _metadata(row, document_id=document_id)
        result = knowledge_service.add_document_and_chunk(
            knowledge_base_id=str(knowledge_base["id"]),
            name=_text(row.get("name")) or template_id,
            content=content,
            vendor=vendor,
            platform=_text(row.get("platform_family")) or None,
            knowledge_source_type="official_template",
            chunk_size=800,
            tenant_id=tenant_id,
            source_trust_level="official",
            metadata=metadata,
            source=_text(row.get("official_reference")) or None,
        )
        published.append({
            "template_id": template_id,
            "document_id": result.get("document_id"),
            "vendor": vendor,
            "feature": metadata.get("feature"),
            "source": metadata.get("official_reference"),
            "chunk_count": int(result.get("chunk_count") or 0),
        })
        existing.add(template_id)

    refreshed_count = _refresh_existing_template_projection(tenant_id)
    return {
        "tenant_id": tenant_id,
        "knowledge_base_id": str(knowledge_base["id"]),
        "published": published,
        "published_count": len(published),
        "skipped_count": len(skipped),
        "skipped_template_ids": skipped,
        "refreshed_count": refreshed_count,
    }


__all__ = ["TARGET_VENDORS", "project_official_templates_to_knowledge"]
