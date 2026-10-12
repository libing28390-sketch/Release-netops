"""Portable tenant-scoped export for the AI knowledge document store.

The export deliberately contains source Markdown and canonical metadata only.
Embeddings, ACLs, tenant identifiers, and other server-owned fields are not
portable knowledge and must never be copied into an export bundle.  A future
import can re-chunk and re-embed the source documents for the destination
tenant, so the bundle remains independent of the current embedding provider.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Mapping

from ai.services.knowledge_document_contract import (
    DOCUMENT_CONTRACT_NAME,
    DOCUMENT_CONTRACT_VERSION,
    REQUIRED_METADATA_FIELDS,
    SUPPORTED_METADATA_SCHEMA_VERSIONS,
)
from ai.services.knowledge_service import knowledge_service


MAX_DOCUMENTS = 500
MAX_CONTENT_BYTES = 50 * 1024 * 1024
EXPORT_SCHEMA_VERSION = "knowledge-export-v1"

_SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|password|passwd|token|api[_-]?key|credential|authorization|cookie|private[_-]?key|"
    r"tenant[_-]?id|user[_-]?id|acl|permission|identity)",
    re.IGNORECASE,
)
_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class KnowledgeExportError(ValueError):
    """Base class for bounded, user-facing export failures."""

    code = "KNOWLEDGE_EXPORT_FAILED"
    status_code = 400


class KnowledgeExportLimitError(KnowledgeExportError):
    code = "KNOWLEDGE_EXPORT_LIMIT_EXCEEDED"
    status_code = 413


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    """Return bounded metadata without server-owned identity or credentials."""

    if depth > 4:
        return "[truncated]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:128]:
            key_text = str(key)[:120]
            if _SENSITIVE_KEY_RE.search(key_text):
                continue
            result[key_text] = _safe_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item, depth=depth + 1) for item in list(value)[:128]]
    if isinstance(value, str):
        if "internal.nexora.local/tenant/" in value.lower():
            return "[internal-source]"
        return value[:20_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:20_000]


def _safe_filename(value: Any, fallback: str) -> str:
    text = _SAFE_FILE_RE.sub("-", str(value or "").strip()).strip(".-")
    return (text[:120] or fallback)


def _canonical_metadata(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Build importable Front Matter from a legacy or V2 document row."""

    raw = detail.get("metadata")
    metadata = dict(_safe_value(raw if isinstance(raw, Mapping) else {}) or {})
    source_type = str(detail.get("knowledge_source_type") or metadata.get("source_type") or "user_document")
    official = source_type in {"official_vendor", "official_url", "official_local", "official_template"}
    metadata.update(
        {
            "schema_version": str(metadata.get("schema_version") or "1.0"),
            "document_id": str(metadata.get("document_id") or detail.get("document_id") or detail.get("id")),
            "title": str(metadata.get("title") or detail.get("name") or "Untitled Document"),
            "vendor": str(metadata.get("vendor") or detail.get("vendor") or "all"),
            "product_type": str(metadata.get("product_type") or metadata.get("product_family") or "network_switch"),
            "document_category": str(metadata.get("document_category") or "configuration"),
            "source_type": source_type,
            "official_only": bool(metadata.get("official_only", official)),
            "status": str(metadata.get("status") or detail.get("status") or "active"),
        }
    )
    for key in (
        "product_family", "product_series", "product_model", "os_family", "os_generation",
        "software_train", "software_release", "cli_platform", "feature_domain", "feature",
        "subfeature", "risk_level", "verification_level", "rag_priority", "source_version",
        "verified_version", "source_uri", "directory_path",
    ):
        value = detail.get(key)
        if value not in (None, "") and key not in metadata:
            metadata[key] = value
    return _safe_value(metadata)


def _front_matter(metadata: Mapping[str, Any], body: str) -> str:
    # JSON is valid YAML and avoids introducing a second serializer or unsafe
    # scalar quoting rules.  The existing importer parses this block with
    # PyYAML and accepts JSON mappings unchanged.
    return "---\n" + json.dumps(dict(metadata), ensure_ascii=False, indent=2, default=str) + "\n---\n\n" + body.strip() + "\n"


class KnowledgeExportService:
    """Build bounded, tenant-scoped ZIP bundles from the knowledge index."""

    def build_export(
        self,
        *,
        tenant_id: str,
        source_type: str | None = None,
        knowledge_scope: str | None = None,
        search: str = "",
        directory_path: str | None = None,
        vendor: str = "",
        product_family: str = "",
        product_series: str = "",
        product_model: str = "",
        os_family: str = "",
        os_generation: str = "",
        software_train: str = "",
        software_release: str = "",
        cli_platform: str = "",
        document_category: str = "",
        feature_domain: str = "",
        status: str = "active",
        source_trust_level: str = "",
        metadata_governance_status: str = "",
    ) -> dict[str, Any]:
        normalized_scope = str(knowledge_scope or "").strip().lower() or None
        if normalized_scope not in {None, "all", "official", "enterprise"}:
            raise KnowledgeExportError("unsupported knowledge scope")
        normalized_status = str(status or "active").strip().lower() or "active"
        if normalized_status not in {"active", "draft", "published", "quarantined", "superseded", "disabled", "all"}:
            raise KnowledgeExportError("unsupported document status")

        filters = {
            "knowledge_source_type": source_type or None,
            "knowledge_scope": None if normalized_scope in {None, "all"} else normalized_scope,
            "search": search,
            "directory_path": directory_path,
            "vendor": vendor,
            "product_family": product_family,
            "product_series": product_series,
            "product_model": product_model,
            "os_family": os_family,
            "os_generation": os_generation,
            "software_train": software_train,
            "software_release": software_release,
            "cli_platform": cli_platform,
            "document_category": document_category,
            "feature_domain": feature_domain,
            "status": normalized_status,
            "source_trust_level": source_trust_level,
            "metadata_governance_status": metadata_governance_status,
        }

        first_page = knowledge_service.list_documents(
            **filters, tenant_id=tenant_id, page=1, page_size=100, sort_by="created_at", sort_order="asc"
        )
        total = int(first_page.get("total") or 0)
        if total > MAX_DOCUMENTS:
            raise KnowledgeExportLimitError(
                f"导出文档数为 {total}，超过单次上限 {MAX_DOCUMENTS}；请缩小厂商、目录或搜索筛选范围"
            )

        summaries: list[dict[str, Any]] = list(first_page.get("items") or [])
        page = 2
        while len(summaries) < total:
            page_result = knowledge_service.list_documents(
                **filters, tenant_id=tenant_id, page=page, page_size=100, sort_by="created_at", sort_order="asc"
            )
            batch = list(page_result.get("items") or [])
            if not batch:
                break
            summaries.extend(batch)
            page += 1
        summaries = summaries[:MAX_DOCUMENTS]

        documents: list[dict[str, Any]] = []
        rendered_by_path: dict[str, str] = {}
        raw_content_bytes = 0
        used_paths: set[str] = set()
        for summary in summaries:
            detail = knowledge_service.get_document_detail(
                str(summary.get("id")), tenant_id=tenant_id, include_inactive=normalized_status != "active"
            )
            if not detail:
                continue
            body = str(detail.get("normalized_content") or detail.get("original_content") or "").strip()
            metadata = _canonical_metadata(detail)
            rendered = _front_matter(metadata, body)
            content_bytes = len(rendered.encode("utf-8"))
            raw_content_bytes += content_bytes
            if raw_content_bytes > MAX_CONTENT_BYTES:
                raise KnowledgeExportLimitError(
                    f"导出正文超过单次上限 {MAX_CONTENT_BYTES // (1024 * 1024)} MB；请缩小筛选范围"
                )

            stem = _safe_filename(detail.get("name"), "document")
            suffix = str(detail.get("id") or "")[:12]
            path = f"documents/{stem}-{suffix}.md"
            if path in used_paths:
                path = f"documents/{stem}-{suffix}-{len(used_paths)}.md"
            used_paths.add(path)
            rendered_by_path[path] = rendered
            source_refs = ((detail.get("raw_source") or {}).get("references") or []) if isinstance(detail.get("raw_source"), Mapping) else []
            source = {
                "source": detail.get("source"),
                "references": _safe_value(source_refs),
            }
            documents.append(
                {
                    "id": str(detail.get("id")),
                    "name": detail.get("name"),
                    "path": path,
                    "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                    "content_bytes": content_bytes,
                    "vendor": detail.get("vendor"),
                    "platform": detail.get("platform"),
                    "status": detail.get("status"),
                    "knowledge_source_type": detail.get("knowledge_source_type"),
                    "source_trust_level": detail.get("source_trust_level"),
                    "source": source,
                    "metadata": metadata,
                }
            )

        exported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        manifest = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": exported_at,
            "document_count": len(documents),
            "content_bytes": raw_content_bytes,
            "embeddings_exported": False,
            "reindex_required_on_import": True,
            "import_contract": {
                "bundle_format": "zip",
                "document_format": "markdown",
                "front_matter": "yaml-json-mapping",
                "document_contract": DOCUMENT_CONTRACT_NAME,
                "document_contract_version": DOCUMENT_CONTRACT_VERSION,
                "supported_metadata_schema_versions": list(SUPPORTED_METADATA_SCHEMA_VERSIONS),
                "required_metadata_fields": list(REQUIRED_METADATA_FIELDS),
                "custom_json_yaml_envelope": {
                    "format": DOCUMENT_CONTRACT_NAME,
                    "required_keys": ["format", "schema_version", "metadata", "content"],
                    "content_type": "string",
                    "metadata_type": "mapping",
                },
                "supported_source_extensions": [
                    ".md", ".markdown", ".txt", ".log", ".html", ".htm",
                    ".json", ".yaml", ".yml", ".csv", ".xml", ".conf", ".cfg", ".ini",
                    ".pdf", ".docx",
                ],
                "embeddings_included": False,
                "destination_reindex_required": True,
            },
            "filters": _safe_value(filters),
            "documents": documents,
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            for document in documents:
                archive.writestr(document["path"], rendered_by_path[document["path"]].encode("utf-8"))
        bundle = output.getvalue()
        return {
            "content": bundle,
            "filename": f"nexora-knowledge-export-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip",
            "document_count": len(documents),
            "content_bytes": raw_content_bytes,
            "manifest": manifest,
        }


knowledge_export_service = KnowledgeExportService()
