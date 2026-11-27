#!/usr/bin/env python3
"""Maintain the semantic (bge-m3) vector index of the knowledge base.

Commands
--------
status        coverage of ``embedding_v2``: current / stale / missing, column
              type, HNSW index state, pgvector version.  Read-only.
build-index   CREATE INDEX CONCURRENTLY on ``embedding_v2`` (no write lock).
              ``--rebuild`` drops and recreates an INVALID index left by an
              interrupted build.
backfill      embeds chunks whose semantic vector is missing or stale (other
              model / version, or the text changed) through the sidecar.
              Resumable: it only ever selects rows that still need work, so
              it can be stopped and restarted at any time.
verify        samples stored vectors and checks dimensions and norms.
fts-index     fills the m0332 ``search_tsv`` column for existing chunks in
              small batches, then builds ``ix_ai_chunk_search_tsv`` with
              CREATE INDEX CONCURRENTLY.  Resumable.  The retriever switches
              to the stored column only when this index is valid.

Typical rollout::

    python scripts/rag_index_maintenance.py status
    python scripts/rag_index_maintenance.py backfill --batch 32 --sleep 0.2
    python scripts/rag_index_maintenance.py build-index --maintenance-work-mem 512MB
    python scripts/rag_index_maintenance.py verify

Building the index after the backfill is faster than maintaining it during
the bulk load.  Run the backfill off-peak: it uses the sidecar's CPU.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
for path in (BACKEND_ROOT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import database.core as database_core  # noqa: E402

INDEX_NAME = "ix_ai_chunk_embedding_v2_hnsw"
_MEMORY_RE = re.compile(r"^\d{1,6}(kB|MB|GB)$")


# ── helpers ──────────────────────────────────────────────────────────────


def _columns(cursor) -> set[str]:
    cursor.execute("SELECT * FROM ai_document_chunk WHERE 1 = 0")
    return {str(item[0]) for item in (cursor.description or [])}


def _text_expr(columns: set[str]) -> str:
    """The text that ingestion embeds (``embedding_content``), with fallbacks."""
    parts = [name for name in ("embedding_content", "search_text", "content") if name in columns]
    return "COALESCE(" + ", ".join(f"NULLIF(c.{name}, '')" for name in parts) + ", '')"


def _hash_expr(text_expr: str) -> str:
    return f"encode(sha256(convert_to({text_expr}, 'UTF8')), 'hex')"


def _scope(columns: set[str], include_all: bool) -> str:
    if include_all or "is_retrieval_candidate" not in columns:
        return "TRUE"
    # Parent / context-only chunks are never ranked by the vector leg.
    return "COALESCE(c.is_retrieval_candidate, 1) = 1"


def _column_type(cursor) -> str | None:
    from ai.services.semantic_vectors import semantic_column_type

    return semantic_column_type(cursor)


def _opclass(column_type: str) -> str:
    return "halfvec_cosine_ops" if column_type.lower().startswith("halfvec") else "vector_cosine_ops"


def _index_state(cursor) -> dict[str, Any]:
    row = cursor.execute(
        "SELECT i.indisvalid, i.indisready, pg_relation_size(i.indexrelid) "
        "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relname = ?",
        (INDEX_NAME,),
    ).fetchone()
    if not row:
        return {"name": INDEX_NAME, "exists": False}
    return {"name": INDEX_NAME, "exists": True, "valid": bool(row[0]), "ready": bool(row[1]), "size_mb": round(int(row[2] or 0) / 1048576, 1)}


def _provider():
    from ai.providers.embedding import semantic_embedding_provider

    provider = semantic_embedding_provider()
    if provider is None:
        raise SystemExit("AI_SEMANTIC_EMBEDDING_PROVIDER is 'none'; set it to 'sidecar' first")
    return provider


# ── commands ─────────────────────────────────────────────────────────────


def status(args: argparse.Namespace) -> dict[str, Any]:
    from ai.providers.embedding import semantic_embedding_status

    with database_core.get_db_connection() as conn:
        cursor = conn.cursor()
        column_type = _column_type(cursor)
        if column_type is None:
            return {"status": "NOT_READY", "error": "embedding_v2 column missing; run migrations (m0331)"}
        columns = _columns(cursor)
        text_expr = _text_expr(columns)
        model = str(args.model)
        version = str(args.version)
        row = cursor.execute(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE c.embedding_v2 IS NULL), "
            "COUNT(*) FILTER (WHERE c.embedding_v2 IS NOT NULL AND (c.embedding_v2_model IS DISTINCT FROM ? "
            "  OR c.embedding_v2_version IS DISTINCT FROM ?)), "
            "COUNT(*) FILTER (WHERE c.embedding_v2 IS NOT NULL AND c.embedding_v2_model = ? AND c.embedding_v2_version = ? "
            f"  AND c.embedding_v2_content_hash IS DISTINCT FROM {_hash_expr(text_expr)}) "
            f"FROM ai_document_chunk c WHERE {_scope(columns, args.all)}",
            (model, version, model, version),
        ).fetchone()
        total, missing, other_model, text_changed = (int(value or 0) for value in row)
        mix = cursor.execute(
            "SELECT COALESCE(embedding_v2_model, '-'), COALESCE(embedding_v2_version, '-'), COUNT(*) "
            "FROM ai_document_chunk WHERE embedding_v2 IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC"
        ).fetchall()
        ext = cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
        index = _index_state(cursor)
    current = total - missing - other_model - text_changed
    return {
        "status": "PASS" if total and current == total and index.get("valid") else "IN_PROGRESS",
        "target": {"model": model, "version": version},
        "column_type": column_type,
        "pgvector": str((ext or [""])[0]),
        "chunks": {
            "total": total,
            "current": current,
            "missing": missing,
            "stale_other_model_or_version": other_model,
            "stale_text_changed": text_changed,
            "coverage": round(current / total, 4) if total else 0.0,
        },
        "stored_versions": [{"model": item[0], "version": item[1], "count": int(item[2])} for item in mix],
        "index": index,
        "sidecar": semantic_embedding_status(),
    }


FTS_INDEX_NAME = "ix_ai_chunk_search_tsv"
FTS_EXPRESSION = "to_tsvector('simple', COALESCE(search_text, ''))"


def _named_index_state(cursor, name: str) -> dict[str, Any]:
    row = cursor.execute(
        "SELECT i.indisvalid, pg_relation_size(c.oid) FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = ?",
        [name],
    ).fetchone()
    if not row:
        return {"name": name, "exists": False}
    return {"name": name, "exists": True, "valid": bool(row[0]), "size_mb": round(int(row[1] or 0) / 1048576, 1)}


def fts_index(args: argparse.Namespace) -> dict[str, Any]:
    """Backfill search_tsv in batches, then build its GIN index concurrently."""
    if not _MEMORY_RE.match(args.maintenance_work_mem):
        raise SystemExit("--maintenance-work-mem must look like 512MB")
    started = time.perf_counter()
    filled = 0
    while True:
        with database_core.get_db_connection() as conn:
            cursor = conn.cursor()
            if "search_tsv" not in _columns(cursor):
                raise SystemExit("search_tsv column missing; run migrations (m0332)")
            # Short transactions: each batch locks only the rows it updates.
            cursor.execute(
                f"UPDATE ai_document_chunk SET search_tsv = {FTS_EXPRESSION} "
                "WHERE id IN (SELECT id FROM ai_document_chunk WHERE search_tsv IS NULL ORDER BY id LIMIT ?)",
                [int(args.batch)],
            )
            changed = int(getattr(cursor, "rowcount", 0) or 0)
            conn.commit()
        filled += max(0, changed)
        if changed <= 0:
            break
        if filled % (int(args.batch) * 20) < int(args.batch):
            print(f"[fts-index] filled {filled} chunks", flush=True)
        if args.sleep:
            time.sleep(float(args.sleep))
    with database_core.get_db_connection() as conn:
        conn.autocommit = True
        cursor = conn.cursor()
        missing = int((cursor.execute("SELECT COUNT(*) FROM ai_document_chunk WHERE search_tsv IS NULL").fetchone() or [0])[0] or 0)
        if missing:
            return {"status": "IN_PROGRESS", "filled": filled, "missing": missing}
        state = _named_index_state(cursor, FTS_INDEX_NAME)
        if state.get("exists") and not state.get("valid"):
            if not args.rebuild:
                return {"status": "INVALID_INDEX", "index": state, "hint": "re-run with --rebuild"}
            cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {FTS_INDEX_NAME}")
            state = {"exists": False}
        build_seconds = 0.0
        if not state.get("exists"):
            cursor.execute(f"SET maintenance_work_mem = '{args.maintenance_work_mem}'")
            build_started = time.perf_counter()
            cursor.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {FTS_INDEX_NAME} ON ai_document_chunk USING GIN (search_tsv)")
            build_seconds = round(time.perf_counter() - build_started, 1)
            cursor.execute("ANALYZE ai_document_chunk")
        state = _named_index_state(cursor, FTS_INDEX_NAME)
        # Spot check: the stored vector must equal the m0138 expression.
        drift = int((cursor.execute(
            f"SELECT COUNT(*) FROM (SELECT search_tsv, {FTS_EXPRESSION} AS expected FROM ai_document_chunk "
            "ORDER BY random() LIMIT 500) sample WHERE search_tsv IS DISTINCT FROM expected"
        ).fetchone() or [0])[0] or 0)
    ok = bool(state.get("valid")) and drift == 0
    return {
        "status": "PASS" if ok else "FAIL",
        "filled": filled,
        "index": state,
        "build_seconds": build_seconds,
        "sample_drift": drift,
        "seconds": round(time.perf_counter() - started, 1),
    }


def build_index(args: argparse.Namespace) -> dict[str, Any]:
    if not _MEMORY_RE.match(args.maintenance_work_mem):
        raise SystemExit("--maintenance-work-mem must look like 512MB")
    if not (4 <= args.m <= 64 and 16 <= args.ef_construction <= 512):
        raise SystemExit("--m must be 4..64 and --ef-construction 16..512")
    with database_core.get_db_connection() as conn:
        # CONCURRENTLY cannot run inside a transaction block.
        conn.autocommit = True
        cursor = conn.cursor()
        column_type = _column_type(cursor)
        if column_type is None:
            raise SystemExit("embedding_v2 column missing; run migrations (m0331)")
        state = _index_state(cursor)
        if state.get("exists") and not state.get("valid"):
            if not args.rebuild:
                return {"status": "INVALID_INDEX", "index": state, "hint": "re-run with --rebuild"}
            cursor.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
            state = {"exists": False}
        if state.get("exists"):
            return {"status": "PASS", "index": state, "note": "already built"}
        cursor.execute(f"SET maintenance_work_mem = '{args.maintenance_work_mem}'")
        if args.parallel_workers is not None:
            cursor.execute(f"SET max_parallel_maintenance_workers = {max(0, min(int(args.parallel_workers), 8))}")
        started = time.perf_counter()
        cursor.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} ON ai_document_chunk "
            f"USING hnsw (embedding_v2 {_opclass(column_type)}) "
            f"WITH (m = {int(args.m)}, ef_construction = {int(args.ef_construction)})"
        )
        elapsed = round(time.perf_counter() - started, 1)
        cursor.execute("ANALYZE ai_document_chunk")
        state = _index_state(cursor)
    return {"status": "PASS" if state.get("valid") else "FAIL", "index": state, "build_seconds": elapsed}


def backfill(args: argparse.Namespace) -> dict[str, Any]:
    from ai.services import semantic_vectors

    provider = None if args.dry_run else _provider()
    model = str(getattr(provider, "model_id", args.model))
    version = str(getattr(provider, "version", args.version))
    processed = written = skipped_changed = failures = 0
    last_id = ""
    started = time.perf_counter()
    while True:
        batch_start = last_id
        with database_core.get_db_connection() as conn:
            cursor = conn.cursor()
            column_type = _column_type(cursor)
            if column_type is None:
                raise SystemExit("embedding_v2 column missing; run migrations (m0331)")
            cast_type = column_type.split("(")[0]
            columns = _columns(cursor)
            text_expr = _text_expr(columns)
            hash_expr = _hash_expr(text_expr)
            rows = cursor.execute(
                f"SELECT c.id, {text_expr}, {hash_expr}, d.tenant_id "
                "FROM ai_document_chunk c JOIN ai_document d ON d.id = c.document_id "
                f"WHERE c.id > ? AND {_scope(columns, args.all)} AND ("
                "c.embedding_v2 IS NULL OR c.embedding_v2_model IS DISTINCT FROM ? "
                "OR c.embedding_v2_version IS DISTINCT FROM ? "
                f"OR c.embedding_v2_content_hash IS DISTINCT FROM {hash_expr}) "
                "ORDER BY c.id LIMIT ?",
                (last_id, model, version, int(args.batch)),
            ).fetchall()
            if not rows:
                break
            last_id = str(rows[-1][0])
            processed += len(rows)
            if not args.dry_run:
                texts = [str(row[1] or "") for row in rows]
                try:
                    batch = semantic_vectors.embed_chunks(
                        texts,
                        tenant_id=str(rows[0][3] or "tenant-default"),
                        task_id="semantic-backfill",
                        provider=provider,
                    )
                except Exception as exc:  # required mode or provider error
                    batch = semantic_vectors.SemanticBatch(status="failed", error_code=type(exc).__name__)
                if batch.status != "ok":
                    failures += 1
                    print(f"[backfill] batch after {last_id} failed ({batch.error_code}); retry {failures}/{args.max_failures}", flush=True)
                    if failures >= args.max_failures:
                        return {
                            "status": "FAIL",
                            "error_code": batch.error_code,
                            "processed": processed,
                            "written": written,
                            "hint": "check the sidecar, then re-run; finished rows are kept",
                        }
                    # Retry the same batch: rewind the keyset cursor.
                    last_id = batch_start
                    processed -= len(rows)
                    time.sleep(min(60.0, 5.0 * failures))
                    continue
                failures = 0
                batch = semantic_vectors.guard_column(cursor, batch)
                if batch.status != "ok":
                    return {"status": "FAIL", "error_code": batch.error_code, "processed": processed, "written": written}
                now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                for index, row in enumerate(rows):
                    values = batch.columns_for(index, texts[index], now=now)
                    # Optimistic guard: only stamp the vector if the text is
                    # still the one that was embedded.
                    cursor.execute(
                        f"UPDATE ai_document_chunk c SET embedding_v2 = CAST(? AS {cast_type}), "
                        "embedding_v2_model = ?, embedding_v2_version = ?, embedding_v2_content_hash = ?, embedding_v2_at = ? "
                        f"WHERE c.id = ? AND {hash_expr} = ?",
                        (
                            values["embedding_v2"], values["embedding_v2_model"], values["embedding_v2_version"],
                            values["embedding_v2_content_hash"], values["embedding_v2_at"], row[0], row[2],
                        ),
                    )
                    if int(getattr(cursor, "rowcount", 1) or 0) == 1:
                        written += 1
                    else:
                        skipped_changed += 1
                conn.commit()
        elapsed = time.perf_counter() - started
        print(f"[backfill] processed={processed} written={written} rate={processed / max(elapsed, 0.001):.1f}/s last={last_id}", flush=True)
        if args.limit and processed >= args.limit:
            break
        if args.sleep:
            time.sleep(args.sleep)
    return {
        "status": "PASS",
        "dry_run": bool(args.dry_run),
        "target": {"model": model, "version": version},
        "processed": processed,
        "written": written,
        "skipped_text_changed": skipped_changed,
        "seconds": round(time.perf_counter() - started, 1),
        "next": "run 'status', then 'build-index' if the index does not exist yet",
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    with database_core.get_db_connection() as conn:
        cursor = conn.cursor()
        column_type = _column_type(cursor)
        if column_type is None:
            return {"status": "NOT_READY", "error": "embedding_v2 column missing"}
        expected = int(re.search(r"\((\d+)\)", column_type).group(1))
        rows = cursor.execute(
            "SELECT id, embedding_v2::text, embedding_v2_model, embedding_v2_version FROM ai_document_chunk "
            "WHERE embedding_v2 IS NOT NULL ORDER BY random() LIMIT ?",
            (int(args.sample),),
        ).fetchall()
    for chunk_id, raw, model, version in rows:
        values = json.loads(raw)
        norm = math.sqrt(sum(value * value for value in values))
        if len(values) != expected or not math.isfinite(norm) or abs(norm - 1.0) > 0.02:
            problems.append({"chunk_id": chunk_id, "dimensions": len(values), "norm": round(norm, 4), "model": model, "version": version})
    return {
        "status": "PASS" if rows and not problems else ("EMPTY" if not rows else "FAIL"),
        "column_type": column_type,
        "sampled": len(rows),
        "problems": problems[:50],
    }


def main(argv: list[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.environ.get("AI_SEMANTIC_EMBEDDING_MODEL", "bge-m3"))
    parser.add_argument("--version", default=os.environ.get("AI_SEMANTIC_EMBEDDING_VERSION", "bge-m3-int8-v1"))
    parser.add_argument("--all", action="store_true", help="include parent/context-only chunks")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    build = sub.add_parser("build-index")
    build.add_argument("--maintenance-work-mem", default="512MB")
    build.add_argument("--parallel-workers", type=int, default=None)
    build.add_argument("--m", type=int, default=16)
    build.add_argument("--ef-construction", type=int, default=64)
    build.add_argument("--rebuild", action="store_true")
    fill = sub.add_parser("backfill")
    fill.add_argument("--batch", type=int, default=32)
    fill.add_argument("--limit", type=int, default=0, help="stop after about N chunks (0 = all)")
    fill.add_argument("--sleep", type=float, default=0.0, help="pause between batches, seconds")
    fill.add_argument("--max-failures", type=int, default=5)
    fill.add_argument("--dry-run", action="store_true", help="count work only, no sidecar calls")
    check = sub.add_parser("verify")
    check.add_argument("--sample", type=int, default=200)
    fts = sub.add_parser("fts-index", help="backfill search_tsv (m0332) and build its GIN index")
    fts.add_argument("--batch", type=int, default=2000)
    fts.add_argument("--sleep", type=float, default=0.0)
    fts.add_argument("--maintenance-work-mem", default="256MB")
    fts.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)
    batch_cap = 20000 if args.command == "fts-index" else 256
    if getattr(args, "batch", 1) < 1 or getattr(args, "batch", 1) > batch_cap:
        raise SystemExit(f"--batch must be 1..{batch_cap}")
    handler = {"status": status, "build-index": build_index, "backfill": backfill, "verify": verify, "fts-index": fts_index}[args.command]
    report = handler(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") in {"PASS", "IN_PROGRESS", "EMPTY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
