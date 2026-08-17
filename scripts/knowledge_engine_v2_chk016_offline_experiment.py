"""Deterministic in-memory CHK-016 chunk-configuration comparison.

This experiment intentionally has no database dependency.  It uses the V2
ChunkingEngine against a fixed network-operations corpus, records reproducible
structural/traceability metrics, and writes a reviewable JSON report.  SQLite
is not used; PostgreSQL remains the persistence authority for other tasks.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from ai.chunking.engine import ChunkingConfig, ChunkingEngine


ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "chk016_chunk_experiment.json"

CORPUS: dict[str, str] = {
    "command_reference": """# Huawei CE6800 command reference

## Interface verification
Use read-only commands before making a change. Confirm the device is in the expected VRP V8R23C00 release.

```huawei
display version
display interface brief
display interface GigabitEthernet0/0/1
```

The output should show the operational state and negotiated speed. Record the command output in the change ticket.

## VLAN configuration
The operator must confirm the maintenance window and rollback plan before entering system-view.

```huawei
system-view
vlan batch 100 200
interface GigabitEthernet0/0/1
 port link-type trunk
 port trunk allow-pass vlan 100 200
```

Warning: applying the configuration can interrupt traffic on the interface.
""",
    "configuration_procedure": """# Cisco Catalyst 9300 configuration procedure

## Prerequisites
Confirm the approved change window, a console fallback, and a recent configuration backup. The target release is IOS XE 17.9.

## Configure the uplink
Enter configuration mode and apply the approved interface settings. Keep the command order unchanged so the rollback is deterministic.

```cisco
enable
configure terminal
interface GigabitEthernet1/0/1
 description uplink-to-core
 switchport mode trunk
 switchport trunk allowed vlan 100,200
 no shutdown
end
```

## Verify and rollback
Run `show interfaces trunk` and `show version`. If the expected VLANs are absent, restore the saved configuration and record the observed output.
""",
    "troubleshooting": """# OSPF adjacency troubleshooting

## Symptoms
The neighbor remains in EXSTART and routes are not installed. The issue is observed after a link flap on a Huawei and Cisco mixed network.

## Evidence collection
Collect timestamps, interface counters, MTU values and the current software train. Do not clear counters before saving evidence.

```huawei
display ospf peer brief
display interface GigabitEthernet0/0/1
display current-configuration interface GigabitEthernet0/0/1
```

```cisco
show ip ospf neighbor
show interface GigabitEthernet1/0/1
show logging | include OSPF
```

## Root cause and resolution
Compare the interface MTU and network type on both ends. Correct only the mismatched setting during the approved window, then verify the adjacency reaches FULL and routes converge.
""",
}

# Add deterministic long-form sections so the comparison exercises actual
# parent/child splitting and different token budgets rather than only the
# short-document fast path.
CORPUS["command_reference"] += "\n\n" + "\n\n".join(
    f"Verification note {index}: capture the interface state, negotiated speed, error counters, VLAN membership, "
    "maintenance ticket and operator timestamp before and after the command. Keep the exact CLI output so a later "
    "review can distinguish a transient control-plane event from a persistent forwarding fault."
    for index in range(1, 18)
)
CORPUS["configuration_procedure"] += "\n\n" + "\n\n".join(
    f"Procedure checkpoint {index}: confirm the peer, approved VLAN list, interface description, spanning-tree state, "
    "configuration archive and rollback owner. Apply one bounded change, verify the resulting state, and stop when "
    "the observed output differs from the expected IOS XE 17.9 baseline."
    for index in range(1, 18)
)
CORPUS["troubleshooting"] += "\n\n" + "\n\n".join(
    f"Evidence record {index}: correlate the OSPF neighbor state with interface MTU, packet counters, log timestamps, "
    "software train, network type and recent change activity. Preserve the before/after observation and do not infer "
    "a root cause until both vendor outputs agree."
    for index in range(1, 18)
)


def _config_variants() -> dict[str, ChunkingConfig]:
    baseline = ChunkingConfig()
    compact_target = dict(baseline.target_tokens)
    compact_max = dict(baseline.max_tokens)
    for key in compact_target:
        compact_target[key] = max(120, int(compact_target[key] * 0.62))
        compact_max[key] = max(compact_target[key], int(compact_max[key] * 0.62))
    balanced_target = dict(baseline.target_tokens)
    balanced_max = dict(baseline.max_tokens)
    for key in ("command", "command_reference", "verification", "warning", "command_output"):
        balanced_target[key] = max(140, int(balanced_target[key] * 0.82))
        balanced_max[key] = max(balanced_target[key], int(balanced_max[key] * 0.82))
    return {
        "baseline_v2": baseline,
        "balanced_network": ChunkingConfig(
            target_tokens=balanced_target,
            max_tokens=balanced_max,
            min_tokens=80,
            overlap_ratio=0.12,
            parent_min_blocks=2,
        ),
        "compact_retrieval": ChunkingConfig(
            target_tokens=compact_target,
            max_tokens=compact_max,
            min_tokens=70,
            overlap_ratio=0.08,
            parent_min_blocks=2,
        ),
        "structure_first": ChunkingConfig(
            target_tokens=dict(baseline.target_tokens),
            max_tokens=dict(baseline.max_tokens),
            min_tokens=100,
            overlap_ratio=0.15,
            parent_min_blocks=3,
        ),
    }


def _fingerprint(chunks: list[Any]) -> str:
    payload = [
        {
            "id": chunk.chunk_id,
            "role": chunk.chunk_role,
            "parent": chunk.parent_chunk_id,
            "ordinal": chunk.ordinal,
            "hash": chunk.content_hash,
            "neighbors": list(chunk.neighbor_chunk_ids),
            "locator": chunk.source_locator,
        }
        for chunk in chunks
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _run_config(name: str, config: ChunkingConfig) -> dict[str, Any]:
    all_chunks: list[Any] = []
    timings: list[float] = []
    per_document: dict[str, Any] = {}
    for document_name, text in CORPUS.items():
        started = time.perf_counter()
        chunks = ChunkingEngine(config=config).chunk(
            text,
            document_identity=f"chk016:{document_name}",
            document_metadata={"vendor": "Huawei" if "Huawei" in text else "Cisco", "document_version": "fixture-v1", "index_version": "offline-v1"},
        )
        timings.append((time.perf_counter() - started) * 1000)
        all_chunks.extend(chunks)
        per_document[document_name] = {
            "chunk_count": len(chunks),
            "parent_count": sum(chunk.chunk_role == "parent" for chunk in chunks),
            "child_count": sum(chunk.chunk_role == "child" for chunk in chunks),
            "candidate_count": sum(bool(chunk.is_retrieval_candidate) for chunk in chunks),
            "token_counts": [chunk.token_count for chunk in chunks],
            "fingerprint": _fingerprint(chunks),
        }

    ids = {chunk.chunk_id for chunk in all_chunks}
    hashes = [chunk.content_hash for chunk in all_chunks]
    duplicate_hash_count = len(hashes) - len(set(hashes))
    parent_child_valid = all(
        chunk.chunk_role != "child" or (chunk.parent_chunk_id in ids and chunk.parent_chunk_id != chunk.chunk_id)
        for chunk in all_chunks
    )
    neighbor_symmetric = all(
        all(chunk.chunk_id in next(item for item in all_chunks if item.chunk_id == neighbor).neighbor_chunk_ids for neighbor in chunk.neighbor_chunk_ids)
        for chunk in all_chunks
    )
    lineage_complete = all(
        bool(chunk.content_hash and chunk.source_locator and chunk.parser_version and chunk.document_version and chunk.index_version)
        for chunk in all_chunks
    )
    code_fences_balanced = all(chunk.raw_content.count("```") % 2 == 0 for chunk in all_chunks)
    marker_set = ("display interface", "system-view", "show ip ospf", "VRP V8R23C00", "IOS XE 17.9")
    marker_coverage = sum(any(marker.lower() in chunk.raw_content.lower() for chunk in all_chunks) for marker in marker_set) / len(marker_set)
    max_tokens = max((chunk.token_count for chunk in all_chunks), default=0)
    avg_tokens = statistics.mean(chunk.token_count for chunk in all_chunks) if all_chunks else 0.0
    max_allowed = max(config.maximum(chunk.chunk_type) for chunk in all_chunks) if all_chunks else 0
    structural_valid = bool(all_chunks) and parent_child_valid and neighbor_symmetric and duplicate_hash_count == 0 and code_fences_balanced
    score = round(
        0.30 * marker_coverage
        + 0.25 * float(lineage_complete)
        + 0.20 * float(structural_valid)
        + 0.15 * float(max_tokens <= max_allowed or any(chunk.oversize_reason for chunk in all_chunks))
        + 0.10 * float(all(chunk.source_locator for chunk in all_chunks)),
        4,
    )
    return {
        "configuration": name,
        "configuration_hash": config.configuration_hash(),
        "config": config.as_dict(),
        "documents": per_document,
        "chunk_count": len(all_chunks),
        "candidate_count": sum(bool(chunk.is_retrieval_candidate) for chunk in all_chunks),
        "parent_count": sum(chunk.chunk_role == "parent" for chunk in all_chunks),
        "child_count": sum(chunk.chunk_role == "child" for chunk in all_chunks),
        "undersized_count": sum(chunk.size_class == "undersized" for chunk in all_chunks),
        "oversized_count": sum(chunk.size_class == "oversized" for chunk in all_chunks),
        "duplicate_hash_count": duplicate_hash_count,
        "empty_count": sum(not chunk.raw_content.strip() for chunk in all_chunks),
        "avg_token_count": round(avg_tokens, 3),
        "max_token_count": max_tokens,
        "parent_child_valid": parent_child_valid,
        "neighbor_symmetric": neighbor_symmetric,
        "lineage_complete": lineage_complete,
        "code_fences_balanced": code_fences_balanced,
        "marker_coverage": round(marker_coverage, 4),
        "structural_valid": structural_valid,
        "latency_ms_avg": round(statistics.mean(timings), 4),
        "determinism_fingerprint": _fingerprint(all_chunks),
        "quality_score": score,
    }


def run_experiment() -> dict[str, Any]:
    results = [_run_config(name, config) for name, config in _config_variants().items()]
    # Repeat the recommended candidate to prove deterministic output, not to
    # claim production relevance from this small fixture corpus.
    repeat = _run_config("balanced_network", _config_variants()["balanced_network"])
    balanced = next(item for item in results if item["configuration"] == "balanced_network")
    deterministic = balanced["determinism_fingerprint"] == repeat["determinism_fingerprint"]
    all_valid = all(item["structural_valid"] and item["lineage_complete"] and item["marker_coverage"] == 1.0 for item in results)
    priority = {"baseline_v2": 0, "balanced_network": 1, "compact_retrieval": 2, "structure_first": 3}
    # Latency is reported for observation but is not used for the decision:
    # millisecond noise must not make two identical-quality runs recommend a
    # different configuration.
    ranked = sorted(
        results,
        key=lambda item: (
            -float(item["quality_score"]),
            int(item["chunk_count"]),
            -float(item["marker_coverage"]),
            priority.get(item["configuration"], 99),
        ),
    )
    recommendation = ranked[0]["configuration"] if ranked else "baseline_v2"
    return {
        "task_id": "CHK-016",
        "authority": "offline_in_memory",
        "database": "none",
        "corpus_documents": list(CORPUS),
        "corpus_sha256": hashlib.sha256(json.dumps(CORPUS, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "engine_version": ChunkingEngine.chunker_version,
        "experiment_contract": "chk016-offline-v1",
        "configurations": results,
        "ranking": [item["configuration"] for item in ranked],
        "recommendation": recommendation,
        "deterministic_repeat": deterministic,
        "all_configurations_valid": all_valid,
        "status": "PASS" if deterministic and all_valid else "FAIL",
    }


def main() -> None:
    report = run_experiment()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "task_id": report["task_id"],
        "database": report["database"],
        "configurations": len(report["configurations"]),
        "recommendation": report["recommendation"],
        "deterministic_repeat": report["deterministic_repeat"],
        "all_configurations_valid": report["all_configurations_valid"],
        "report": str(REPORT_PATH),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
