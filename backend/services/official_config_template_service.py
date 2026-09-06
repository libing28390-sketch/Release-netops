"""Deterministic fallback over reviewed official configuration templates."""

from __future__ import annotations

import re
from typing import Any

try:
    from jinja2 import Undefined as _JinjaUndefined
except Exception:  # pragma: no cover - exercised only without optional Jinja
    class _JinjaUndefined:  # type: ignore[no-redef]
        pass

from ai.services.knowledge_metadata import canonical_vendor
from database import get_db_connection


_FEATURE_ALIASES = {
    "ospf": {"ospf", "开放式最短路径优先", "开放最短路径优先"},
    "bgp": {"bgp", "边界网关协议"},
    "vlan": {"vlan", "虚拟局域网"},
    "stp": {"stp", "生成树", "mstp", "rstp"},
    "vrrp": {"vrrp", "网关冗余"},
    "vxlan": {"vxlan", "evpn"},
    "lacp": {"lacp", "链路聚合", "eth-trunk", "bridge-aggregation"},
    "access_port": {
        "access port", "access-port", "vlan + access", "vlan+access", "接入口", "接入端口",
    },
    "port_security": {"port security", "port-security", "端口安全"},
    "trunk": {"trunk", "中继端口", "trunk端口"},
    "loopback": {"loopback", "环回接口", "环回口"},
    "ntp": {"ntp", "网络时间协议"},
    "snmp": {"snmp", "snmpv3", "简单网络管理协议"},
    "static_route": {"static route", "static-route", "static routing", "静态路由", "ip route-static"},
    "ssh": {"ssh", "stelnet", "secure shell", "安全登录"},
    "acl": {"acl", "访问控制列表"},
    "qos": {"qos", "quality of service", "服务质量", "traffic policy", "traffic-policy"},
    "aaa": {"aaa", "authentication", "authorization", "accounting", "认证", "授权"},
    "mlag": {"mlag", "m-lag", "s-mlag", "smlag", "multi-chassis", "vpc", "多机箱", "跨设备链路聚合"},
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _feature(request: Any) -> str:
    explicit = _text(getattr(request, "feature", "")).lower()
    for name, aliases in _FEATURE_ALIASES.items():
        if explicit == name or explicit in aliases:
            return name
    haystack = " ".join(
        _text(getattr(request, field, ""))
        for field in ("query", "feature", "subfeature", "document_category")
    ).lower()
    if re.search(r"(?<![a-z0-9])vlan\s*\+\s*access(?![a-z0-9])", haystack):
        return "access_port"
    for name, aliases in _FEATURE_ALIASES.items():
        if any(alias in haystack for alias in aliases):
            return name
    return ""


def _feature_domain(feature: str) -> str:
    return {
        "ospf": "routing", "bgp": "routing", "static_route": "routing", "vrrp": "reliability",
        "vlan": "switching", "stp": "switching", "lacp": "switching",
        "access_port": "switching", "trunk": "switching", "port_security": "security",
        "loopback": "routing", "ntp": "management", "snmp": "management", "ssh": "management", "acl": "security",
        "vxlan": "overlay", "qos": "management", "aaa": "security", "mlag": "reliability",
    }.get(feature, "")


def _product_tokens(request: Any) -> list[str]:
    values = [
        _text(getattr(request, "product_model", "")),
        _text(getattr(request, "product_series", "")),
        _text(getattr(request, "product_family", "")),
    ]
    tokens: list[str] = []
    for value in values:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9/-]{2,}|\d{4,}", value):
            lowered = token.lower()
            if lowered not in tokens:
                tokens.append(lowered)
    return tokens


def _is_product_compatible(request: Any, haystack: str) -> bool:
    tokens = _product_tokens(request)
    if not tokens:
        return True
    normalized = haystack.lower().replace(" ", "")
    # Concrete product identifiers are hard gates.  A generic “交换机” query
    # may use the family templates, but S5735 must not receive S5700 content.
    return any(token.replace(" ", "") in normalized for token in tokens)


class _OperatorPlaceholderUndefined(_JinjaUndefined):
    """Small Jinja Undefined implementation for safe operator-facing output.

    The template catalogue is intentionally parameterised.  Rendering a
    template with ``StrictUndefined`` made one missing secret/parameter abort
    the whole render and returned the raw ``{{ variable }}`` source to the
    browser.  That is an implementation detail, not a usable network answer.
    Keep Jinja's ``default(...)`` behaviour, while rendering an unresolved
    value as a visible, safe placeholder instead of leaking template syntax or
    inventing a credential.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._undefined_name = str(kwargs.get("name") or "parameter")

    def __str__(self) -> str:
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", self._undefined_name).strip("._-") or "parameter"
        lowered = name.lower()
        if any(token in lowered for token in ("password", "secret", "auth_key", "priv_key", "token")):
            return f"<from-secret-vault:{name}>"
        return f"<{name.upper()}>"

    def __html__(self) -> str:
        return str(self)

    def __bool__(self) -> bool:
        return False


def _render_template(content: str) -> str:
    """Render reviewed templates into safe, copyable operator output.

    Defaults remain useful example values.  Values without defaults become
    ``<PARAMETER>`` placeholders; credential-like values always remain
    ``<from-secret-vault:...>`` markers.  A conservative regex fallback keeps
    the catalogue usable if the optional Jinja dependency is unavailable.
    """
    try:
        from jinja2 import Environment

        rendered = Environment(
            undefined=_OperatorPlaceholderUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        ).from_string(content).render(
            snmp_auth_key="<from-secret-vault:snmp_auth_key>",
            snmp_priv_key="<from-secret-vault:snmp_priv_key>",
            password_from_vault="<from-secret-vault:password>",
        )
        return rendered.strip()
    except Exception:
        # This path is only a dependency failure.  It still removes Jinja
        # delimiters rather than exposing internal template source verbatim.
        def replace(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            name = re.split(r"\s*\|", expression, maxsplit=1)[0].strip().strip("' \"")
            return f"<{name.upper() or 'PARAMETER'}>"

        return re.sub(r"{{\s*(.*?)\s*}}", replace, content).strip()


def search_official_templates(request: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """Return vendor/product/feature-compatible chunk-shaped evidence.

    This path is local-only and deliberately refuses a cross-vendor fallback.
    It is used only after exact document retrieval has no result.
    """

    vendor_raw = _text(getattr(request, "vendor", ""))
    if not vendor_raw or vendor_raw.lower() == "all":
        return []
    vendor = canonical_vendor(vendor_raw)
    feature = _feature(request)
    category = _text(getattr(request, "document_category", "")).lower()
    if category and category not in {"configuration", "command"}:
        return []
    requested_platform = _text(getattr(request, "cli_platform", "")).lower()
    try:
        bounded_limit = max(1, min(10, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = 5
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, type, category, vendor, content, rollback,
                       description, platform_family, software_version,
                       official_reference, validation_status, source_type,
                       risk_level, status, is_official, current_version,
                       updated_at
                FROM templates
                WHERE LOWER(COALESCE(vendor, '')) = LOWER(?)
                  AND (COALESCE(is_official, 0) = 1 OR LOWER(COALESCE(source_type, '')) = 'official')
                  AND LOWER(COALESCE(status, 'published')) NOT IN ('disabled', 'archived', 'deleted')
                ORDER BY COALESCE(quality_score, 0) DESC, id ASC
                """,
                (vendor,),
            ).fetchall()
    except Exception:
        # Older or partially upgraded test databases simply have no template
        # fallback; exact RAG retrieval remains the source of truth there.
        return []

    ranked: list[tuple[int, dict[str, Any]]] = []
    feature_domain = _feature_domain(feature)
    for row in rows:
        values = list(row)
        while len(values) < 18:
            values.append("")
        (
            template_id, name, _type, template_category, row_vendor, content,
            rollback, description, platform_family, software_version,
            official_reference, validation_status, source_type, risk_level,
            status, is_official, current_version, updated_at,
        ) = values[:18]
        searchable = " ".join(
            _text(value)
            for value in (name, description, platform_family, software_version, content, template_category)
        )
        if not _is_product_compatible(request, searchable):
            continue
        if requested_platform and requested_platform not in _text(platform_family).lower():
            continue
        feature_aliases = _FEATURE_ALIASES.get(feature, {feature})
        feature_hit = bool(
            feature
            and any(alias.casefold() in searchable.casefold() for alias in feature_aliases if _text(alias))
        )
        if feature and not feature_hit:
            continue
        score = 20
        if feature_hit:
            score += 50
        if feature_domain and feature_domain in _text(template_category).lower():
            score += 10
        if requested_platform and requested_platform == _text(platform_family).lower():
            score += 20
        rendered = _render_template(_text(content))
        if not rendered.strip():
            continue
        source_url = _text(official_reference)
        chunk_id = f"official-template:{template_id}"
        document_id = f"template:{template_id}"
        metadata = {
            "schema_version": "1.0",
            "document_id": document_id,
            "title": _text(name),
            "vendor": _text(row_vendor) or vendor,
            "product_type": "network_switch",
            "document_category": "configuration",
            "source_type": "official_template",
            "official_only": True,
            "status": _text(status) or "published",
            "product_family": _text(getattr(request, "product_family", "")),
            "product_series": _text(getattr(request, "product_series", "")),
            "product_model": _text(getattr(request, "product_model", "")),
            "cli_platform": _text(platform_family),
            "feature_domain": feature_domain or _text(template_category),
            "feature": feature,
            "software_release": _text(software_version),
            "software_train": _text(software_version),
            "official_reference": source_url,
            "canonical_url": source_url,
            "source_type": "official_template",
            "source_trust_level": "official",
            "validation_status": _text(validation_status),
            "risk_level": _text(risk_level) or "low",
        }
        ranked.append(
            (
                score,
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "storage_document_id": document_id,
                    "document_name": _text(name),
                    "document_version": _text(current_version) or _text(software_version),
                    "document_status": _text(status) or "published",
                    "source": source_url,
                    "section": _text(template_category) or "routing",
                    "content": rendered,
                    "raw_content": rendered,
                    "vendor": _text(row_vendor) or vendor,
                    "platform": _text(platform_family),
                    "cli_platform": _text(platform_family),
                    "product_family": _text(getattr(request, "product_family", "")),
                    "product_series": _text(getattr(request, "product_series", "")),
                    "product_model": _text(getattr(request, "product_model", "")),
                    "software_release": _text(software_version),
                    "feature": feature,
                    "feature_domain": feature_domain or _text(template_category),
                    "knowledge_source_type": "official_template",
                    "source_trust_level": "official",
                    "metadata": metadata,
                    "relevance_score": min(1.0, score / 100.0),
                    "template_id": _text(template_id),
                    "rollback": _text(rollback),
                    "description": _text(description),
                },
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1]["document_id"]))
    return [item for _, item in ranked[:bounded_limit]]


__all__ = ["search_official_templates"]
