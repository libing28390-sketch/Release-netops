"""
AI Assistant Service combining Intent Parsing, Fact Retrieval, RAG Knowledge Base, and LLM Conversational Synthesis
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.gateway.exceptions import AISecurityBlockedException
from ai.services.intent_parser import intent_parser
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.rag_retriever import rag_retriever, RetrievalRequest
from ai.services.product_resolver import product_resolver, EntityResolution
from ai.services.retrieval_contract import build_retrieval_explanation
from ai.services.citation_service import (
    answer_contract,
    build_grounded_citations,
    refusal_for_missing_evidence,
)
from services.official_config_template_service import _render_template, search_official_templates
from services.official_source_suggestion_service import suggest_official_sources
from services.official_source_supplement_service import record_official_source_suggestions
from ai.services.copilot_contract import build_copilot_contract
from ai.services.retrieval_trace_store import record_retrieval_trace, update_retrieval_trace
from ai.services.metrics import ai_metrics
from ai.security.sanitizer import sanitize_log_text
from core.context import request_id_var, resolve_request_id


# Only explicit knowledge/configuration/troubleshooting intents opt into
# tenant RAG context. General conversation must not inherit an internal
# document because a broad lexical search happened to find a weak match.
_RAG_CONTEXT_INTENTS = {"knowledge", "config_search", "troubleshooting", "alarm_search"}

logger = logging.getLogger(__name__)

SSE_EVENT_VERSION = "nxa.sse.v1"
SSE_EVENT_TYPES = frozenset({"meta", "progress", "token", "citation", "done", "error"})
LOW_CONFIDENCE_THRESHOLD = 0.45
_SSE_CONTEXT: ContextVar["_SSEEventContext | None"] = ContextVar("nexora_sse_context", default=None)


class _SSEEventContext:
    def __init__(self, stream_id: str, request_id: str = "-"):
        self.stream_id = stream_id
        self.request_id = request_id
        self.next_sequence = 1

    def identity(self) -> tuple[str, int]:
        sequence = self.next_sequence
        self.next_sequence += 1
        return self.stream_id, sequence


def _sse_event(event_type: str, payload: Dict[str, Any]) -> str:
    """Serialize one versioned SSE event with a stable, additive envelope."""

    if event_type not in SSE_EVENT_TYPES:
        raise ValueError(f"unsupported SSE event type: {event_type}")
    data = dict(payload)
    data["event_version"] = SSE_EVENT_VERSION
    context = _SSE_CONTEXT.get()
    event_id = ""
    if context is not None:
        data["request_id"] = context.request_id
        stream_id, sequence = context.identity()
        data["stream_id"] = stream_id
        data["sequence"] = sequence
        event_id = f"id: {stream_id}:{sequence}\n"
    return f"event: {event_type}\n{event_id}data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _meta_event(payload: Dict[str, Any]) -> str:
    """Emit meta first, then bounded citation events for streaming clients."""

    events = [_sse_event("meta", payload)]
    citations = payload.get("citations")
    if isinstance(citations, list):
        for index, citation in enumerate(citations[:20]):
            if isinstance(citation, dict):
                events.append(_sse_event("citation", {"index": index, "citation": citation}))
    return "".join(events)


def _token_event(content: Any) -> str:
    return _sse_event("token", {"content": str(content or "")})


def _progress_event(
    step_id: str,
    label: str,
    status: str,
    *,
    detail: Optional[str] = None,
    operation: Optional[str] = None,
    command: Optional[str] = None,
) -> str:
    """Create a safe, user-visible progress event without leaking query data or secrets."""
    payload: Dict[str, Any] = {"id": step_id, "label": label, "status": status}
    if detail:
        payload["detail"] = detail
    if operation:
        payload["operation"] = operation
    if command:
        payload["command"] = command
    return _sse_event("progress", payload)


def _done_event(started_at: float, extra: Optional[Dict[str, Any]] = None) -> str:
    duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    payload: Dict[str, Any] = {"status": "completed", "duration_ms": duration_ms}
    if extra and isinstance(extra, dict):
        payload.update({k: v for k, v in extra.items() if v is not None})
    return _sse_event("done", payload)


def _build_system_prompt(*, knowledge_no_match: bool = False) -> str:
    import datetime
    # Keep the trusted system clock readable without looking like a phone/IP
    # identifier to the outbound classifier (hyphenated ISO timestamps can be
    # mistaken for L2 data by conservative regexes).
    now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H时%M分%S秒")
    prompt = (
        f"Current System Time: {now_str}\n"
        "You are Nexora AI Assistant, an expert AI network operations copilot and assistant. "
        "For general questions, greetings, current time, common knowledge, programming, or network concept explanations, answer naturally, politely, and accurately. "
        "For enterprise network asset, topology, inventory, IP address, and telemetry queries within Nexora, always prioritize the provided real facts from CMDB/IPAM/Telemetry database. "
        "Never invent network devices, IPs, or alarms that are not present in inventory facts. "
        "For knowledge requests, use exact retrieved knowledge chunks. "
        "If entity_resolution is ambiguous but clarification_required is false, keep each retrieved CLI platform's syntax in a separately labeled section and never merge commands across platforms. "
        "For network vendor CLI commands, use language tags like ```huawei, ```cisco, ```h3c, or ```bash."
    )
    if knowledge_no_match:
        prompt += (
            "\nThe local knowledge base did not return a verified document for this request. "
            "You may answer as a cloud general reference assistant when the security gateway permits it, "
            "but you must clearly state that the answer is not a locally verified or official citation. "
            "Do not claim that a command is valid for the named hardware or software release without evidence. "
            "Give a useful example labelled by vendor, list the version and platform assumptions, and finish with "
            "a short verification command or official document check. Never invent citations or URLs."
        )
    return prompt


class AIAssistantService:
    """Core AI Copilot / Assistant handling interactive chat queries."""

    @staticmethod
    def _requires_platform_clarification(
        request: RetrievalRequest,
        resolution: EntityResolution,
    ) -> bool:
        """Decide whether an ambiguous registry match must stop retrieval.

        A query such as ``display ospf peer`` has no device identity.  It is
        useful to retrieve the exact command variants and label them by CLI
        platform.  A query that names a train, model, series, or OS boundary
        is different: returning another platform's syntax would be unsafe, so
        it still requires clarification when the registry cannot resolve one
        platform.
        """
        if not resolution.ambiguous:
            return False
        if str(getattr(request, "risk_level", "") or "").lower() in {"high", "critical"}:
            return True
        # Short series prefixes such as S57 are search scopes rather than a
        # claim about one exact hardware/OS mapping.  Return the exact
        # matching variants and let the answer keep them separated by
        # platform.
        series = str(getattr(request, "product_series", "") or "").strip().upper()
        if re.fullmatch(r"S\d{2,5}(?:-[A-Z0-9-]+)?", series):
            return False
        identity_fields = (
            "product_family",
            "product_series",
            "product_model",
            "os_family",
            "os_generation",
            "software_train",
            "software_release",
            "cli_platform",
        )
        return any(getattr(request, field_name, None) for field_name in identity_fields)

    @staticmethod
    def _knowledge_no_match_context(knowledge_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Build the minimal context allowed for a cloud general-reference fallback.

        A retrieval miss must not send raw RAG debug payloads, document bodies, or
        tenant facts to a cloud provider.  Keep only the structured query scope
        needed for the model to produce a useful, explicitly unverified answer;
        the security gateway still classifies, minimizes and tokenizes the final
        request before transport.
        """
        result = knowledge_result or {}
        request = result.get("request")
        resolution = result.get("resolution")
        resolution_data = resolution.to_dict() if hasattr(resolution, "to_dict") else (resolution or {})
        debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
        fields = (
            "vendor", "product_family", "product_series", "product_model", "os_family",
            "os_generation", "software_train", "software_release", "cli_platform",
            "document_category", "feature_domain", "feature", "subfeature",
        )
        query_scope = {
            field: getattr(request, field, None)
            for field in fields
            if getattr(request, field, None) not in (None, "", [], {})
        }
        platforms = resolution_data.get("platform_candidates") or []
        official_sources = suggest_official_sources(request, limit=3)
        return {
            "knowledge_status": "no_local_match",
            "query_scope": query_scope,
            "platform_candidates": [str(item) for item in platforms[:8]],
            "local_candidate_count": int(debug.get("metadata_candidate_documents", debug.get("candidate_count", 0)) or 0),
            "answer_mode": "cloud_general_reference_unverified",
            "official_source_suggestions": official_sources,
        }

    @staticmethod
    def build_knowledge_request(
        message: str,
        intent_info: Dict[str, Any],
        *,
        tenant_id: str = "tenant-default",
        user_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
    ) -> tuple[RetrievalRequest, EntityResolution]:
        metadata = intent_info.get("knowledge_intent") or intent_info.get("metadata") or intent_info.get("filters") or {}
        resolution = product_resolver.resolve_query(
            message,
            dict(metadata),
            tenant_id=tenant_id or "tenant-default",
        )
        request = RetrievalRequest.from_mapping(
            message,
            resolution.metadata,
            top_k=5,
            tenant_id=tenant_id or "tenant-default",
            user_id=user_id,
            roles=roles,
            site_ids=site_ids,
        )
        return request, resolution

    def retrieve_knowledge(
        self,
        message: str,
        intent_info: Dict[str, Any],
        *,
        tenant_id: str = "tenant-default",
        user_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        retrieval_started_at = time.perf_counter()
        request, resolution = self.build_knowledge_request(
            message,
            intent_info,
            tenant_id=tenant_id,
            user_id=user_id,
            roles=roles,
            site_ids=site_ids,
        )
        clarification_required = self._requires_platform_clarification(request, resolution)
        if clarification_required:
            retrieval = {
                "results": [],
                "debug": {
                    "metadata_candidate_documents": len(resolution.candidates),
                    "candidate_count": 0,
                    "dedup_document_count": 0,
                    "vector_top_n": 0,
                    "clarification_required": True,
                    "cross_platform_search": False,
                },
            }
            retrieval["explanation"] = build_retrieval_explanation(request, retrieval["debug"], [])
        else:
            retrieval = rag_retriever.search(request)
            retrieval.setdefault("debug", {})["clarification_required"] = False
            retrieval["debug"]["cross_platform_search"] = bool(resolution.ambiguous)
        quality = self._retrieval_quality_signals(request, retrieval)
        retrieval.setdefault("debug", {})["quality"] = quality
        ai_metrics.retrieval_observed(
            no_match=bool(quality["no_match"]),
            wrong_vendor=bool(quality["wrong_vendor_count"]),
            version_conflict=bool(quality["version_conflict_count"]),
            low_confidence=bool(quality["low_confidence_count"]),
            error=bool(quality["error"]),
        )
        trace_seed = self._knowledge_retrieval_trace(
            {"request": request, "resolution": resolution, **retrieval},
            retrieval.get("results") or [],
        )
        request_id = resolve_request_id(request_id or request_id_var.get("-"), prefix="req")
        trace_seed["request_id"] = request_id
        trace_seed.setdefault("runtime", {}).setdefault("latency", {})["retrieval_ms"] = max(0, int((time.perf_counter() - retrieval_started_at) * 1000))
        trace_seed.setdefault("runtime", {})["quality"] = quality
        retrieval["retrieval_trace_id"] = record_retrieval_trace(
            tenant_id=tenant_id or "tenant-default",
            user_id=user_id,
            query=message,
            trace=trace_seed,
            observation={
                "raw_query": message,
                "normalized_query": resolution.normalized_query,
                "entities": resolution.metadata,
                "filters": {
                    field: getattr(request, field, None)
                    for field in (
                        "vendor", "product_family", "product_series", "product_model", "os_family",
                        "os_generation", "software_train", "software_release", "cli_platform",
                        "document_category", "feature_domain", "feature", "subfeature", "risk_level",
                        "verification_level", "rag_priority", "status",
                    )
                    if getattr(request, field, None) not in (None, "", [], {})
                },
                "candidates": [*(resolution.candidates or []), *(retrieval.get("results") or [])],
                "final_chunks": retrieval.get("results") or [],
                "shadow": (retrieval.get("debug") or {}).get("shadow") or {},
            },
            request_id=request_id,
        )
        if quality["no_match"]:
            try:
                record_official_source_suggestions(
                    request,
                    tenant_id=tenant_id or "tenant-default",
                    trace_id=str(retrieval["retrieval_trace_id"]),
                    request_id=request_id,
                    query=message,
                )
            except Exception:
                # Retrieval must remain available if the administrative task
                # store is temporarily unavailable; the miss still fails
                # closed and never pretends that a source was imported.
                pass
        retrieval["request_id"] = request_id
        return {"request": request, "resolution": resolution, **retrieval}

    @staticmethod
    def _retrieval_quality_signals(request: RetrievalRequest, retrieval: Dict[str, Any]) -> Dict[str, Any]:
        """Derive bounded quality counters from structured retrieval output."""

        results = retrieval.get("results") if isinstance(retrieval.get("results"), list) else []
        debug = retrieval.get("debug") if isinstance(retrieval.get("debug"), dict) else {}
        requested_vendor = str(getattr(request, "vendor", "") or "").strip().lower()
        requested_version = bool(getattr(request, "software_train", None) or getattr(request, "software_release", None))
        wrong_vendor_count = int(debug.get("wrong_vendor_count") or 0)
        if requested_vendor:
            def vendor_for(item: Any) -> str:
                metadata = item.get("metadata") if isinstance(item, dict) and isinstance(item.get("metadata"), dict) else {}
                return str((item.get("vendor") if isinstance(item, dict) else None) or metadata.get("vendor") or "").strip().lower()

            wrong_vendor_count = max(
                wrong_vendor_count,
                sum(
                    1
                    for item in results
                    if vendor_for(item) and vendor_for(item) != requested_vendor
                ),
            )
        version_conflict_count = int(debug.get("version_conflict_count") or 0)
        if requested_version:
            version_conflict_count = max(
                version_conflict_count,
                sum(1 for item in results if float(item.get("version_score") or 0.0) <= 0.0),
            )
        scores = [
            max(0.0, min(1.0, float(item.get("relevance_score") or 0.0)))
            for item in results
            if isinstance(item, dict)
        ]
        low_confidence_count = sum(1 for score in scores if score < LOW_CONFIDENCE_THRESHOLD)
        return {
            "no_match": not bool(results),
            "wrong_vendor_count": wrong_vendor_count,
            "version_conflict_count": version_conflict_count,
            "low_confidence_count": low_confidence_count,
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
            "top_relevance_score": round(max(scores), 4) if scores else None,
            "error": bool(debug.get("error")),
        }

    @staticmethod
    def _knowledge_no_match_answer(knowledge_result: Optional[Dict[str, Any]]) -> str:
        """Return a deterministic no-match response without inventing config."""
        knowledge_result = knowledge_result or {}
        resolution = knowledge_result.get("resolution")
        resolution_data = resolution.to_dict() if hasattr(resolution, "to_dict") else (resolution or {})
        debug = knowledge_result.get("debug") or {}
        if resolution_data.get("ambiguous") and debug.get("clarification_required"):
            platforms = resolution_data.get("platform_candidates") or []
            platform_text = "、".join(str(item) for item in platforms) or "多个平台"
            return (
                "当前信息不足以安全确定唯一 CLI 平台，暂未执行跨平台检索。\n\n"
                f"知识库候选平台：{platform_text}\n"
                "请补充设备型号、OS 平台，或真实 display version 结果后再查询。"
            )

        request = knowledge_result.get("request")
        official_sources = suggest_official_sources(request, limit=3)

        def official_followup() -> str:
            if not official_sources:
                return ""
            lines = ["\n\n官方补充入口（仅建议，不代表已导入或已验证）："]
            for item in official_sources:
                lines.append(
                    f"- [{item['label']}]({item['url']})：{item['review_action']}；"
                    "确认后通过知识库的‘官方 URL 导入’提交。"
                )
            return "\n".join(lines)
        category = getattr(request, "document_category", None)
        criteria = []
        for label, field_name in (
            ("厂商", "vendor"),
            ("产品系列", "product_series"),
            ("产品型号", "product_model"),
            ("CLI 平台", "cli_platform"),
            ("软件版本", "software_train"),
            ("知识类型", "document_category"),
            ("特性", "feature"),
        ):
            value = getattr(request, field_name, None)
            if value:
                criteria.append(f"{label}={value}")
        criteria_text = "；".join(criteria) or "当前请求条件"
        match_count = debug.get("metadata_candidate_documents", debug.get("candidate_count", 0))
        evidence = resolution_data.get("evidence")
        registry_note = "产品注册信息已确认，但" if evidence == "product_registry" else ""
        if category == "configuration":
            return (
                "当前没有匹配的配置指南。\n\n"
                f"精确检索条件：{criteria_text}\n"
                f"精确命中：{match_count} 份\n\n"
                f"{registry_note}知识库没有同时满足上述条件的配置文档；"
                "未使用其他平台内容或 CLI 输出替代配置来源。"
                + official_followup()
            )
        if category == "troubleshooting":
            return (
                "当前知识库没有对应的故障排查 SOP。\n\n"
                f"精确检索条件：{criteria_text}\n"
                f"精确命中：{match_count} 份\n\n"
                "未使用 CLI 输出替代故障排查文档。"
                + official_followup()
            )
        return (
            refusal_for_missing_evidence(intent="knowledge") + "\n\n"
            f"精确检索条件：{criteria_text}\n"
            f"精确命中：{match_count} 份"
            + official_followup()
        )

    @staticmethod
    def _knowledge_platform_label(platform: Any) -> str:
        """Turn an internal platform key into a label a network operator can scan."""
        raw = str(platform or "").strip()
        labels = {
            "huawei_vrp5_v200": "Huawei VRP5（V200）",
            "huawei_yunshan_v300": "Huawei YunShan（V300）",
            "huawei_yunshan_v600": "Huawei YunShan（V600）",
            "huawei_vrp": "Huawei VRP",
            "huawei_vrpv8": "Huawei VRP8",
            "huawei_vrp_v200": "Huawei VRP（V200）",
            "huawei_vrp_v300": "Huawei VRP（V300）",
            "huawei_vrp_v600": "Huawei VRP（V600）",
            "h3c_comware": "H3C Comware",
            "h3c_comware7": "H3C Comware 7",
            "cisco_iosxe": "Cisco IOS XE",
            "cisco_ios": "Cisco IOS",
            "cisco_nxos": "Cisco NX-OS",
        }
        if raw in labels:
            return labels[raw]
        return raw.replace("_", " ") if raw else "未标注平台"

    @staticmethod
    def _knowledge_sections(content: str) -> List[tuple[str, str]]:
        """Split a KB Markdown object into sections and remove duplicated headings."""
        matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", content))
        if not matches:
            return [("", content.strip())] if content.strip() else []

        sections: List[tuple[str, str]] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            title = match.group(1).strip()
            body_lines = content[match.end():end].strip().splitlines()
            # The importer keeps the full heading as the first body line too.
            # It is useful in source documents but only creates visual noise here.
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)
            if body_lines and body_lines[0].strip() == title:
                body_lines.pop(0)
            body = "\n".join(body_lines).strip()
            if body:
                sections.append((title, body))
        return sections

    @staticmethod
    def _knowledge_section_title(title: str) -> str:
        """Use the readable right-most part of an imported hierarchical heading."""
        return title.rsplit(">", 1)[-1].strip() if title else ""

    @staticmethod
    def _knowledge_section_allowed(title: str, category: str) -> bool:
        name = AIAssistantService._knowledge_section_title(title).lower()
        if category == "configuration":
            return any(
                keyword in name
                for keyword in ("配置骨架", "验证命令", "注意事项", "补充说明")
            )
        if category == "cli_output":
            return any(
                keyword in name
                for keyword in ("command", "输出结构", "特殊状态", "状态/", "状态")
            )
        # Hardware/command documents do not normally reach this deterministic
        # path, but keep a conservative, user-facing subset if they do.
        return any(
            keyword in name
            for keyword in ("command", "说明", "含义", "用途", "验证")
        )

    @staticmethod
    def _knowledge_clean_section_body(body: str, platform: str) -> str:
        """Remove importer-only fields while retaining commands and explanations."""
        internal_keys = (
            "risk_level:",
            "verification_level:",
            "cli_verified:",
            "example_verified:",
            "parser_ready:",
            "source_scope:",
            "raw_output_status:",
            "software train:",
            "cli platform:",
            "product registry",
            "official evidence",
            "configuration mode:",
            "os family:",
            "os generation:",
            "parser key:",
        )
        lines = []
        for line in body.splitlines():
            stripped = line.strip()
            # Chunking assigns this synthetic section when an imported file
            # has no heading.  It is useful in the admin trace, but it is not
            # an answer section and becomes noisy when repeated per chunk.
            if stripped.lower() in {"general overview", "general overview:"}:
                continue
            if stripped and any(stripped.lower().lstrip("- ").startswith(key) for key in internal_keys):
                continue
            lines.append(line.rstrip())
        cleaned = "\n".join(lines).strip()
        # The source uses generic text fences.  A Huawei tag makes the command
        # block easier to read in the Markdown renderer without changing it.
        cleaned = re.sub(r"```text\b", "```huawei", cleaned, flags=re.IGNORECASE)
        # User-uploaded configuration documents can contain the same reviewed
        # Jinja envelope as the official catalogue.  Render every answer path,
        # not only the deterministic official-template path, so raw
        # ``{{...}}`` syntax never reaches the operator-facing chat bubble.
        cleaned = _render_template(cleaned)
        return re.sub(r"{{\s*.*?\s*}}", "<PARAM>", cleaned, flags=re.DOTALL).strip()

    @staticmethod
    def _template_command_parts(content: str) -> tuple[str, str]:
        """Separate a reviewed template's configuration from its checks.

        Official templates store the configuration and verification commands as
        two paragraphs.  Keeping them separate makes a broad configuration
        query copyable and prevents ``display``/``show`` commands from being
        mistaken for configuration input.
        """
        text = str(content or "").replace("\r\n", "\n").strip()
        if not text:
            return "", ""
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        if len(blocks) > 1:
            verification_index = None
            for index, block in enumerate(blocks[1:], start=1):
                if re.search(r"(?m)^\s*(?:display|show|copy\s+(?:running-config|run)|save)\b", block, re.I):
                    verification_index = index
                    break
            if verification_index is not None:
                config = "\n\n".join(blocks[:verification_index]).strip()
                verification = "\n\n".join(blocks[verification_index:]).strip()
                return config, verification
        # Some imported templates have no blank line.  Split at the first
        # verification command only when there is a preceding config command.
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if index > 0 and re.match(r"^\s*(?:display|show|copy\s+(?:running-config|run)|save)\b", line, re.I):
                config = "\n".join(lines[:index]).strip()
                verification = "\n".join(lines[index:]).strip()
                return config, verification
        return text, ""

    @staticmethod
    def _template_code_block(content: str, platform: str) -> str:
        if not content:
            return ""
        language = "huawei" if "huawei" in platform.lower() else "h3c" if "h3c" in platform.lower() else "cisco" if "cisco" in platform.lower() else "text"
        if content.lstrip().startswith("```"):
            return content
        return f"```{language}\n{content.strip()}\n```"

    @classmethod
    def _render_official_template_chunk(cls, item: Dict[str, Any]) -> str:
        """Build an operator-facing answer for one reviewed CLI template."""
        content = str(item.get("content") or "").strip()
        # Official URL/template ingestion may wrap the command body in the
        # synthetic ``General Overview`` chunk heading.  It is trace metadata,
        # not a command, so remove it before splitting configuration/checks.
        content = cls._knowledge_clean_section_body(content, str(item.get("platform") or ""))
        content = re.sub(r"(?m)^#{1,6}\s+.*$", "", content).strip()
        content = _render_template(content)
        config, verification = cls._template_command_parts(content)
        if not config and not verification:
            return ""
        title = str(item.get("document_name") or item.get("title") or "官方配置模板").strip()
        description = str(item.get("description") or "").strip()
        platform = str(item.get("platform") or item.get("cli_platform") or "").strip()
        version = str(item.get("software_release") or item.get("document_version") or "").strip()
        source = str(item.get("official_source") or item.get("official_reference") or "").strip()
        rollback = _render_template(str(item.get("rollback") or "").strip())
        parts = [f"#### {title}"]
        if platform:
            parts.append(f"适用 CLI：{cls._knowledge_platform_label(platform)}")
        if version:
            parts.append(f"适用版本：{version}")
        if description:
            parts.append(f"用途：{description}")
        parts.append(
            "执行前检查：确认设备型号、软件版本、接口/VLAN/IP/区域编号与变更窗口；先保存当前配置，"
            "在一台设备或维护窗口内验证，Nexora 不会自动下发命令。"
        )
        parts.append("参数提示：命令中的示例 VLAN、地址、AS 号、接口和名称必须按现场规划替换；密钥只允许从密钥库注入。")
        if config:
            parts.append("**配置步骤**\n" + cls._template_code_block(config, platform))
        if verification:
            parts.append("**验证命令**\n" + cls._template_code_block(verification, platform))
        if rollback:
            parts.append("**回滚命令**\n" + cls._template_code_block(rollback, platform))
        if source:
            parts.append(f"官方依据：[查看已审核来源]({source})")
        return "\n\n".join(parts)

    @classmethod
    def _render_knowledge_chunk(cls, item: Dict[str, Any]) -> tuple[str, str]:
        platform = cls._knowledge_platform_label(item.get("platform"))
        if item.get("template_id") or item.get("knowledge_source_type") == "official_template":
            rendered_template = cls._render_official_template_chunk(item)
            if rendered_template:
                return platform, rendered_template
        category = str(item.get("document_category") or "").lower()
        content = str(item.get("content") or "").strip()
        selected: List[str] = []
        for title, body in cls._knowledge_sections(content):
            if cls._knowledge_section_allowed(title, category):
                body = cls._knowledge_clean_section_body(body, platform)
                if body:
                    heading = cls._knowledge_section_title(title)
                    # Translate the few English importer labels used by output
                    # signature documents; keep command names untouched.
                    heading = {
                        "Command": "命令",
                        "Output Variant": "输出类型",
                        "Normalized Signature Skeleton": "输出示例骨架",
                    }.get(heading, heading)
                    selected.append(f"**{heading}**\n{body}")

        if not selected:
            # Keep a small useful prefix for older/plain-text documents, but
            # never expose the full raw object as the final assistant answer.
            compact = cls._knowledge_clean_section_body(content, platform)
            compact = re.sub(r"(?m)^##\s+.*$", "", compact).strip()
            if compact:
                selected.append(compact[:1600].rstrip())
        return platform, "\n\n".join(selected)

    @classmethod
    def _knowledge_fallback_answer(
        cls,
        chunks: List[Dict[str, Any]],
        *,
        request: Optional[Any] = None,
    ) -> str:
        """Render a concise, platform-separated answer from retrieved KB chunks.

        This is intentionally deterministic for ambiguous platform queries.  The
        complete chunks remain available to the Trace/citation panel; the user
        answer should contain only the operator-facing command and interpretation.
        """
        if not chunks:
            return "当前没有可展示的知识库结果。"

        grouped: Dict[str, List[str]] = {}
        for item in chunks:
            platform, rendered = cls._render_knowledge_chunk(item)
            if rendered:
                grouped.setdefault(platform, [])
                if rendered not in grouped[platform]:
                    grouped[platform].append(rendered)

        category = str(getattr(request, "document_category", "") or "").lower()
        feature = str(getattr(request, "feature", "") or "").strip()
        feature_label = {
            "ospf": "OSPF",
            "bgp": "BGP",
            "vlan": "VLAN",
            "arp": "ARP",
        }.get(feature.lower(), feature)
        single_platform = len(grouped) == 1
        resolved_platform = next(iter(grouped), "")
        if category == "configuration":
            subject = f"{feature_label} " if feature_label else ""
            if single_platform:
                lead = (
                    f"已按 {resolved_platform} 平台整理知识库中的 {subject}配置骨架。"
                    "尖括号参数请按设备实际信息填写。"
                )
            else:
                lead = (
                    f"未指定唯一 CLI 平台。下面按平台分别给出知识库中的 {subject}配置骨架，"
                    "命令不能跨平台混用；尖括号参数请按设备实际信息填写。"
                )
        elif category == "cli_output":
            command_intro = ""
            if feature.lower() == "ospf":
                command_intro = (
                    "`display ospf peer` 用于查看 OSPF 邻居。重点看 `State`："
                    "`Full` 表示邻接已建立，`2-Way` 表示双向通信但尚未形成 Full 邻接；"
                    "`Neighbor ID`、`Address`、`Interface` 分别是邻居 Router ID、对端地址和本端接口。"
                )
            if single_platform:
                lead = (
                    f"已按 {resolved_platform} 平台整理知识库中的命令和输出说明。"
                    + command_intro
                    + "重点字段请结合设备实际回显判断。"
                )
            else:
                lead = (
                    "未指定唯一 CLI 平台。"
                    + command_intro
                    + "下面按平台列出命令、重点字段和常见状态；不同平台的输出布局请分开理解。"
                )
        else:
            lead = (
                f"已按 {resolved_platform} 平台展示命中的知识库内容。"
                if single_platform
                else "未指定唯一 CLI 平台。下面按平台分别展示命中的可用内容，命令不能跨平台混用。"
            )

        rendered_platforms = []
        for platform, entries in grouped.items():
            rendered_platforms.append(f"### {platform}\n" + "\n\n".join(entries))
        if not rendered_platforms:
            return lead + "\n\n知识库命中了文档，但没有可展示的用户级命令或说明。请打开 Trace 查看引用。"
        return lead + "\n\n" + "\n\n---\n\n".join(rendered_platforms)

    @staticmethod
    def _should_use_cross_platform_retrieval_answer(
        knowledge_result: Optional[Dict[str, Any]],
        rag_chunks: Optional[List[Dict[str, Any]]],
    ) -> bool:
        """Keep retrieved network command answers grounded and readable.

        Configuration/command/output documents are rendered deterministically
        even when a single platform was resolved.  This prevents the LLM from
        echoing importer metadata (for example ``risk_level``) into an operator
        answer, while hardware/concept documents can still use normal synthesis.
        """
        if not rag_chunks or not knowledge_result:
            return False
        resolution = knowledge_result.get("resolution")
        resolution_data = resolution.to_dict() if hasattr(resolution, "to_dict") else (resolution or {})
        debug = knowledge_result.get("debug") or {}
        request = knowledge_result.get("request")
        category = str(getattr(request, "document_category", "") or "").lower()
        if category in {"configuration", "command", "cli_output"}:
            return True
        return bool(
            resolution_data.get("ambiguous")
            and debug.get("cross_platform_search")
            and not debug.get("clarification_required")
        )

    @staticmethod
    def _knowledge_retrieval_trace(
        knowledge_result: Optional[Dict[str, Any]],
        rag_chunks: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Expose safe retrieval facts to the developer Trace panel."""
        knowledge_result = knowledge_result or {}
        debug = knowledge_result.get("debug") or {}
        resolution = knowledge_result.get("resolution")
        resolution_data = resolution.to_dict() if hasattr(resolution, "to_dict") else (resolution or {})
        request = knowledge_result.get("request")

        def as_int(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        request_fields = (
            "vendor", "product_series", "product_model", "software_train",
            "cli_platform", "document_category", "feature_domain", "feature",
        )
        return {
            "request_id": knowledge_result.get("request_id"),
            "trace_id": knowledge_result.get("retrieval_trace_id"),
            "source": "local_rag",
            "status": "hit" if rag_chunks else "no_match",
            "metadata_candidate_documents": as_int(debug.get("metadata_candidate_documents")),
            "candidate_count": as_int(debug.get("candidate_count")),
            "dedup_document_count": as_int(debug.get("dedup_document_count")),
            "final_document_count": len(rag_chunks or []),
            "vector_top_n": as_int(debug.get("vector_top_n")),
            "clarification_required": bool(debug.get("clarification_required")),
            "cross_platform_search": bool(debug.get("cross_platform_search")),
            "request": {
                field: getattr(request, field, None)
                for field in request_fields
                if getattr(request, field, None) not in (None, "", [], {})
            },
            "resolution": {
                "ambiguous": bool(resolution_data.get("ambiguous")),
                "platform_candidates": resolution_data.get("platform_candidates") or [],
                "evidence": resolution_data.get("evidence") or "none",
            },
            "runtime": {
                "reranker": debug.get("reranker") or {},
                "latency": {
                    "retrieval_ms": as_int(debug.get("retrieval_latency_ms")),
                },
                "quality": debug.get("quality") or {},
                "shadow": debug.get("shadow") or {},
            },
            "citations": knowledge_result.get("citations") or [],
            "explanation": knowledge_result.get("explanation") or {},
        }

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        model_selection_source: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        request_id = resolve_request_id(request_id or request_id_var.get("-"), prefix="req")
        # 1. Parse intent
        intent_info = await intent_parser.parse_intent(message, user_id=user_id)
        intent = intent_info.get("intent", "general_qa")
        filters = intent_info.get("filters", {})

        context_facts: Dict[str, Any] = {}
        copilot_context = {
            key: value for key, value in (context or {}).items()
            if key in {"device_id", "interface", "site_id", "workspace_id", "department", "time_range", "alert_ids", "recent_changes", "topology_neighbors", "metrics", "history_events", "vendor", "model", "version", "impact_scope", "os", "document_scope"}
        }
        if copilot_context:
            context_facts["copilot_context"] = copilot_context
        citations = []
        knowledge_trace: Optional[Dict[str, Any]] = None

        # 2. Dispatch to specialized intent handler
        if intent == "asset_analysis":
            report = await natural_query_service.execute_asset_analysis(
                message,
                filters,
                tenant_id=tenant_id,
            )
            return {
                "answer": report.get("summary", ""),
                "intent": intent,
                "facts_retrieved": bool(report.get("matched_count", 0) or report.get("analysis")),
                "citations": report.get("citations", []),
                "answer_contract": answer_contract(
                    intent=intent,
                    citations=report.get("citations", []) or [],
                    grounded=bool(report.get("matched_count", 0) or report.get("analysis")),
                ),
                "request_id": request_id,
                "execution_mode": "local_operation",
                "external_egress": False,
                "input_tokens": 0,
                "output_tokens": 0,
                "token_source": "local_zero",
                "copilot": build_copilot_contract(
                    intent=intent, message=message, context=copilot_context,
                    citations=report.get("citations", []) or [],
                    runtime={"execution_mode": "local_operation", "external_egress": False, "input_tokens": 0, "output_tokens": 0},
                ),
            }
        if intent == "device_search":
            query_res = await natural_query_service.execute_query(
                message,
                filters,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            context_facts["devices"] = query_res.get("data")
        elif intent == "ip_location" and filters.get("ip"):
            ip_res = await ip_troubleshooting_service.troubleshoot_ip(filters["ip"], user_id=user_id)
            context_facts["ip_trace"] = ip_res.get("facts")
        elif intent == "mac_location" and filters.get("mac"):
            mac_res = await mac_troubleshooting_service.troubleshoot_mac(filters["mac"], user_id=user_id)
            context_facts["mac_trace"] = mac_res.get("facts")
        
        # 3. Retrieve RAG only for intents that explicitly need internal
        # evidence; general chat remains a clean, non-tenant-context request.
        if intent == "knowledge":
            knowledge_result = self.retrieve_knowledge(
                message,
                intent_info,
                tenant_id=tenant_id or "tenant-default",
                user_id=user_id,
                roles=roles,
                site_ids=site_ids,
                request_id=request_id,
            )
            rag_chunks = knowledge_result.get("results") or []
            knowledge_trace = self._knowledge_retrieval_trace(knowledge_result, rag_chunks)
            context_facts["knowledge_intent"] = knowledge_result["request"].__dict__
            context_facts["entity_resolution"] = knowledge_result["resolution"].to_dict()
            context_facts["retrieval_debug"] = knowledge_result.get("debug", {})
        elif intent in _RAG_CONTEXT_INTENTS:
            rag_chunks = rag_retriever.retrieve(
                message,
                top_k=3,
                tenant_id=tenant_id or "tenant-default",
                user_id=user_id,
                roles=roles,
                site_ids=site_ids,
            )
        else:
            rag_chunks = []
        if rag_chunks:
            context_facts["knowledge_chunks"] = [
                {
                    "content": c["content"],
                    "source": c["document_name"],
                    "document_name": c.get("document_name"),
                    "section": c["section"],
                    "platform": c.get("cli_platform") or c.get("platform"),
                    "document_category": c.get("document_category"),
                    "template_id": c.get("template_id") or (c.get("metadata") or {}).get("template_id"),
                    "knowledge_source_type": c.get("knowledge_source_type") or (c.get("metadata") or {}).get("source_type"),
                    "rollback": c.get("rollback") or (c.get("metadata") or {}).get("rollback"),
                    "description": c.get("description") or (c.get("metadata") or {}).get("description"),
                    "software_release": c.get("software_release") or (c.get("metadata") or {}).get("software_release"),
                    "official_reference": c.get("source") or (c.get("metadata") or {}).get("official_reference"),
                    "official_source": c.get("source") or (c.get("metadata") or {}).get("official_reference"),
                    "untrusted_data": True,
                }
                for c in rag_chunks
            ]
            citations, citation_warnings = build_grounded_citations(
                rag_chunks,
                request=knowledge_result.get("request") if intent == "knowledge" else None,
            )
            context_facts["citation_warnings"] = citation_warnings
            if knowledge_trace is not None:
                knowledge_trace["citations"] = citations
                knowledge_trace["citation_warnings"] = citation_warnings
                if knowledge_trace.get("trace_id"):
                    update_retrieval_trace(
                        str(knowledge_trace["trace_id"]),
                        citations=citations,
                        citation_warnings=citation_warnings,
                    )

        knowledge_no_match = intent == "knowledge" and not rag_chunks
        if knowledge_no_match:
            # Keep the normal LLM path alive for a useful DeepSeek/general
            # answer.  The local miss is explicit in the prompt and the
            # context is reduced to structured query metadata only; provider
            # egress still goes through the security gateway.
            context_facts = self._knowledge_no_match_context(knowledge_result)

        # A plain general question in a blank composer is a public cloud
        # conversation. Keep an explicit device/site/diagnostic scope
        # internal, but do not let incidental non-sensitive context keys make
        # every ChatGPT-style greeting require enterprise supplier evidence.
        explicit_scope_keys = ("device_id", "interface", "site_id", "vendor", "platform", "time_range", "document_scope")
        public_general_chat = intent == "general_qa" and not any(copilot_context.get(key) for key in explicit_scope_keys)

        # Keep retrieved command/configuration documents deterministic and
        # visibly separated by platform.  This prevents a provider from
        # echoing importer metadata or claiming that a verified hit is empty.
        if intent == "knowledge" and self._should_use_cross_platform_retrieval_answer(knowledge_result, rag_chunks):
            return {
                "answer": self._knowledge_fallback_answer(
                    context_facts.get("knowledge_chunks") or [],
                    request=knowledge_result.get("request"),
                ),
                "intent": intent,
                "facts_retrieved": True,
                "citations": citations,
                "answer_contract": answer_contract(intent=intent, citations=citations, grounded=True),
                "retrieval": knowledge_trace,
                "request_id": request_id,
                "execution_mode": "local_knowledge",
                "external_egress": False,
                "input_tokens": 0,
                "output_tokens": 0,
                "token_source": "local_zero",
                "copilot": build_copilot_contract(
                    intent=intent, message=message, context=copilot_context,
                    retrieval=knowledge_trace, citations=citations,
                    runtime={"execution_mode": "local_knowledge", "external_egress": False, "input_tokens": 0, "output_tokens": 0},
                ),
            }

        # 4. Synthesize with LLM
        sys_prompt = _build_system_prompt(knowledge_no_match=knowledge_no_match)

        messages = [{"role": "system", "content": sys_prompt}]
        if history:
            messages.extend(history[-6:])  # Keep last 3 turns of conversation history
        
        user_content = f"User Question: {message}\n"
        if context_facts:
            user_content += f"Nexora Network Facts & Knowledge:\n{json.dumps(context_facts, ensure_ascii=False)}"
        messages.append({"role": "user", "content": user_content})

        llm_started_at = time.perf_counter()
        try:
            res = await llm_gateway.chat(
                scene="chat",
                messages=messages,
                model_id=model_id,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
                selection_source=model_selection_source,
                # CMDB/RAG context is read-only and is minimized/tokenized by
                # the gateway before cloud egress.  Mark it INTERNAL
                # explicitly so identifiers do not accidentally escalate the
                # request to a provider's confidential-only boundary.
                # An otherwise context-free general answer is PUBLIC by
                # contract. Internal evidence is opt-in and remains INTERNAL
                # so supplier assurance is still required before cloud egress.
                data_classification="PUBLIC" if public_general_chat else ("INTERNAL" if context_facts else "PUBLIC"),
                request_id=request_id,
            )
        except AISecurityBlockedException:
            if knowledge_trace is not None and knowledge_trace.get("trace_id"):
                update_retrieval_trace(
                    str(knowledge_trace["trace_id"]),
                    runtime={
                        "security_result": "blocked",
                        "security": {"decision": "block", "result_code": "AI_SECURITY_BLOCKED"},
                        "latency": {"llm_ms": max(0, int((time.perf_counter() - llm_started_at) * 1000))},
                        "tokens": {"input": 0, "output": 0},
                    },
                )
            raise

        if knowledge_trace is not None and knowledge_trace.get("trace_id"):
            update_retrieval_trace(
                str(knowledge_trace["trace_id"]),
                runtime={
                    "provider_id": res.get("provider_id"),
                    "model_id": res.get("model_id"),
                    "requested_model_id": res.get("requested_model_id") or model_id,
                    "route_reason": res.get("route_reason"),
                    "fallback_used": bool(res.get("fallback_used")),
                    "security_result": "allow",
                    "security": {"decision": "allow", "result_code": "AI_SECURITY_ALLOWED"},
                    "latency": {"llm_ms": max(0, int((time.perf_counter() - llm_started_at) * 1000))},
                    "tokens": {
                        "input": max(0, int(res.get("input_tokens") or 0)),
                        "output": max(0, int(res.get("output_tokens") or 0)),
                    },
                },
            )

        answer = res.get("content", "")
        if not answer and knowledge_no_match:
            answer = self._knowledge_no_match_answer(knowledge_result)
        external_egress = bool(res.get("provider_id"))
        execution_mode = "provider_generated" if res.get("content") else "local_fallback"
        return {
            "answer": answer,
            "intent": intent,
            "facts_retrieved": bool(context_facts) and not knowledge_no_match,
            "citations": citations,
            "answer_contract": answer_contract(intent=intent, citations=citations, grounded=bool(citations or context_facts) and not knowledge_no_match, no_match=knowledge_no_match),
            "retrieval": knowledge_trace,
            "request_id": res.get("request_id") or request_id,
            "model_id": res.get("model_id"),
            "provider_id": res.get("provider_id"),
            "requested_model_id": res.get("requested_model_id"),
            "route_reason": res.get("route_reason"),
            "fallback_used": bool(res.get("fallback_used")),
            "execution_mode": execution_mode,
            "external_egress": external_egress,
            "input_tokens": max(0, int(res.get("input_tokens") or 0)),
            "output_tokens": max(0, int(res.get("output_tokens") or 0)),
            "latency_ms": max(0, int((time.perf_counter() - llm_started_at) * 1000)),
            "token_source": res.get("token_source"),
            "copilot": build_copilot_contract(
                intent=intent,
                message=message,
                context=copilot_context,
                retrieval=knowledge_trace,
                citations=citations,
                runtime={
                    "device_connected": False,
                    "cli_executed": False,
                    "external_egress": external_egress,
                    "execution_mode": execution_mode,
                    "input_tokens": max(0, int(res.get("input_tokens") or 0)),
                    "output_tokens": max(0, int(res.get("output_tokens") or 0)),
                    "latency_ms": max(0, int((time.perf_counter() - llm_started_at) * 1000)),
                    "knowledge_fallback": "cloud_general_reference" if knowledge_no_match else None,
                    "provider_id": res.get("provider_id"),
                    "model_id": res.get("model_id"),
                },
            ),
        }

    async def chat_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        model_selection_source: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        stream_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        """Stream one request under a stable, resumable SSE identity.

        The transport identity is intentionally scoped to this generator.  A
        cancelled generator resets the context so a later request can safely
        reopen the same registry entry without leaking a stream id across
        concurrent requests.
        """

        request_id = resolve_request_id(request_id or request_id_var.get("-"), prefix="req")
        active_stream_id = stream_id or f"sse_{uuid.uuid4().hex}"
        context_token = _SSE_CONTEXT.set(_SSEEventContext(active_stream_id, request_id))
        try:
            async for event in self._chat_stream_impl(
                message,
                history=history,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=roles,
                site_ids=site_ids,
                model_id=model_id,
                model_selection_source=model_selection_source,
                context=context,
                request_id=request_id,
            ):
                yield event
        finally:
            _SSE_CONTEXT.reset(context_token)

    async def _chat_stream_impl(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        model_selection_source: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ):
        request_id = resolve_request_id(request_id or request_id_var.get("-"), prefix="req")
        started_at = time.perf_counter()
        active_step = ("intent", "识别问题类型", "intent_parser.parse_intent")
        yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])

        context_facts: Dict[str, Any] = {}
        copilot_context = {
            key: value for key, value in (context or {}).items()
            if key in {"device_id", "interface", "site_id", "workspace_id", "department", "time_range", "alert_ids", "recent_changes", "topology_neighbors", "metrics", "history_events", "vendor", "model", "version", "impact_scope", "os", "document_scope"}
        }
        if copilot_context:
            context_facts["copilot_context"] = copilot_context
        citations = []
        knowledge_trace: Optional[Dict[str, Any]] = None
        knowledge_result: Dict[str, Any] | None = None

        try:
            intent_info = await intent_parser.parse_intent(message, user_id=user_id)
            intent = intent_info.get("intent", "general_qa")
            filters = intent_info.get("filters", {})
            yield _progress_event(
                "intent",
                "识别问题类型",
                "completed",
                detail=f"识别为 {intent}",
                operation="intent_parser.parse_intent",
            )

            if intent == "asset_analysis":
                active_step = ("asset_analysis", "\u805a\u5408 CMDB \u8d44\u4ea7\uff08\u53ea\u8bfb\uff09", "natural_query_service.execute_asset_analysis")
                yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])
                report = await natural_query_service.execute_asset_analysis(
                    message,
                    filters,
                    tenant_id=tenant_id,
                )
                yield _progress_event(
                    active_step[0],
                    active_step[1],
                    "completed",
                    detail=f"\u6309 PostgreSQL \u5b9e\u9645\u8bb0\u5f55\u805a\u5408 {report.get('matched_count', 0)} \u53f0\u8bbe\u5907",
                    operation=active_step[2],
                )
                yield _meta_event({
                    "intent": intent,
                    "facts_retrieved": True,
                    "citations": report.get("citations", []),
                    "execution_mode": "local_operation",
                    "external_egress": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "token_source": "local_zero",
                })
                report_step = ("report", "\u751f\u6210\u786e\u5b9a\u6027\u62a5\u8868", "natural_query_service.render_asset_analysis")
                yield _progress_event(report_step[0], report_step[1], "running", operation=report_step[2])
                yield _token_event(report.get("summary", ""))
                yield _progress_event(report_step[0], report_step[1], "completed", detail="\u672a\u8c03\u7528\u5927\u6a21\u578b\u6539\u5199\u4e8b\u5b9e\u7edf\u8ba1", operation=report_step[2])
                yield _done_event(started_at, extra={
                    "execution_mode": "local_operation",
                    "external_egress": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "token_source": "local_zero",
                })
                return

            if intent == "device_search":
                active_step = ("device_query", "查询 CMDB 资产（只读）", "natural_query_service.execute_query")
                yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])
                query_res = await natural_query_service.execute_query(
                    message,
                    filters,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                devices = query_res.get("data", []) if isinstance(query_res, dict) else []
                context_facts["devices"] = devices
                count = len(devices) if isinstance(devices, list) else 0
                yield _progress_event(
                    active_step[0],
                    active_step[1],
                    "completed",
                    detail=f"返回 {count} 条资产记录",
                    operation=active_step[2],
                )
            elif intent == "ip_location" and filters.get("ip"):
                active_step = ("ip_trace", "追踪 IP 证据链（只读）", "ip_troubleshooting.troubleshoot_ip")
                yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])
                ip_res = await ip_troubleshooting_service.troubleshoot_ip(filters["ip"], user_id=user_id)
                context_facts["ip_trace"] = ip_res.get("facts") if isinstance(ip_res, dict) else None
                yield _progress_event(
                    active_step[0],
                    active_step[1],
                    "completed",
                    detail="已收集 IP、ARP、拓扑与告警证据",
                    operation=active_step[2],
                )
            elif intent == "mac_location" and filters.get("mac"):
                active_step = ("mac_trace", "追踪 MAC 证据链（只读）", "mac_troubleshooting.troubleshoot_mac")
                yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])
                mac_res = await mac_troubleshooting_service.troubleshoot_mac(filters["mac"], user_id=user_id)
                context_facts["mac_trace"] = mac_res.get("facts") if isinstance(mac_res, dict) else None
                yield _progress_event(
                    active_step[0],
                    active_step[1],
                    "completed",
                    detail="已完成端口、交换机 MAC 表与拓扑对账",
                    operation=active_step[2],
                )

            active_step = ("knowledge", "检索知识库", "rag_retriever.retrieve")
            yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])
            if intent == "knowledge":
                knowledge_result = self.retrieve_knowledge(
                    message,
                    intent_info,
                    tenant_id=tenant_id or "tenant-default",
                    user_id=user_id,
                    roles=roles,
                    site_ids=site_ids,
                    request_id=request_id,
                )
                rag_chunks = knowledge_result.get("results") or []
                knowledge_trace = self._knowledge_retrieval_trace(knowledge_result, rag_chunks)
                context_facts["knowledge_intent"] = knowledge_result["request"].__dict__
                context_facts["entity_resolution"] = knowledge_result["resolution"].to_dict()
                context_facts["retrieval_debug"] = knowledge_result.get("debug", {})
            elif intent in _RAG_CONTEXT_INTENTS:
                rag_chunks = rag_retriever.retrieve(
                    message,
                    top_k=3,
                    tenant_id=tenant_id or "tenant-default",
                    user_id=user_id,
                    roles=roles,
                    site_ids=site_ids,
                )
            else:
                rag_chunks = []
            # Exact document retrieval is intentionally fail-closed.  When a
            # configuration query is otherwise well-scoped, use only the
            # reviewed local official template catalog as a second chance;
            # never broaden to another vendor or an unverified web result.
            if intent == "knowledge" and not rag_chunks and knowledge_result is not None:
                template_request = knowledge_result.get("request")
                template_chunks = search_official_templates(template_request, limit=5)
                if template_chunks:
                    rag_chunks = template_chunks
                    knowledge_result["results"] = template_chunks
                    debug = knowledge_result.setdefault("debug", {})
                    debug.update({
                        "template_fallback": True,
                        "template_fallback_count": len(template_chunks),
                        "template_fallback_source": "official_config_template_catalog",
                    })
                    context_facts["retrieval_debug"] = debug
                    if knowledge_trace is not None:
                        knowledge_trace["source"] = "local_official_template"
                        knowledge_trace["status"] = "template_fallback"
                        knowledge_trace["final_document_count"] = len(template_chunks)
                        quality = knowledge_trace.get("runtime", {}).get("quality")
                        if isinstance(quality, dict):
                            quality["no_match"] = False
                            quality["template_fallback"] = True
            if rag_chunks:
                context_facts["knowledge_chunks"] = [
                    {
                        "content": c["content"],
                        "source": c["document_name"],
                        "document_name": c.get("document_name"),
                        "section": c["section"],
                        "platform": c.get("cli_platform") or c.get("platform"),
                        "document_category": c.get("document_category"),
                        "template_id": c.get("template_id") or (c.get("metadata") or {}).get("template_id"),
                        "knowledge_source_type": c.get("knowledge_source_type") or (c.get("metadata") or {}).get("source_type"),
                        "rollback": c.get("rollback") or (c.get("metadata") or {}).get("rollback"),
                        "description": c.get("description") or (c.get("metadata") or {}).get("description"),
                        "software_release": c.get("software_release") or (c.get("metadata") or {}).get("software_release"),
                        "official_reference": c.get("source") or (c.get("metadata") or {}).get("official_reference"),
                        "official_source": c.get("source") or (c.get("metadata") or {}).get("official_reference"),
                        "untrusted_data": True,
                    }
                    for c in rag_chunks
                ]
                citations, citation_warnings = build_grounded_citations(
                    rag_chunks,
                    request=knowledge_result.get("request") if intent == "knowledge" else None,
                )
                context_facts["citation_warnings"] = citation_warnings
                if knowledge_trace is not None:
                    knowledge_trace["citations"] = citations
                    knowledge_trace["citation_warnings"] = citation_warnings
                    if knowledge_trace.get("trace_id"):
                        update_retrieval_trace(
                            str(knowledge_trace["trace_id"]),
                            citations=citations,
                            citation_warnings=citation_warnings,
                        )
            yield _progress_event(
                active_step[0],
                active_step[1],
                "completed",
                detail=f"命中 {len(rag_chunks) if rag_chunks else 0} 个知识片段",
                operation=active_step[2],
            )
            knowledge_no_match = intent == "knowledge" and not rag_chunks
            if knowledge_no_match:
                # Continue through the ordinary model path in general-reference
                # mode.  Only structured query scope is retained for cloud
                # egress; no raw document/debug/context payload is forwarded.
                context_facts = self._knowledge_no_match_context(knowledge_result)

            # A blank Copilot composer is a public conversation. Keep an
            # explicit device/site/diagnostic scope internal, but do not let
            # incidental non-sensitive context keys make every ChatGPT-style
            # greeting require enterprise supplier assurance.
            explicit_scope_keys = (
                "device_id", "interface", "site_id", "vendor", "platform",
                "time_range", "document_scope",
            )
            public_general_chat = intent == "general_qa" and not any(
                copilot_context.get(key) for key in explicit_scope_keys
            )
        except Exception:
            logger.error("Assistant read-only preparation failed code=%s", sanitize_log_text("ASSISTANT_CONTEXT_ERROR", limit=64))
            yield _progress_event(
                active_step[0],
                active_step[1],
                "error",
                detail="只读数据准备失败",
                operation=active_step[2],
            )
            yield _sse_event("error", {"code": "ASSISTANT_CONTEXT_ERROR", "message": "只读数据准备失败", "retryable": True})
            yield _done_event(started_at)
            return

        # Send SSE metadata
        contract = answer_contract(
            intent=intent,
            citations=citations,
            grounded=bool(citations or context_facts) and not knowledge_no_match,
            no_match=knowledge_no_match,
        )
        route_meta: Dict[str, Any] = {}
        use_grounded_retrieval_answer = (
            intent == "knowledge"
            and bool(rag_chunks)
            and self._should_use_cross_platform_retrieval_answer(knowledge_result, rag_chunks)
        )
        meta = {
            "request_id": request_id,
            "intent": intent,
            "facts_retrieved": bool(context_facts) and not knowledge_no_match,
            "citations": citations,
            "answer_contract": contract,
            "requested_model_id": model_id,
            "selection_source": model_selection_source,
            "execution_mode": "local_knowledge" if use_grounded_retrieval_answer else None,
            "external_egress": False if use_grounded_retrieval_answer else None,
            "input_tokens": 0 if use_grounded_retrieval_answer else None,
            "output_tokens": 0 if use_grounded_retrieval_answer else None,
            "token_source": "local_zero" if use_grounded_retrieval_answer else None,
            "copilot": build_copilot_contract(
                intent=intent, message=message, context=copilot_context,
                retrieval=knowledge_trace, citations=citations,
                runtime={
                    "device_connected": False,
                    "cli_executed": False,
                    # Grounded configuration/CLI answers are rendered from
                    # local evidence and return before the provider call.
                    # Final provider metadata changes this to true only after
                    # the outbound adapter call actually starts.
                    "external_egress": False,
                    "execution_mode": "local_knowledge" if use_grounded_retrieval_answer else None,
                    "input_tokens": 0 if use_grounded_retrieval_answer else None,
                    "output_tokens": 0 if use_grounded_retrieval_answer else None,
                    "knowledge_fallback": "cloud_general_reference" if knowledge_no_match else None,
                },
            ),
        }
        if intent == "knowledge":
            meta["retrieval"] = knowledge_trace
        yield _meta_event(meta)

        if use_grounded_retrieval_answer:
            platform_count = len({
                str(item.get("platform") or item.get("cli_platform") or "unknown")
                for item in (context_facts.get("knowledge_chunks") or [])
            })
            fallback_step = (
                "fallback",
                "按 CLI 平台整理知识库片段" if platform_count > 1 else "整理知识库命令",
                "assistant.cross_platform_retrieval" if platform_count > 1 else "assistant.grounded_knowledge_render",
            )
            yield _progress_event(fallback_step[0], fallback_step[1], "running", operation=fallback_step[2])
            yield _token_event(self._knowledge_fallback_answer(context_facts.get("knowledge_chunks") or [], request=knowledge_result.get("request")))
            yield _progress_event(
                fallback_step[0],
                fallback_step[1],
                "completed",
                detail="已按平台分隔检索结果" if platform_count > 1 else "已整理检索结果",
                operation=fallback_step[2],
            )
            yield _done_event(started_at, extra={
                "execution_mode": "local_knowledge",
                "external_egress": False,
                "input_tokens": 0,
                "output_tokens": 0,
                "token_source": "local_zero",
            })
            return

        sys_prompt = _build_system_prompt(knowledge_no_match=knowledge_no_match)

        messages = [{"role": "system", "content": sys_prompt}]
        if history:
            messages.extend(history[-6:])
        
        user_content = f"User Question: {message}\n"
        if context_facts:
            user_content += f"Nexora Network Facts & Knowledge:\n{json.dumps(context_facts, ensure_ascii=False)}"
        messages.append({"role": "user", "content": user_content})

        llm_step = ("llm", "生成回答", "llm_gateway.chat_stream")
        yield _progress_event(llm_step[0], llm_step[1], "running", operation=llm_step[2])
        tokens_emitted = 0
        llm_failed = False
        try:
            async for token in llm_gateway.chat_stream(
                scene="chat", messages=messages, model_id=model_id, user_id=user_id,
                tenant_id=tenant_id, roles=roles, selection_source=model_selection_source,
                route_meta=route_meta, workspace_id=copilot_context.get("workspace_id"),
                site_id=copilot_context.get("site_id"), department=copilot_context.get("department"),
                document_scope=copilot_context.get("document_scope"),
                # Read-only CMDB/RAG context may contain identifiers.  Mark
                # the authorized context as INTERNAL so the security gateway
                # tokenizes identifiers instead of treating the whole
                # request as CONFIDENTIAL and rejecting an INTERNAL provider.
                data_classification="PUBLIC" if public_general_chat else ("INTERNAL" if context_facts else "PUBLIC"),
                request_id=request_id,
            ):
                if token:
                    tokens_emitted += 1
                    yield _token_event(token)
        except AISecurityBlockedException as exc:
            # A security block is a terminal policy decision. Do not turn it
            # into a normal answer or try another external model.
            if knowledge_trace is not None and knowledge_trace.get("trace_id"):
                update_retrieval_trace(
                    str(knowledge_trace["trace_id"]),
                    runtime={
                        "provider_id": route_meta.get("provider_id"),
                        "model_id": route_meta.get("model_id"),
                        "requested_model_id": route_meta.get("requested_model_id") or model_id,
                        "route_reason": route_meta.get("route_reason"),
                        "security_result": "blocked",
                        "security": {"decision": "block", "result_code": getattr(exc, "code", "AI_SECURITY_BLOCKED")},
                        "latency": {"llm_ms": max(0, int(route_meta.get("latency_ms") or 0))},
                        "tokens": {"input": 0, "output": 0},
                    },
                )
            yield _progress_event(
                llm_step[0],
                llm_step[1],
                "error",
                detail=str(exc) or "请求被 AI 安全策略拦截",
                operation=llm_step[2],
            )
            yield _sse_event("error", {"code": getattr(exc, "code", "AI_SECURITY_BLOCKED"), "message": str(exc) or "请求被 AI 安全策略拦截", "retryable": False})
            yield _done_event(started_at)
            return
        except Exception as err:
            llm_failed = True
            logger.error("Error in LLM stream code=%s", sanitize_log_text(getattr(err, "code", "AI_INTERNAL_ERROR"), limit=64))
            yield _progress_event(
                llm_step[0],
                llm_step[1],
                "error",
                detail="模型服务未返回内容，将生成本地回退说明",
                operation=llm_step[2],
            )

        # Fallback if 0 tokens emitted (e.g. LLM provider key missing/network error or facts synthesis)
        if tokens_emitted == 0:
            fallback_step = ("fallback", "生成回退说明", "assistant.fallback_response")
            yield _progress_event(fallback_step[0], fallback_step[1], "running", operation=fallback_step[2])
            import datetime
            msg_lower = message.lower()
            
            # Check for date/time query
            if any(k in msg_lower for k in ["星期", "周几", "今天几号", "几点", "时间", "日期", "今天"]):
                weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
                now = datetime.datetime.now()
                weekday_str = weekdays[now.weekday()]
                fallback_text = f"今天是 **{now.strftime('%Y年%m月%d日')} {weekday_str}**。"
            elif intent == "device_search":
                devices = context_facts.get("devices")
                if devices and isinstance(devices, list) and len(devices) > 0:
                    dev_lines = [f"- **{d.get('hostname')}** (`{d.get('ip_address')}`) | 厂商: {d.get('vendor')} | 平台: {d.get('platform')} | 角色: {d.get('role')} | 状态: {d.get('status')}" for d in devices[:10]]
                    fallback_text = (
                        f"根据 Nexora CMDB 数据库实时查询，当前内网共纳管 **{len(devices)}** 台网络设备：\n\n"
                        + "\n".join(dev_lines)
                        + "\n\n您可以继续询问特定设备的接口配置或诊断命令。"
                    )
                else:
                    fallback_text = "根据 Nexora CMDB 数据库查询，目前内网设备表中暂未发现匹配的资产记录。"
            elif intent == "ip_location":
                fallback_text = "根据 Nexora 智能 IP 定位分析，已完成对目标的 IP 路径与拓扑链路收集。"
            elif intent == "mac_location":
                fallback_text = "根据 Nexora 智能 MAC 定位分析，已完成端口对账与交换机 Mac 表追踪。"
            elif intent == "knowledge" and context_facts.get("knowledge_chunks"):
                fallback_text = self._knowledge_fallback_answer(context_facts["knowledge_chunks"])
            elif context_facts.get("knowledge_chunks"):
                fallback_text = self._knowledge_fallback_answer(context_facts["knowledge_chunks"])
            elif intent == "knowledge":
                fallback_text = self._knowledge_no_match_answer(knowledge_result)
            else:
                fallback_text = (
                    "您好！我是 **Nexora AI 智能运维助手**。\n\n"
                    "💡 **提示**：当前 AI 供应商 API Key 尚未配置或在线大模型服务暂时不可用。\n"
                    "您可以前往 **AI 中心 ➔ 供应商管理** 配置 DeepSeek API Key 开启全量 LLM 对话能力，或继续向我查询 CMDB 资产、IP 定位与本地知识库！"
                )

            yield _token_event(fallback_text)
            yield _progress_event(
                fallback_step[0],
                fallback_step[1],
                "completed",
                detail="已生成本地回退结果",
                operation=fallback_step[2],
            )
        elif not llm_failed:
            yield _progress_event(
                llm_step[0],
                llm_step[1],
                "completed",
                detail="回答生成完成",
                operation=llm_step[2],
            )

        if knowledge_trace is not None and knowledge_trace.get("trace_id"):
            output_tokens = max(0, int(route_meta.get("output_tokens") or 0))
            if not output_tokens and tokens_emitted:
                output_tokens = tokens_emitted
            update_retrieval_trace(
                str(knowledge_trace["trace_id"]),
                runtime={
                    "provider_id": route_meta.get("provider_id"),
                    "model_id": route_meta.get("model_id"),
                    "requested_model_id": route_meta.get("requested_model_id") or model_id,
                    "route_reason": route_meta.get("route_reason"),
                    "fallback_used": bool(route_meta.get("fallback_used")),
                    "security_result": route_meta.get("security_result") or ("provider_error" if llm_failed else "allow"),
                    "security": {"decision": route_meta.get("security_result") or ("provider_error" if llm_failed else "allow"), "result_code": "AI_PROVIDER_ERROR" if llm_failed else "AI_SECURITY_ALLOWED"},
                    "latency": {"llm_ms": max(0, int(route_meta.get("latency_ms") or 0)), "total_ms": max(0, int((time.perf_counter() - started_at) * 1000))},
                    "tokens": {"input": max(0, int(route_meta.get("input_tokens") or 0)), "output": output_tokens},
                },
            )

        external_egress = bool(route_meta.get("external_egress")) if route_meta else False
        execution_mode = "provider_generated" if tokens_emitted > 0 else "local_fallback"
        if route_meta:
            route_meta["execution_mode"] = execution_mode
            route_meta["external_egress"] = external_egress
            route_meta["copilot"] = build_copilot_contract(
                intent=intent, message=message, context=copilot_context,
                retrieval=knowledge_trace, citations=citations,
                runtime={"device_connected": False, "cli_executed": False, "external_egress": external_egress,
                         "execution_mode": execution_mode,
                         "input_tokens": max(0, int(route_meta.get("input_tokens") or 0)),
                         "output_tokens": max(0, int(route_meta.get("output_tokens") or 0)),
                         "latency_ms": max(0, int(route_meta.get("latency_ms") or 0)),
                         "provider_id": route_meta.get("provider_id"), "model_id": route_meta.get("model_id")},
            )
            yield _meta_event(route_meta)

        done_extra = {
            "latency_ms": max(0, int((time.perf_counter() - started_at) * 1000)),
            "input_tokens": max(0, int(route_meta.get("input_tokens") or 0)) if route_meta else 0,
            "output_tokens": max(0, int(route_meta.get("output_tokens") or tokens_emitted or 0)) if route_meta else tokens_emitted,
            "model_id": route_meta.get("model_id") if route_meta else None,
            "provider_id": route_meta.get("provider_id") if route_meta else None,
            "route_reason": route_meta.get("route_reason") if route_meta else None,
            "execution_mode": execution_mode,
            "external_egress": external_egress,
            "token_source": route_meta.get("token_source") if route_meta else ("local_zero" if execution_mode.startswith("local_") else None),
        } if route_meta or tokens_emitted else None

        yield _done_event(started_at, extra=done_extra)


ai_assistant_service = AIAssistantService()
