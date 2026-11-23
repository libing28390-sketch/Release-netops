#!/usr/bin/env python3
"""Compare retrieval configurations before switching the vector source (phase 4).

Runs on a disposable PostgreSQL database (same protection as the Gold-400
runner), imports the checked-in local knowledge pack, and evaluates:

    v1            current engine
    v2_legacy     V2 engine, legacy 1536-d hash vectors
    v2_semantic   V2 engine, bge-m3 vectors (only with a ready sidecar; the
                  disposable corpus is back-filled and indexed first)

on two datasets:

    gold400   eval-golden-400.yaml answer cases (vendor/platform/feature filters)
    zh50      eval-semantic-zh-50.yaml colloquial Chinese cases (vendor/platform
              filters only -- the vector signal has to find the feature)

Weight tuning (``--grid``) is done on the tune splits only (gold400
train+debug, zh50 tune); the hidden splits are scored once with the chosen
weights so the reported numbers are not fitted to themselves.

Examples::

    python scripts/rag_semantic_eval.py                      # v1 + v2_legacy (+ v2_semantic if sidecar ready)
    python scripts/rag_semantic_eval.py --grid               # also sweep score weights for v2_semantic
    python scripts/rag_semantic_eval.py --weights lexical=0.35,vector=0.35,metadata=0.15,trust=0.10,version=0.05

Writes ``docs/knowledge-engine/eval/rag-semantic-comparison.json`` and a
Markdown summary next to it.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "backend", ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import database  # noqa: E402
import database.core as database_core  # noqa: E402
import database.schema as database_schema  # noqa: E402
from backend.tests.pg_test_utils import (  # noqa: E402
    capture_database_state,
    close_database_pool,
    create_test_database,
    drop_test_database,
    restore_database_state,
    switch_database,
    validate_test_server_url,
)

EVAL_DIR = ROOT / "docs" / "knowledge-engine" / "eval"
GOLD_PATH = EVAL_DIR / "eval-golden-400.yaml"
ZH_PATH = EVAL_DIR / "eval-semantic-zh-50.yaml"
PACK_CATALOG = ROOT / "data" / "kb_import" / "source_catalog.yaml"
DEFAULT_OUTPUT = EVAL_DIR / "rag-semantic-comparison.json"
TENANT = "tenant-semantic-eval"

VENDORS = {"Huawei", "Cisco", "H3C", "Ruijie"}
CORE_FEATURES = {"vlan", "access_port", "trunk", "ospf", "bgp", "lacp", "acl", "ssh", "ntp", "static_route"}
GATES = {"gold400_recall_at_5": 0.95, "gold400_recall_at_10": 0.97, "max_recall_drop_vs_v1": 0.01}
ENV_KEYS = (
    "AI_RETRIEVAL_ENGINE",
    "AI_RETRIEVAL_V2_EXACT_THRESHOLD",
    "AI_RETRIEVAL_VECTOR_SOURCE",
    "AI_RETRIEVAL_SCORE_WEIGHTS",
    "AI_RETRIEVAL_TRGM_MODE",
    "AI_RETRIEVAL_FTS_SOURCE",
    "AI_RETRIEVAL_NATIVE_LEXICAL",
)

# Small, interpretable grid: shift weight between lexical and vector, keep
# metadata/trust/version close to the frozen defaults.
GRID_LEXICAL_VECTOR = [(0.45, 0.25), (0.40, 0.30), (0.35, 0.35), (0.30, 0.40), (0.25, 0.45)]
GRID_TAIL = [(0.15, 0.10, 0.05), (0.20, 0.05, 0.05)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


# ── datasets ─────────────────────────────────────────────────────────────


def _load_cases() -> dict[str, list[dict[str, Any]]]:
    gold = yaml.safe_load(GOLD_PATH.read_text(encoding="utf-8")) or {}
    zh = yaml.safe_load(ZH_PATH.read_text(encoding="utf-8")) or {}
    gold_cases = []
    for case in gold.get("cases") or []:
        if _text(case.get("expected_outcome")) != "answer":
            continue
        vendor, feature = _text(case.get("vendor")), _text(case.get("feature"))
        gold_cases.append({
            "id": _text(case.get("id")),
            "query": _text(case.get("query")),
            "filters": {
                "vendor": vendor if vendor in VENDORS else None,
                "platform": _text(case.get("platform")) if vendor in VENDORS else None,
                "feature": feature if feature in CORE_FEATURES else None,
            },
            "expected": [*(case.get("acceptable_document_ids") or []), *(case.get("gold_document_ids") or [])],
            "split": "hidden" if _text(case.get("split")) == "hidden" else "tune",
            "vendor": vendor,
            "keyword_free": False,
        })
    zh_cases = []
    for case in zh.get("cases") or []:
        vendor = _text(case.get("vendor"))
        zh_cases.append({
            "id": _text(case.get("id")),
            "query": _text(case.get("query")),
            "filters": {"vendor": vendor, "platform": _text(case.get("platform"))},
            "expected": [*(case.get("gold_document_ids") or []), *(case.get("acceptable_document_ids") or [])],
            "split": _text(case.get("split")) or "tune",
            "vendor": vendor,
            "keyword_free": bool(case.get("keyword_free")),
        })
    return {"gold400": gold_cases, "zh50": zh_cases}


# ── evaluation ───────────────────────────────────────────────────────────


def _apply_env(values: Mapping[str, str | None]) -> None:
    for key in ENV_KEYS:
        value = values.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _config_env(name: str, weights: str | None = None) -> dict[str, str | None]:
    base: dict[str, dict[str, str]] = {
        "v1": {"AI_RETRIEVAL_ENGINE": "v1"},
        "v2_legacy": {"AI_RETRIEVAL_ENGINE": "v2", "AI_RETRIEVAL_V2_EXACT_THRESHOLD": "0", "AI_RETRIEVAL_VECTOR_SOURCE": "legacy"},
        # Same as v2_legacy but the fuzzy leg always runs: measures what the
        # default "auto" mode (skip for plain Latin-word queries) costs in recall.
        "v2_legacy_trgm_always": {
            "AI_RETRIEVAL_ENGINE": "v2", "AI_RETRIEVAL_V2_EXACT_THRESHOLD": "0",
            "AI_RETRIEVAL_VECTOR_SOURCE": "legacy", "AI_RETRIEVAL_TRGM_MODE": "query",
        },
        "v2_semantic": {"AI_RETRIEVAL_ENGINE": "v2", "AI_RETRIEVAL_V2_EXACT_THRESHOLD": "0", "AI_RETRIEVAL_VECTOR_SOURCE": "semantic"},
    }[name]
    env: dict[str, str | None] = dict(base)
    env["AI_RETRIEVAL_SCORE_WEIGHTS"] = weights
    return env


def _evaluate(cases: list[dict[str, Any]], env: Mapping[str, str | None]) -> dict[str, Any]:
    from ai.services.rag_retriever import RAGRetriever

    _apply_env(env)
    retriever = RAGRetriever(cache_enabled=False)
    rows = []
    degraded: dict[str, int] = {}
    for case in cases:
        started = time.perf_counter()
        returned = retriever.retrieve(
            case["query"], top_k=10, tenant_id=TENANT, knowledge_scope="enterprise",
            **{key: value for key, value in case["filters"].items() if value},
        )
        latency = (time.perf_counter() - started) * 1000.0
        ids = [_text(item.get("document_id") or item.get("storage_document_id")) for item in returned]
        ids = [item for item in ids if item]
        expected = set(case["expected"])
        rank = next((index for index, document_id in enumerate(ids, start=1) if document_id in expected), None)
        vendors = {_text(item.get("vendor")) for item in returned if _text(item.get("vendor"))}
        for code in (retriever.last_debug or {}).get("capability_degraded") or []:
            degraded[code] = degraded.get(code, 0) + 1
        rows.append({
            "id": case["id"],
            "split": case["split"],
            "keyword_free": case["keyword_free"],
            "rank": rank,
            "returned": ids[:5],
            "vendor_isolation_passed": case["vendor"] not in VENDORS or vendors <= {case["vendor"]},
            "latency_ms": round(latency, 2),
            "vector_source": (retriever.last_debug or {}).get("vector_source"),
        })
    return {"rows": rows, "capability_degraded": degraded}


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0}
    count = len(rows)
    latencies = [row["latency_ms"] for row in rows]
    return {
        "count": count,
        "recall_at_1": round(sum(1 for row in rows if row["rank"] == 1) / count, 4),
        "recall_at_5": round(sum(1 for row in rows if row["rank"] and row["rank"] <= 5) / count, 4),
        "recall_at_10": round(sum(1 for row in rows if row["rank"] and row["rank"] <= 10) / count, 4),
        "mrr": round(statistics.fmean(1.0 / row["rank"] if row["rank"] else 0.0 for row in rows), 4),
        "vendor_isolation_failures": sum(1 for row in rows if not row["vendor_isolation_passed"]),
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
    }


def _summarise(result: dict[str, Any]) -> dict[str, Any]:
    rows = result["rows"]
    return {
        "all": _metrics(rows),
        "tune": _metrics([row for row in rows if row["split"] != "hidden"]),
        "hidden": _metrics([row for row in rows if row["split"] == "hidden"]),
        "keyword_free": _metrics([row for row in rows if row["keyword_free"]]),
        "capability_degraded": result["capability_degraded"],
    }


def _grid() -> list[str]:
    combos = []
    for (lexical, vector), (metadata, trust, version) in itertools.product(GRID_LEXICAL_VECTOR, GRID_TAIL):
        combos.append(f"lexical={lexical},vector={vector},metadata={metadata},trust={trust},version={version}")
    return combos


# ── corpus ───────────────────────────────────────────────────────────────


def _load_corpus() -> int:
    from ai.services.knowledge_bundle_import_service import import_knowledge_bundle
    from ai.services.knowledge_service import knowledge_service
    from build_local_knowledge_pack import build_pack

    with tempfile.TemporaryDirectory(prefix="nexora_semantic_eval_") as directory:
        root = Path(directory)
        archive = root / "local-pack.zip"
        build_pack(
            catalog_path=PACK_CATALOG,
            source_dir=root / "source",
            manifest_path=root / "manifest.json",
            coverage_path=root / "coverage.json",
            archive_path=archive,
        )
        knowledge_base = knowledge_service.create_knowledge_base("Semantic eval corpus", tenant_id=TENANT)
        imported = import_knowledge_bundle(archive.read_bytes(), tenant_id=TENANT, knowledge_base_id=knowledge_base["id"])
    return int(imported.get("document_count") or 0)


def _build_fts_index() -> None:
    """Production state after ``rag_index_maintenance.py fts-index``.

    The m0332 trigger has filled search_tsv during the import; on this
    disposable database the GIN index can be built directly.
    """
    with database_core.get_db_connection() as conn:
        columns = {str(item[0]) for item in (conn.execute("SELECT * FROM ai_document_chunk WHERE 1 = 0").description or [])}
        if "search_tsv" in columns:
            conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_chunk_search_tsv ON ai_document_chunk USING GIN (search_tsv)")
        conn.execute("ANALYZE ai_document_chunk")
        conn.commit()


def _prepare_semantic() -> dict[str, Any]:
    """Back-fill and index the disposable corpus; report why if impossible."""
    from ai.providers.embedding import semantic_embedding_status

    status = semantic_embedding_status()
    if status.get("status") != "ready":
        return {"available": False, "sidecar": status}
    import rag_index_maintenance as maintenance

    model = os.environ.get("AI_SEMANTIC_EMBEDDING_MODEL", "bge-m3")
    version = os.environ.get("AI_SEMANTIC_EMBEDDING_VERSION", "bge-m3-int8-v1")
    fill = maintenance.backfill(argparse.Namespace(
        model=model, version=version, all=False, batch=32, limit=0, sleep=0.0, max_failures=3, dry_run=False,
    ))
    if fill.get("status") != "PASS":
        return {"available": False, "sidecar": status, "backfill": fill}
    index = maintenance.build_index(argparse.Namespace(
        maintenance_work_mem="256MB", parallel_workers=None, m=16, ef_construction=64, rebuild=True,
    ))
    coverage = maintenance.status(argparse.Namespace(model=model, version=version, all=False))
    return {"available": coverage["chunks"]["coverage"] >= 0.999, "sidecar": status, "backfill": fill, "index": index, "coverage": coverage["chunks"]}


# ── report ───────────────────────────────────────────────────────────────


def _gate(report: dict[str, Any]) -> dict[str, Any]:
    configs = report["configs"]
    checks: dict[str, Any] = {}
    baseline = configs.get("v1", {}).get("gold400", {}).get("all", {})
    for name, values in configs.items():
        gold = values["gold400"]["all"]
        checks[name] = {
            "gold400_recall_at_5": gold.get("recall_at_5", 0) >= GATES["gold400_recall_at_5"],
            "gold400_recall_at_10": gold.get("recall_at_10", 0) >= GATES["gold400_recall_at_10"],
            "no_vendor_leak": gold.get("vendor_isolation_failures", 1) == 0 and values["zh50"]["all"].get("vendor_isolation_failures", 1) == 0,
            "not_worse_than_v1": name == "v1" or (
                gold.get("recall_at_5", 0) >= baseline.get("recall_at_5", 0) - GATES["max_recall_drop_vs_v1"]
                and gold.get("recall_at_10", 0) >= baseline.get("recall_at_10", 0) - GATES["max_recall_drop_vs_v1"]
            ),
        }
        checks[name]["passed"] = all(checks[name].values())
    return checks


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 检索配置对比（阶段 4）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 语料：{report['corpus_documents']} 篇（本地知识包，一次性数据库）",
        f"- 语义向量：{'可用' if report['semantic']['available'] else '不可用（' + json.dumps(report['semantic'].get('sidecar', {}), ensure_ascii=False) + '）'}",
        "",
        "| 配置 | 金标 R@5 | 金标 R@10 | 金标 MRR | 口语集 R@5（hidden） | 口语集 R@5（无关键词） | 口语集 MRR | 厂商越界 | p95 ms | 门槛 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for name, values in report["configs"].items():
        gold, zh = values["gold400"], values["zh50"]
        leaks = gold["all"].get("vendor_isolation_failures", 0) + zh["all"].get("vendor_isolation_failures", 0)
        gate = report["gates"].get(name, {})
        lines.append(
            f"| {name}{' (' + values['weights'] + ')' if values.get('weights') else ''} "
            f"| {gold['all'].get('recall_at_5', 0):.3f} | {gold['all'].get('recall_at_10', 0):.3f} | {gold['all'].get('mrr', 0):.3f} "
            f"| {zh['hidden'].get('recall_at_5', 0):.3f} | {zh['keyword_free'].get('recall_at_5', 0):.3f} | {zh['all'].get('mrr', 0):.3f} "
            f"| {leaks} | {gold['all'].get('latency_ms', {}).get('p95', 0)} | {'通过' if gate.get('passed') else '未通过'} |"
        )
    lost = report.get("trgm_auto_losses") or []
    lines += ["", f"模糊匹配跳过（auto）相对始终运行（trgm_always）的 R@10 损失：{len(lost)} 条"]
    for item in lost[:30]:
        lines.append(f"- `{item['dataset']}` {item['id']}：{item['query']}（rank {item['always']} → {item['auto']}）")
    if report.get("grid"):
        lines += ["", "## 权重搜索（只用 tune 集）", "", "| 权重 | 金标 tune MRR | 口语集 tune MRR | 合计 |", "| :--- | ---: | ---: | ---: |"]
        for item in report["grid"]:
            lines.append(f"| `{item['weights']}` | {item['gold400_tune_mrr']:.3f} | {item['zh50_tune_mrr']:.3f} | {item['objective']:.3f} |")
        lines += ["", f"选中：`{report['grid_best']}`（hidden 集结果见上表 `v2_semantic_tuned`）"]
    lines += [
        "",
        "门槛：金标 R@5 ≥ 0.95、R@10 ≥ 0.97，无厂商越界，且 R@5/R@10 不比 v1 低超过 0.01。",
        "口语集目前为草稿（需人工复核），只作参考，不作为门槛。",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not database_core._USE_PG or not database_schema._USE_PG:
        raise RuntimeError("PostgreSQL DATABASE_URL is required")
    datasets = _load_cases()
    saved_env = {key: os.environ.get(key) for key in ENV_KEYS}
    original_state = capture_database_state()
    source_url = database_core._DATABASE_URL
    validate_test_server_url(source_url)
    target = None
    try:
        target = create_test_database(source_url, purpose="semantic_eval")
        switch_database(target.url, initialized=False)
        database.init_db()
        close_database_pool()
        document_count = _load_corpus()
        _build_fts_index()
        semantic = _prepare_semantic()

        plan: list[tuple[str, str, str | None]] = [
            ("v1", "v1", None),
            ("v2_legacy", "v2_legacy", None),
            ("v2_legacy_trgm_always", "v2_legacy_trgm_always", None),
        ]
        if semantic["available"]:
            plan.append(("v2_semantic", "v2_semantic", None))
            for weights in args.weights or []:
                plan.append((f"v2_semantic[{weights}]", "v2_semantic", weights))

        configs: dict[str, Any] = {}
        for label, name, weights in plan:
            print(f"[eval] {label}", flush=True)
            entry: dict[str, Any] = {"weights": weights}
            for dataset, cases in datasets.items():
                result = _evaluate(cases, _config_env(name, weights))
                entry[dataset] = _summarise(result)
                if label in {"v2_legacy", "v2_legacy_trgm_always"}:
                    entry[f"_{dataset}_rows"] = result["rows"]
            configs[label] = entry

        grid_results: list[dict[str, Any]] = []
        best = None
        if args.grid and semantic["available"]:
            tune = {dataset: [case for case in cases if case["split"] != "hidden"] for dataset, cases in datasets.items()}
            for weights in _grid():
                print(f"[grid] {weights}", flush=True)
                gold_mrr = _metrics(_evaluate(tune["gold400"], _config_env("v2_semantic", weights))["rows"]).get("mrr", 0.0)
                zh_mrr = _metrics(_evaluate(tune["zh50"], _config_env("v2_semantic", weights))["rows"]).get("mrr", 0.0)
                # Gold-400 protects exact/official questions; zh50 measures the
                # semantic gain.  Equal weight, gold must not drop below v1.
                grid_results.append({"weights": weights, "gold400_tune_mrr": gold_mrr, "zh50_tune_mrr": zh_mrr, "objective": round(0.5 * gold_mrr + 0.5 * zh_mrr, 4)})
            grid_results.sort(key=lambda item: -item["objective"])
            best = grid_results[0]["weights"]
            configs["v2_semantic_tuned"] = {
                "weights": best,
                **{dataset: _summarise(_evaluate(cases, _config_env("v2_semantic", best))) for dataset, cases in datasets.items()},
            }

        losses = []
        for dataset in datasets:
            auto_rows = {row["id"]: row for row in configs["v2_legacy"][f"_{dataset}_rows"]}
            for row in configs["v2_legacy_trgm_always"][f"_{dataset}_rows"]:
                other = auto_rows.get(row["id"])
                if row["rank"] and row["rank"] <= 10 and other and not (other["rank"] and other["rank"] <= 10):
                    query = next((case["query"] for case in datasets[dataset] if case["id"] == row["id"]), "")
                    losses.append({"dataset": dataset, "id": row["id"], "query": query, "always": row["rank"], "auto": other["rank"]})
        for values in configs.values():
            for key in [key for key in values if key.startswith("_") and key.endswith("_rows")]:
                values.pop(key)
        report = {
            "status": "PASS",
            "trgm_auto_losses": losses,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "database": "PostgreSQL (disposable)",
            "corpus_documents": document_count,
            "semantic": semantic,
            "configs": configs,
            "grid": grid_results,
            "grid_best": best,
        }
        report["gates"] = _gate(report)
        return report
    finally:
        _apply_env(saved_env)
        close_database_pool()
        restore_database_state(original_state)
        if target is not None:
            drop_test_database(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grid", action="store_true", help="sweep score weights for v2_semantic on the tune splits")
    parser.add_argument("--weights", action="append", help="extra v2_semantic weight setting (repeatable)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.weights:
        from ai.services.retrieval_contract import parse_score_weights

        for weights in args.weights:
            parse_score_weights(weights)  # fail fast on a typo
    try:
        report = run(args)
    except Exception as exc:
        report = {"status": "NOT_READY", "errors": [type(exc).__name__, str(exc)[:300]]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report.get("status") == "PASS":
        args.output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"configs", "grid"}}, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
