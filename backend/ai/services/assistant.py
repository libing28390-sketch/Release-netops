"""
AI Assistant Service combining Intent Parsing, Fact Retrieval, RAG Knowledge Base, and LLM Conversational Synthesis
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.gateway.exceptions import AISecurityBlockedException
from ai.services.intent_parser import intent_parser
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.rag_retriever import rag_retriever, RetrievalRequest
from ai.services.product_resolver import product_resolver, EntityResolution

logger = logging.getLogger(__name__)


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
    return f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _done_event(started_at: float) -> str:
    duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    return f"event: done\ndata: {json.dumps({'duration_ms': duration_ms}, ensure_ascii=False)}\n\n"


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
        # Short series prefixes such as S57 are search scopes rather than a
        # claim about one exact hardware/OS mapping.  Return the exact
        # matching variants and let the answer keep them separated by
        # platform.
        series = str(getattr(request, "product_series", "") or "").strip().upper()
        if re.fullmatch(r"S\d{2,4}", series):
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
        resolution = product_resolver.resolve(
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
    ) -> Dict[str, Any]:
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
        else:
            retrieval = rag_retriever.search(request)
            retrieval.setdefault("debug", {})["clarification_required"] = False
            retrieval["debug"]["cross_platform_search"] = bool(resolution.ambiguous)
        return {"request": request, "resolution": resolution, **retrieval}

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
            )
        if category == "troubleshooting":
            return (
                "当前知识库没有对应的故障排查 SOP。\n\n"
                f"精确检索条件：{criteria_text}\n"
                f"精确命中：{match_count} 份\n\n"
                "未使用 CLI 输出替代故障排查文档。"
            )
        return (
            "当前知识库没有与请求条件完全匹配的文档。\n\n"
            f"精确检索条件：{criteria_text}\n"
            f"精确命中：{match_count} 份"
        )

    @staticmethod
    def _knowledge_platform_label(platform: Any) -> str:
        """Turn an internal platform key into a label a network operator can scan."""
        raw = str(platform or "").strip()
        labels = {
            "huawei_vrp5_v200": "Huawei VRP5（V200）",
            "huawei_yunshan_v300": "Huawei YunShan（V300）",
            "huawei_yunshan_v600": "Huawei YunShan（V600）",
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
            if stripped and any(stripped.lower().lstrip("- ").startswith(key) for key in internal_keys):
                continue
            lines.append(line.rstrip())
        cleaned = "\n".join(lines).strip()
        # The source uses generic text fences.  A Huawei tag makes the command
        # block easier to read in the Markdown renderer without changing it.
        cleaned = re.sub(r"```text\b", "```huawei", cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def _render_knowledge_chunk(cls, item: Dict[str, Any]) -> tuple[str, str]:
        platform = cls._knowledge_platform_label(item.get("platform"))
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
        if category == "configuration":
            subject = f"{feature_label} " if feature_label else ""
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
            lead = (
                "未指定唯一 CLI 平台。"
                + command_intro
                + "下面按平台列出命令、重点字段和常见状态；不同平台的输出布局请分开理解。"
            )
        else:
            lead = "未指定唯一 CLI 平台。下面按平台分别展示命中的可用内容，命令不能跨平台混用。"

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
        }

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # 1. Parse intent
        intent_info = await intent_parser.parse_intent(message, user_id=user_id)
        intent = intent_info.get("intent", "general_qa")
        filters = intent_info.get("filters", {})

        context_facts: Dict[str, Any] = {}
        citations: List[Dict[str, Any]] = []
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
                "request_id": None,
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
        
        # 3. Retrieve relevant RAG knowledge chunks.  Knowledge queries use
        # the structured intent/entity contract; generic questions retain the
        # legacy lexical path for compatibility.
        if intent == "knowledge":
            knowledge_result = self.retrieve_knowledge(
                message,
                intent_info,
                tenant_id=tenant_id or "tenant-default",
                user_id=user_id,
                roles=roles,
                site_ids=site_ids,
            )
            rag_chunks = knowledge_result.get("results") or []
            knowledge_trace = self._knowledge_retrieval_trace(knowledge_result, rag_chunks)
            context_facts["knowledge_intent"] = knowledge_result["request"].__dict__
            context_facts["entity_resolution"] = knowledge_result["resolution"].to_dict()
            context_facts["retrieval_debug"] = knowledge_result.get("debug", {})
        else:
            rag_chunks = rag_retriever.retrieve(
                message,
                top_k=3,
                tenant_id=tenant_id or "tenant-default",
                user_id=user_id,
                roles=roles,
                site_ids=site_ids,
            )
        if rag_chunks:
            context_facts["knowledge_chunks"] = [
                {
                    "content": c["content"],
                    "source": c["document_name"],
                    "section": c["section"],
                    "platform": c.get("cli_platform") or c.get("platform"),
                    "document_category": c.get("document_category"),
                    "untrusted_data": True,
                }
                for c in rag_chunks
            ]
            citations = [{"document": c["document_name"], "document_id": c.get("document_id"), "section": c["section"], "trust": c.get("source_trust_level", "untrusted")} for c in rag_chunks]

        if intent == "knowledge" and not rag_chunks:
            return {
                "answer": self._knowledge_no_match_answer(knowledge_result),
                "intent": intent,
                "facts_retrieved": False,
                "citations": [],
                "retrieval": knowledge_trace,
                "request_id": None,
            }

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
                "retrieval": knowledge_trace,
                "request_id": None,
            }

        # 4. Synthesize with LLM
        sys_prompt = (
            "You are Nexora AI Assistant, an expert AI network operations copilot. "
            "Always prioritize real facts queried from Nexora's CMDB, IPAM, and Telemetry database. "
            "Be professional, direct, and structured in your answer. "
            "Never invent missing device fields, counts, locations, software lifecycle status, EOL claims, or alarm causes. "
            "If a fact is absent from the supplied database facts, say that it is unavailable instead of guessing. "
            "For knowledge requests, use only exact retrieved knowledge chunks; never provide a generic or remembered network configuration when retrieval is empty. "
            "If entity_resolution is ambiguous but clarification_required is false, keep each retrieved CLI platform's syntax in a separately labeled section and never merge commands across platforms."
        )

        messages = [{"role": "system", "content": sys_prompt}]
        if history:
            messages.extend(history[-6:])  # Keep last 3 turns of conversation history
        
        user_content = f"User Question: {message}\n"
        if context_facts:
            user_content += f"Nexora Network Facts & Knowledge:\n{json.dumps(context_facts, ensure_ascii=False)}"
        messages.append({"role": "user", "content": user_content})

        res = await llm_gateway.chat(
            scene="chat",
            messages=messages,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        answer = res.get("content", "")
        if not answer and intent == "knowledge":
            answer = self._knowledge_no_match_answer(knowledge_result)
        return {
            "answer": answer,
            "intent": intent,
            "facts_retrieved": bool(context_facts),
            "citations": citations,
            "retrieval": knowledge_trace,
            "request_id": res.get("request_id")
        }

    async def chat_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
    ):
        started_at = time.perf_counter()
        active_step = ("intent", "识别问题类型", "intent_parser.parse_intent")
        yield _progress_event(active_step[0], active_step[1], "running", operation=active_step[2])

        context_facts: Dict[str, Any] = {}
        citations: List[Dict[str, Any]] = []
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
                yield f"event: meta\ndata: {json.dumps({'intent': intent, 'facts_retrieved': True, 'citations': report.get('citations', [])}, ensure_ascii=False)}\n\n"
                report_step = ("report", "\u751f\u6210\u786e\u5b9a\u6027\u62a5\u8868", "natural_query_service.render_asset_analysis")
                yield _progress_event(report_step[0], report_step[1], "running", operation=report_step[2])
                yield f"event: token\ndata: {json.dumps({'content': report.get('summary', '')}, ensure_ascii=False)}\n\n"
                yield _progress_event(report_step[0], report_step[1], "completed", detail="\u672a\u8c03\u7528\u5927\u6a21\u578b\u6539\u5199\u4e8b\u5b9e\u7edf\u8ba1", operation=report_step[2])
                yield _done_event(started_at)
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
                )
                rag_chunks = knowledge_result.get("results") or []
                knowledge_trace = self._knowledge_retrieval_trace(knowledge_result, rag_chunks)
                context_facts["knowledge_intent"] = knowledge_result["request"].__dict__
                context_facts["entity_resolution"] = knowledge_result["resolution"].to_dict()
                context_facts["retrieval_debug"] = knowledge_result.get("debug", {})
            else:
                rag_chunks = rag_retriever.retrieve(
                    message,
                    top_k=3,
                    tenant_id=tenant_id or "tenant-default",
                    user_id=user_id,
                    roles=roles,
                    site_ids=site_ids,
                )
            if rag_chunks:
                context_facts["knowledge_chunks"] = [
                    {
                        "content": c["content"],
                        "source": c["document_name"],
                        "section": c["section"],
                        "platform": c.get("cli_platform") or c.get("platform"),
                        "document_category": c.get("document_category"),
                        "untrusted_data": True,
                    }
                    for c in rag_chunks
                ]
                citations = [{"document": c["document_name"], "document_id": c.get("document_id"), "section": c["section"], "trust": c.get("source_trust_level", "untrusted")} for c in rag_chunks]
            yield _progress_event(
                active_step[0],
                active_step[1],
                "completed",
                detail=f"命中 {len(rag_chunks) if rag_chunks else 0} 个知识片段",
                operation=active_step[2],
            )
            if intent == "knowledge" and not rag_chunks:
                meta = {
                    "intent": intent,
                    "facts_retrieved": False,
                    "citations": [],
                    "retrieval": knowledge_trace,
                }
                yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"
                no_match_step = ("knowledge_no_match", "返回知识库检索结果", "assistant.knowledge_no_match")
                yield _progress_event(no_match_step[0], no_match_step[1], "running", operation=no_match_step[2])
                yield f"event: token\ndata: {json.dumps({'content': self._knowledge_no_match_answer(knowledge_result)}, ensure_ascii=False)}\n\n"
                yield _progress_event(no_match_step[0], no_match_step[1], "completed", detail="已阻止生成未经知识库验证的通用配置", operation=no_match_step[2])
                yield _done_event(started_at)
                return
        except Exception:
            logger.exception("Assistant read-only preparation failed")
            yield _progress_event(
                active_step[0],
                active_step[1],
                "error",
                detail="只读数据准备失败",
                operation=active_step[2],
            )
            yield f"event: error\ndata: {json.dumps({'code': 'ASSISTANT_CONTEXT_ERROR', 'message': '只读数据准备失败'}, ensure_ascii=False)}\n\n"
            yield _done_event(started_at)
            return

        # Send SSE metadata
        meta = {"intent": intent, "facts_retrieved": bool(context_facts), "citations": citations}
        if intent == "knowledge":
            meta["retrieval"] = knowledge_trace
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"

        if intent == "knowledge" and self._should_use_cross_platform_retrieval_answer(knowledge_result, rag_chunks):
            fallback_step = ("fallback", "按 CLI 平台整理知识库片段", "assistant.cross_platform_retrieval")
            yield _progress_event(fallback_step[0], fallback_step[1], "running", operation=fallback_step[2])
            yield f"event: token\ndata: {json.dumps({'content': self._knowledge_fallback_answer(context_facts.get('knowledge_chunks') or [], request=knowledge_result.get('request'))}, ensure_ascii=False)}\n\n"
            yield _progress_event(fallback_step[0], fallback_step[1], "completed", detail="已按平台分隔检索结果", operation=fallback_step[2])
            yield _done_event(started_at)
            return

        sys_prompt = (
            "You are Nexora AI Assistant, an expert AI network operations copilot. "
            "Always prioritize real facts queried from Nexora's CMDB, IPAM, and Telemetry database. "
            "Use clear Markdown formatting. Never invent missing fields, counts, locations, EOL claims, or alarm causes. "
            "If a fact is absent from the supplied database facts, state that it is unavailable. "
            "For knowledge requests, use only exact retrieved knowledge chunks; never provide a generic or remembered network configuration when retrieval is empty. "
            "If entity_resolution is ambiguous but clarification_required is false, keep each retrieved CLI platform's syntax in a separately labeled section and never merge commands across platforms. "
            "For network vendor CLI commands, use language tags like ```huawei, ```cisco, ```h3c, or ```bash."
        )

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
            async for token in llm_gateway.chat_stream(scene="chat", messages=messages, user_id=user_id, tenant_id=tenant_id):
                if token:
                    tokens_emitted += 1
                    yield f"event: token\ndata: {json.dumps({'content': token}, ensure_ascii=False)}\n\n"
        except AISecurityBlockedException:
            # A security block is a terminal policy decision. Do not turn it
            # into a normal answer or try another external model.
            yield _progress_event(
                llm_step[0],
                llm_step[1],
                "error",
                detail="请求被 AI 安全策略拦截",
                operation=llm_step[2],
            )
            yield f"event: error\ndata: {json.dumps({'code': 'AI_SECURITY_BLOCKED'}, ensure_ascii=False)}\n\n"
            yield _done_event(started_at)
            return
        except Exception as err:
            llm_failed = True
            logger.error("Error in LLM stream: %s", err)
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

            yield f"event: token\ndata: {json.dumps({'content': fallback_text}, ensure_ascii=False)}\n\n"
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

        yield _done_event(started_at)


ai_assistant_service = AIAssistantService()
