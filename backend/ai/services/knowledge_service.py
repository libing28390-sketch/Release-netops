"""
AI Knowledge Base and Document Chunking Service
Supports Normalized Markdown Middle Format & Heading/CLI-Aware Smart Chunking
"""

from __future__ import annotations

import json
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection, _USE_PG
from ai.chunking.engine import ChunkingEngine
from ai.providers.embedding import embedding_provider, embedding_metadata
from ai.services.knowledge_metadata import (
    MetadataParseError,
    MetadataValidationError,
    json_safe_metadata,
    merge_metadata,
    metadata_columns,
    parse_markdown_document,
    validate_metadata,
)


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
        tenant_id: str = "tenant-default",
        search: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List active documents with tenant-safe server-side filtering and pagination."""
        safe_page_size = min(max(int(page_size or 20), 1), 100)
        requested_page = max(int(page or 1), 1)
        search_term = (search or "").strip().lower()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            where = [
                "d.status = 'active'",
                "(d.tenant_id = ? OR d.tenant_id = 'tenant-default')",
            ]
            params: List[Any] = [tenant_id]
            if knowledge_source_type:
                where.append("d.knowledge_source_type = ?")
                params.append(knowledge_source_type)
            if directory_path and directory_path.strip():
                # Directory paths are persisted inside metadata_json.  Keep
                # this portable across PostgreSQL/SQLite and tolerate the
                # minimal legacy test schema that has no metadata column.
                directory_columns = self._table_columns(cursor, "ai_document")
                if "metadata_json" in directory_columns:
                    normalized_directory_path = directory_path.strip().strip("/").lower()
                    # metadata_json is JSONB on PostgreSQL after migration
                    # 0113 and TEXT on legacy/SQLite installations.
                    where.append("LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ?")
                    params.append(f"%kb_import/{normalized_directory_path}%")
                else:
                    where.append("1 = 0")
            if search_term:
                where.append(
                    "(LOWER(COALESCE(d.name, '')) LIKE ? "
                    "OR LOWER(COALESCE(d.vendor, '')) LIKE ? "
                    "OR LOWER(COALESCE(d.platform, '')) LIKE ?)"
                )
                search_pattern = f"%{search_term}%"
                params.extend([search_pattern, search_pattern, search_pattern])

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
                "ORDER BY d.created_at DESC LIMIT ? OFFSET ?"
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
            available_semantic = [field for field in semantic_fields if field in self._table_columns(cursor, "ai_document")]
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

    def get_document_detail(self, doc_id: str, tenant_id: str = "tenant-default") -> Optional[Dict[str, Any]]:
        """Return one document's metadata and ordered chunk content for the viewer."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT d.id, d.knowledge_base_id, d.name, d.source, d.vendor, d.platform,
                       d.status, d.knowledge_source_type, d.tenant_id, d.acl_json,
                       d.source_trust_level, d.created_at, d.updated_at
                FROM ai_document d
                WHERE d.id = ?
                  AND d.status = 'active'
                  AND (d.tenant_id = ? OR d.tenant_id = 'tenant-default')
                """,
                (doc_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            cursor.execute(
                """
                SELECT c.id, c.page, c.section, c.content, c.created_at
                FROM ai_document_chunk c
                WHERE c.document_id = ?
                ORDER BY c.page ASC, c.created_at ASC, c.id ASC
                """,
                (doc_id,),
            )
            chunks = [
                {
                    "id": chunk[0],
                    "page": int(chunk[1] or index + 1),
                    "section": chunk[2] or "General Overview",
                    "content": chunk[3] or "",
                    "created_at": chunk[4],
                }
                for index, chunk in enumerate(cursor.fetchall())
            ]

            return {
                "id": row[0],
                "knowledge_base_id": row[1],
                "name": row[2],
                "source": row[3],
                "vendor": row[4],
                "platform": row[5],
                "status": row[6],
                "knowledge_source_type": row[7] or "user_document",
                "tenant_id": row[8] or "tenant-default",
                "acl": parse_acl(row[9]),
                "source_trust_level": row[10] or "untrusted",
                "created_at": row[11],
                "updated_at": row[12],
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
            return {"deleted_count": deleted, "requested": len(doc_ids)}

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
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        
        # Front Matter is parsed before chunking so YAML keys never pollute
        # retrieval content.  A malformed header is a hard indexing error;
        # callers receive the exact reason and the source is not persisted.
        try:
            parsed_document = parse_markdown_document(str(content or ""))
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

        with get_db_connection() as conn:
            cursor = conn.cursor()
            document_columns = self._table_columns(cursor, "ai_document")
            document_values = {
                "id": doc_id,
                "knowledge_base_id": knowledge_base_id,
                "name": name,
                "source": "upload",
                "vendor": document_vendor,
                "platform": document_platform,
                "status": "active",
                "knowledge_source_type": knowledge_source_type,
                "tenant_id": tenant_id,
                "acl_json": json.dumps(acl or {}, ensure_ascii=False),
                "source_trust_level": source_trust_level,
                "metadata_json": _json_db_value(merged),
                "normalized_content": normalized_markdown,
                "original_content": parsed_document.original_content,
                "content_hash": content_hash,
                "chunking_version": "v2",
                "ingestion_status": "ready",
                "metadata_parse_status": parsed_document.metadata_parse_status,
                "metadata_parse_error": parsed_document.metadata_parse_error,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            document_values.update(semantic_columns)
            document_values.update({
                "embedding_model": embedding_metadata().get("embedding_model"),
                "embedding_dimensions": embedding_metadata().get("embedding_dimensions"),
                "embedding_version": embedding_metadata().get("embedding_version"),
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
            for idx, chk in enumerate(structured_chunks):
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
                vec = embedding_provider.embed_text(chk.embedding_content)
                chunk_values = {
                    "id": chk.chunk_id,
                    "document_id": doc_id,
                    "content": chk.raw_content,
                    "raw_content": chk.raw_content,
                    "embedding_content": chk.embedding_content,
                    "embedding": json.dumps(vec),
                    "metadata_json": _json_db_value(chunk_metadata),
                    "page": int(chk.source_locator.get("line_start") or idx + 1),
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
                }
                chunk_values.update({
                    key: value for key, value in metadata_columns(merged).items()
                    if key != "document_id" and key in chunk_columns
                })
                chunk_values.update({
                    "chunk_index": idx,
                    "embedding_model": embedding_metadata().get("embedding_model"),
                    "embedding_dimensions": len(vec),
                    "embedding_version": embedding_metadata().get("embedding_version"),
                })
                chunk_values = {key: value for key, value in chunk_values.items() if key in chunk_columns}
                chunk_columns_ordered = list(chunk_values)
                cursor.execute(
                    f"INSERT INTO ai_document_chunk ({', '.join(chunk_columns_ordered)}) "
                    f"VALUES ({', '.join('?' for _ in chunk_columns_ordered)})",
                    [chunk_values[key] for key in chunk_columns_ordered],
                )
            conn.commit()

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
