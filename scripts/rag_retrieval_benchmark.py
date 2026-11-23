#!/usr/bin/env python3
"""RAG retrieval benchmark and ACL projection check (refactor phases 0-1).

Two commands:

``benchmark``
    Builds a disposable PostgreSQL database (same protection as the Gold-400
    runner: the name carries the test prefix and the database is dropped in
    ``finally``), loads a synthetic network-documentation corpus through the
    normal ingestion path, and runs the same query set with the V1 engine and
    the V2 indexed engine.  Reports p50/p95 latency, rows loaded into Python,
    and how often V1 and V2 agree.  Never touches the application database.

``verify-acl``
    Read-only check against the configured database: compares the SQL
    ``ai_document.acl_principals`` projection (m0330) with the Python policy
    ``rag_policy.document_is_visible`` for every document.

Examples::

    python scripts/rag_retrieval_benchmark.py benchmark --chunks 10000
    python scripts/rag_retrieval_benchmark.py benchmark --chunks 100000 --output docs/knowledge-engine/eval/rag-benchmark-100k.json
    python scripts/rag_retrieval_benchmark.py verify-acl
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
for path in (BACKEND_ROOT, ROOT):
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

DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "rag-retrieval-benchmark.json"
TENANT = "tenant-rag-benchmark"

VENDORS = {
    "Huawei": {"platform": "huawei_vrp", "family": "Campus Switch", "series": "S5700", "model": "S5735-L48T4S", "release": "V200R023"},
    "Cisco": {"platform": "cisco_ios", "family": "Catalyst", "series": "Catalyst 9300", "model": "C9300-48T", "release": "17.9"},
    "H3C": {"platform": "h3c_comware", "family": "S5500 Series", "series": "S5560X", "model": "S5560X-54C-EI", "release": "Comware 7"},
    "Ruijie": {"platform": "ruijie_rgos", "family": "RG-S5750", "series": "RG-S5750C", "model": "RG-S5750C-48GT4XS-H", "release": "RGOS 11.4"},
}

FEATURES = {
    "ospf": {
        "commands": ["display ospf peer", "show ip ospf neighbor", "ospf 1 router-id 1.1.1.1", "area 0.0.0.0"],
        "zh": ["OSPF 邻居状态停留在 ExStart，通常是 MTU 不一致", "检查 OSPF 区域和网络类型是否匹配", "OSPF 邻居建立后状态应为 Full"],
    },
    "vlan": {
        "commands": ["vlan batch 10 20", "port link-type trunk", "port trunk allow-pass vlan 10", "switchport mode access"],
        "zh": ["Trunk 端口需要放行业务 VLAN", "Access 端口只属于一个 VLAN", "VLAN 不通时先检查端口类型和放行列表"],
    },
    "bgp": {
        "commands": ["display bgp peer", "show ip bgp summary", "peer 10.0.0.2 as-number 65001", "network 192.168.0.0 24"],
        "zh": ["BGP 会话应处于 Established 状态", "检查 AS 号和更新源地址是否正确", "BGP 路由未学习时查看路由策略"],
    },
    "lacp": {
        "commands": ["display eth-trunk 1", "interface eth-trunk 1", "mode lacp", "channel-group 1 mode active"],
        "zh": ["链路聚合成员端口速率和双工需要一致", "LACP 协商失败时检查两端模式", "Eth-Trunk 成员口状态应为 Selected"],
    },
    "ntp": {
        "commands": ["ntp-service unicast-server 10.1.1.1", "display ntp-service status", "ntp server 10.1.1.1"],
        "zh": ["NTP 时钟未同步时检查服务器可达性", "设备时间偏差会影响日志关联", "NTP 状态应显示 synchronized"],
    },
    "ssh": {
        "commands": ["stelnet server enable", "ssh user admin authentication-type password", "ip ssh version 2"],
        "zh": ["SSH 登录失败时检查 VTY 认证模式", "启用 SSH 前需要生成本地密钥对", "建议关闭 Telnet 只保留 SSH"],
    },
    "acl": {
        "commands": ["acl number 3000", "rule 5 permit ip source 10.1.1.0 0.0.0.255", "access-list 101 permit ip any any"],
        "zh": ["ACL 规则按编号顺序匹配", "流量被意外拒绝时检查 ACL 最后的隐含规则", "ACL 需要在接口方向上应用"],
    },
    "static_route": {
        "commands": ["ip route-static 0.0.0.0 0 10.1.1.254", "ip route 0.0.0.0 0.0.0.0 10.1.1.254", "display ip routing-table"],
        "zh": ["静态路由下一跳不可达时路由不会生效", "默认路由用于访问外部网络", "检查路由表确认静态路由已安装"],
    },
}

QUERIES = [
    ("display ospf peer 邻居状态 ExStart", "Huawei"),
    ("OSPF neighbor stuck in ExStart MTU", "Cisco"),
    ("trunk 端口放行 VLAN 配置", "Huawei"),
    ("switchport mode access VLAN", "Cisco"),
    ("BGP 会话 Established 状态检查", "H3C"),
    ("show ip bgp summary peer down", "Cisco"),
    ("Eth-Trunk LACP 成员口 Selected", "Huawei"),
    ("channel-group mode active LACP", "Cisco"),
    ("NTP 时钟未同步 synchronized", "Ruijie"),
    ("ssh user authentication-type password", "Huawei"),
    ("ACL 隐含规则 流量被拒绝", "H3C"),
    ("ip route-static 默认路由 下一跳", "Huawei"),
    ("display ip routing-table 静态路由", "Huawei"),
    ("VLAN 不通 端口类型", "Ruijie"),
    ("ospf router-id area 0", "H3C"),
    ("access-list permit ip any any", "Cisco"),
    ("stelnet server enable 关闭 Telnet", "Huawei"),
    ("BGP 路由未学习 路由策略", "Huawei"),
    ("链路聚合 速率 双工 一致", "H3C"),
    ("ntp server 可达性 日志关联", "Cisco"),
]


def _document(rng: random.Random, index: int) -> tuple[str, str, str, dict[str, Any]]:
    vendor = rng.choice(list(VENDORS))
    feature = rng.choice(list(FEATURES))
    profile, catalog = VENDORS[vendor], FEATURES[feature]
    sections = []
    for section_no in range(rng.randint(3, 6)):
        commands = "\n".join(rng.sample(catalog["commands"], k=min(2, len(catalog["commands"]))))
        notes = "；".join(rng.sample(catalog["zh"], k=2))
        interface = f"GigabitEthernet0/0/{rng.randint(1, 48)}"
        sections.append(
            f"## {feature.upper()} 场景 {section_no + 1}\n\n"
            f"{notes}。接口 {interface}，VLAN {rng.randint(2, 4000)}，文档编号 {index}-{section_no}。\n\n"
            f"```\n{commands}\n```"
        )
    content = f"# {vendor} {feature.upper()} 运维手册 {index}\n\n" + "\n\n".join(sections)
    metadata = {
        "vendor": vendor,
        "product_family": profile["family"],
        "product_series": profile["series"],
        "product_model": profile["model"],
        "cli_platform": profile["platform"],
        "software_release": profile["release"],
        "source_type": "user_document",
        "document_category": "configuration",
        "feature": feature,
    }
    return f"{vendor} {feature} guide {index}", content, vendor, metadata


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def _load_corpus(target_chunks: int, seed: int) -> dict[str, Any]:
    from ai.services.knowledge_service import knowledge_service

    rng = random.Random(seed)
    knowledge_base = knowledge_service.create_knowledge_base("RAG benchmark corpus", tenant_id=TENANT)
    documents = chunks = 0
    started = time.perf_counter()
    while chunks < target_chunks:
        name, content, vendor, metadata = _document(rng, documents)
        result = knowledge_service.add_document_and_chunk(
            knowledge_base_id=knowledge_base["id"],
            name=name,
            content=content,
            vendor=vendor,
            platform=metadata["cli_platform"],
            tenant_id=TENANT,
            metadata=metadata,
            invalidate_cache=False,
        )
        documents += 1
        chunks += int(result.get("chunk_count") or 0)
        if documents % 200 == 0:
            print(f"[benchmark] loaded {documents} documents / {chunks} chunks", flush=True)
    with database_core.get_db_connection() as conn:
        # Disposable database: build the m0332 index directly (production
        # uses rag_index_maintenance.py fts-index, CONCURRENTLY).  The
        # trigger has already filled search_tsv for every loaded chunk.
        columns = {str(item[0]) for item in (conn.execute("SELECT * FROM ai_document_chunk WHERE 1 = 0").description or [])}
        if "search_tsv" in columns:
            conn.execute("CREATE INDEX IF NOT EXISTS ix_ai_chunk_search_tsv ON ai_document_chunk USING GIN (search_tsv)")
        conn.execute("ANALYZE ai_document")
        conn.execute("ANALYZE ai_document_chunk")
        conn.commit()
    return {"documents": documents, "chunks": chunks, "load_seconds": round(time.perf_counter() - started, 1)}


DIAG_TOP_K = 50
TIE_EPSILON = 1e-6


def _run_engine(
    engine: str,
    repeats: int,
    *,
    warmup: bool = True,
    label: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    from ai.services.rag_retriever import RAGRetriever, RetrievalRequest

    label = label or engine
    os.environ["AI_RETRIEVAL_ENGINE"] = engine
    os.environ["AI_RETRIEVAL_V2_EXACT_THRESHOLD"] = "0"
    for key in ("AI_RETRIEVAL_NATIVE_LEXICAL", "AI_RETRIEVAL_FTS_SOURCE", "AI_RETRIEVAL_TRGM_MODE"):
        os.environ.pop(key, None)
    for key, value in (extra_env or {}).items():
        os.environ[key] = value
    retriever = RAGRetriever(cache_enabled=False)
    latencies: list[float] = []
    rows_loaded: list[int] = []
    stage_samples: dict[str, list[float]] = {}
    results: dict[str, list[str]] = {}
    ranked: dict[str, list[tuple[str, float]]] = {}
    degraded: dict[str, int] = {}
    fts_sources: dict[str, int] = {}
    python_vector_rows: list[int] = []
    engine_started = time.perf_counter()
    for number, (query, vendor) in enumerate(QUERIES, start=1):
        request = RetrievalRequest(query=query, vendor=vendor, top_k=5, tenant_id=TENANT, user_id="bench", roles=["Operator"])
        if warmup:
            retriever.search(request, min_relevance=0.0)
        query_latencies: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            payload = retriever.search(request, min_relevance=0.0)
            query_latencies.append((time.perf_counter() - started) * 1000.0)
            debug = payload["debug"]
            rows_loaded.append(int(debug.get("candidate_count") or 0))
            python_vector_rows.append(int(debug.get("rank_python_vector_rows") or 0))
            if debug.get("v2_fts_source"):
                fts_sources[str(debug["v2_fts_source"])] = fts_sources.get(str(debug["v2_fts_source"]), 0) + 1
            for key, value in (debug.get("v2_timing_ms") or {}).items():
                stage_samples.setdefault(key, []).append(float(value))
            for leg, info in (debug.get("v2_legs") or {}).items():
                if isinstance(info, dict) and "ms" in info:
                    stage_samples.setdefault(f"leg_{leg}", []).append(float(info["ms"]))
        latencies.extend(query_latencies)
        results[query] = [str(item.get("storage_document_id")) for item in payload["results"]]
        for code in payload["debug"].get("capability_degraded") or []:
            degraded[code] = degraded.get(code, 0) + 1
        # Untimed wide search: scores of the top 50 documents, used for
        # tie-aware agreement (synthetic documents share templates, so many
        # documents can have exactly the same score).
        wide = retriever.search(
            RetrievalRequest(query=query, vendor=vendor, top_k=DIAG_TOP_K, tenant_id=TENANT, user_id="bench", roles=["Operator"]),
            min_relevance=0.0,
        )
        ranked[query] = [
            (str(item.get("storage_document_id")), float(item.get("relevance_score") or 0.0))
            for item in wide["results"]
        ]
        print(
            f"[benchmark] {label} query {number}/{len(QUERIES)} "
            f"{statistics.fmean(query_latencies):.0f} ms, rows={rows_loaded[-1]} "
            f"(elapsed {time.perf_counter() - engine_started:.0f}s)",
            flush=True,
        )
    return {
        "engine": label,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 2) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        },
        "stage_ms_mean": {key: round(statistics.fmean(values), 2) for key, values in sorted(stage_samples.items())},
        "rows_loaded_into_python": {"mean": round(statistics.fmean(rows_loaded), 1) if rows_loaded else 0, "max": max(rows_loaded or [0])},
        "capability_degraded": degraded,
        "fts_source": fts_sources,
        "python_cosine_rows_mean": round(statistics.fmean(python_vector_rows), 1) if python_vector_rows else 0,
        "results": results,
        "ranked": ranked,
    }


def _agreement(reference: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Compare another engine's top 5 with the v1 reference."""
    top1 = overlap = tie_aware = recall50 = 0.0
    tie_sizes: list[int] = []
    per_query: dict[str, Any] = {}
    for query, _vendor in QUERIES:
        ref_top = reference["results"].get(query, [])
        got_top = other["results"].get(query, [])
        ref_ranked = reference["ranked"].get(query, [])
        ref_scores = dict(ref_ranked)
        cutoff = ref_ranked[min(4, len(ref_ranked) - 1)][1] if ref_ranked else 0.0
        tie_size = sum(1 for _doc, score in ref_ranked if score >= cutoff - TIE_EPSILON)
        tie_sizes.append(tie_size)
        top1 += int(bool(ref_top and got_top and ref_top[0] == got_top[0]))
        overlap += len(set(ref_top) & set(got_top)) / max(1, len(ref_top)) if ref_top else int(not got_top)
        # A result "agrees" when v1 scores it at least as high as v1's own
        # 5th result, i.e. it is interchangeable with v1's choice.
        good = sum(1 for doc in got_top if ref_scores.get(doc, -1.0) >= cutoff - TIE_EPSILON)
        tie_aware += good / max(1, len(got_top)) if got_top else int(not ref_top)
        other_wide = {doc for doc, _score in other["ranked"].get(query, [])}
        found = sum(1 for doc in ref_top if doc in other_wide)
        recall50 += found / max(1, len(ref_top)) if ref_top else 1.0
        per_query[query] = {
            "v1_top5_score_cutoff": round(cutoff, 4),
            "v1_docs_tied_at_or_above_cutoff": tie_size,
            "tie_aware_hits": good,
            "v1_top5_found_in_top50": found,
        }
    n = len(QUERIES)
    return {
        "top1_match_rate": round(top1 / n, 4),
        "mean_overlap_at_5": round(overlap / n, 4),
        "tie_aware_overlap_at_5": round(tie_aware / n, 4),
        "v1_top5_recall_in_top50": round(recall50 / n, 4),
        "mean_v1_tie_group_size": round(statistics.fmean(tie_sizes), 1) if tie_sizes else 0,
        "per_query": per_query,
    }


def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if not database_core._USE_PG or not database_schema._USE_PG:
        raise RuntimeError("PostgreSQL DATABASE_URL is required")
    original_state = capture_database_state()
    source_url = database_core._DATABASE_URL
    validate_test_server_url(source_url)
    target = None
    saved_env = {key: os.environ.get(key) for key in ("AI_RETRIEVAL_ENGINE", "AI_RETRIEVAL_V2_EXACT_THRESHOLD", "AI_RETRIEVAL_NATIVE_LEXICAL", "AI_RETRIEVAL_FTS_SOURCE", "AI_RETRIEVAL_TRGM_MODE")}
    try:
        target = create_test_database(source_url, purpose="rag_benchmark")
        switch_database(target.url, initialized=False)
        database.init_db()
        close_database_pool()
        corpus = _load_corpus(args.chunks, args.seed)
        # v1 scans every visible chunk in Python; one timed pass per query
        # is enough to measure it and keeps a 10k-chunk run practical.
        v1 = _run_engine("v1", args.v1_repeats, warmup=False)
        v2 = _run_engine("v2", args.repeats)
        # Previous V2 legs for comparison: m0138 expression FTS and the
        # whole-query trigram match.
        v2_pylex = _run_engine(
            "v2", args.repeats, label="v2_previous_legs",
            extra_env={"AI_RETRIEVAL_FTS_SOURCE": "expression", "AI_RETRIEVAL_TRGM_MODE": "query"},
        )
        # Term-based trigram matching, measured separately.
        v2_terms = _run_engine(
            "v2", args.repeats, label="v2_trgm_terms",
            extra_env={"AI_RETRIEVAL_TRGM_MODE": "terms"},
        )
        engines = (v1, v2, v2_pylex, v2_terms)
        agreement = {
            "v2": _agreement(v1, v2),
            "v2_previous_legs": _agreement(v1, v2_pylex),
            "v2_trgm_terms": _agreement(v1, v2_terms),
        }
        strip = {"results", "ranked"}
        return {
            "status": "PASS",
            "database": "PostgreSQL (disposable)",
            "corpus": corpus,
            "query_count": len(QUERIES),
            "repeats": {"v1": args.v1_repeats, "v2": args.repeats},
            "engines": {item["engine"]: {k: v for k, v in item.items() if k not in strip} for item in engines},
            "agreement": {name: {k: v for k, v in data.items() if k != "per_query"} for name, data in agreement.items()},
            "per_query": {
                query: {
                    "v1": v1["results"].get(query),
                    "v2": v2["results"].get(query),
                    "v2_previous_legs": v2_pylex["results"].get(query),
                    "v2_diag": agreement["v2"]["per_query"][query],
                    "v2_previous_legs_diag": agreement["v2_previous_legs"]["per_query"][query],
                }
                for query, _ in QUERIES
            },
        }
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        close_database_pool()
        restore_database_state(original_state)
        if target is not None:
            drop_test_database(target)


def verify_acl(_args: argparse.Namespace) -> dict[str, Any]:
    """Read-only: compare the SQL ACL projection with the Python policy."""
    from ai.services.rag_policy import document_is_visible, parse_acl

    mismatches: list[dict[str, Any]] = []
    unprojected = checked = 0
    with database_core.get_db_connection() as conn:
        rows = conn.execute("SELECT id, acl_json, acl_principals FROM ai_document").fetchall()
    for document_id, raw_acl, projected in rows:
        checked += 1
        if projected is None:
            unprojected += 1
            continue
        projected_set = set(projected)
        acl = parse_acl(raw_acl)
        probes: list[tuple[str | None, list[str], list[str]]] = [(None, [], []), ("__probe_nobody__", ["__probe_role__"], ["__probe_site__"])]
        probes += [(value, [], []) for key in ("users", "user_ids") for value in acl.get(key, [])]
        probes += [(None, [value], []) for value in acl.get("roles", [])]
        probes += [(None, [], [value]) for key in ("sites", "site_ids") for value in acl.get(key, [])]
        for user_id, roles, sites in probes:
            principals = {"*"} | ({f"u:{user_id}"} if user_id else set()) | {f"r:{r}" for r in roles} | {f"s:{s}" for s in sites}
            sql_visible = bool(principals & projected_set)
            python_visible = document_is_visible({"acl_json": raw_acl}, user_id=user_id, roles=roles, site_ids=sites)
            if sql_visible != python_visible:
                mismatches.append({
                    "document_id": document_id,
                    "probe": {"user": user_id, "roles": roles, "sites": sites},
                    "sql_visible": sql_visible,
                    "python_visible": python_visible,
                    # sql_visible=True/python_visible=False is harmless (the
                    # retriever re-checks in Python); the reverse loses recall.
                    "effect": "recall_loss" if python_visible else "filtered_by_python_recheck",
                })
    return {
        "status": "PASS" if not mismatches and not unprojected else "REVIEW",
        "documents_checked": checked,
        "documents_without_projection": unprojected,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:200],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    bench = sub.add_parser("benchmark", help="V1 vs V2 retrieval on a disposable synthetic corpus")
    bench.add_argument("--chunks", type=int, default=10_000)
    bench.add_argument("--repeats", type=int, default=3, help="timed runs per query for v2")
    bench.add_argument("--v1-repeats", type=int, default=1, help="timed runs per query for v1 (slow full scan; no warm-up)")
    bench.add_argument("--seed", type=int, default=20261122)
    bench.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    acl = sub.add_parser("verify-acl", help="read-only ACL projection check on the configured database")
    acl.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        report = benchmark(args) if args.command == "benchmark" else verify_acl(args)
    except Exception as exc:
        report = {"status": "NOT_READY", "errors": [type(exc).__name__, str(exc)[:300]]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"per_query", "mismatches"}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report.get("status") in {"PASS", "REVIEW"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
