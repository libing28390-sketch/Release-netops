"""Atomic PostgreSQL/SQLite import for Nexora knowledge export bundles."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import zipfile
from collections import Counter
from collections.abc import Mapping
from typing import Any

from database.core import get_db_connection
from ai.services.knowledge_service import knowledge_service
from ai.services.knowledge_source_parser import KnowledgeSourceParseError, parse_knowledge_source
from ai.services.retrieval_contract import retrieval_cache


MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_DOCUMENTS = 500
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
SUPPORTED_SCHEMA = "knowledge-export-v1"


class KnowledgeBundleImportError(ValueError):
    code = "KNOWLEDGE_BUNDLE_IMPORT_FAILED"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


def _safe_member_path(path: str) -> str:
    value = str(path or "").replace("\\", "/")
    parts = value.split("/")
    if not value or value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise KnowledgeBundleImportError("ZIP 包含不安全的路径", code="KNOWLEDGE_BUNDLE_PATH_INVALID")
    if any(ord(char) < 32 for char in value):
        raise KnowledgeBundleImportError("ZIP 路径包含控制字符", code="KNOWLEDGE_BUNDLE_PATH_INVALID")
    return "/".join(parts)


def _safe_metadata(value: Any) -> dict[str, Any]:
    """Copy bounded semantic metadata while dropping server-owned identity."""

    if not isinstance(value, Mapping):
        return {}

    forbidden = {"tenant_id", "user_id", "acl", "acl_json", "permissions", "identity", "credentials"}

    def clean(item: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "[truncated]"
        if isinstance(item, Mapping):
            return {
                str(key)[:120]: clean(child, depth + 1)
                for key, child in list(item.items())[:128]
                if str(key).casefold() not in forbidden
            }
        if isinstance(item, (list, tuple, set)):
            return [clean(child, depth + 1) for child in list(item)[:128]]
        if isinstance(item, str):
            return item[:20_000]
        if isinstance(item, (int, float, bool)) or item is None:
            return item
        return str(item)[:20_000]

    result = clean(value)
    return result if isinstance(result, dict) else {}


def _semantic_value(metadata: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (list, tuple, set)):
            value = next((item for item in value if str(item or "").strip()), "")
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _reconciliation_report(prepared: list[dict[str, Any]], manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Compare portable manifest fields with parsed semantic metadata before commit."""

    vendor_counts: Counter[str] = Counter()
    models: set[str] = set()
    software_releases: set[str] = set()
    source_types: set[str] = set()
    mismatches: list[dict[str, str]] = []
    for item in prepared:
        metadata = item["metadata"]
        source_item = item["manifest"]
        path = item["path"]
        vendor = _semantic_value(metadata, "vendor") or str(source_item.get("vendor") or "all").strip() or "all"
        vendor_counts[vendor] += 1
        model = _semantic_value(metadata, "product_model", "model", "product_models", "applicable_product_models")
        if model:
            models.add(model)
        release = _semantic_value(metadata, "software_release", "software_version", "verified_version", "version")
        if release:
            software_releases.add(release)
        source_type = _semantic_value(metadata, "original_source_type") or str(source_item.get("knowledge_source_type") or "user_document").strip()
        source_types.add(source_type or "user_document")

        comparisons = {
            "vendor": (source_item.get("vendor"), vendor),
            "platform": (source_item.get("platform"), _semantic_value(metadata, "cli_platform", "platform")),
        }
        manifest_metadata = source_item.get("metadata") if isinstance(source_item.get("metadata"), Mapping) else {}
        for field, keys in {
            "product_model": ("product_model", "model", "product_models", "applicable_product_models"),
            "software_release": ("software_release", "software_version", "verified_version", "version"),
        }.items():
            comparisons[field] = (_semantic_value(manifest_metadata, *keys), _semantic_value(metadata, *keys))
        for field, (expected, actual) in comparisons.items():
            expected_text = str(expected or "").strip()
            actual_text = str(actual or "").strip()
            if expected_text and actual_text and expected_text.casefold() != actual_text.casefold():
                mismatches.append({"path": path, "field": field, "manifest": expected_text, "parsed": actual_text})

    return {
        "manifest_document_count": int(manifest.get("document_count") or 0),
        "imported_document_count": len(prepared),
        "vendors": dict(sorted(vendor_counts.items())),
        "models": sorted(models),
        "software_releases": sorted(software_releases),
        "source_types": sorted(source_types),
        "effective_source_types": ["user_document"] if prepared else [],
        "metadata_mismatches": mismatches,
        "embedding_status": "rebuilt_on_destination",
    }


def _read_bundle(bundle: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(bundle, (bytes, bytearray)) or not bundle:
        raise KnowledgeBundleImportError("知识库导出包为空", code="KNOWLEDGE_BUNDLE_EMPTY")
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise KnowledgeBundleImportError("知识库导出包超过 64 MB 限制", code="KNOWLEDGE_BUNDLE_TOO_LARGE", status_code=413)
    try:
        archive = zipfile.ZipFile(io.BytesIO(bundle), "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise KnowledgeBundleImportError("知识库导出包不是有效 ZIP", code="KNOWLEDGE_BUNDLE_INVALID") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_DOCUMENTS + 8:
            raise KnowledgeBundleImportError("ZIP 文件条目超过限制", code="KNOWLEDGE_BUNDLE_ENTRY_LIMIT", status_code=413)
        members: dict[str, zipfile.ZipInfo] = {}
        total_uncompressed = 0
        for info in infos:
            path = _safe_member_path(info.filename)
            if path in members:
                raise KnowledgeBundleImportError("ZIP 包含重复路径", code="KNOWLEDGE_BUNDLE_DUPLICATE_PATH")
            # Reject UNIX symlinks and other special files; only regular files
            # are allowed to enter the document parser.
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
                raise KnowledgeBundleImportError("ZIP 包含不允许的特殊文件", code="KNOWLEDGE_BUNDLE_SPECIAL_FILE")
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise KnowledgeBundleImportError("ZIP 解压后正文超过 50 MB 限制", code="KNOWLEDGE_BUNDLE_UNCOMPRESSED_LIMIT", status_code=413)
            members[path] = info

        if "manifest.json" not in members:
            raise KnowledgeBundleImportError("导出包缺少根目录 manifest.json", code="KNOWLEDGE_BUNDLE_MANIFEST_MISSING")
        try:
            manifest = json.loads(archive.read(members["manifest.json"]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise KnowledgeBundleImportError("manifest.json 无法解析", code="KNOWLEDGE_BUNDLE_MANIFEST_INVALID") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != SUPPORTED_SCHEMA:
            raise KnowledgeBundleImportError("不支持的知识库导出包版本", code="KNOWLEDGE_BUNDLE_SCHEMA_UNSUPPORTED")
        if manifest.get("embeddings_exported") is True or manifest.get("reindex_required_on_import") is not True:
            raise KnowledgeBundleImportError("导出包必须声明目标主机重新生成向量", code="KNOWLEDGE_BUNDLE_EMBEDDING_POLICY")
        entries = manifest.get("documents")
        if not isinstance(entries, list) or len(entries) > MAX_DOCUMENTS:
            raise KnowledgeBundleImportError("manifest documents 清单无效或超限", code="KNOWLEDGE_BUNDLE_DOCUMENT_LIST_INVALID")
        if int(manifest.get("document_count") or 0) != len(entries):
            raise KnowledgeBundleImportError("manifest 文档数量与清单不一致", code="KNOWLEDGE_BUNDLE_DOCUMENT_COUNT_MISMATCH")

        documents: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for item in entries:
            if not isinstance(item, Mapping):
                raise KnowledgeBundleImportError("manifest 文档项必须是对象", code="KNOWLEDGE_BUNDLE_DOCUMENT_INVALID")
            path = _safe_member_path(str(item.get("path") or ""))
            if path in seen_paths or path not in members or path == "manifest.json":
                raise KnowledgeBundleImportError("manifest 文档路径无效", code="KNOWLEDGE_BUNDLE_DOCUMENT_PATH_INVALID")
            seen_paths.add(path)
            raw = archive.read(members[path])
            expected_hash = str(item.get("content_sha256") or "").lower()
            actual_hash = hashlib.sha256(raw).hexdigest()
            if expected_hash != actual_hash:
                raise KnowledgeBundleImportError(f"文档校验失败：{path}", code="KNOWLEDGE_BUNDLE_HASH_MISMATCH")
            expected_bytes = int(item.get("content_bytes") or len(raw))
            if expected_bytes != len(raw):
                raise KnowledgeBundleImportError(f"文档大小校验失败：{path}", code="KNOWLEDGE_BUNDLE_SIZE_MISMATCH")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise KnowledgeBundleImportError(f"文档不是 UTF-8 文本：{path}", code="KNOWLEDGE_BUNDLE_ENCODING_INVALID") from exc
            if not text.strip():
                raise KnowledgeBundleImportError(f"文档为空：{path}", code="KNOWLEDGE_BUNDLE_DOCUMENT_EMPTY")
            documents.append({"manifest": dict(item), "path": path, "text": text})

        extra_documents = {
            path for path in members
            if path.startswith("documents/") and path not in seen_paths
        }
        if extra_documents:
            raise KnowledgeBundleImportError("ZIP 中存在未列入 manifest 的文档", code="KNOWLEDGE_BUNDLE_MANIFEST_INCOMPLETE")
        return manifest, documents


def import_knowledge_bundle(
    bundle: bytes,
    *,
    tenant_id: str,
    knowledge_base_id: str | None = None,
) -> dict[str, Any]:
    """Validate a bundle fully, then insert all documents in one DB transaction."""

    manifest, raw_documents = _read_bundle(bundle)
    prepared: list[dict[str, Any]] = []
    for item in raw_documents:
        try:
            parsed = parse_knowledge_source(item["text"], filename=item["path"])
        except KnowledgeSourceParseError as exc:
            raise KnowledgeBundleImportError(
                f"文档 Metadata 无法解析：{item['path']}：{exc.message}",
                code="KNOWLEDGE_BUNDLE_METADATA_INVALID",
            ) from exc
        metadata = _safe_metadata(parsed.metadata)
        source_item = item["manifest"]
        # An exported bundle is an untrusted transport boundary.  It must not
        # self-assert official status on the destination host; an administrator
        # can explicitly re-review the source URL through ING-002 afterwards.
        original_source_type = str(metadata.get("source_type") or source_item.get("knowledge_source_type") or "user_document")
        metadata.update({
            "source_type": "user_document",
            "original_source_type": original_source_type,
            "official_only": False,
            "verification_status": "unverified_bundle",
            "imported_from_bundle": True,
            "source_bundle_schema": SUPPORTED_SCHEMA,
        })
        metadata.pop("tenant_id", None)
        name = str(source_item.get("name") or os.path.basename(item["path"]) or "Imported document")[:256]
        vendor = str(metadata.get("vendor") or source_item.get("vendor") or "all")[:128]
        platform = metadata.get("cli_platform") or source_item.get("platform")
        prepared.append({
            "manifest": source_item,
            "path": item["path"],
            "name": name,
            "content": parsed.content,
            "vendor": vendor,
            "platform": platform,
            "metadata": metadata,
            "source": "knowledge-bundle-import",
        })

    reconciliation = _reconciliation_report(prepared, manifest)
    if reconciliation["metadata_mismatches"]:
        reconciliation["embedding_status"] = "not_started"
        raise KnowledgeBundleImportError(
            "导出清单与文档 Metadata 不一致，未写入目标知识库",
            code="KNOWLEDGE_BUNDLE_METADATA_MISMATCH",
            status_code=409,
            details={"reconciliation": reconciliation},
        )

    if knowledge_base_id:
        kb_id = knowledge_base_id
    else:
        bases = knowledge_service.list_knowledge_bases(tenant_id=tenant_id)
        kb_id = bases[0]["id"] if bases else knowledge_service.create_knowledge_base("Default KB", tenant_id=tenant_id)["id"]

    results: list[dict[str, Any]] = []
    with get_db_connection() as conn:
        try:
            for item in prepared:
                results.append(
                    knowledge_service.add_document_and_chunk(
                        knowledge_base_id=kb_id,
                        name=item["name"],
                        content=item["content"],
                        vendor=item["vendor"],
                        platform=item["platform"],
                        knowledge_source_type="user_document",
                        tenant_id=tenant_id,
                        source_trust_level="internal",
                        metadata=item["metadata"],
                        source=item["source"],
                        db_connection=conn,
                        invalidate_cache=False,
                    )
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # Cache invalidation happens only after the shared transaction commits.
    retrieval_cache.invalidate_documents([item["document_id"] for item in results])
    return {
        "success": True,
        "schema_version": manifest["schema_version"],
        "document_count": len(results),
        "documents": results,
        "atomic": True,
        "official_claims": "downgraded_to_user_document",
        "reindex_required": False,
        "reconciliation": reconciliation,
    }


__all__ = ["KnowledgeBundleImportError", "import_knowledge_bundle"]
