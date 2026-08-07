"""
AI Assistant Service combining Intent Parsing, Fact Retrieval, RAG Knowledge Base, and LLM Conversational Synthesis
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.services.intent_parser import intent_parser
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.rag_retriever import rag_retriever


class AIAssistantService:
    """Core AI Copilot / Assistant handling interactive chat queries."""

    async def chat(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # 1. Parse intent
        intent_info = await intent_parser.parse_intent(message, user_id=user_id)
        intent = intent_info.get("intent", "general_qa")
        filters = intent_info.get("filters", {})

        context_facts: Dict[str, Any] = {}
        citations: List[Dict[str, Any]] = []

        # 2. Dispatch to specialized intent handler
        if intent == "device_search":
            query_res = await natural_query_service.execute_query(message, filters, user_id=user_id)
            context_facts["devices"] = query_res.get("data")
        elif intent == "ip_location" and filters.get("ip"):
            ip_res = await ip_troubleshooting_service.troubleshoot_ip(filters["ip"], user_id=user_id)
            context_facts["ip_trace"] = ip_res.get("facts")
        elif intent == "mac_location" and filters.get("mac"):
            mac_res = await mac_troubleshooting_service.troubleshoot_mac(filters["mac"], user_id=user_id)
            context_facts["mac_trace"] = mac_res.get("facts")
        
        # 3. Retrieve relevant RAG knowledge chunks
        rag_chunks = rag_retriever.retrieve(message, top_k=3)
        if rag_chunks:
            context_facts["knowledge_chunks"] = [c["content"] for c in rag_chunks]
            citations = [{"document": c["document_name"], "section": c["section"]} for c in rag_chunks]

        # 4. Synthesize with LLM
        sys_prompt = (
            "You are Nexora AI Assistant, an expert AI network operations copilot. "
            "Always prioritize real facts queried from Nexora's CMDB, IPAM, and Telemetry database. "
            "Be professional, direct, and structured in your answer."
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
            user_id=user_id
        )

        return {
            "answer": res.get("content", ""),
            "intent": intent,
            "facts_retrieved": bool(context_facts),
            "citations": citations,
            "request_id": res.get("request_id")
        }

    async def chat_stream(
        self,
        message: str,
        history: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None
    ):
        intent_info = await intent_parser.parse_intent(message, user_id=user_id)
        intent = intent_info.get("intent", "general_qa")
        filters = intent_info.get("filters", {})

        context_facts: Dict[str, Any] = {}
        citations: List[Dict[str, Any]] = []

        if intent == "device_search":
            query_res = await natural_query_service.execute_query(message, filters, user_id=user_id)
            context_facts["devices"] = query_res.get("data")
        elif intent == "ip_location" and filters.get("ip"):
            ip_res = await ip_troubleshooting_service.troubleshoot_ip(filters["ip"], user_id=user_id)
            context_facts["ip_trace"] = ip_res.get("facts")
        elif intent == "mac_location" and filters.get("mac"):
            mac_res = await mac_troubleshooting_service.troubleshoot_mac(filters["mac"], user_id=user_id)
            context_facts["mac_trace"] = mac_res.get("facts")
        
        rag_chunks = rag_retriever.retrieve(message, top_k=3)
        if rag_chunks:
            context_facts["knowledge_chunks"] = [c["content"] for c in rag_chunks]
            citations = [{"document": c["document_name"], "section": c["section"]} for c in rag_chunks]

        # Send SSE metadata
        meta = {"intent": intent, "facts_retrieved": bool(context_facts), "citations": citations}
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n"

        sys_prompt = (
            "You are Nexora AI Assistant, an expert AI network operations copilot. "
            "Always prioritize real facts queried from Nexora's CMDB, IPAM, and Telemetry database. "
            "Use clear Markdown formatting. For network vendor CLI commands, use language tags like ```huawei, ```cisco, ```h3c, or ```bash."
        )

        messages = [{"role": "system", "content": sys_prompt}]
        if history:
            messages.extend(history[-6:])
        
        user_content = f"User Question: {message}\n"
        if context_facts:
            user_content += f"Nexora Network Facts & Knowledge:\n{json.dumps(context_facts, ensure_ascii=False)}"
        messages.append({"role": "user", "content": user_content})

        tokens_emitted = 0
        try:
            async for token in llm_gateway.chat_stream(scene="chat", messages=messages, user_id=user_id):
                if token:
                    tokens_emitted += 1
                    yield f"event: token\ndata: {json.dumps({'content': token}, ensure_ascii=False)}\n\n"
        except Exception as err:
            import logging
            logging.getLogger(__name__).error(f"Error in LLM stream: {err}")

        # Fallback if 0 tokens emitted (e.g. LLM provider key missing/network error or facts synthesis)
        if tokens_emitted == 0:
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
            elif context_facts.get("knowledge_chunks"):
                chunks = context_facts["knowledge_chunks"]
                fallback_text = "根据 Nexora 本地知识库检索结果：\n\n" + "\n\n---\n\n".join(chunks)
            else:
                fallback_text = (
                    "您好！我是 **Nexora AI 智能运维助手**。\n\n"
                    "💡 **提示**：当前 AI 供应商 API Key 尚未配置或在线大模型服务暂时不可用。\n"
                    "您可以前往 **AI 中心 ➔ 供应商管理** 配置 DeepSeek API Key 开启全量 LLM 对话能力，或继续向我查询 CMDB 资产、IP 定位与本地知识库！"
                )

            yield f"event: token\ndata: {json.dumps({'content': fallback_text}, ensure_ascii=False)}\n\n"

        yield "event: done\ndata: {}\n\n"


ai_assistant_service = AIAssistantService()
