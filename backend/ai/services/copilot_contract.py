"""Stable engineer-facing Copilot contract layered over assistant output."""

from __future__ import annotations

from typing import Any

from ai.security.sanitizer import sanitize_text


INTENT_RISK = {
    "general_qa": ("consultation", "low"),
    "knowledge": ("knowledge_retrieval", "low"),
    "ip_location": ("diagnosis", "medium"),
    "mac_location": ("diagnosis", "medium"),
    "device_search": ("consultation", "low"),
    "asset_analysis": ("consultation", "low"),
    "config_generation": ("config_generation", "high"),
    "troubleshooting": ("diagnosis", "medium"),
}


def _safe_list(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [sanitize_text(str(item))[:240] for item in list(value)[:limit] if str(item).strip()]


def build_copilot_contract(
    *,
    intent: str,
    message: str,
    context: dict[str, Any] | None = None,
    retrieval: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context if isinstance(context, dict) else {}
    category, risk = INTENT_RISK.get(str(intent), ("consultation", "low"))
    resolution = (retrieval or {}).get("resolution") or {}
    if hasattr(resolution, "to_dict"):
        resolution = resolution.to_dict()
    request = (retrieval or {}).get("request")
    # Evidence requirements are intent-specific.  A CMDB inventory question
    # is already answered by a read-only database query; asking for a device
    # vendor/model/version/impact scope in that case is both misleading and
    # noisy.  Those fields are required only when the assistant is about to
    # diagnose a symptom or generate a device-specific change.
    evidence_free_intents = {"general_qa", "chitchat", "device_search", "asset_analysis"}
    if str(intent) in evidence_free_intents:
        required_fields = {}
    else:
        required_fields = {
            "vendor": context.get("vendor"),
            "model": context.get("model") or context.get("product_model"),
            "version": context.get("version") or context.get("software_version"),
            "impact_scope": context.get("impact_scope") or context.get("scope"),
        }
    missing = [key for key, value in required_fields.items() if not value]
    candidates = _safe_list(resolution.get("platform_candidates") or resolution.get("candidates"))
    facts = []
    if context.get("device_id"):
        facts.append(f"设备范围: {sanitize_text(str(context['device_id']))[:120]}")
    if context.get("interface"):
        facts.append(f"接口范围: {sanitize_text(str(context['interface']))[:120]}")
    if retrieval and (
        retrieval.get("results")
        or retrieval.get("citations")
        or int(retrieval.get("final_document_count") or 0) > 0
    ):
        facts.append("知识库返回了经过权限过滤的证据")
    if context.get("recent_changes"):
        facts.append("已关联最近变更")
    if context.get("topology_neighbors"):
        facts.append("已关联拓扑邻居")
    if context.get("metrics"):
        facts.append("已关联性能指标")
    if str(intent) in evidence_free_intents:
        confidence = 0.95
        next_checks = []
    else:
        confidence = 0.35 if missing else (0.75 if facts else 0.55)
        if candidates:
            confidence = min(confidence, 0.45)
        next_checks = [
            "确认设备厂商、型号和 OS/软件版本",
            "确认影响范围、发生时间及最近变更",
            "执行一项授权的只读连通性或接口状态检查",
        ]
        if category == "knowledge_retrieval":
            next_checks = ["确认产品/平台边界", "核对官方来源版本", "在目标设备上验证命令适用性"]
    source_labels = []
    for item in citations or []:
        source_type = str(item.get("source_type") or "enterprise").lower()
        source_labels.append(
            "official"
            if "official" in source_type
            else (
                "realtime_device"
                if any(marker in source_type for marker in ("device", "live", "cmdb", "asset", "system"))
                else "enterprise"
            )
        )
    source_labels = sorted(set(source_labels))
    if not source_labels:
        # CMDB/IP/MAC handlers are deterministic read-only evidence sources,
        # even when their response does not carry citation rows.  Reserve the
        # model-inference label for true free-form synthesis/no-match paths.
        source_labels = (
            ["realtime_device"]
            if str(intent) in {"device_search", "asset_analysis", "ip_location", "mac_location"}
            else ["model_inference"]
        )
    # Keep a deterministic, explainable budget for the structured Copilot
    # context.  Raw prompt/retrieval bodies are not exposed in this contract.
    context_limit = 12000
    context_parts = [str(message or "")]
    context_parts.extend(str(value) for key, value in context.items() if key in {
        "device_id", "interface", "site_id", "time_range", "alert_ids", "recent_changes",
        "topology_neighbors", "metrics", "history_events", "vendor", "model", "version",
        "impact_scope", "os", "document_scope",
    })
    context_used = sum(len(sanitize_text(part)) for part in context_parts)
    context_truncated = context_used > context_limit
    retrieval_trace = {}
    if isinstance(retrieval, dict):
        debug = retrieval.get("debug") if isinstance(retrieval.get("debug"), dict) else {}
        final_document_count = int(retrieval.get("final_document_count") or 0)
        retrieval_trace = {
            "status": retrieval.get("status") or ("hit" if retrieval.get("results") or final_document_count > 0 else "no_match"),
            "metadata_candidate_documents": debug.get("metadata_candidate_documents"),
            "final_document_count": final_document_count or len(retrieval.get("results") or []),
            "vector_top_n": debug.get("vector_top_n"),
            "clarification_required": debug.get("clarification_required"),
        }
    return {
        "contract_version": "copilot.v2",
        "intent": category,
        "risk": risk,
        "confirmed_facts": facts[:12],
        "assumptions": ["未执行写操作", "未将模型推断当作设备事实"],
        "confidence": round(float(confidence), 2),
        "required_evidence": [f"补充 {item}" for item in missing],
        "next_checks": next_checks,
        "source_labels": source_labels,
        "recognized": {
            "vendor": context.get("vendor"),
            "model": context.get("model") or context.get("product_model"),
            "os": context.get("os") or context.get("os_family"),
            "version": context.get("version") or context.get("software_version"),
            "ambiguous_candidates": candidates,
        },
        "runtime": {
            "device_connected": bool((runtime or {}).get("device_connected", False)),
            "cli_executed": bool((runtime or {}).get("cli_executed", False)),
            "external_egress": bool((runtime or {}).get("external_egress", False)),
            "provider_id": (runtime or {}).get("provider_id"),
            "model_id": (runtime or {}).get("model_id"),
            "execution_mode": (runtime or {}).get("execution_mode"),
            "input_tokens": (runtime or {}).get("input_tokens"),
            "output_tokens": (runtime or {}).get("output_tokens"),
            "latency_ms": (runtime or {}).get("latency_ms"),
        },
        "context_budget": {
            "limit_chars": context_limit,
            "used_chars": min(context_used, context_limit),
            "truncated": context_truncated,
            "summary": "仅保留结构化设备、范围、时间和证据字段" if context_truncated else "结构化上下文完整纳入",
        },
        "context": {
            key: sanitize_text(str(value))[:200]
            for key, value in context.items()
            if key in {"device_id", "interface", "site_id", "time_range", "alert_ids", "recent_changes", "topology_neighbors", "metrics", "history_events"}
        },
        "engineer_evidence": {
            "citations": (citations or [])[:20],
            "trace_available": bool(retrieval),
        },
        "developer_trace": {"retrieval": retrieval_trace, "message_hash_only": True},
    }
