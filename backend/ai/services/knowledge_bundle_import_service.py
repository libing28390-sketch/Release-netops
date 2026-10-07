"""Atomic PostgreSQL import for Nexora knowledge export bundles."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import stat
import zipfile
from collections import Counter
from collections.abc import Mapping
from typing import Any

from core.context import request_id_var, resolve_request_id
from database.core import get_db_connection
from ai.services.knowledge_service import knowledge_service
from ai.services.knowledge_source_parser import KnowledgeSourceParseError, parse_knowledge_source
from ai.services.retrieval_contract import retrieval_cache


MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_DOCUMENTS = 500
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
SUPPORTED_SCHEMA = "knowledge-export-v1"

logger = logging.getLogger(__name__)

_SENSITIVE_ERROR_VALUE_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|password|passwd|secret|community|"
    r"token|auth_pass|priv_pass|credential|authorization|cookie|private[_ -]?key)\b"
    r"\s*[:=]\s*[^\s,;}]+"
)
_PRIVATE_KEY_RE = re.compile(
    r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_URI_CREDENTIAL_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+@")
_DOCUMENT_PATH_RE = re.compile(r"(?i)(?<![\w-])documents[\\/][^\s,;}]+'?\b")
_IMPORT_DIAGNOSTIC_STAGES = frozenset(
    {"read_bundle", "parse", "reconcile", "chunk", "embedding", "database", "cache_invalidation"}
)
_IMPORT_DIAGNOSTIC_STATUSES = frozenset(
    {"started", "completed", "document_completed", "committed", "failed", "rolled_back", "rollback_failed"}
)
_IMPORT_DIAGNOSTIC_DETAIL_KEYS = frozenset(
    {
        "bundle_bytes",
        "manifest_document_count",
        "parser_version",
        "metadata_parse_status",
        "chunk_count",
        "vector_count",
        "embedding_dimensions",
        "embedding_model",
        "mismatch_count",
        "error_type",
        "error_code",
        "error_summary",
    }
)


def _stable_document_ref(path: str, content_sha256: str = "") -> str:
    """Return a non-reversible document reference suitable for logs."""

    material = f"{path}\x00{content_sha256}".encode("utf-8", errors="replace")
    return hashlib.sha256(material).hexdigest()[:16]


def _safe_error_summary(exc: BaseException) -> str:
    """Bound an exception summary without logging document or credential data."""

    if isinstance(exc, KnowledgeBundleImportError):
        return f"bundle_validation:{exc.code}"
    if isinstance(exc, KnowledgeSourceParseError):
        return f"document_parser:{exc.code}"

    text = " ".join(str(exc or "").split())
    text = _PRIVATE_KEY_RE.sub("<REDACTED_PRIVATE_KEY>", text)
    text = _URI_CREDENTIAL_RE.sub(r"\1<REDACTED>@", text)
    text = _DOCUMENT_PATH_RE.sub("<REDACTED_DOCUMENT_PATH>", text)
    text = _SENSITIVE_ERROR_VALUE_RE.sub(
        lambda match: f"{match.group(1)}=***",
        text,
    )
    return (text[:237] + "...") if len(text) > 240 else (text or "no message")


class _ImportDiagnostics:
    """Emit bounded, grep-friendly import progress without sensitive payloads."""

    def __init__(self, bundle: bytes, request_id: str | None = None):
        self.request_id = resolve_request_id(
            request_id or request_id_var.get("-"),
            prefix="req",
        )
        raw_bundle = bytes(bundle) if isinstance(bundle, (bytes, bytearray)) else b""
        self.bundle_ref = hashlib.sha256(raw_bundle).hexdigest()[:16]
        self.transaction_state = "not_started"
        self.document_count = 0
        self.prepared_count = 0
        self.processed_count = 0
        self.current_stage = "read_bundle"
        self.current_document_index: int | None = None
        self.current_document_ref: str | None = None

    def select_document(self, index: int, document_ref: str) -> None:
        self.current_document_index = int(index)
        self.current_document_ref = str(document_ref)

    def set_transaction_state(self, state: str) -> None:
        self.transaction_state = str(state)

    def emit(
        self,
        *,
        stage: str,
        status: str,
        document_index: int | None = None,
        document_ref: str | None = None,
        **details: Any,
    ) -> None:
        safe_stage = str(stage) if str(stage) in _IMPORT_DIAGNOSTIC_STAGES else "unknown"
        safe_status = str(status) if str(status) in _IMPORT_DIAGNOSTIC_STATUSES else "unknown"
        self.current_stage = safe_stage
        if document_index is not None:
            self.current_document_index = int(document_index)
        if document_ref is not None:
            self.current_document_ref = str(document_ref)

        payload: dict[str, Any] = {
            "event": "knowledge_bundle_import",
            "request_id": self.request_id,
            "bundle_ref": self.bundle_ref,
            "stage": safe_stage,
            "status": safe_status,
            "transaction_state": self.transaction_state,
            "document_count": int(self.document_count),
            "prepared_count": int(self.prepared_count),
            "processed_count": int(self.processed_count),
        }
        if self.current_document_index is not None:
            payload["document_index"] = self.current_document_index
        if self.current_document_ref and re.fullmatch(r"[0-9a-f]{16}", self.current_document_ref):
            payload["document_ref"] = self.current_document_ref

        # Only explicitly supplied, bounded scalar diagnostics are included.
        # In particular, never pass metadata, document content, or exception
        # objects through to the logger.
        for key, value in details.items():
            if key not in _IMPORT_DIAGNOSTIC_DETAIL_KEYS:
                continue
            if key == "error_summary":
                value = _safe_error_summary(RuntimeError(str(value)))
            elif key == "error_code":
                code = str(value or "")[:64]
                value = code if re.fullmatch(r"[A-Za-z0-9_.-]+", code) else "UNSAFE_ERROR_CODE"
            if isinstance(value, str):
                payload[key] = value[:240]
            elif isinstance(value, (int, float, bool)) or value is None:
                payload[key] = value

        level = logging.ERROR if safe_status in {"failed", "rollback_failed"} else logging.WARNING if safe_status == "rolled_back" else logging.INFO
        if safe_status in {"started", "completed"} and self.current_document_index is not None and safe_stage in {"parse", "chunk", "embedding", "database"}:
            level = logging.DEBUG
        try:
            logger.log(
                level,
                "knowledge_bundle_import %s",
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        except Exception:
            # Diagnostics must never affect the import transaction.
            return

    def failure(
        self,
        *,
        stage: str,
        exc: BaseException,
        document_index: int | None = None,
        document_ref: str | None = None,
        **details: Any,
    ) -> None:
        self.emit(
            stage=stage,
            status="failed",
            document_index=document_index,
            document_ref=document_ref,
            error_type=type(exc).__name__,
            error_code=getattr(exc, "code", None),
            error_summary=_safe_error_summary(exc),
            **details,
        )


def _exception_diagnostic(exc: BaseException) -> dict[str, Any]:
    """Keep exception-attached diagnostics to stable, non-sensitive fields."""

    raw = getattr(exc, "diagnostic", {})
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Any] = {}
    if raw.get("document_index") is not None:
        result["document_index"] = int(raw["document_index"])
    if raw.get("document_ref"):
        result["document_ref"] = str(raw["document_ref"])[:32]
    return result


class KnowledgeBundleImportError(ValueError):
    code = "KNOWLEDGE_BUNDLE_IMPORT_FAILED"
    status_code = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
        diagnostic: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details
        self.diagnostic = dict(diagnostic or {})


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
        for document_index, item in enumerate(entries, start=1):
            if not isinstance(item, Mapping):
                raise KnowledgeBundleImportError("manifest 文档项必须是对象", code="KNOWLEDGE_BUNDLE_DOCUMENT_INVALID")
            raw_path = str(item.get("path") or "")
            declared_hash = item.get("content_sha256")
            declared_bytes = item.get("content_bytes")
            expected_hash = declared_hash.lower() if isinstance(declared_hash, str) else ""
            diagnostic = {
                "document_index": document_index,
                "document_ref": _stable_document_ref(raw_path, expected_hash),
            }
            if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
                raise KnowledgeBundleImportError(
                    "manifest 文档 content_sha256 必须是 64 位十六进制字符串",
                    code="KNOWLEDGE_BUNDLE_CONTENT_HASH_INVALID",
                    diagnostic=diagnostic,
                )
            if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int) or declared_bytes < 0:
                raise KnowledgeBundleImportError(
                    "manifest 文档 content_bytes 必须是非负整数",
                    code="KNOWLEDGE_BUNDLE_CONTENT_SIZE_INVALID",
                    diagnostic=diagnostic,
                )
            try:
                path = _safe_member_path(raw_path)
            except KnowledgeBundleImportError as exc:
                exc.diagnostic.update(diagnostic)
                raise
            if path in seen_paths or path not in members or path == "manifest.json":
                raise KnowledgeBundleImportError(
                    "manifest 文档路径无效",
                    code="KNOWLEDGE_BUNDLE_DOCUMENT_PATH_INVALID",
                    diagnostic=diagnostic,
                )
            seen_paths.add(path)
            raw = archive.read(members[path])
            actual_hash = hashlib.sha256(raw).hexdigest()
            if expected_hash != actual_hash:
                raise KnowledgeBundleImportError(
                    f"文档校验失败：{path}",
                    code="KNOWLEDGE_BUNDLE_HASH_MISMATCH",
                    diagnostic=diagnostic,
                )
            expected_bytes = declared_bytes
            if expected_bytes != len(raw):
                raise KnowledgeBundleImportError(
                    f"文档大小校验失败：{path}",
                    code="KNOWLEDGE_BUNDLE_SIZE_MISMATCH",
                    diagnostic=diagnostic,
                )
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise KnowledgeBundleImportError(
                    f"文档不是 UTF-8 文本：{path}",
                    code="KNOWLEDGE_BUNDLE_ENCODING_INVALID",
                    diagnostic=diagnostic,
                ) from exc
            if not text.strip():
                raise KnowledgeBundleImportError(
                    f"文档为空：{path}",
                    code="KNOWLEDGE_BUNDLE_DOCUMENT_EMPTY",
                    diagnostic=diagnostic,
                )
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
    request_id: str | None = None,
) -> dict[str, Any]:
    """Validate a bundle fully, then insert all documents in one DB transaction."""

    diagnostics = _ImportDiagnostics(bundle, request_id=request_id)
    diagnostics.emit(
        stage="read_bundle",
        status="started",
        bundle_bytes=len(bundle) if isinstance(bundle, (bytes, bytearray)) else 0,
    )
    try:
        manifest, raw_documents = _read_bundle(bundle)
    except KnowledgeBundleImportError as exc:
        diagnostics.failure(
            stage="read_bundle",
            exc=exc,
            **_exception_diagnostic(exc),
        )
        raise
    except Exception as exc:
        diagnostics.failure(stage="read_bundle", exc=exc)
        raise

    diagnostics.document_count = len(raw_documents)
    diagnostics.emit(
        stage="read_bundle",
        status="completed",
        manifest_document_count=int(manifest.get("document_count") or 0),
    )
    prepared: list[dict[str, Any]] = []
    for document_index, item in enumerate(raw_documents, start=1):
        document_ref = _stable_document_ref(
            item["path"],
            str(item["manifest"].get("content_sha256") or ""),
        )
        diagnostics.select_document(document_index, document_ref)
        diagnostics.emit(stage="parse", status="started")
        try:
            parsed = parse_knowledge_source(item["text"], filename=item["path"])
        except KnowledgeSourceParseError as exc:
            import_error = KnowledgeBundleImportError(
                f"文档 Metadata 无法解析：{item['path']}：{exc.message}",
                code="KNOWLEDGE_BUNDLE_METADATA_INVALID",
                diagnostic={
                    "document_index": document_index,
                    "document_ref": document_ref,
                },
            )
            diagnostics.failure(
                stage="parse",
                exc=import_error,
                document_index=document_index,
                document_ref=document_ref,
            )
            raise import_error from exc
        except Exception as exc:
            diagnostics.failure(
                stage="parse",
                exc=exc,
                document_index=document_index,
                document_ref=document_ref,
            )
            raise

        try:
            metadata = _safe_metadata(parsed.metadata)
            source_item = item["manifest"]
            # An exported bundle is an untrusted transport boundary.  It must
            # not self-assert official status on the destination host; an
            # administrator can explicitly re-review the source URL through
            # ING-002 afterwards.
            original_source_type = str(
                metadata.get("source_type")
                or source_item.get("knowledge_source_type")
                or "user_document"
            )
            metadata.update({
                "source_type": "user_document",
                "original_source_type": original_source_type,
                "official_only": False,
                # The source document can contain an official-looking
                # Front Matter claim, but an imported ZIP is an untrusted
                # transport boundary.  Keep the downgraded trust level in
                # the portable metadata as well as in the indexed column;
                # otherwise citations/trace consumers could still observe a
                # stale ``official`` claim after import.
                "source_trust_level": "internal",
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
        except Exception as exc:
            diagnostics.failure(
                stage="parse",
                exc=exc,
                document_index=document_index,
                document_ref=document_ref,
            )
            raise

        diagnostics.prepared_count = len(prepared)
        diagnostics.emit(
            stage="parse",
            status="completed",
            document_index=document_index,
            document_ref=document_ref,
        )

    diagnostics.emit(stage="reconcile", status="started")
    try:
        reconciliation = _reconciliation_report(prepared, manifest)
    except Exception as exc:
        diagnostics.failure(stage="reconcile", exc=exc)
        raise
    if reconciliation["metadata_mismatches"]:
        reconciliation["embedding_status"] = "not_started"
        mismatch = reconciliation["metadata_mismatches"][0]
        mismatch_path = str(mismatch.get("path") or "")
        mismatch_index = next(
            (
                index
                for index, item in enumerate(prepared, start=1)
                if item["path"] == mismatch_path
            ),
            None,
        )
        mismatch_ref = next(
            (
                _stable_document_ref(
                    item["path"],
                    str(item["manifest"].get("content_sha256") or ""),
                )
                for item in prepared
                if item["path"] == mismatch_path
            ),
            None,
        )
        import_error = KnowledgeBundleImportError(
            "导出清单与文档 Metadata 不一致，未写入目标知识库",
            code="KNOWLEDGE_BUNDLE_METADATA_MISMATCH",
            status_code=409,
            details={"reconciliation": reconciliation},
            diagnostic={
                "document_index": mismatch_index,
                "document_ref": mismatch_ref,
            },
        )
        diagnostics.failure(
            stage="reconcile",
            exc=import_error,
            document_index=mismatch_index,
            document_ref=mismatch_ref,
            mismatch_count=len(reconciliation["metadata_mismatches"]),
        )
        raise import_error
    diagnostics.emit(
        stage="reconcile",
        status="completed",
        mismatch_count=0,
    )

    try:
        if knowledge_base_id:
            kb_id = knowledge_base_id
        else:
            bases = knowledge_service.list_knowledge_bases(tenant_id=tenant_id)
            kb_id = bases[0]["id"] if bases else knowledge_service.create_knowledge_base("Default KB", tenant_id=tenant_id)["id"]
    except Exception as exc:
        diagnostics.failure(stage="database", exc=exc)
        raise

    results: list[dict[str, Any]] = []
    diagnostics.set_transaction_state("opening")
    diagnostics.emit(
        stage="database",
        status="started",
    )
    conn = None
    try:
        with get_db_connection() as conn:
            diagnostics.set_transaction_state("active")
            for document_index, item in enumerate(prepared, start=1):
                document_ref = _stable_document_ref(
                    item["path"],
                    str(item["manifest"].get("content_sha256") or ""),
                )
                diagnostics.select_document(document_index, document_ref)

                def stage_callback(stage: str, status: str, details: dict[str, Any]) -> None:
                    diagnostics.emit(
                        stage=stage,
                        status=status,
                        document_index=document_index,
                        document_ref=document_ref,
                        **dict(details),
                    )

                try:
                    result = knowledge_service.add_document_and_chunk(
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
                        diagnostic_callback=stage_callback,
                    )
                except Exception as exc:
                    diagnostics.failure(
                        stage=diagnostics.current_stage or "database",
                        exc=exc,
                        document_index=document_index,
                        document_ref=document_ref,
                    )
                    raise
                results.append(result)
                diagnostics.processed_count += 1
                diagnostics.emit(
                    stage="database",
                    status="document_completed",
                    document_index=document_index,
                    document_ref=document_ref,
                )
            try:
                conn.commit()
            except Exception as exc:
                diagnostics.failure(stage="database", exc=exc)
                raise
            diagnostics.set_transaction_state("committed")
            diagnostics.emit(stage="database", status="committed")
    except Exception as exc:
        if diagnostics.transaction_state == "active" and conn is not None:
            try:
                conn.rollback()
            except Exception as rollback_exc:
                diagnostics.set_transaction_state("rollback_failed")
                diagnostics.failure(stage="database", exc=rollback_exc)
            else:
                diagnostics.set_transaction_state("rolled_back")
                diagnostics.emit(stage="database", status="rolled_back")
        elif diagnostics.transaction_state == "opening":
            diagnostics.set_transaction_state("open_failed")
            diagnostics.failure(stage="database", exc=exc)
        elif diagnostics.transaction_state == "committed":
            # The database commit already succeeded; surface a diagnostic if
            # the connection context itself failed while closing.
            diagnostics.failure(stage="database", exc=exc)
        raise
    else:
        # The shared connection has committed at this point; cache work is
        # intentionally outside the transaction boundary.
        diagnostics.emit(stage="cache_invalidation", status="started")
        try:
            retrieval_cache.invalidate_documents([item["document_id"] for item in results])
        except Exception as exc:
            diagnostics.failure(stage="cache_invalidation", exc=exc)
            raise
        diagnostics.emit(stage="cache_invalidation", status="completed")

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
