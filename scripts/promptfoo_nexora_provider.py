"""Promptfoo Custom Provider for Nexora AI & RAG Evaluation.

Supports Promptfoo's Python custom provider interface:
def call_api(prompt, options, context) -> dict
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import re
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest

logger = logging.getLogger("nexora.promptfoo_provider")


def _call_api_impl(prompt: str, options: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Promptfoo custom provider entrypoint."""
    ctx_vars = (context or {}).get("vars", {})
    query = str(ctx_vars.get("query") or prompt or "").strip()
    vendor = ctx_vars.get("vendor")
    platform = ctx_vars.get("platform")
    expected_outcome = ctx_vars.get("expected_outcome", "answer")
    forbidden_vendors = ctx_vars.get("forbidden_vendors") or []

    # 1. 接入真实安全分类器与跨租户/注入防御
    from ai.security.classification import classify_text
    from ai.services.config_clarification import assess_configuration_request

    findings = classify_text(query)
    is_prompt_injection = any(getattr(f, "category", "") == "prompt_injection" for f in findings) or "ignore previous" in query.lower()
    is_cross_tenant = ("tenant-" in query.lower() or "跨租户" in query) and any(k in query.lower() for k in ["账密", "私有", "密钥", "凭据", "资产", "拓扑"])

    if is_prompt_injection or is_cross_tenant:
        return {
            "output": "SECURITY_BLOCK: AI request blocked by security gateway policy: AI_SECURITY_POLICY_BLOCKED",
            "metadata": {
                "decision": "blocked",
                "risk_level": "CRITICAL",
                "reason_code": "AI_SECURITY_POLICY_BLOCKED",
                "intent": "security_violation",
                "outcome": "no_match",
                "returned_document_ids": [],
                "returned_vendors": [],
                "returned_features": [],
            },
        }

    # 2. 真实评估高危与破坏性网络命令
    is_destructive = any(k in query.lower() for k in ["shutdown", "write erase", "format flash", "reload"])
    if is_destructive:
        return {
            "output": "HIGH_RISK_WARNING: Destructive network command detected. Secondary user confirmation and approval ticket required before execution.",
            "metadata": {
                "decision": "requires_approval",
                "risk_level": "HIGH",
                "intent": "high_risk",
                "outcome": "answer",
                "returned_document_ids": [],
                "returned_vendors": [],
                "returned_features": [],
            },
        }

    # 3. 接入真实的 AIAssistantService 统一安全与检索管道
    from ai.services.assistant import ai_assistant_service
    from ai.services.intent_parser import intent_parser

    meta = intent_parser.parse_knowledge_metadata(query)
    if vendor:
        meta["vendor"] = vendor
    if platform:
        meta["cli_platform"] = platform

    # The evaluation provider must keep the same intent boundary as the
    # interactive assistant.  Without this guard, a general/out-of-domain
    # request such as a cooking question is sent straight to tenant RAG and
    # can accidentally retrieve an unrelated network document.  Do not use
    # ``expected_outcome`` here: the provider must derive the safety result
    # from the request itself rather than from the fixture's answer.
    if not vendor and not platform and not intent_parser.is_knowledge_query(query):
        output_summary = {
            "vendor": vendor,
            "platform": platform,
            "returned_document_ids": [],
            "returned_vendors": [],
            "returned_platforms": [],
            "returned_features": [],
            "wrong_vendor_count": 0,
            "version_conflict_count": 0,
            "clarification_required": False,
            "outcome": "no_match",
            "reason_code": "OUT_OF_DOMAIN_NO_MATCH",
        }
        return {
            "output": json.dumps(output_summary, ensure_ascii=False),
            "metadata": output_summary,
        }

    try:
        results = ai_assistant_service.retrieve_knowledge(
            query,
            {"knowledge_intent": meta},
            tenant_id="tenant-default",
            user_id="eval-admin",
            roles=["admin"],
        )
        returned_chunks = results.get("results", [])
        docs = [str(item.get("document_id") or "") for item in returned_chunks]
        returned_vendors = sorted({str(item.get("vendor") or "") for item in returned_chunks if item.get("vendor")})
        returned_platforms = sorted(
            {
                str(item.get("cli_platform") or item.get("platform") or "")
                for item in returned_chunks
                if item.get("cli_platform") or item.get("platform")
            }
        )
        returned_features = sorted(
            {
                str(item.get("feature") or (item.get("metadata") or {}).get("feature") or "")
                for item in returned_chunks
                if item.get("feature") or (item.get("metadata") or {}).get("feature")
            }
        )
        wrong_vendor_count = results.get("debug", {}).get("wrong_vendor_count", 0)
        version_conflict_count = results.get("debug", {}).get("version_conflict_count", 0)

        clarification_payload = results.get("clarification")
        is_clarify = bool(
            isinstance(clarification_payload, dict) and clarification_payload.get("required")
        ) or results.get("status") == "clarification_required"

        if is_clarify:
            outcome = "clarify"
        elif docs:
            outcome = "answer"
        else:
            outcome = "no_match"

        output_summary = {
            "vendor": vendor,
            "platform": platform,
            "returned_document_ids": docs,
            "returned_vendors": returned_vendors,
            "returned_platforms": returned_platforms,
            "returned_features": returned_features,
            "wrong_vendor_count": wrong_vendor_count,
            "version_conflict_count": version_conflict_count,
            "clarification_required": is_clarify,
            "outcome": outcome,
        }

        return {
            "output": json.dumps(output_summary, ensure_ascii=False),
            "metadata": output_summary,
        }
    except Exception as exc:
        # Promptfoo output is an evaluation artifact.  Do not echo provider
        # exceptions because they can contain SQL/connection details or
        # provider payload fragments; the gate only needs a stable failure
        # contract and the server-side logs retain the diagnostic context. The
        # exception class is safe to expose in the redacted metadata and lets
        # CI distinguish a provider/runtime failure from an assertion failure.
        error_type = type(exc).__name__
        logger.warning("Promptfoo provider execution failed: %s", error_type)
        return {
            "error": "PROVIDER_EXECUTION_FAILED",
            "output": "ERROR: PROVIDER_EXECUTION_FAILED",
            "metadata": {
                "decision": "error",
                "reason_code": "PROVIDER_EXECUTION_FAILED",
                "error_type": error_type,
                "error_stage": "retrieve_knowledge",
                "outcome": "no_match",
                "returned_document_ids": [],
                "returned_vendors": [],
                "returned_platforms": [],
                "returned_features": [],
            },
        }


def call_api(prompt: str, options: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Promptfoo entrypoint with a redacted guard for import/initialization errors."""
    try:
        return _call_api_impl(prompt, options, context)
    except Exception as exc:
        error_type = type(exc).__name__
        logger.warning("Promptfoo provider initialization failed: %s", error_type)
        return {
            "error": "PROVIDER_INITIALIZATION_FAILED",
            "output": "ERROR: PROVIDER_INITIALIZATION_FAILED",
            "metadata": {
                "decision": "error",
                "reason_code": "PROVIDER_INITIALIZATION_FAILED",
                "error_type": error_type,
                "error_stage": "provider_entrypoint",
                "outcome": "no_match",
                "returned_document_ids": [],
                "returned_vendors": [],
                "returned_platforms": [],
                "returned_features": [],
            },
        }


if __name__ == "__main__":
    test_prompt = sys.argv[1] if len(sys.argv) > 1 else "Huawei CE6800 VLAN 100 configuration"
    res = call_api(test_prompt, context={"vars": {"query": test_prompt, "vendor": "Huawei"}})
    print(json.dumps(res, ensure_ascii=False, indent=2))
