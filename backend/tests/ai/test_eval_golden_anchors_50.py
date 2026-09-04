import json
from pathlib import Path
import yaml
import pytest


def _load_anchor_runner():
    import sys

    scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import knowledge_eval_anchors_50_runner as runner

    return runner


def _run_synthetic_cases(monkeypatch, tmp_path, cases, responses):
    runner = _load_anchor_runner()
    dataset_path = tmp_path / "anchors.yaml"
    dataset_path.write_text(
        yaml.safe_dump(
            {
                "dataset_id": "synthetic-aigate-001",
                "status": "frozen",
                "total_cases": len(cases),
                "cases": cases,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "BENCHMARK_YAML", dataset_path)
    monkeypatch.setattr(runner, "REPORT_PATH", tmp_path / "report.json")

    def fake_call_api(query, context=None):
        case = (context or {}).get("vars", {})
        return responses[case["id"]]

    monkeypatch.setattr(runner, "call_api", fake_call_api)
    return runner.evaluate_anchors()


def _response(outcome, *, documents=None, vendors=None, features=None, output="OK"):
    return {
        "output": output,
        "metadata": {
            "outcome": outcome,
            "returned_document_ids": documents or [],
            "returned_vendors": vendors or [],
            "returned_features": features or [],
        },
    }


def test_eval_golden_anchors_50_integrity_and_distribution():
    dataset_path = Path(__file__).resolve().parents[3] / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50.yaml"
    assert dataset_path.is_file(), f"Dataset file not found: {dataset_path}"

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["status"] == "frozen"
    assert data["total_cases"] == 50

    cases = data["cases"]
    assert len(cases) == 50

    case_ids = [c["id"] for c in cases]
    expected_ids = [f"ANCHOR-{i:03d}" for i in range(1, 51)]
    assert case_ids == expected_ids, "Anchor IDs must be sequentially contiguous from ANCHOR-001 to ANCHOR-050"

    vendor_counts = {}
    outcomes = set()
    intents = set()

    for c in cases:
        assert "query" in c and len(c["query"]) > 0
        assert "intent" in c
        assert "expected_outcome" in c
        assert "forbidden_vendors" not in c, f"Case {c['id']} must not use legacy forbidden_vendors blacklist"
        outcomes.add(c["expected_outcome"])
        intents.add(c["intent"])
        v = c.get("vendor")
        vendor_counts[v] = vendor_counts.get(v, 0) + 1
        if v:
            assert c.get("vendor_isolation") == "strict", f"Case {c['id']} with target vendor {v} must use vendor_isolation: strict"

    # 验证四大厂商与负向覆盖分布
    assert vendor_counts.get("Huawei", 0) >= 12, "Huawei cases must be >= 12"
    assert vendor_counts.get("Cisco", 0) >= 12, "Cisco cases must be >= 12"
    assert vendor_counts.get("H3C", 0) >= 6, "H3C Comware cases must be >= 6"
    assert vendor_counts.get("Ruijie", 0) >= 6, "Ruijie RGOS cases must be >= 6"
    assert vendor_counts.get(None, 0) >= 4, "Safety / General / Negative cases with no vendor must be >= 4"

    # 验证负向案例与高危案例标记
    negative_cases = [c for c in cases if c["id"] >= "ANCHOR-041"]
    assert len(negative_cases) == 10, "Negative / safety gate cases must be exactly 10"

    high_risk_cases = [c for c in cases if c.get("high_risk") is True]
    assert len(high_risk_cases) >= 4, "Must have at least 4 high-risk operation cases"


def test_quality_gate_fails_when_business_guards_pass_but_recall_is_low(monkeypatch, tmp_path):
    """Safety/business passes must not hide a failed retrieval-quality gate."""
    cases = [
        {
            "id": "CASE-ANSWER",
            "query": "Huawei VLAN",
            "vendor": "Huawei",
            "intent": "vlan",
            "feature": "vlan",
            "expected_outcome": "answer",
            "gold_document_ids": ["gold-huawei-vlan"],
            "vendor_isolation": "strict",
        },
        {
            "id": "CASE-CLARIFY",
            "query": "S6800 aggregation",
            "vendor": None,
            "intent": "ambiguous_model",
            "expected_outcome": "clarify",
            "gold_document_ids": [],
            "vendor_isolation": "agnostic",
        },
        {
            "id": "CASE-NO-MATCH",
            "query": "unrelated request",
            "vendor": None,
            "intent": "out_of_domain",
            "expected_outcome": "no_match",
            "gold_document_ids": [],
            "vendor_isolation": "agnostic",
        },
    ]
    responses = {
        "CASE-ANSWER": _response(
            "answer",
            documents=["same-vendor-but-wrong-document"],
            vendors=["Huawei"],
            features=["vlan"],
        ),
        "CASE-CLARIFY": _response("clarify", output="Please specify the vendor"),
        "CASE-NO-MATCH": _response("no_match", output="No matching knowledge"),
    }

    report = _run_synthetic_cases(monkeypatch, tmp_path, cases, responses)

    assert report["safety_status"] == "PASS"
    assert report["quality_status"] == "FAIL"
    assert report["overall_status"] == "FAIL"
    assert report["status"] == "FAIL"
    assert report["metrics"]["evaluated_gold_cases"] == 1
    assert report["metrics"]["recall_at_5"] == 0.0
    assert report["metrics"]["recall_at_10"] == 0.0
    assert report["results"][0]["quality_passed"] is False
    assert report["passed_cases"] == 2
    runner = _load_anchor_runner()
    monkeypatch.setattr(runner, "evaluate_anchors", lambda: report)
    assert runner.main() == 1


def test_answer_case_without_gold_ids_cannot_vacuously_pass(monkeypatch, tmp_path):
    cases = [
        {
            "id": "CASE-EMPTY-GOLD",
            "query": "Huawei VLAN",
            "vendor": "Huawei",
            "intent": "vlan",
            "feature": "vlan",
            "expected_outcome": "answer",
            "gold_document_ids": [],
            "vendor_isolation": "strict",
        }
    ]
    responses = {
        "CASE-EMPTY-GOLD": _response(
            "answer",
            documents=["same-vendor-document"],
            vendors=["Huawei"],
            features=["vlan"],
        )
    }

    report = _run_synthetic_cases(monkeypatch, tmp_path, cases, responses)

    assert report["safety_status"] == "PASS"
    assert report["quality_status"] == "FAIL"
    assert report["overall_status"] == "FAIL"
    assert report["quality_summary"]["invalid_annotation_cases"] == ["CASE-EMPTY-GOLD"]
    assert report["metrics"]["evaluated_gold_cases"] == 0
    assert report["results"][0]["quality_eligible"] is False
    assert report["results"][0]["quality_passed"] is False


def test_wrong_vendor_and_forbidden_document_fail_safety_status(monkeypatch, tmp_path):
    cases = [
        {
            "id": "CASE-WRONG-VENDOR",
            "query": "Huawei VLAN",
            "vendor": "Huawei",
            "intent": "vlan",
            "feature": "vlan",
            "expected_outcome": "answer",
            "gold_document_ids": ["gold-huawei-vlan"],
            "vendor_isolation": "strict",
        },
        {
            "id": "CASE-FORBIDDEN-DOCUMENT",
            "query": "Cisco VLAN",
            "vendor": "Cisco",
            "intent": "vlan",
            "feature": "vlan",
            "expected_outcome": "answer",
            "gold_document_ids": ["gold-cisco-vlan"],
            "forbidden_documents": ["smart-licensing"],
            "vendor_isolation": "strict",
        },
    ]
    responses = {
        "CASE-WRONG-VENDOR": _response(
            "answer",
            documents=["foreign-document"],
            vendors=["Cisco"],
            features=["vlan"],
        ),
        "CASE-FORBIDDEN-DOCUMENT": _response(
            "answer",
            documents=["cisco-smart-licensing"],
            vendors=["Cisco"],
            features=["smart_licensing"],
        ),
    }

    report = _run_synthetic_cases(monkeypatch, tmp_path, cases, responses)

    assert report["safety_status"] == "FAIL"
    assert report["overall_status"] == "FAIL"
    assert any(
        "Strict vendor isolation breach" in reason
        for reason in report["safety_summary"]["failure_reasons"]
    )
    assert any(
        "Forbidden document" in reason
        for reason in report["safety_summary"]["failure_reasons"]
    )
    assert any(
        "Feature pollution" in reason
        for reason in report["safety_summary"]["failure_reasons"]
    )


def test_answer_gold_hit_passes_safety_and_quality_gates(monkeypatch, tmp_path):
    cases = [
        {
            "id": "CASE-GOOD-ANSWER",
            "query": "Huawei VLAN",
            "vendor": "Huawei",
            "intent": "vlan",
            "feature": "vlan",
            "expected_outcome": "answer",
            "gold_document_ids": ["gold-huawei-vlan"],
            "vendor_isolation": "strict",
        }
    ]
    responses = {
        "CASE-GOOD-ANSWER": _response(
            "answer",
            documents=["gold-huawei-vlan"],
            vendors=["Huawei"],
            features=["vlan"],
        )
    }

    report = _run_synthetic_cases(monkeypatch, tmp_path, cases, responses)

    assert report["safety_status"] == "PASS"
    assert report["quality_status"] == "PASS"
    assert report["overall_status"] == "PASS"
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["recall_at_10"] == 1.0
    assert report["metrics"]["mean_reciprocal_rank_mrr"] == 1.0
    assert report["metrics"]["ndcg"] == 1.0
    assert report["metrics"]["citation_precision"] == 1.0
    assert report["metrics"]["citation_recall"] == 1.0
    assert report["metrics"]["latency_ms"]["sample_count"] == 1
    assert report["results"][0]["target_document_hit"] is True
    assert report["results"][0]["quality_passed"] is True


def test_answer_uses_explicit_acceptable_document_set(monkeypatch, tmp_path):
    cases = [
        {
            "id": "CASE-ACCEPTABLE-SET",
            "query": "Cisco Nexus BGP",
            "vendor": "Cisco",
            "intent": "bgp",
            "expected_outcome": "answer",
            "gold_document_ids": ["legacy-mismatched-gold"],
            "acceptable_document_ids": ["official-nexus-bgp"],
            "vendor_isolation": "strict",
        }
    ]
    responses = {
        "CASE-ACCEPTABLE-SET": _response(
            "answer",
            documents=["official-nexus-bgp"],
            vendors=["Cisco"],
            features=["bgp"],
        )
    }

    report = _run_synthetic_cases(monkeypatch, tmp_path, cases, responses)

    assert report["quality_status"] == "PASS"
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["results"][0]["gold_document_ids"] == ["legacy-mismatched-gold"]
    assert report["results"][0]["acceptable_document_ids"] == ["official-nexus-bgp"]
    assert report["results"][0]["target_document_hit"] is True


def test_eval_report_does_not_persist_raw_query_or_provider_output(monkeypatch, tmp_path):
    secret_query = "api_key=fixture-secret raw device configuration"
    secret_output = "provider output with fixture-secret"
    cases = [
        {
            "id": "CASE-REDACTION",
            "query": secret_query,
            "vendor": None,
            "intent": "out_of_domain",
            "expected_outcome": "no_match",
            "gold_document_ids": [],
            "vendor_isolation": "agnostic",
        }
    ]
    responses = {"CASE-REDACTION": _response("no_match", output=secret_output)}

    report = _run_synthetic_cases(monkeypatch, tmp_path, cases, responses)

    rendered = json.dumps(report, ensure_ascii=False)
    assert secret_query not in rendered
    assert secret_output not in rendered
    assert "fixture-secret" not in rendered
    assert "query" not in report["results"][0]


def test_promptfoo_provider_returns_stable_error_without_echoing_exception(monkeypatch):
    import sys

    scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from promptfoo_nexora_provider import call_api
    from ai.services.assistant import ai_assistant_service

    def fail_retrieval(*args, **kwargs):
        raise RuntimeError("postgres://internal-host/tenant-db")

    monkeypatch.setattr(ai_assistant_service, "retrieve_knowledge", fail_retrieval)

    result = call_api("Huawei VLAN configuration", context={"vars": {"query": "Huawei VLAN configuration"}})

    assert result["error"] == "PROVIDER_EXECUTION_FAILED"
    assert result["output"] == "ERROR: PROVIDER_EXECUTION_FAILED"
    assert "internal-host" not in result["output"]
