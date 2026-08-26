"""
AI Knowledge Base and Document Chunking Service
Supports Normalized Markdown Middle Format & Heading/CLI-Aware Smart Chunking
"""

from __future__ import annotations

import json
import hashlib
import re
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection, _USE_PG
from ai.chunking.engine import ChunkingEngine
from ai.providers.embedding import (
    EmbeddingProviderError,
    assert_pgvector_column_compatible,
    embed_documents_batch,
    embedding_contract,
    embedding_provider,
    embedding_metadata,
)
from ai.security.gateway import SecurityBlocked
from ai.services.knowledge_metadata import (
    MetadataParseError,
    MetadataValidationError,
    json_safe_metadata,
    merge_metadata,
    metadata_columns,
    chunk_projection_metadata,
    document_category_query_values,
    validate_metadata,
)
from ai.services.knowledge_source_parser import KnowledgeSourceParseError, parse_knowledge_source


try:
    import sqlite3
    from psycopg2.extras import Json as _PgJson
    sqlite3.register_adapter(_PgJson, lambda j: json.dumps(getattr(j, "adapted", j), ensure_ascii=False))
except Exception:
    pass


def _json_db_value(value: Dict[str, Any]) -> Any:
    """Adapt a metadata mapping to JSONB on PostgreSQL and TEXT on SQLite."""
    if _USE_PG:
        try:
            from psycopg2.extras import Json
            return Json(value, dumps=lambda item: json.dumps(item, ensure_ascii=False))
        except ImportError:
            pass
    return json_safe_metadata(value)
from ai.services.rag_policy import parse_acl
from ai.services.retrieval_contract import retrieval_cache


_DEFAULT_DIRECTORY_NAMES = (
    "01_product",
    "02_commands",
    "03_configuration",
    "04_cli_outputs",
    "05_troubleshooting",
    "06_examples",
)
_DEFAULT_VENDOR_DIRECTORY_NAMES = ("huawei", "h3c", "cisco", "ruijie")
_DIRECTORY_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_OFFICIAL_KNOWLEDGE_TYPES = ("official_vendor", "official_url", "official_local", "official_template")
_ENTERPRISE_KNOWLEDGE_TYPES = ("internal_sop", "internal_standard", "case", "user_document", "sample")
_DOCUMENT_ACTIONS = frozenset({"delete", "disable", "enable", "reparse", "rechunk", "reindex"})
_CHUNK_DETAIL_SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|password|passwd|token|api[_-]?key|credential|authorization|cookie|private[_-]?key|tenant[_-]?id|user[_-]?id|acl|permission|identity)",
    re.IGNORECASE,
)
_CHUNK_DETAIL_MAX_TEXT = 20_000


def _decode_json_value(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return default
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return default
    return parsed


def _safe_chunk_detail_value(value: Any, *, depth: int = 0) -> Any:
    """Bound metadata/source locator output and remove identity/secrets."""

    if depth > 3:
        return "[truncated]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:128]:
            key_text = str(key)
            if _CHUNK_DETAIL_SENSITIVE_KEY_RE.search(key_text):
                continue
            result[key_text[:120]] = _safe_chunk_detail_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_chunk_detail_value(item, depth=depth + 1) for item in list(value)[:128]]
    if isinstance(value, str):
        return value[:_CHUNK_DETAIL_MAX_TEXT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_CHUNK_DETAIL_MAX_TEXT]


class KnowledgeDocumentActionError(ValueError):
    """Stable, bounded error for a confirmed document lifecycle action."""

    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class KnowledgeService:
    """Service for Knowledge Base CRUD, metadata tagging, normalized Markdown middle format, and smart chunking."""

    def create_knowledge_base(
        self,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[str] = "admin",
        tenant_id: str = "tenant-default",
        acl: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        kb_id = f"kb_{uuid.uuid4().hex[:12]}"
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ai_knowledge_base (id, name, description, enabled, created_by, tenant_id, acl_json, created_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
                (kb_id, name, description, created_by, tenant_id, json.dumps(acl or {}, ensure_ascii=False), now_iso)
            )
            conn.commit()
        return {"id": kb_id, "name": name, "description": description, "tenant_id": tenant_id, "acl": acl or {}, "created_at": now_iso}

    def list_knowledge_bases(self, tenant_id: str = "tenant-default") -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, description, enabled, created_by, tenant_id, acl_json, created_at FROM ai_knowledge_base WHERE enabled = 1 AND (tenant_id = ? OR tenant_id = 'tenant-default')", (tenant_id,))
            rows = cursor.fetchall()
            result = []
            for r in rows:
                try:
                    acl = json.loads(r[6] or "{}")
                except (TypeError, ValueError):
                    acl = {}
                result.append({"id": r[0], "name": r[1], "description": r[2], "enabled": bool(r[3]), "created_by": r[4], "tenant_id": r[5], "acl": acl, "created_at": r[7]})
            return result

    def get_or_create_default_knowledge_base(
        self,
        tenant_id: str = "tenant-default",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """Return the first enabled tenant KB, creating the default one when needed."""
        knowledge_bases = self.list_knowledge_bases(tenant_id=tenant_id)
        if knowledge_bases:
            return knowledge_bases[0]
        return self.create_knowledge_base(
            name="Default KB",
            description="Enterprise network knowledge base",
            created_by=created_by,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _directory_node_from_row(row: Any) -> Dict[str, Any]:
        return {
            "id": row[0],
            "knowledge_base_id": row[1],
            "tenant_id": row[2],
            "parent_id": row[3],
            "name": row[4],
            "path": row[5],
            "depth": int(row[6] or 0),
            "is_system": bool(row[7]),
            "sort_order": int(row[8] or 0),
            "created_by": row[9],
            "created_at": row[10],
            "updated_at": row[11],
            "children": [],
        }

    @staticmethod
    def _validate_directory_name(name: str) -> str:
        value = str(name or "").strip()
        if not value:
            raise ValueError("目录名称不能为空")
        if len(value) > 80:
            raise ValueError("目录名称不能超过 80 个字符")
        if value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("目录名称不能包含路径分隔符或 . / ..")
        if _DIRECTORY_CONTROL_CHARS.search(value):
            raise ValueError("目录名称不能包含控制字符")
        return value

    @staticmethod
    def _ensure_default_directories(cursor, knowledge_base_id: str, tenant_id: str, created_by: str) -> None:
        """Seed the initial template once; later tree edits are authoritative."""
        cursor.execute(
            "SELECT defaults_seeded FROM ai_knowledge_directory_state WHERE knowledge_base_id = ? AND tenant_id = ?",
            (knowledge_base_id, tenant_id),
        )
        if cursor.fetchone():
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            INSERT INTO ai_knowledge_directory_state
            (knowledge_base_id, tenant_id, defaults_seeded, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT (knowledge_base_id, tenant_id) DO NOTHING
            """,
            (knowledge_base_id, tenant_id, now_iso, now_iso),
        )
        if getattr(cursor, "rowcount", 1) == 0:
            return

        cursor.execute(
            "SELECT id, path FROM ai_knowledge_directory WHERE knowledge_base_id = ? AND tenant_id = ?",
            (knowledge_base_id, tenant_id),
        )
        existing = {str(row[1]): str(row[0]) for row in cursor.fetchall()}

        for root_order, root_name in enumerate(_DEFAULT_DIRECTORY_NAMES):
            root_id = existing.get(root_name)
            if not root_id:
                root_id = f"dir_{uuid.uuid4().hex[:12]}"
                cursor.execute(
                    """
                    INSERT INTO ai_knowledge_directory
                    (id, knowledge_base_id, tenant_id, parent_id, name, path, depth, is_system,
                     sort_order, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?, 0, 1, ?, ?, ?, ?)
                    """,
                    (root_id, knowledge_base_id, tenant_id, root_name, root_name, root_order, created_by, now_iso, now_iso),
                )
                existing[root_name] = root_id

            for vendor_order, vendor_name in enumerate(_DEFAULT_VENDOR_DIRECTORY_NAMES):
                vendor_path = f"{root_name}/{vendor_name}"
                if vendor_path in existing:
                    continue
                vendor_id = f"dir_{uuid.uuid4().hex[:12]}"
                cursor.execute(
                    """
                    INSERT INTO ai_knowledge_directory
                    (id, knowledge_base_id, tenant_id, parent_id, name, path, depth, is_system,
                     sort_order, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?)
                    """,
                    (vendor_id, knowledge_base_id, tenant_id, root_id, vendor_name, vendor_path, vendor_order, created_by, now_iso, now_iso),
                )
                existing[vendor_path] = vendor_id

    def list_knowledge_directories(
        self,
        knowledge_base_id: str,
        tenant_id: str = "tenant-default",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """Return a nested directory tree for one tenant knowledge base."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            self._ensure_default_directories(cursor, knowledge_base_id, tenant_id, created_by)
            conn.commit()
            cursor.execute(
                """
                SELECT id, knowledge_base_id, tenant_id, parent_id, name, path, depth,
                       is_system, sort_order, created_by, created_at, updated_at
                FROM ai_knowledge_directory
                WHERE knowledge_base_id = ? AND tenant_id = ?
                ORDER BY depth ASC, sort_order ASC, LOWER(name) ASC, name ASC
                """,
                (knowledge_base_id, tenant_id),
            )
            nodes = {str(row[0]): self._directory_node_from_row(row) for row in cursor.fetchall()}

        roots: List[Dict[str, Any]] = []
        for node in nodes.values():
            parent_id = node["parent_id"]
            if parent_id and str(parent_id) in nodes:
                nodes[str(parent_id)]["children"].append(node)
            else:
                roots.append(node)

        def sort_children(node: Dict[str, Any]) -> None:
            node["children"].sort(key=lambda child: (child["sort_order"], str(child["name"]).lower(), child["name"]))
            for child in node["children"]:
                sort_children(child)

        roots.sort(key=lambda node: (node["sort_order"], str(node["name"]).lower(), node["name"]))
        for root in roots:
            sort_children(root)
        return {"items": roots, "total": len(nodes)}

    def create_knowledge_directory(
        self,
        knowledge_base_id: str,
        name: str,
        parent_id: Optional[str] = None,
        tenant_id: str = "tenant-default",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """Create one root or child directory after validating tenant ownership."""
        directory_name = self._validate_directory_name(name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            self._ensure_default_directories(cursor, knowledge_base_id, tenant_id, created_by)

            parent: Optional[Any] = None
            if parent_id:
                cursor.execute(
                    """
                    SELECT id, path, depth
                    FROM ai_knowledge_directory
                    WHERE id = ? AND knowledge_base_id = ? AND tenant_id = ?
                    """,
                    (parent_id, knowledge_base_id, tenant_id),
                )
                parent = cursor.fetchone()
                if not parent:
                    raise ValueError("父目录不存在或无权访问")

            if parent:
                directory_path = f"{parent[1]}/{directory_name}"
                depth = int(parent[2] or 0) + 1
                sibling_sql = (
                    "SELECT id FROM ai_knowledge_directory "
                    "WHERE knowledge_base_id = ? AND tenant_id = ? AND parent_id = ? "
                    "AND LOWER(name) = LOWER(?)"
                )
                sibling_params = (knowledge_base_id, tenant_id, parent[0], directory_name)
            else:
                directory_path = directory_name
                depth = 0
                sibling_sql = (
                    "SELECT id FROM ai_knowledge_directory "
                    "WHERE knowledge_base_id = ? AND tenant_id = ? AND parent_id IS NULL "
                    "AND LOWER(name) = LOWER(?)"
                )
                sibling_params = (knowledge_base_id, tenant_id, directory_name)

            cursor.execute(sibling_sql, sibling_params)
            if cursor.fetchone():
                raise ValueError("同级目录已存在同名目录")

            if parent:
                cursor.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM ai_knowledge_directory WHERE knowledge_base_id = ? AND tenant_id = ? AND parent_id = ?",
                    (knowledge_base_id, tenant_id, parent[0]),
                )
            else:
                cursor.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) FROM ai_knowledge_directory WHERE knowledge_base_id = ? AND tenant_id = ? AND parent_id IS NULL",
                    (knowledge_base_id, tenant_id),
                )
            sort_order = int((cursor.fetchone() or [-1])[0] or -1) + 1
            now_iso = datetime.now(timezone.utc).isoformat()
            directory_id = f"dir_{uuid.uuid4().hex[:12]}"
            try:
                cursor.execute(
                    """
                    INSERT INTO ai_knowledge_directory
                    (id, knowledge_base_id, tenant_id, parent_id, name, path, depth, is_system,
                     sort_order, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (directory_id, knowledge_base_id, tenant_id, parent[0] if parent else None,
                     directory_name, directory_path, depth, sort_order, created_by, now_iso, now_iso),
                )
            except Exception as exc:
                conn.rollback()
                raise ValueError("目录已存在或无法创建") from exc
            conn.commit()
            cursor.execute(
                """
                SELECT id, knowledge_base_id, tenant_id, parent_id, name, path, depth,
                       is_system, sort_order, created_by, created_at, updated_at
                FROM ai_knowledge_directory WHERE id = ?
                """,
                (directory_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise RuntimeError("目录创建后无法读取")
            return self._directory_node_from_row(row)

    def rename_knowledge_directory(
        self,
        directory_id: str,
        name: str,
        tenant_id: str = "tenant-default",
    ) -> Dict[str, Any]:
        """Rename a directory and keep every descendant path consistent."""
        directory_name = self._validate_directory_name(name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, knowledge_base_id, tenant_id, parent_id, name, path, depth
                FROM ai_knowledge_directory
                WHERE id = ? AND tenant_id = ?
                """,
                (directory_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("目录不存在或无权访问")

            knowledge_base_id = row[1]
            parent_id = row[3]
            if parent_id:
                cursor.execute(
                    """
                    SELECT id FROM ai_knowledge_directory
                    WHERE knowledge_base_id = ? AND tenant_id = ? AND parent_id = ?
                      AND LOWER(name) = LOWER(?) AND id <> ?
                    """,
                    (knowledge_base_id, tenant_id, parent_id, directory_name, directory_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT id FROM ai_knowledge_directory
                    WHERE knowledge_base_id = ? AND tenant_id = ? AND parent_id IS NULL
                      AND LOWER(name) = LOWER(?) AND id <> ?
                    """,
                    (knowledge_base_id, tenant_id, directory_name, directory_id),
                )
            if cursor.fetchone():
                raise ValueError("同级目录已存在同名目录")

            old_path = str(row[5])
            parent_path = old_path.rsplit("/", 1)[0] if "/" in old_path else ""
            new_path = f"{parent_path}/{directory_name}" if parent_path else directory_name
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "SELECT id, path FROM ai_knowledge_directory WHERE knowledge_base_id = ? AND tenant_id = ? AND (path = ? OR path LIKE ?)",
                (knowledge_base_id, tenant_id, old_path, f"{old_path}/%"),
            )
            descendants = cursor.fetchall()
            try:
                for descendant_id, descendant_path in sorted(descendants, key=lambda item: str(item[1]).count("/")):
                    descendant_path = str(descendant_path)
                    suffix = descendant_path[len(old_path):]
                    replacement_path = f"{new_path}{suffix}"
                    if str(descendant_id) == str(directory_id):
                        cursor.execute(
                            "UPDATE ai_knowledge_directory SET name = ?, path = ?, updated_at = ? WHERE id = ?",
                            (directory_name, replacement_path, now_iso, descendant_id),
                        )
                    else:
                        cursor.execute(
                            "UPDATE ai_knowledge_directory SET path = ?, updated_at = ? WHERE id = ?",
                            (replacement_path, now_iso, descendant_id),
                        )
            except Exception as exc:
                conn.rollback()
                raise ValueError("目录重命名失败，可能存在路径冲突") from exc
            conn.commit()
            cursor.execute(
                """
                SELECT id, knowledge_base_id, tenant_id, parent_id, name, path, depth,
                       is_system, sort_order, created_by, created_at, updated_at
                FROM ai_knowledge_directory WHERE id = ?
                """,
                (directory_id,),
            )
            renamed = cursor.fetchone()
            if not renamed:
                raise RuntimeError("目录重命名后无法读取")
            return self._directory_node_from_row(renamed)

    def delete_knowledge_directory(self, directory_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
        """Delete one directory and all of its descendants, leaving documents intact."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, knowledge_base_id, path FROM ai_knowledge_directory WHERE id = ? AND tenant_id = ?",
                (directory_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("目录不存在或无权访问")
            knowledge_base_id, directory_path = row[1], str(row[2])
            cursor.execute(
                "SELECT id FROM ai_knowledge_directory WHERE knowledge_base_id = ? AND tenant_id = ? AND (path = ? OR path LIKE ?) ORDER BY depth DESC",
                (knowledge_base_id, tenant_id, directory_path, f"{directory_path}/%"),
            )
            ids = [item[0] for item in cursor.fetchall()]
            for item_id in ids:
                cursor.execute("DELETE FROM ai_knowledge_directory WHERE id = ?", (item_id,))
            conn.commit()
            return {"deleted_count": len(ids), "directory_id": directory_id}

    def get_knowledge_stats(self, tenant_id: str = "tenant-default") -> Dict[str, Any]:
        """Return metrics: total_documents, total_chunks, total_vendors, ready_indexes."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            scope = "COALESCE(tenant_id, 'tenant-default') IN (?, 'tenant-default')"
            cursor.execute(f"SELECT COUNT(*) FROM ai_document WHERE status = 'active' AND {scope}", (tenant_id,))
            total_docs = (cursor.fetchone() or [0])[0]

            cursor.execute(
                "SELECT COUNT(*) FROM ai_document_chunk c "
                "JOIN ai_document d ON d.id = c.document_id "
                f"WHERE d.status = 'active' AND {scope.replace('tenant_id', 'd.tenant_id')}",
                (tenant_id,),
            )
            total_chunks = (cursor.fetchone() or [0])[0]

            cursor.execute(
                f"SELECT COUNT(DISTINCT vendor) FROM ai_document WHERE status = 'active' "
                f"AND vendor IS NOT NULL AND vendor != 'all' AND {scope}",
                (tenant_id,),
            )
            total_vendors = (cursor.fetchone() or [0])[0]

            return {
                "total_documents": total_docs,
                "total_chunks": total_chunks,
                "total_vendors": total_vendors,
                "ready_indexes": total_docs,
            }

    def list_asset_vendor_platform_options(self) -> Dict[str, Any]:
        """Return the vendor/platform combinations currently present in asset inventory."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT TRIM(vendor), TRIM(platform), COUNT(*) "
                "FROM physical_assets "
                "WHERE asset_type = ? "
                "AND TRIM(COALESCE(vendor, '')) <> '' "
                "AND TRIM(COALESCE(platform, '')) <> '' "
                "GROUP BY TRIM(vendor), TRIM(platform) "
                "ORDER BY LOWER(TRIM(vendor)), LOWER(TRIM(platform))",
                ("network_device",),
            )
            vendors: Dict[str, Dict[str, Any]] = {}
            asset_count = 0
            for row in cursor.fetchall():
                vendor = str(row[0] or '').strip()
                platform = str(row[1] or '').strip()
                count = int(row[2] or 0)
                if not vendor or not platform:
                    continue
                vendor_option = vendors.setdefault(
                    vendor,
                    {"value": vendor, "label": vendor, "platforms": []},
                )
                vendor_option["platforms"].append(
                    {"value": platform, "label": platform, "asset_count": count}
                )
                asset_count += count

            return {
                "source": "physical_assets",
                "asset_count": asset_count,
                "vendors": list(vendors.values()),
            }

    def list_documents(
        self,
        knowledge_source_type: Optional[str] = None,
        directory_path: Optional[str] = None,
        knowledge_scope: Optional[str] = None,
        tenant_id: str = "tenant-default",
        search: str = "",
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
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """List tenant-safe document summaries with semantic server-side filtering.

        The physical ``kb_import`` path is an internal storage detail.  It is
        accepted only as a server-side directory selector and is never copied
        into the response summary.  Semantic filters use relational columns
        when present so PostgreSQL can use the metadata indexes created by the
        V2 migrations; legacy rows without a column simply fail closed for
        that filter instead of falling back to an unbounded scan.
        """
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        requested_page = max(int(page or 1), 1)
        sort_columns = {
            "created_at": "d.created_at",
            "name": "d.name",
            "vendor": "d.vendor",
            "platform": "d.platform",
            "status": "d.status",
            "chunk_count": "chunk_count",
        }
        sort_column = sort_columns.get(str(sort_by or "created_at").strip().lower(), "d.created_at")
        sort_direction = "ASC" if str(sort_order or "desc").strip().lower() == "asc" else "DESC"
        search_term = (search or "").strip().lower()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            document_columns = self._table_columns(cursor, "ai_document")
            where = [
                "(d.tenant_id = ? OR d.tenant_id = 'tenant-default')",
            ]
            params: List[Any] = [tenant_id]
            normalized_status = str(status or "active").strip().lower()
            allowed_statuses = {"active", "draft", "published", "quarantined", "superseded", "disabled", "all"}
            if normalized_status not in allowed_statuses:
                normalized_status = "active"
            if normalized_status != "all":
                where.append("d.status = ?")
                params.append(normalized_status)
            if knowledge_source_type:
                where.append("d.knowledge_source_type = ?")
                params.append(knowledge_source_type)
            normalized_scope = str(knowledge_scope or "").strip().lower()
            scope_types = {
                "official": _OFFICIAL_KNOWLEDGE_TYPES,
                "enterprise": _ENTERPRISE_KNOWLEDGE_TYPES,
            }.get(normalized_scope)
            if scope_types:
                where.append(f"d.knowledge_source_type IN ({', '.join('?' for _ in scope_types)})")
                params.extend(scope_types)
            if directory_path and directory_path.strip():
                # Directory paths are persisted inside metadata_json.  Keep
                # this portable across PostgreSQL/SQLite and tolerate the
                # minimal legacy test schema that has no metadata column.
                if "metadata_json" in document_columns:
                    normalized_directory_path = directory_path.strip().strip("/").lower()
                    # metadata_json is JSONB on PostgreSQL after migration
                    # 0113 and TEXT on legacy/SQLite installations.
                    # New documents store only the semantic directory path;
                    # the legacy kb_import prefix remains readable for
                    # existing rows during the migration window.
                    where.append(
                        "(LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ? "
                        "OR LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ?)"
                    )
                    params.extend([
                        f"%{normalized_directory_path}%",
                        f"%kb_import/{normalized_directory_path}%",
                    ])
                else:
                    where.append("1 = 0")
            semantic_filters = {
                "vendor": vendor,
                "product_family": product_family,
                "product_series": product_series,
                "product_model": product_model,
                "os_family": os_family,
                "os_generation": os_generation,
                "software_train": software_train,
                "software_release": software_release,
            "cli_platform": cli_platform,
            # Keep the caller's value here so the query helper can match both
            # canonical categories and legacy directory ids during migration.
            "document_category": document_category,
            "feature_domain": feature_domain,
            "source_trust_level": source_trust_level,
            }
            for column, value in semantic_filters.items():
                normalized_value = str(value or "").strip().lower()
                if not normalized_value:
                    continue
                if column not in document_columns:
                    where.append("1 = 0")
                    continue
                if column == "document_category":
                    category_values = document_category_query_values(value)
                    if not category_values:
                        where.append("1 = 0")
                        continue
                    placeholders = ", ".join("?" for _ in category_values)
                    where.append(f"LOWER(COALESCE(d.{column}, '')) IN ({placeholders})")
                    params.extend(category_values)
                    continue
                where.append(f"LOWER(COALESCE(d.{column}, '')) = ?")
                params.append(normalized_value)
            if search_term:
                search_clauses = [
                    "LOWER(COALESCE(d.name, '')) LIKE ?",
                    "LOWER(COALESCE(d.vendor, '')) LIKE ?",
                    "LOWER(COALESCE(d.platform, '')) LIKE ?",
                ]
                if "metadata_json" in document_columns:
                    search_clauses.append("LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ?")
                where.append(f"({' OR '.join(search_clauses)})")
                search_pattern = f"%{search_term}%"
                params.extend([search_pattern] * len(search_clauses))

            where_sql = " AND ".join(where)
            cursor.execute(f"SELECT COUNT(*) FROM ai_document d WHERE {where_sql}", params)
            total = int((cursor.fetchone() or [0])[0] or 0)
            total_pages = max(1, (total + safe_page_size - 1) // safe_page_size)
            current_page = min(requested_page, total_pages)
            offset = (current_page - 1) * safe_page_size

            query = (
                "SELECT d.id, d.knowledge_base_id, d.name, d.source, d.vendor, d.platform, "
                "d.status, d.knowledge_source_type, d.tenant_id, d.acl_json, d.source_trust_level, "
                "d.created_at, COUNT(c.id) AS chunk_count "
                "FROM ai_document d "
                "LEFT JOIN ai_document_chunk c ON c.document_id = d.id "
                f"WHERE {where_sql} "
                "GROUP BY d.id, d.knowledge_base_id, d.name, d.source, d.vendor, d.platform, "
                "d.status, d.knowledge_source_type, d.tenant_id, d.acl_json, d.source_trust_level, d.created_at "
                f"ORDER BY {sort_column} {sort_direction}, d.id ASC LIMIT ? OFFSET ?"
            )
            cursor.execute(query, [*params, safe_page_size, offset])
            rows = cursor.fetchall()

            semantic_lookup: Dict[str, Dict[str, Any]] = {}
            semantic_fields = (
                "document_id", "document_category", "product_family", "product_series",
                "product_model", "os_family", "os_generation", "software_train",
                "software_release", "cli_platform", "feature_domain", "feature",
                "subfeature", "risk_level", "verification_level", "rag_priority",
                "metadata_parse_status", "exclude_from_rag",
            )
            available_semantic = [field for field in semantic_fields if field in document_columns]
            if available_semantic and rows:
                placeholders = ", ".join("?" for _ in rows)
                cursor.execute(
                    f"SELECT id, {', '.join(available_semantic)} FROM ai_document "
                    f"WHERE id IN ({placeholders})",
                    [row[0] for row in rows],
                )
                for semantic_row in cursor.fetchall():
                    semantic_lookup[str(semantic_row[0])] = {
                        field: semantic_row[index + 1] for index, field in enumerate(available_semantic)
                    }

            results = []
            for r in rows:
                semantic = semantic_lookup.get(str(r[0]), {})
                results.append({
                    "id": r[0],
                    "knowledge_base_id": r[1],
                    "name": r[2],
                    "source": r[3],
                    "vendor": r[4],
                    "platform": r[5] or semantic.get("cli_platform"),
                    "cli_platform": semantic.get("cli_platform"),
                    "document_id": semantic.get("document_id"),
                    "document_category": semantic.get("document_category"),
                    "product_family": semantic.get("product_family"),
                    "product_series": semantic.get("product_series"),
                    "product_model": semantic.get("product_model"),
                    "os_family": semantic.get("os_family"),
                    "os_generation": semantic.get("os_generation"),
                    "software_train": semantic.get("software_train"),
                    "software_release": semantic.get("software_release"),
                    "feature_domain": semantic.get("feature_domain"),
                    "feature": semantic.get("feature"),
                    "subfeature": semantic.get("subfeature"),
                    "risk_level": semantic.get("risk_level"),
                    "verification_level": semantic.get("verification_level"),
                    "rag_priority": semantic.get("rag_priority"),
                    "metadata_parse_status": semantic.get("metadata_parse_status"),
                    "exclude_from_rag": bool(semantic.get("exclude_from_rag")),
                    "status": r[6],
                    "knowledge_source_type": r[7] or "user_document",
                    "tenant_id": r[8] or "tenant-default",
                    "acl": parse_acl(r[9]),
                    "source_trust_level": r[10] or "untrusted",
                    "created_at": r[11],
                    "chunk_count": int(r[12] or 0),
                })
            return {
                "items": results,
                "total": total,
                "page": current_page,
                "page_size": safe_page_size,
                "total_pages": total_pages,
            }

    def list_document_facets(
        self,
        *,
        tenant_id: str = "tenant-default",
        knowledge_source_type: Optional[str] = None,
        directory_path: Optional[str] = None,
        knowledge_scope: Optional[str] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """Return bounded Vendor/Family/Series browse facets without bodies."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            document_columns = self._table_columns(cursor, "ai_document")
            required = {"vendor", "product_family", "product_series", "metadata_json"}
            if not required <= document_columns:
                return {"vendors": [], "families": [], "series": []}
            where = ["(d.tenant_id = ? OR d.tenant_id = 'tenant-default')"]
            params: List[Any] = [tenant_id]
            normalized_status = str(status or "active").strip().lower()
            if normalized_status not in {"active", "draft", "published", "quarantined", "superseded", "disabled", "all"}:
                normalized_status = "active"
            if normalized_status != "all":
                where.append("d.status = ?")
                params.append(normalized_status)
            if knowledge_source_type:
                where.append("d.knowledge_source_type = ?")
                params.append(knowledge_source_type)
            normalized_scope = str(knowledge_scope or "").strip().lower()
            scope_types = {
                "official": _OFFICIAL_KNOWLEDGE_TYPES,
                "enterprise": _ENTERPRISE_KNOWLEDGE_TYPES,
            }.get(normalized_scope)
            if scope_types:
                where.append(f"d.knowledge_source_type IN ({', '.join('?' for _ in scope_types)})")
                params.extend(scope_types)
            if directory_path and directory_path.strip():
                normalized_path = directory_path.strip().strip("/").lower()
                where.append(
                    "(LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ? "
                    "OR LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ?)"
                )
                params.extend([f"%{normalized_path}%", f"%kb_import/{normalized_path}%"])
            cursor.execute(
                "SELECT d.vendor, d.product_family, d.product_series, COUNT(*) "
                "FROM ai_document d WHERE " + " AND ".join(where) +
                " GROUP BY d.vendor, d.product_family, d.product_series "
                "ORDER BY LOWER(COALESCE(d.vendor, '')), LOWER(COALESCE(d.product_family, '')), LOWER(COALESCE(d.product_series, '')) "
                "LIMIT 500",
                params,
            )
            vendors: Dict[str, int] = {}
            families: Dict[str, int] = {}
            series: Dict[str, int] = {}
            for vendor, family, product_series, count in cursor.fetchall():
                vendor_value = str(vendor or "UNKNOWN").strip() or "UNKNOWN"
                family_value = str(family or "UNKNOWN").strip() or "UNKNOWN"
                series_value = str(product_series or "UNKNOWN").strip() or "UNKNOWN"
                vendors[vendor_value] = vendors.get(vendor_value, 0) + int(count or 0)
                families[family_value] = families.get(family_value, 0) + int(count or 0)
                series[series_value] = series.get(series_value, 0) + int(count or 0)
            return {
                "vendors": [{"value": key, "count": value} for key, value in vendors.items()],
                "families": [{"value": key, "count": value} for key, value in families.items()],
                "series": [{"value": key, "count": value} for key, value in series.items()],
            }

    def get_document_detail(
        self,
        doc_id: str,
        tenant_id: str = "tenant-default",
        *,
        include_inactive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return one document's on-demand body, provenance and ordered chunks.

        The legacy ``ai_document`` table is still the V1-compatible index
        projection.  When the canonical V2 version tables contain a matching
        document id, their immutable version rows are joined into the detail
        response; otherwise the response explicitly returns an empty history
        instead of inventing lineage.
        """
        with get_db_connection() as conn:
            cursor = conn.cursor()
            document_columns = self._table_columns(cursor, "ai_document")
            base_columns = [
                "id", "knowledge_base_id", "name", "source", "vendor", "platform",
                "status", "knowledge_source_type", "tenant_id", "acl_json",
                "source_trust_level", "created_at", "updated_at",
            ]
            optional_columns = [
                "document_id", "original_content", "normalized_content", "metadata_json",
                "document_version", "index_version", "parser_version",
                "retrieval_index_version", "metadata_parse_status",
            ]
            selected_optional = [field for field in optional_columns if field in document_columns]
            status_clause = "" if include_inactive else " AND d.status = 'active'"
            cursor.execute(
                f"SELECT {', '.join(f'd.{field}' for field in base_columns + selected_optional)} "
                "FROM ai_document d "
                f"WHERE d.id = ?{status_clause} "
                "AND (d.tenant_id = ? OR d.tenant_id = 'tenant-default')",
                (doc_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            row_values = dict(zip(base_columns + selected_optional, row))
            metadata_value: Dict[str, Any] = {}
            raw_metadata = row_values.get("metadata_json")
            if isinstance(raw_metadata, dict):
                metadata_value = raw_metadata
            elif raw_metadata:
                try:
                    decoded_metadata = json.loads(str(raw_metadata))
                    if isinstance(decoded_metadata, dict):
                        metadata_value = decoded_metadata
                except (TypeError, ValueError):
                    metadata_value = {}

            chunk_columns = self._table_columns(cursor, "ai_document_chunk")
            chunk_detail_fields = (
                "id", "page", "section", "content", "created_at", "parent_chunk_id",
                "chunk_role", "chunk_type", "ordinal", "metadata_json", "heading_path_json",
                "token_count", "content_hash", "source_locator_json", "chunking_version",
                "document_version", "index_version", "parser_version", "neighbor_chunk_ids_json",
                "is_retrieval_candidate",
            )
            selected_chunk_fields = [field for field in chunk_detail_fields if field in chunk_columns]
            chunk_select = ", ".join(
                f"c.{field} AS {field}" for field in selected_chunk_fields
            )
            order_terms = []
            if "ordinal" in chunk_columns:
                order_terms.append("COALESCE(c.ordinal, 0) ASC")
            if "page" in chunk_columns:
                order_terms.append("COALESCE(c.page, 0) ASC")
            order_terms.extend(["c.created_at ASC", "c.id ASC"])
            cursor.execute(
                f"SELECT {chunk_select} FROM ai_document_chunk c "
                "WHERE c.document_id = ? "
                f"ORDER BY {', '.join(order_terms)}",
                (doc_id,),
            )
            raw_chunk_rows = cursor.fetchall()
            chunk_records: list[dict[str, Any]] = []
            for index, raw_chunk in enumerate(raw_chunk_rows):
                values = dict(zip(selected_chunk_fields, raw_chunk))
                chunk_metadata = _decode_json_value(values.get("metadata_json"), {})
                if not isinstance(chunk_metadata, dict):
                    chunk_metadata = {}
                heading_path = _decode_json_value(values.get("heading_path_json"), [])
                if not isinstance(heading_path, list):
                    heading_path = []
                source_locator = _decode_json_value(values.get("source_locator_json"), {})
                if not isinstance(source_locator, dict):
                    source_locator = {}
                neighbor_ids = _decode_json_value(values.get("neighbor_chunk_ids_json"), [])
                if not isinstance(neighbor_ids, list):
                    neighbor_ids = []
                chunk_records.append({
                    "id": values.get("id"),
                    "page": int(values.get("page") or index + 1),
                    "section": values.get("section") or "General Overview",
                    "content": str(values.get("content") or "")[:_CHUNK_DETAIL_MAX_TEXT],
                    "created_at": values.get("created_at"),
                    "parent_chunk_id": values.get("parent_chunk_id"),
                    "chunk_role": values.get("chunk_role") or "standalone",
                    "chunk_type": values.get("chunk_type") or "concept",
                    "ordinal": int(values.get("ordinal") or index),
                    "metadata": _safe_chunk_detail_value(chunk_metadata),
                    "heading_path": _safe_chunk_detail_value(heading_path),
                    "token_count": int(values.get("token_count") or 0),
                    "content_hash": values.get("content_hash"),
                    "source_locator": _safe_chunk_detail_value(source_locator),
                    "chunking_version": values.get("chunking_version"),
                    "document_version": values.get("document_version") or row_values.get("document_version"),
                    "index_version": values.get("index_version") or row_values.get("index_version"),
                    "parser_version": values.get("parser_version") or row_values.get("parser_version"),
                    "neighbor_chunk_ids": [str(item) for item in neighbor_ids[:8] if item not in (None, "")],
                    "is_retrieval_candidate": bool(values.get("is_retrieval_candidate", 1)),
                })
            chunk_by_id = {str(item.get("id")): item for item in chunk_records if item.get("id")}

            def compact_chunk(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
                if not item:
                    return None
                return {
                    "id": item.get("id"),
                    "page": item.get("page"),
                    "section": item.get("section"),
                    "ordinal": item.get("ordinal"),
                    "chunk_role": item.get("chunk_role"),
                    "content": str(item.get("content") or "")[:_CHUNK_DETAIL_MAX_TEXT],
                }

            chunks = []
            for index, item in enumerate(chunk_records):
                explicit_neighbors = [
                    chunk_by_id[neighbor_id]
                    for neighbor_id in item.get("neighbor_chunk_ids", [])
                    if neighbor_id in chunk_by_id and neighbor_id != str(item.get("id"))
                ]
                if not explicit_neighbors:
                    explicit_neighbors = [
                        candidate for candidate in (
                            chunk_records[index - 1] if index > 0 else None,
                            chunk_records[index + 1] if index + 1 < len(chunk_records) else None,
                        ) if candidate is not None
                    ]
                enriched = dict(item)
                enriched["parent_chunk"] = compact_chunk(chunk_by_id.get(str(item.get("parent_chunk_id") or "")))
                enriched["neighbors"] = [compact_chunk(neighbor) for neighbor in explicit_neighbors[:2]]
                enriched.pop("neighbor_chunk_ids", None)
                chunks.append(enriched)

            source_version_history: List[Dict[str, Any]] = []
            raw_sources: List[Dict[str, Any]] = []
            canonical_document_id = str(row_values.get("document_id") or doc_id)
            canonical_tables_ready = False
            try:
                cursor.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() "
                    "AND table_name IN ('kb_document', 'kb_document_version', 'kb_document_source')"
                )
                canonical_tables_ready = len(cursor.fetchall()) == 3
            except Exception:
                try:
                    cursor.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                        "AND name IN ('kb_document', 'kb_document_version', 'kb_document_source')"
                    )
                    canonical_tables_ready = int((cursor.fetchone() or [0])[0] or 0) == 3
                except Exception:
                    canonical_tables_ready = False
            if canonical_tables_ready:
                cursor.execute(
                    "SELECT id, source_uri, canonical_key, source_registry_id, current_version_id "
                    "FROM kb_document WHERE tenant_id = ? AND id = ?",
                    (tenant_id, canonical_document_id),
                )
                canonical_row = cursor.fetchone()
                if canonical_row:
                    canonical_id = str(canonical_row[0])
                    cursor.execute(
                        "SELECT id, version_no, source_version_id, content_hash, status, "
                        "lifecycle_status, mime_type, byte_size, created_at, updated_at "
                        "FROM kb_document_version WHERE tenant_id = ? AND document_id = ? "
                        "ORDER BY version_no DESC",
                        (tenant_id, canonical_id),
                    )
                    source_version_history = [
                        {
                            "id": version[0],
                            "version_no": int(version[1] or 0),
                            "source_version_id": version[2],
                            "content_hash": version[3],
                            "status": version[4],
                            "lifecycle_status": version[5],
                            "mime_type": version[6],
                            "byte_size": int(version[7] or 0),
                            "created_at": version[8],
                            "updated_at": version[9],
                        }
                        for version in cursor.fetchall()
                    ]
                    cursor.execute(
                        "SELECT canonical_url, source_registry_id, source_version_id, status, observed_at "
                        "FROM kb_document_source WHERE tenant_id = ? AND document_id = ? "
                        "ORDER BY observed_at DESC",
                        (tenant_id, canonical_id),
                    )
                    raw_sources = [
                        {
                            "canonical_url": source[0],
                            "source_registry_id": source[1],
                            "source_version_id": source[2],
                            "status": source[3],
                            "observed_at": source[4],
                        }
                        for source in cursor.fetchall()
                    ]

            return {
                "id": row_values["id"],
                "knowledge_base_id": row_values["knowledge_base_id"],
                "name": row_values["name"],
                "source": row_values["source"],
                "vendor": row_values["vendor"],
                "platform": row_values["platform"],
                "status": row_values["status"],
                "knowledge_source_type": row_values["knowledge_source_type"] or "user_document",
                "tenant_id": row_values["tenant_id"] or "tenant-default",
                "acl": parse_acl(row_values["acl_json"]),
                "source_trust_level": row_values["source_trust_level"] or "untrusted",
                "created_at": row_values["created_at"],
                "updated_at": row_values["updated_at"],
                "document_id": row_values.get("document_id"),
                "original_content": row_values.get("original_content") or "",
                "normalized_content": row_values.get("normalized_content") or "",
                "metadata": _safe_chunk_detail_value(metadata_value),
                "document_version": row_values.get("document_version"),
                "index_version": row_values.get("index_version") or row_values.get("retrieval_index_version"),
                "parser_version": row_values.get("parser_version"),
                "metadata_parse_status": row_values.get("metadata_parse_status"),
                "raw_source": {
                    "source": row_values["source"],
                    "references": raw_sources,
                },
                "source_version_history": source_version_history,
                "chunk_count": len(chunks),
                "chunks": chunks,
            }

    def clear_sample_knowledge(self, tenant_id: str = "tenant-default") -> Dict[str, Any]:
        """Delete all documents and chunks tagged as sample."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM ai_document WHERE knowledge_source_type = 'sample' "
                "AND COALESCE(tenant_id, 'tenant-default') = ?",
                (tenant_id,),
            )
            doc_ids = [r[0] for r in cursor.fetchall()]
            
            for doc_id in doc_ids:
                cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
                cursor.execute("DELETE FROM ai_document WHERE id = ?", (doc_id,))
            
            conn.commit()
            retrieval_cache.invalidate_documents(doc_ids)
            return {"deleted_count": len(doc_ids)}

    def delete_document(self, doc_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
        """Delete a single document and its chunks by ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM ai_document WHERE id = ? "
                "AND COALESCE(tenant_id, 'tenant-default') = ?",
                (doc_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                return {"deleted": False, "error": "文档不存在"}
            
            cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
            cursor.execute("DELETE FROM ai_document WHERE id = ?", (doc_id,))
            conn.commit()
            retrieval_cache.invalidate_documents([doc_id])
            return {"deleted": True, "id": doc_id}

    def batch_delete_documents(self, doc_ids: List[str], tenant_id: str = "tenant-default") -> Dict[str, Any]:
        """Delete multiple documents and their chunks by IDs."""
        if not doc_ids:
            return {"deleted_count": 0}
        with get_db_connection() as conn:
            cursor = conn.cursor()
            deleted = 0
            for doc_id in doc_ids:
                cursor.execute(
                    "SELECT id FROM ai_document WHERE id = ? "
                    "AND COALESCE(tenant_id, 'tenant-default') = ?",
                    (doc_id, tenant_id),
                )
                if cursor.fetchone():
                    cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
                    cursor.execute("DELETE FROM ai_document WHERE id = ?", (doc_id,))
                    deleted += 1
            conn.commit()
            retrieval_cache.invalidate_documents(doc_ids)
            return {"deleted_count": deleted, "requested": len(doc_ids)}

    @staticmethod
    def _safe_action_text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
        text = str(value or "").strip()
        if (required and not text) or len(text) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise KnowledgeDocumentActionError("KNOWLEDGE_ACTION_INPUT_INVALID", f"{field} is invalid")
        return text

    @staticmethod
    def _action_json(value: Dict[str, Any]) -> Any:
        return _json_db_value(value)

    @staticmethod
    def _write_action_audit(
        *,
        action_id: str,
        action: str,
        document_id: str,
        tenant_id: str,
        actor_id: str,
        actor_username: str,
        status: str,
        impact: Dict[str, Any],
        reason: str,
        job_id: str | None = None,
    ) -> None:
        """Write metadata-only audit evidence without exposing source text."""
        try:
            from services.audit_service import log_audit_event

            log_audit_event(
                event_type=f"knowledge_document_{action}",
                category="knowledge_document",
                severity="warning" if action in {"delete", "disable"} else "info",
                status="success" if status == "succeeded" else "open",
                summary=f"Knowledge document action {action} {status}",
                actor_id=actor_id,
                actor_username=actor_username,
                actor_role="knowledge_admin",
                target_type="ai_document",
                target_id=document_id,
                job_id=job_id,
                details={
                    "action_id": action_id,
                    "tenant_id": tenant_id,
                    "action": action,
                    "status": status,
                    "reason": reason,
                    "impact": impact,
                },
            )
        except Exception:
            # The dedicated action ledger is the authoritative evidence.  A
            # legacy audit provider must not make a durable document action
            # appear to have failed or leak an implementation error.
            return

    @staticmethod
    def _table_exists(cursor, table_name: str) -> bool:
        """Check an optional canonical table without aborting a PG transaction."""
        try:
            cursor.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table_name,),
            )
            return cursor.fetchone() is not None
        except Exception:
            try:
                cursor.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table_name,),
                )
                return cursor.fetchone() is not None
            except Exception:
                return False

    def _document_action_impact(self, cursor, row_values: Dict[str, Any]) -> Dict[str, Any]:
        doc_id = str(row_values.get("id") or "")
        chunk_row = cursor.execute(
            "SELECT COUNT(*) FROM ai_document_chunk WHERE document_id = ?",
            (doc_id,),
        ).fetchone()
        chunk_count = int((chunk_row[0] if chunk_row else 0) or 0)
        canonical_document_id = str(row_values.get("document_id") or doc_id)
        source_references = 0
        version_references = 0
        reference_details: list[Dict[str, Any]] = []
        if self._table_exists(cursor, "kb_document_source"):
            source_references = int((cursor.execute(
                "SELECT COUNT(*) FROM kb_document_source WHERE tenant_id = ? AND document_id = ?",
                (str(row_values.get("tenant_id") or "tenant-default"), canonical_document_id),
            ).fetchone() or [0])[0] or 0)
            if source_references:
                reference_details.append({"type": "source_observation", "count": source_references})
        if self._table_exists(cursor, "kb_document_version"):
            version_references = int((cursor.execute(
                "SELECT COUNT(*) FROM kb_document_version WHERE tenant_id = ? AND document_id = ?",
                (str(row_values.get("tenant_id") or "tenant-default"), canonical_document_id),
            ).fetchone() or [0])[0] or 0)
            if version_references:
                reference_details.append({"type": "document_version", "count": version_references})
        references = source_references + version_references
        return {
            "documents": 1,
            "chunks": chunk_count,
            "indexes": chunk_count,
            "references": references,
            "reference_details": reference_details,
            "reference_scope": "kb_document_source_and_kb_document_version" if self._table_exists(cursor, "kb_document_source") or self._table_exists(cursor, "kb_document_version") else "legacy_ai_document_has_no_reference_graph",
        }

    def get_document_action_impact(self, *, doc_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
        """Return a safe, read-only impact/recovery preview before confirmation."""
        doc_id = self._safe_action_text(doc_id, field="document_id", maximum=256, required=True)
        tenant_id = self._safe_action_text(tenant_id or "tenant-default", field="tenant_id", maximum=256, required=True)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id, name, status, tenant_id, document_id FROM ai_document "
                "WHERE id = ? AND COALESCE(tenant_id, 'tenant-default') = ?",
                (doc_id, tenant_id),
            ).fetchone()
            if not row:
                raise KnowledgeDocumentActionError("KNOWLEDGE_DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
            row_values = dict(row) if hasattr(row, "keys") else {
                "id": row[0], "name": row[1], "status": row[2], "tenant_id": row[3], "document_id": row[4],
            }
            impact = self._document_action_impact(cursor, row_values)
            return {
                "document_id": doc_id,
                "name": str(row_values.get("name") or ""),
                "current_status": str(row_values.get("status") or "active"),
                "impact": impact,
                "recovery": {
                    "disable": "POST /api/ai/assistant/documents/{id}/actions/enable",
                    "enable": "POST /api/ai/assistant/documents/{id}/actions/disable",
                    "reparse": "rechunk or reindex the same document if body/index becomes stale",
                    "rechunk": "reindex the same document if embedding/index repair is required",
                    "reindex": "retry the returned tenant-scoped job",
                    "delete": "restore from the approved PostgreSQL backup; no in-place undelete",
                },
                "safe_to_confirm": True,
            }

    def execute_document_action(
        self,
        *,
        doc_id: str,
        action: str,
        tenant_id: str = "tenant-default",
        actor_id: str = "system",
        actor_username: str = "system",
        confirm: bool = False,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Execute one explicitly confirmed, tenant-scoped document action.

        Delete/disable/enable are committed in one transaction with the
        action ledger.  Reparse/rechunk/reindex create a tenant-scoped job
        carrying the action id; the worker owns the subsequent transactional
        document/chunk replacement.
        """
        action = self._safe_action_text(action, field="action", maximum=32, required=True).lower()
        if action not in _DOCUMENT_ACTIONS:
            raise KnowledgeDocumentActionError("KNOWLEDGE_ACTION_NOT_ALLOWED", "document action is not allowed")
        doc_id = self._safe_action_text(doc_id, field="document_id", maximum=256, required=True)
        tenant_id = self._safe_action_text(tenant_id or "tenant-default", field="tenant_id", maximum=256, required=True)
        actor_id = self._safe_action_text(actor_id or "system", field="actor_id", maximum=256, required=True)
        actor_username = self._safe_action_text(actor_username or actor_id, field="actor_username", maximum=256, required=True)
        reason = self._safe_action_text(reason, field="reason", maximum=1024)
        if not confirm:
            raise KnowledgeDocumentActionError(
                "KNOWLEDGE_ACTION_CONFIRMATION_REQUIRED",
                "explicit confirmation is required for this document action",
                status_code=409,
            )

        action_id = f"kda_{uuid.uuid4().hex[:20]}"
        now = datetime.now(timezone.utc).isoformat()
        pending_job: Dict[str, Any] | None = None
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id, name, status, tenant_id FROM ai_document "
                "WHERE id = ? AND COALESCE(tenant_id, 'tenant-default') = ?",
                (doc_id, tenant_id),
            ).fetchone()
            if not row:
                raise KnowledgeDocumentActionError("KNOWLEDGE_DOCUMENT_NOT_FOUND", "document was not found", status_code=404)
            row_values = dict(row) if hasattr(row, "keys") else {
                "id": row[0], "name": row[1], "status": row[2], "tenant_id": row[3],
            }
            impact = self._document_action_impact(cursor, row_values)
            recovery = {
                "disable": "POST /api/ai/assistant/documents/{id}/actions/enable",
                "enable": "POST /api/ai/assistant/documents/{id}/actions/disable",
                "reparse": "rechunk or reindex the same document if body/index becomes stale",
                "rechunk": "reindex the same document if embedding/index repair is required",
                "reindex": "retry the returned tenant-scoped job",
                "delete": "restore from the approved PostgreSQL backup; no in-place undelete",
            }[action]
            queued = action in {"reparse", "rechunk", "reindex"}
            cursor.execute(
                """INSERT INTO ai_knowledge_document_action
                (id, tenant_id, document_id, action, status, confirmed, actor_id,
                 actor_username, reason, impact_json, recovery_json, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                (
                    action_id, tenant_id, doc_id, action, "queued" if queued else "running",
                    actor_id, actor_username, reason, self._action_json(impact),
                    self._action_json({"recovery": recovery}), now,
                ),
            )
            if action in {"disable", "enable"}:
                target = "disabled" if action == "disable" else "active"
                current = str(row_values.get("status") or "active")
                if current != target:
                    cursor.execute(
                        "UPDATE ai_document SET status = ?, updated_at = ? WHERE id = ? "
                        "AND COALESCE(tenant_id, 'tenant-default') = ?",
                        (target, now, doc_id, tenant_id),
                    )
                cursor.execute(
                    "UPDATE ai_knowledge_document_action SET status = 'succeeded', completed_at = ? WHERE id = ?",
                    (now, action_id),
                )
                conn.commit()
                result = {
                    "action_id": action_id,
                    "action": action,
                    "document_id": doc_id,
                    "status": "succeeded",
                    "idempotent": current == target,
                    "previous_status": current,
                    "current_status": target,
                    "impact": impact,
                    "recovery": {"recovery": recovery},
                }
                self._write_action_audit(
                    action_id=action_id, action=action, document_id=doc_id, tenant_id=tenant_id,
                    actor_id=actor_id, actor_username=actor_username, status="succeeded",
                    impact=impact, reason=reason,
                )
                retrieval_cache.invalidate_documents([doc_id])
                return result
            if action == "delete":
                cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
                cursor.execute(
                    "DELETE FROM ai_document WHERE id = ? AND COALESCE(tenant_id, 'tenant-default') = ?",
                    (doc_id, tenant_id),
                )
                cursor.execute(
                    "UPDATE ai_knowledge_document_action SET status = 'succeeded', completed_at = ? WHERE id = ?",
                    (now, action_id),
                )
                conn.commit()
                result = {
                    "action_id": action_id,
                    "action": action,
                    "document_id": doc_id,
                    "status": "succeeded",
                    "impact": impact,
                    "recovery": {"recovery": recovery},
                }
                self._write_action_audit(
                    action_id=action_id, action=action, document_id=doc_id, tenant_id=tenant_id,
                    actor_id=actor_id, actor_username=actor_username, status="succeeded",
                    impact=impact, reason=reason,
                )
                retrieval_cache.invalidate_documents([doc_id])
                return result
            conn.commit()

        try:
            from ai.services.knowledge_reindex_service import knowledge_reindex_service

            pending_job = knowledge_reindex_service.create_job(
                tenant_id=tenant_id,
                scope={"document_id": doc_id},
                operation=action,
                action_id=action_id,
                run_async=True,
            )
            job_id = str(pending_job.get("id") or "")
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE ai_knowledge_document_action SET job_id = ? WHERE id = ?",
                    (job_id, action_id),
                )
                conn.commit()
            result = {
                "action_id": action_id,
                "action": action,
                "document_id": doc_id,
                "status": "queued",
                "job_id": job_id,
                "impact": impact,
                "recovery": {"recovery": recovery},
                "job": pending_job,
            }
            self._write_action_audit(
                action_id=action_id, action=action, document_id=doc_id, tenant_id=tenant_id,
                actor_id=actor_id, actor_username=actor_username, status="queued",
                impact=impact, reason=reason, job_id=job_id,
            )
            return result
        except Exception as exc:
            safe_code = "KNOWLEDGE_ACTION_JOB_CREATE_FAILED"
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE ai_knowledge_document_action SET status = 'failed', error_code = ?, completed_at = ? WHERE id = ?",
                    (safe_code, datetime.now(timezone.utc).isoformat(), action_id),
                )
                conn.commit()
            raise KnowledgeDocumentActionError(safe_code, "document action could not be queued", status_code=503) from exc

    def smart_chunk_markdown(self, markdown_text: str, max_chunk_size: int = 800) -> List[Dict[str, Any]]:
        """Compatibility wrapper around the V2 chunking engine.

        ``max_chunk_size`` is retained for callers of the old service method,
        but V2 interprets it as a token target. New code should use the
        structured fields returned by :class:`ChunkingEngine` directly.
        """
        chunks = ChunkingEngine().chunk(
            markdown_text,
            document_identity="compatibility",
            target_tokens_override=max_chunk_size,
        )
        return [chunk.to_dict() for chunk in chunks]

    @staticmethod
    def _table_columns(cursor, table_name: str) -> set[str]:
        """Return columns for both PostgreSQL and SQLite cursor adapters."""
        cursor.execute(f"SELECT * FROM {table_name} WHERE 1 = 0")
        return {str(description[0]) for description in (cursor.description or [])}

    def add_document_and_chunk(
        self,
        knowledge_base_id: str,
        name: str,
        content: str,
        vendor: str = "all",
        platform: Optional[str] = None,
        knowledge_source_type: str = "user_document",
        chunk_size: int = 800,
        tenant_id: str = "tenant-default",
        acl: Optional[Dict[str, Any]] = None,
        source_trust_level: str = "internal",
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        db_connection: Any = None,
        invalidate_cache: bool = True,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        
        # Front Matter is parsed before chunking so YAML keys never pollute
        # retrieval content.  A malformed header is a hard indexing error;
        # callers receive the exact reason and the source is not persisted.
        try:
            parsed_document = parse_knowledge_source(str(content or ""), filename=name)
            source_metadata = metadata if isinstance(metadata, dict) else {}
            directory_path = (
                source_metadata.get("knowledge_directory_path")
                or source_metadata.get("source_relative_path")
            )
            frontmatter = validate_metadata(
                parsed_document.metadata,
                directory_path=directory_path,
                name=name,
                allow_missing_required=parsed_document.metadata_parse_status == "missing",
            )
        except KnowledgeSourceParseError as exc:
            raise ValueError(f"知识文档文件格式无法解析: {exc.message}") from exc
        except (MetadataParseError, MetadataValidationError) as exc:
            raise ValueError(f"知识文档 Metadata 无法索引: {exc}") from exc

        merged = merge_metadata(frontmatter, source_metadata)
        # A source/upload hint may be used only when the document has no
        # Front Matter.  Once semantic metadata exists, it is authoritative.
        if parsed_document.metadata_parse_status == "missing":
            if vendor and str(vendor).lower() != "all":
                merged.setdefault("vendor", vendor)
            if platform and str(platform).lower() != "all":
                merged.setdefault("cli_platform", platform)
        merged.setdefault("document_id", doc_id)
        merged.setdefault("status", "active")
        merged.setdefault("exclude_from_rag", False)
        normalized_markdown = parsed_document.content.strip()
        content_hash = hashlib.sha256(normalized_markdown.encode("utf-8")).hexdigest()
        merged.setdefault("document_version", str(merged.get("source_version") or content_hash[:16]))
        merged.setdefault("parser_version", ChunkingEngine.parser_version)
        merged.setdefault("index_version", ChunkingEngine.default_index_version)
        document_vendor = str(merged.get("vendor") or vendor or "all")
        document_platform = merged.get("cli_platform")
        if str(document_platform or "").strip().lower() == "all":
            document_platform = None
        semantic_columns = metadata_columns(merged)
        content_hash = hashlib.sha256(normalized_markdown.encode("utf-8")).hexdigest()
        structured_chunks = ChunkingEngine().chunk(
            normalized_markdown,
            document_identity=doc_id,
            document_metadata={
                **merged,
                "vendor": document_vendor,
                "platform": document_platform,
                "knowledge_source_type": knowledge_source_type,
                "tenant_id": tenant_id,
                "source_trust_level": source_trust_level,
                "verified_version": merged.get("verified_version"),
            },
            target_tokens_override=chunk_size,
        )
        try:
            embedding_vectors = embed_documents_batch(
                [chk.embedding_content for chk in structured_chunks],
                provider=embedding_provider,
                tenant_id=tenant_id,
                task_id=f"knowledge-ingestion:{doc_id}",
                idempotency_namespace=f"knowledge:{tenant_id}",
            )
        except (EmbeddingProviderError, SecurityBlocked) as exc:
            # Embeddings are computed before the document transaction starts;
            # a provider/dimension failure therefore cannot leave partial rows.
            raise ValueError(f"知识文档 Embedding 无法索引: {exc}") from exc
        contract = embedding_contract(embedding_provider)
        embedding_info = embedding_metadata()

        owns_connection = db_connection is None
        connection_context = get_db_connection() if owns_connection else nullcontext(db_connection)
        with connection_context as conn:
            cursor = conn.cursor()
            document_columns = self._table_columns(cursor, "ai_document")
            document_values = {
                "id": doc_id,
                "knowledge_base_id": knowledge_base_id,
                "name": name,
                "source": str(source or "upload"),
                "vendor": document_vendor,
                "platform": document_platform,
                "status": "active",
                "knowledge_source_type": knowledge_source_type,
                "tenant_id": tenant_id,
                "acl_json": json.dumps(acl or {}, ensure_ascii=False),
                "source_trust_level": source_trust_level,
                "metadata_json": _json_db_value(merged),
                "normalized_content": normalized_markdown,
                "fts_text": f"{name}\n{normalized_markdown}",
                "original_content": parsed_document.original_content,
                "content_hash": content_hash,
                "chunking_version": "v2",
                "ingestion_status": "ready",
                "metadata_parse_status": parsed_document.metadata_parse_status,
                "metadata_parse_error": parsed_document.metadata_parse_error,
                "chunker_version": ChunkingEngine.chunker_version,
                "parser_version": merged.get("parser_version"),
                "document_version": merged.get("document_version"),
                "index_version": merged.get("index_version"),
                "embedding_mode": contract.mode,
                "embedding_contract_version": contract.contract_version,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            document_values.update(semantic_columns)
            document_values.update({
                "embedding_model": embedding_info.get("embedding_model"),
                "embedding_dimensions": embedding_info.get("embedding_dimensions"),
                "embedding_version": embedding_info.get("embedding_version"),
                "exclude_from_rag": 1 if merged.get("exclude_from_rag") else 0,
            })
            document_values = {key: value for key, value in document_values.items() if key in document_columns}
            document_columns_ordered = list(document_values)
            cursor.execute(
                f"INSERT INTO ai_document ({', '.join(document_columns_ordered)}) "
                f"VALUES ({', '.join('?' for _ in document_columns_ordered)})",
                [document_values[key] for key in document_columns_ordered],
            )

            chunk_columns = self._table_columns(cursor, "ai_document_chunk")
            assert_pgvector_column_compatible(cursor, expected_dimensions=contract.dimensions)
            for idx, (chk, vec) in enumerate(zip(structured_chunks, embedding_vectors)):
                section_name = chk.to_dict()["section"]
                # Every chunk carries the complete document metadata so a
                # retriever can apply hard filters without reading the parent
                # document content or reconstructing Front Matter.
                chunk_metadata = dict(merged)
                chunk_metadata.update(chk.metadata)
                chunk_metadata.update(
                    {
                        "chunk_idx": idx,
                        "chunk_index": idx,
                        "knowledge_source_type": knowledge_source_type,
                        "tenant_id": tenant_id,
                        "source_trust_level": source_trust_level,
                        "section": section_name,
                    }
                )
                chunk_metadata = chunk_projection_metadata(chunk_metadata)
                chunk_values = {
                    "id": chk.chunk_id,
                    "document_id": doc_id,
                    "content": chk.raw_content,
                    "raw_content": chk.raw_content,
                    "embedding_content": chk.embedding_content,
                    "embedding": json.dumps(vec),
                    "embedding_vector": json.dumps(vec, separators=(",", ":")),
                    "search_text": f"{section_name}\n{chk.embedding_content}",
                    "retrieval_index_version": "retrieval-v1",
                    "metadata_json": _json_db_value(chunk_metadata),
                    "page": int(chk.page or chk.source_locator.get("line_start") or idx + 1),
                    "section": section_name,
                    "created_at": now_iso,
                    "parent_chunk_id": chk.parent_chunk_id,
                    "chunk_role": chk.chunk_role,
                    "chunk_type": chk.chunk_type,
                    "ordinal": chk.ordinal,
                    "heading_path_json": json.dumps(list(chk.heading_path), ensure_ascii=False),
                    "token_count": chk.token_count,
                    "content_hash": chk.content_hash,
                    "source_locator_json": json.dumps(chk.source_locator, ensure_ascii=False),
                    "chunking_version": "v2",
                    "is_retrieval_candidate": 1 if chk.is_retrieval_candidate else 0,
                    "oversize_reason": chk.oversize_reason,
                    "chunker_version": ChunkingEngine.chunker_version,
                    "structure_types_json": json.dumps(list(chk.structure_types), ensure_ascii=False),
                    "neighbor_chunk_ids_json": json.dumps(list(chk.neighbor_chunk_ids), ensure_ascii=False),
                    "parser_version": chk.parser_version,
                    "document_version": chk.document_version,
                    "index_version": chk.index_version,
                    "embedding_mode": contract.mode,
                    "embedding_contract_version": contract.contract_version,
                }
                chunk_values.update({
                    key: value for key, value in metadata_columns(merged).items()
                    if key != "document_id" and key in chunk_columns
                })
                chunk_values.update({
                    "chunk_index": idx,
                    "embedding_model": embedding_info.get("embedding_model"),
                    "embedding_dimensions": len(vec),
                    "embedding_version": embedding_info.get("embedding_version"),
                })
                chunk_values = {key: value for key, value in chunk_values.items() if key in chunk_columns}
                chunk_columns_ordered = list(chunk_values)
                cursor.execute(
                    f"INSERT INTO ai_document_chunk ({', '.join(chunk_columns_ordered)}) "
                    f"VALUES ({', '.join('?' for _ in chunk_columns_ordered)})",
                    [chunk_values[key] for key in chunk_columns_ordered],
                )
            if owns_connection:
                conn.commit()

        # Exact invalidation occurs only after the document and all chunks are
        # committed; a failed transaction cannot evict a still-valid result.
        if invalidate_cache:
            retrieval_cache.invalidate_documents([doc_id])

        return {
            "document_id": doc_id,
            "name": name,
            "chunk_count": len(structured_chunks),
            "knowledge_source_type": knowledge_source_type,
            "tenant_id": tenant_id,
            "source_trust_level": source_trust_level,
            "chunking_version": "v2",
            "content_hash": content_hash,
        }


knowledge_service = KnowledgeService()
