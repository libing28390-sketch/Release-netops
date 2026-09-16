"""Front Matter parsing, validation, and canonical metadata helpers.

Knowledge documents use a YAML Front Matter block as their semantic source of
truth.  The import directory is deliberately treated as a validation hint;
it can never overwrite values authored in the document itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

try:  # PyYAML is a small, explicit runtime dependency of the ingestion path.
    import yaml
except ImportError:  # pragma: no cover - surfaced as a useful configuration error
    yaml = None  # type: ignore[assignment]


ROOT_CATEGORY_MAP = {
    "01_product": "hardware",
    "02_commands": "command",
    "03_configuration": "configuration",
    "04_cli_outputs": "cli_output",
    "05_troubleshooting": "troubleshooting",
    "06_examples": "example",
}
DOCUMENT_CATEGORY_ALIASES = {
    **ROOT_CATEGORY_MAP,
    "hardware": "hardware",
    "command": "command",
    "configuration": "configuration",
    "cli_output": "cli_output",
    "troubleshooting": "troubleshooting",
    "example": "example",
}
DIRECTORY_VENDOR_MAP = {
    "huawei": "Huawei",
    "h3c": "H3C",
    "cisco": "Cisco",
    "ruijie": "Ruijie",
}
REQUIRED_METADATA_FIELDS = (
    "schema_version",
    "document_id",
    "title",
    "vendor",
    "product_type",
    "document_category",
    "source_type",
    "official_only",
    "status",
)
HIGH_FREQUENCY_METADATA_FIELDS = (
    "document_id",
    "vendor",
    "document_category",
    "product_family",
    "product_series",
    "product_model",
    "os_family",
    "os_generation",
    "software_train",
    "software_release",
    "cli_platform",
    "feature_domain",
    "feature",
    "subfeature",
    "risk_level",
    "verification_level",
    "rag_priority",
    "status",
    "metadata_governance_status",
    "metadata_governance_reason",
)

METADATA_GOVERNANCE_READY = "ready"
METADATA_GOVERNANCE_PENDING_REVIEW = "pending_review"
_TAXONOMY_FIELDS = ("vendor", "product_family", "product_series")

# These values belong to the server-owned document/ACL boundary.  They may
# remain on the parent row for authorization, but must never be copied into a
# searchable Chunk metadata projection (including nested mappings).
CHUNK_METADATA_FORBIDDEN_KEYS = frozenset(
    {
        "tenant_id",
        "workspace_id",
        "user_id",
        "created_by",
        "updated_by",
        "acl",
        "acl_json",
        "permissions",
        "roles",
        "authorization",
        "api_key",
        "password",
        "secret",
        "token",
        "private_key",
    }
)


class MetadataParseError(ValueError):
    """Raised when a document starts as Front Matter but contains invalid YAML."""


class MetadataValidationError(ValueError):
    """Raised when required metadata or directory consistency checks fail."""


@dataclass(frozen=True)
class ParsedKnowledgeDocument:
    original_content: str
    content: str
    metadata: dict[str, Any]
    metadata_parse_status: str
    metadata_parse_error: Optional[str] = None


_OPENING_RE = re.compile(r"\A(?:\ufeff)?---[ \t]*(?:\r?\n|\Z)")


def _normalise_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MetadataParseError("YAML Front Matter must be a mapping")
    result: dict[str, Any] = {}
    for key, item in value.items():
        canonical_key = str(key).strip().lower().replace("-", "_")
        result[canonical_key] = item
    return result


def parse_markdown_document(raw_text: str) -> ParsedKnowledgeDocument:
    """Parse only a Front Matter block at byte zero.

    A later ``---`` in the Markdown body is ordinary content.  If the file
    begins with an opening marker but has no closing marker, it is rejected
    rather than silently indexed with a partial header.
    """

    original = str(raw_text or "")
    text = original.replace("\r\n", "\n").replace("\r", "\n")
    opening = _OPENING_RE.match(text)
    if not opening:
        return ParsedKnowledgeDocument(original, text, {}, "missing")

    rest = text[opening.end():]
    closing = re.search(r"^---[ \t]*$", rest, flags=re.MULTILINE)
    if not closing:
        raise MetadataParseError("Front Matter opening marker has no closing --- marker")

    yaml_text = rest[:closing.start()]
    body = rest[closing.end():]
    if body.startswith("\n"):
        body = body[1:]
    if yaml is None:
        raise MetadataParseError("PyYAML is required to parse knowledge metadata")
    try:
        loaded = yaml.safe_load(yaml_text) or {}
    except Exception as exc:  # yaml.YAMLError differs across supported versions
        raise MetadataParseError(f"Invalid YAML Front Matter: {exc}") from exc
    metadata = _normalise_mapping(loaded)
    return ParsedKnowledgeDocument(original, body, metadata, "parsed")


def _first_path_parts(directory_path: str | None) -> tuple[str | None, str | None]:
    parts = [part.strip().lower() for part in str(directory_path or "").replace("\\", "/").split("/") if part.strip()]
    if parts and parts[0] == "kb_import":
        parts = parts[1:]
    if not parts:
        return None, None
    root = parts[0]
    vendor = parts[1] if len(parts) > 1 else None
    return root, vendor


def is_system_registry_document(name: str | None, metadata: Mapping[str, Any] | None = None) -> bool:
    """Recognise the metadata schema/registry itself as non-RAG content."""

    lowered = str(name or "").lower()
    data = metadata or {}
    document_type = str(data.get("document_type") or "").lower()
    return (
        "metadata_schema" in document_type
        or "rag_metadata_schema" in lowered
        or "nexora_network_kb_metadata_schema" in lowered
        or str(data.get("exclude_from_rag") or "").lower() in {"1", "true", "yes"}
    )


def validate_metadata(
    metadata: Mapping[str, Any],
    *,
    directory_path: str | None = None,
    name: str | None = None,
    allow_missing_required: bool = False,
) -> dict[str, Any]:
    """Validate and canonicalise metadata without allowing directory overrides."""

    result = _normalise_mapping(dict(metadata))
    missing = [field for field in REQUIRED_METADATA_FIELDS if field not in result]
    if missing and not allow_missing_required:
        raise MetadataValidationError("Missing required metadata: " + ", ".join(missing))

    if "official_only" in result and not isinstance(result["official_only"], bool):
        # YAML values such as ``"true"`` are common in hand-written files.
        value = str(result["official_only"]).strip().lower()
        if value in {"true", "yes", "1"}:
            result["official_only"] = True
        elif value in {"false", "no", "0"}:
            result["official_only"] = False
        else:
            raise MetadataValidationError("official_only must be a boolean")

    category = canonical_document_category(result.get("document_category"))
    if category:
        result["document_category"] = category
    vendor = str(result.get("vendor") or "").strip()
    if vendor:
        result["vendor"] = canonical_vendor(vendor)
    if result.get("feature"):
        result["feature"] = canonical_feature(result["feature"])

    root, directory_vendor = _first_path_parts(directory_path)
    expected_category = ROOT_CATEGORY_MAP.get(root or "")
    if expected_category and category and category != expected_category:
        raise MetadataValidationError(
            f"Directory category '{expected_category}' conflicts with metadata document_category '{category}'"
        )
    if expected_category and not category:
        result["document_category"] = expected_category
    expected_vendor = DIRECTORY_VENDOR_MAP.get(directory_vendor or "")
    if expected_vendor and vendor and canonical_vendor(vendor) != expected_vendor:
        raise MetadataValidationError(
            f"Directory vendor '{expected_vendor}' conflicts with metadata vendor '{vendor}'"
        )
    # A directory hint is retained for audit, never used to replace metadata.
    if root:
        result.setdefault("knowledge_directory_root", root)
    if directory_vendor:
        result.setdefault("knowledge_directory_vendor", directory_vendor)

    if is_system_registry_document(name, result):
        result["exclude_from_rag"] = True
    else:
        result.setdefault("exclude_from_rag", False)

    # ``cli_platform`` is intentionally nullable.  In particular, V300/V600
    # software trains do not, on their own, identify a CLI platform.
    if not str(result.get("cli_platform") or "").strip():
        result["cli_platform"] = None
    return result


def canonical_vendor(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return {
        "huawei": "Huawei",
        "华为": "Huawei",
        "华为技术": "Huawei",
        "huawei technologies": "Huawei",
        "h3c": "H3C",
        "华三": "H3C",
        "新华三": "H3C",
        "cisco": "Cisco",
        "思科": "Cisco",
        "思科系统": "Cisco",
        "ruijie": "Ruijie",
        "锐捷": "Ruijie",
        "锐捷网络": "Ruijie",
        "all": "all",
    }.get(normalized, str(value or "").strip())


def canonical_cli_platform(value: Any) -> str:
    """Normalize version-qualified CLI aliases to the storage taxonomy.

    The document projection stores a stable CLI family (for example
    ``h3c_comware``), while callers may include an OS generation in the
    platform token. Generation evidence remains available in
    ``os_generation``; collapsing only the platform alias keeps SQL joins
    deterministic without treating a version-qualified request as a
    different vendor dialect.
    """

    normalized = str(value or "").strip().lower().replace("-", "_")
    return {
        "cisco_ios_xe": "cisco_iosxe",
        "cisco_iosxe": "cisco_iosxe",
        "h3c_comware_v3": "h3c_comware",
        "h3c_comware_v5": "h3c_comware",
        "h3c_comware_v7": "h3c_comware",
        "h3c_comware_v9": "h3c_comware",
        "h3c_comware5": "h3c_comware",
        "h3c_comware7": "h3c_comware",
        "h3c_comware9": "h3c_comware",
        "huawei_vrpv8": "huawei_vrp",
        "huawei_vrp_v8": "huawei_vrp",
    }.get(normalized, str(value or "").strip())


_FEATURE_ALIASES = {
    "ospf": {"ospf", "tospf", "开放式最短路径优先"},
    "bgp": {"bgp", "边界网关协议"},
    "arp": {"arp", "地址解析"},
    "vlan": {"vlan", "虚拟局域网"},
    "stp": {"stp", "生成树"},
    "access_port": {
        "access port", "access-port", "vlan + access", "vlan+access", "接入口", "接入端口",
    },
    "port_security": {"port security", "port-security", "端口安全"},
    "trunk": {"trunk", "中继端口", "trunk端口"},
    "lacp": {"lacp", "eth-trunk", "etherchannel", "bridge-aggregation", "链路聚合"},
    "loopback": {"loopback", "环回接口", "环回口"},
    "static_route": {"static route", "static-route", "静态路由", "ip route-static", "ip route"},
    "ntp": {"ntp", "网络时间协议"},
    "snmp": {"snmp", "snmpv3", "简单网络管理协议"},
    "ssh": {"ssh", "stelnet", "secure shell", "安全登录"},
    "hsrp": {"hsrp", "hot standby router protocol", "热备份路由器协议"},
    "vrrp": {"vrrp", "虚拟路由器冗余"},
    "bfd": {"bfd", "双向转发检测"},
    "pam": {"pam", "aaa", "super password", "权限管理", "身份认证"},
    "system_monitoring": {"system monitoring", "cpu-usage", "cpu usage", "memory-usage", "memory usage", "设备状态"},
    "interface": {"interface", "interface brief", "接口简要"},
    "lldp": {"lldp", "链路层发现"},
    "evpn": {"evpn"},
    "vxlan": {"vxlan"},
    "acl": {"acl", "packet-filter", "traffic-filter", "access-list", "访问控制列表"},
}


def canonical_feature(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    for canonical, aliases in _FEATURE_ALIASES.items():
        if normalized in aliases:
            return canonical
    return str(value or "").strip()


def normalize_facet_value(value: Any) -> str:
    """Return a displayable facet or empty for values requiring governance."""

    normalized = str(value or "").strip()
    if not normalized or normalized.upper() in {"UNKNOWN", "未分类", "未识别", "ALL"}:
        return ""
    return canonical_vendor(normalized)


def metadata_governance(metadata: Mapping[str, Any], *, name: str | None = None) -> tuple[str, str]:
    """Classify whether a document has enough taxonomy evidence for RAG.

    Missing taxonomy is not a reason to fabricate a vendor or product family.
    It is kept visible for administrators, but excluded from retrieval until a
    reviewer supplies the missing evidence.  System registry documents are
    deliberately exempt because they are already excluded from RAG for a
    separate reason.
    """

    if is_system_registry_document(name, metadata):
        return METADATA_GOVERNANCE_READY, ""

    missing: list[str] = []
    for field in _TAXONOMY_FIELDS:
        value = str(metadata.get(field) or "").strip()
        normalized = value.upper()
        if not value or normalized in {"UNKNOWN", "未分类", "未识别"} or (field == "vendor" and normalized == "ALL"):
            missing.append(field)
    if not missing:
        return METADATA_GOVERNANCE_READY, ""
    return (
        METADATA_GOVERNANCE_PENDING_REVIEW,
        "missing_taxonomy_fields:" + ",".join(missing),
    )


def directory_metadata_for_document(document_category: Any, vendor: Any) -> dict[str, Any]:
    """Return the stable directory projection for a document's taxonomy.

    The directory tree is a browse/import projection, while the relational
    category and vendor fields remain the semantic source of truth.  Keep the
    mapping in one place so official publication, migration backfill and
    future import paths cannot drift apart.
    """
    category = canonical_document_category(document_category)
    root = next(
        (directory for directory, semantic in ROOT_CATEGORY_MAP.items() if semantic == category),
        None,
    )
    if not root:
        return {}

    canonical = canonical_vendor(vendor)
    vendor_slug = next(
        (slug for slug, display in DIRECTORY_VENDOR_MAP.items() if display == canonical),
        None,
    )
    path = f"{root}/{vendor_slug}" if vendor_slug else root
    return {
        "knowledge_directory": root,
        "knowledge_directory_root": root,
        "knowledge_directory_vendor": vendor_slug,
        "knowledge_directory_path": path,
    }


def canonical_document_category(value: Any) -> str:
    """Normalize UI directory ids and semantic categories to one RAG value."""
    normalized = str(value or "").strip().lower().replace("-", "_")
    return DOCUMENT_CATEGORY_ALIASES.get(normalized, normalized)


def document_category_query_values(value: Any) -> tuple[str, ...]:
    """Return canonical and legacy storage values during the migration window."""
    normalized = str(value or "").strip().lower().replace("-", "_")
    canonical = canonical_document_category(normalized)
    if not canonical:
        return ()
    return (canonical,) if normalized == canonical else (canonical, normalized)


def merge_metadata(frontmatter: Mapping[str, Any], source_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Merge source/audit metadata while giving meaningful Front Matter precedence.

    Validation adds nullable defaults (for example ``cli_platform: None``)
    when a document has no Front Matter.  Those defaults must not erase a
    trusted value supplied by the importer/template projection.  A real,
    non-empty Front Matter value still wins over the source metadata.
    """

    merged: dict[str, Any] = {}
    for key, value in (source_metadata or {}).items():
        if value is not None:
            merged[str(key)] = value
    for key, value in frontmatter.items():
        normalized_key = str(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            # Preserve a meaningful source value when validation supplied an
            # empty/default Front Matter value.  If no source value exists,
            # retain the explicit empty value for schema completeness.
            if normalized_key in merged:
                continue
        merged[normalized_key] = value
    return merged


def json_safe_metadata(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"), default=str)


def chunk_projection_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Remove server-owned identity and credential keys from Chunk metadata.

    Chunk rows inherit tenant/ACL from their parent document.  Keeping those
    values in JSONB makes them searchable and can create a second, stale
    authorization surface.  The sanitizer is deterministic, recursive and
    leaves semantic fields/arrays intact.
    """

    def clean(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): clean(child)
                for key, child in item.items()
                if str(key).casefold() not in CHUNK_METADATA_FORBIDDEN_KEYS
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, tuple):
            return [clean(child) for child in item]
        return item

    result = clean(dict(value))
    return result if isinstance(result, dict) else {}


def metadata_columns(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the indexed scalar columns; arrays remain in metadata_json."""

    result: dict[str, Any] = {}
    for field in HIGH_FREQUENCY_METADATA_FIELDS:
        value = metadata.get(field)
        if isinstance(value, (list, dict, tuple, set)):
            continue
        result[field] = value
    # Keep a stable alias for singular model filtering while accepting the
    # schema's historical ``product_models`` array.
    if not result.get("product_model"):
        models = metadata.get("product_models") or metadata.get("applicable_product_models")
        if isinstance(models, (list, tuple)) and len(models) == 1:
            result["product_model"] = models[0]
    return result
