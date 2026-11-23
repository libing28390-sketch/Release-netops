#!/usr/bin/env python3
"""Summarise RAG shadow comparisons and decide whether V2 can be switched on.

Reads ``ai_retrieval_shadow_comparison`` (m0333) on the configured database;
read-only.  Rows are written while ``AI_RETRIEVAL_ENGINE=shadow``.

Only comparisons that went through the *indexed* V2 path count as evidence:
below AI_RETRIEVAL_V2_EXACT_THRESHOLD chunks V2 uses the exact V1 scoring
(``v2_exact_small_set``), so those always agree and prove nothing.

Gate (all must hold, over the selected window)::

    indexed comparisons      >= --min-indexed   (default 200)
    top-1 agreement          >= --min-top1      (default 0.98)
    mean overlap@k           >= --min-overlap   (default 0.95)
    V2 error rate            <= --max-errors    (default 0.01)

Examples::

    python scripts/rag_shadow_report.py                 # last 7 days
    python scripts/rag_shadow_report.py --days 3 --worst 30

Writes ``docs/knowledge-engine/eval/rag-shadow-report.json`` and ``.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "backend", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "rag-shadow-report.json"
TABLE = "ai_retrieval_shadow_comparison"
INDEXED = "v2_indexed"


def _float(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _rows(conn, sql: str, params: list[Any]) -> list[tuple]:
    return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def summarize(
    conn,
    *,
    days: int = 7,
    min_indexed: int = 200,
    min_top1: float = 0.98,
    min_overlap: float = 0.95,
    max_errors: float = 0.01,
    worst: int = 20,
) -> dict[str, Any]:
    window = "created_at >= now() - make_interval(days => ?)"
    params = [int(days)]

    def aggregate(extra: str = "", extra_params: list[Any] | None = None) -> dict[str, Any]:
        row = _rows(
            conn,
            f"""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE status = 'ok'),
                   COUNT(*) FILTER (WHERE status <> 'ok'),
                   AVG(CASE WHEN top1_match THEN 1.0 ELSE 0.0 END) FILTER (WHERE status = 'ok'),
                   AVG(overlap_at_k) FILTER (WHERE status = 'ok'),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY v1_latency_ms),
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY v1_latency_ms),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY v2_latency_ms) FILTER (WHERE status = 'ok'),
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY v2_latency_ms) FILTER (WHERE status = 'ok'),
                   COUNT(*) FILTER (WHERE status = 'ok' AND v1_result_count = 0 AND v2_result_count > 0),
                   COUNT(*) FILTER (WHERE status = 'ok' AND v1_result_count > 0 AND v2_result_count = 0)
            FROM {TABLE} WHERE {window}{extra}
            """,
            [*params, *(extra_params or [])],
        )[0]
        total, ok, errors = int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
        return {
            "comparisons": total,
            "ok": ok,
            "errors": errors,
            "error_rate": _float(errors / total) if total else None,
            "top1_match_rate": _float(row[3]),
            "mean_overlap_at_k": _float(row[4]),
            "v1_latency_ms": {"p50": _float(row[5], 1), "p95": _float(row[6], 1)},
            "v2_latency_ms": {"p50": _float(row[7], 1), "p95": _float(row[8], 1)},
            "v2_only_results": int(row[9] or 0),
            "v1_only_results": int(row[10] or 0),
        }

    overall = aggregate()
    indexed = aggregate(" AND v2_engine = ?", [INDEXED])
    by_engine = {
        str(engine or "(none)"): int(count)
        for engine, count in _rows(conn, f"SELECT v2_engine, COUNT(*) FROM {TABLE} WHERE {window} GROUP BY 1 ORDER BY 2 DESC", params)
    }
    by_day = [
        {
            "day": str(day),
            "comparisons": int(total),
            "indexed": int(indexed_count),
            "top1_match_rate": _float(top1),
            "mean_overlap_at_k": _float(overlap),
            "errors": int(errors),
        }
        for day, total, indexed_count, top1, overlap, errors in _rows(
            conn,
            f"""
            SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date,
                   COUNT(*),
                   COUNT(*) FILTER (WHERE v2_engine = ?),
                   AVG(CASE WHEN top1_match THEN 1.0 ELSE 0.0 END) FILTER (WHERE status = 'ok' AND v2_engine = ?),
                   AVG(overlap_at_k) FILTER (WHERE status = 'ok' AND v2_engine = ?),
                   COUNT(*) FILTER (WHERE status <> 'ok')
            FROM {TABLE} WHERE {window} GROUP BY 1 ORDER BY 1
            """,
            [INDEXED, INDEXED, INDEXED, *params],
        )
    ]
    degraded = {
        str(code): int(count)
        for code, count in _rows(
            conn,
            f"SELECT code, COUNT(*) FROM {TABLE}, unnest(capability_degraded) AS code WHERE {window} GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
            params,
        )
    }
    error_codes = {
        str(code or "(none)"): int(count)
        for code, count in _rows(
            conn, f"SELECT error_code, COUNT(*) FROM {TABLE} WHERE {window} AND status <> 'ok' GROUP BY 1 ORDER BY 2 DESC", params
        )
    }
    # array_agg over TEXT[] builds a 2-D array, and [1] of a 2-D array is
    # NULL in PostgreSQL; take the newest row's lists with DISTINCT ON.
    mismatch = f"{window} AND status = 'ok' AND v2_engine = ? AND (NOT top1_match OR overlap_at_k < 1)"
    worst_rows = _rows(
        conn,
        f"""
        WITH grouped AS (
            SELECT query_hash, COUNT(*) AS seen,
                   COUNT(*) FILTER (WHERE NOT top1_match) AS top1_misses,
                   AVG(overlap_at_k) AS overlap,
                   MAX(query_preview) AS preview
            FROM {TABLE} WHERE {mismatch}
            GROUP BY query_hash
        ), latest AS (
            SELECT DISTINCT ON (query_hash) query_hash, v1_document_ids, v2_document_ids
            FROM {TABLE} WHERE {mismatch}
            ORDER BY query_hash, created_at DESC, id DESC
        )
        SELECT g.query_hash, g.seen, g.top1_misses, g.overlap, g.preview, l.v1_document_ids, l.v2_document_ids
        FROM grouped g JOIN latest l ON l.query_hash = g.query_hash
        ORDER BY g.top1_misses DESC, g.overlap ASC, g.seen DESC, g.query_hash
        LIMIT ?
        """,
        [*params, INDEXED, *params, INDEXED, int(worst)],
    )
    worst_queries = [
        {
            "query_hash": str(row[0]),
            "seen": int(row[1]),
            "top1_misses": int(row[2] or 0),
            "mean_overlap_at_k": _float(row[3]),
            "query_preview": row[4],
            "v1_top": list(row[5] or [])[:5],
            "v2_top": list(row[6] or [])[:5],
        }
        for row in worst_rows
    ]

    checks = {
        "enough_indexed_comparisons": indexed["comparisons"] >= min_indexed,
        "top1_agreement": (indexed["top1_match_rate"] or 0.0) >= min_top1,
        "overlap": (indexed["mean_overlap_at_k"] or 0.0) >= min_overlap,
        "error_rate": (indexed["error_rate"] if indexed["error_rate"] is not None else 1.0) <= max_errors,
    }
    if not overall["comparisons"]:
        status, hint = "NO_DATA", "没有影子对比记录：确认 AI_RETRIEVAL_ENGINE=shadow 已生效、m0333 已执行，并且有检索请求。"
    elif not indexed["comparisons"]:
        status, hint = "ONLY_EXACT_PATH", (
            "所有对比都走了精确路径：知识库在过滤后不超过 AI_RETRIEVAL_V2_EXACT_THRESHOLD 个分块，"
            "此时 V2 与 V1 计算方式相同。切换到 v2 没有风险，但也没有性能收益。"
        )
    elif not checks["enough_indexed_comparisons"]:
        status, hint = "INSUFFICIENT_DATA", f"索引路径对比 {indexed['comparisons']} 次，少于 {min_indexed} 次，继续观察。"
    elif all(checks.values()):
        status, hint = "READY", "达到切换门槛，可以设置 AI_RETRIEVAL_ENGINE=v2。"
    else:
        status, hint = "NOT_READY", "未达到切换门槛，先查看下方不一致的问题。"
    return {
        "status": status,
        "hint": hint,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "window_days": int(days),
        "thresholds": {"min_indexed": min_indexed, "min_top1": min_top1, "min_overlap": min_overlap, "max_errors": max_errors},
        "checks": checks,
        "overall": overall,
        "indexed": indexed,
        "by_engine": by_engine,
        "by_day": by_day,
        "capability_degraded": degraded,
        "error_codes": error_codes,
        "worst_queries": worst_queries,
    }


def markdown(report: dict[str, Any]) -> str:
    indexed, overall = report["indexed"], report["overall"]

    def pct(value: Any) -> str:
        return "-" if value is None else f"{float(value) * 100:.1f}%"

    lines = [
        "# RAG 影子对比报告",
        "",
        f"- 生成时间：{report['generated_at']}（最近 {report['window_days']} 天）",
        f"- 结论：**{report['status']}** — {report['hint']}",
        "",
        "| 范围 | 对比次数 | top1 一致 | 平均重合 | 错误率 | V1 p50 / p95 ms | V2 p50 / p95 ms |",
        "| :--- | ---: | ---: | ---: | ---: | :--- | :--- |",
    ]
    for label, data in (("索引路径（用于判断）", indexed), ("全部", overall)):
        lines.append(
            f"| {label} | {data['comparisons']} | {pct(data['top1_match_rate'])} | {pct(data['mean_overlap_at_k'])} | {pct(data['error_rate'])} "
            f"| {data['v1_latency_ms']['p50']} / {data['v1_latency_ms']['p95']} | {data['v2_latency_ms']['p50']} / {data['v2_latency_ms']['p95']} |"
        )
    lines += ["", "引擎分布：" + "，".join(f"`{name}` {count}" for name, count in report["by_engine"].items())]
    lines += ["", "## 按天（索引路径）", "", "| 日期 | 对比 | 索引路径 | top1 一致 | 平均重合 | 错误 |", "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for day in report["by_day"]:
        lines.append(f"| {day['day']} | {day['comparisons']} | {day['indexed']} | {pct(day['top1_match_rate'])} | {pct(day['mean_overlap_at_k'])} | {day['errors']} |")
    if report["capability_degraded"]:
        lines += ["", "能力降级：" + "，".join(f"`{code}` {count}" for code, count in report["capability_degraded"].items())]
    if report["error_codes"]:
        lines += ["", "V2 错误：" + "，".join(f"`{code}` {count}" for code, count in report["error_codes"].items())]
    if report["worst_queries"]:
        lines += ["", "## 不一致最多的问题（索引路径）", "", "| 问题 | 出现 | top1 不一致 | 平均重合 | V1 前 3 | V2 前 3 |", "| :--- | ---: | ---: | ---: | :--- | :--- |"]
        for item in report["worst_queries"]:
            label = (item["query_preview"] or f"`{item['query_hash'][:12]}`").replace("|", "/")
            lines.append(
                f"| {label} | {item['seen']} | {item['top1_misses']} | {pct(item['mean_overlap_at_k'])} "
                f"| {', '.join(item['v1_top'][:3])} | {', '.join(item['v2_top'][:3])} |"
            )
    checks = report["checks"]
    th = report["thresholds"]
    lines += [
        "",
        f"门槛：索引路径对比 ≥ {th['min_indexed']}（{'✓' if checks['enough_indexed_comparisons'] else '✗'}）、"
        f"top1 一致 ≥ {th['min_top1']:.0%}（{'✓' if checks['top1_agreement'] else '✗'}）、"
        f"平均重合 ≥ {th['min_overlap']:.0%}（{'✓' if checks['overlap'] else '✗'}）、"
        f"错误率 ≤ {th['max_errors']:.0%}（{'✓' if checks['error_rate'] else '✗'}）。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import database.core as database_core

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--min-indexed", type=int, default=200)
    parser.add_argument("--min-top1", type=float, default=0.98)
    parser.add_argument("--min-overlap", type=float, default=0.95)
    parser.add_argument("--max-errors", type=float, default=0.01)
    parser.add_argument("--worst", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 365:
        raise SystemExit("--days must be 1..365")
    try:
        with database_core.get_db_connection() as conn:
            report = summarize(
                conn, days=args.days, min_indexed=args.min_indexed, min_top1=args.min_top1,
                min_overlap=args.min_overlap, max_errors=args.max_errors, worst=max(1, min(args.worst, 200)),
            )
    except Exception as exc:
        report = {"status": "ERROR", "errors": [type(exc).__name__, str(exc)[:300]],
                  "hint": "读取失败：确认 DATABASE_URL 指向正式库，且 m0333 已执行。"}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    summary = {key: report[key] for key in ("status", "hint", "checks", "indexed", "by_engine")}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] in {"READY", "INSUFFICIENT_DATA", "ONLY_EXACT_PATH"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
