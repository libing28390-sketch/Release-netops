"""Bootstrap the deterministic PostgreSQL corpus used by Knowledge Engine CI.

``database.init_db()`` applies the schema and migration seeds, but the service
startup lifecycle also performs an idempotent projection from the reviewed
template catalog into the RAG tables.  CI does not start the API process, so
that projection must be made explicit before an evaluation runs.

This script is intentionally PostgreSQL-only.  It creates no synthetic Gold
annotations and does not make network calls; it only materializes the
checked-in official template and product-registry records into the isolated
database named by ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import _USE_PG, get_db_connection, init_db  # noqa: E402
from services.official_product_catalog_service import (  # noqa: E402
    ensure_official_product_registry_documents,
)
from services.official_template_projection_service import (  # noqa: E402
    project_official_templates_to_knowledge,
)


TENANT_ID = "tenant-default"


def _count(conn: Any, query: str, params: tuple[Any, ...]) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0] if not hasattr(row, "keys") else next(iter(row.values())))


def _verify_projection() -> dict[str, int | bool]:
    with get_db_connection() as conn:
        vector_available = bool(
            conn.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
        )
        official_template_documents = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM ai_document
            WHERE tenant_id = ?
              AND knowledge_source_type = 'official_template'
              AND source_trust_level = 'official'
              AND COALESCE(exclude_from_rag, 0) = 0
            """,
            (TENANT_ID,),
        )
        official_template_chunks = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM ai_document_chunk AS chunk
            JOIN ai_document AS document ON document.id = chunk.document_id
            WHERE document.tenant_id = ?
              AND document.knowledge_source_type = 'official_template'
              AND document.source_trust_level = 'official'
              AND COALESCE(document.exclude_from_rag, 0) = 0
            """,
            (TENANT_ID,),
        )
        product_registry_documents = _count(
            conn,
            """
            SELECT COUNT(*)
            FROM ai_document
            WHERE tenant_id = ?
              AND source_trust_level = 'official'
              AND COALESCE(exclude_from_rag, 0) = 0
              AND metadata_json->>'document_type' = 'product_registry'
            """,
            (TENANT_ID,),
        )

    if not vector_available:
        raise RuntimeError(
            "PostgreSQL extension 'vector' is unavailable; the Knowledge "
            "Engine evaluation requires the pgvector CI service"
        )
    if official_template_documents <= 0 or official_template_chunks <= 0:
        raise RuntimeError(
            "Official template projection produced no searchable documents "
            f"(documents={official_template_documents}, "
            f"chunks={official_template_chunks})"
        )
    if product_registry_documents <= 0:
        raise RuntimeError("Official product registry projection produced no documents")

    return {
        "vector_extension": vector_available,
        "official_template_documents": official_template_documents,
        "official_template_chunks": official_template_chunks,
        "product_registry_documents": product_registry_documents,
    }


def main() -> int:
    if not _USE_PG:
        raise RuntimeError(
            "Knowledge Engine CI bootstrap is PostgreSQL-only; configure "
            "DATABASE_URL with the postgresql:// scheme"
        )

    # Keep this script safe to run directly as well as after a separate
    # init_db step.  init_db is idempotent within the process and migrations
    # are the source of the reviewed official template rows.
    init_db()
    projection = project_official_templates_to_knowledge(
        tenant_id=TENANT_ID,
        created_by="system",
    )
    registry = ensure_official_product_registry_documents(
        tenant_id=TENANT_ID,
        created_by="system",
    )
    counts = _verify_projection()
    print(
        json.dumps(
            {
                "status": "PASS",
                "database": "PostgreSQL",
                "external_network": "forbidden",
                "secrets": False,
                "projection_published": int(projection.get("published_count") or 0),
                "projection_refreshed": int(projection.get("refreshed_count") or 0),
                "registry_published": int(registry.get("published_count") or 0),
                **counts,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
