"""
Prompt Center Manager for Prompt CRUD, Versioning, and Initial Seed Prompts
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection

logger = logging.getLogger(__name__)

SEED_PROMPTS = [
    {
        "code": "COMMAND_EXPLAIN",
        "name": "CLI 命令解释与巡检分析",
        "scene": "command_explain",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a senior network operations engineer. Analyze the provided network CLI command and output. Return a structured JSON object with keys: 'command_purpose', 'summary', 'important_fields', 'abnormalities', 'recommendations'.",
        "user_prompt_template": "Command: {{command}}\nVendor: {{vendor}}\nPlatform: {{platform}}\nOutput:\n{{output}}",
        "output_schema": "{\"command_purpose\":\"string\",\"summary\":\"string\",\"important_fields\":[],\"abnormalities\":[],\"recommendations\":[]}",
        "temperature": 0.2,
        "max_tokens": 2048,
    },
    {
        "code": "CONFIG_EXPLAIN",
        "name": "设备配置架构与风险评估",
        "scene": "config_explain",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are an expert network architect. Analyze the device configuration text. Return a structured JSON object with keys: 'summary', 'routing_protocols', 'security_risks', 'network_services', 'management_services', 'risk_items', 'recommendations'.",
        "user_prompt_template": "Vendor: {{vendor}}\nPlatform: {{platform}}\nConfig:\n{{config_text}}",
        "output_schema": "{\"summary\":\"string\",\"routing_protocols\":[],\"security_risks\":[],\"network_services\":[],\"management_services\":[],\"risk_items\":[],\"recommendations\":[]}",
        "temperature": 0.2,
        "max_tokens": 3072,
    },
    {
        "code": "CONFIG_DIFF_ANALYSIS",
        "name": "配置变更 Diff 风险智能分析",
        "scene": "config_diff",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a network change control expert. Analyze the provided configuration diff from Nexora Diff Engine. Return a structured JSON object with keys: 'summary', 'risk_level' (LOW|MEDIUM|HIGH|CRITICAL), 'changes' (array of objects with type, risk, description, possible_impact), 'affected_services', 'verification_commands', 'rollback_recommendation'.",
        "user_prompt_template": "Vendor: {{vendor}}\nPlatform: {{platform}}\nDiff:\n{{diff_text}}",
        "output_schema": "{\"summary\":\"string\",\"risk_level\":\"LOW|MEDIUM|HIGH|CRITICAL\",\"changes\":[],\"affected_services\":[],\"verification_commands\":[],\"rollback_recommendation\":[]}",
        "temperature": 0.1,
        "max_tokens": 2048,
    },
    {
        "code": "ALARM_ANALYSIS",
        "name": "告警事件根因与影响智能分析",
        "scene": "alarm_analysis",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are an expert network SRE and incident investigator. Analyze the alarm event and network context. Return a structured JSON object with keys: 'incident_summary', 'suspected_root_cause', 'confidence' (float 0.0-1.0), 'evidence', 'affected_scope', 'recommended_actions'.",
        "user_prompt_template": "Alarm Title: {{alarm_title}}\nSeverity: {{severity}}\nFingerprint: {{fingerprint}}\nRaw Content:\n{{raw_content}}\nContext:\n{{context_data}}",
        "output_schema": "{\"incident_summary\":\"string\",\"suspected_root_cause\":\"string\",\"confidence\":0,\"evidence\":[],\"affected_scope\":[],\"recommended_actions\":[]}",
        "temperature": 0.2,
        "max_tokens": 2048,
    },
    {
        "code": "TOPOLOGY_ANALYSIS",
        "name": "拓扑链路与邻居异常分析",
        "scene": "topology_analysis",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a senior network topology engineer. Analyze the sanitized topology snapshot and the reported symptom. Separate observed facts from hypotheses, identify suspicious links or missing neighbors, and return JSON only. Never invent a device, link, interface, or credential that is not present in the input.",
        "user_prompt_template": "Symptom:\n{{symptom}}\nTopology snapshot (sanitized):\n{{topology_data}}\nReturn a JSON object with: summary, observed_facts, suspicious_links, missing_neighbors, verification_steps, recommendations.",
        "output_schema": "{\"summary\":\"string\",\"observed_facts\":[],\"suspicious_links\":[],\"missing_neighbors\":[],\"verification_steps\":[],\"recommendations\":[]}",
        "temperature": 0.1,
        "max_tokens": 3072,
    },
    {
        "code": "HEALTH_SUMMARY",
        "name": "设备健康状态摘要",
        "scene": "health_summary",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a network monitoring analyst. Summarize the sanitized device health snapshot for an operator. Prioritize availability, capacity, interface errors, and trend evidence. Mark missing data as unknown and return JSON only; do not expose secrets or identity fields.",
        "user_prompt_template": "Device snapshot (sanitized):\n{{device_snapshot}}\nObservation window: {{metrics_window}}\nReturn JSON with: overall_status, summary, critical_findings, warning_findings, evidence, recommended_actions.",
        "output_schema": "{\"overall_status\":\"healthy|warning|critical|unknown\",\"summary\":\"string\",\"critical_findings\":[],\"warning_findings\":[],\"evidence\":[],\"recommended_actions\":[]}",
        "temperature": 0.1,
        "max_tokens": 2048,
    },
    {
        "code": "COMPLIANCE_AUDIT",
        "name": "网络配置合规审计",
        "scene": "compliance_audit",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a network security compliance reviewer. Compare the sanitized configuration against the supplied policy controls. Cite only evidence present in the input, distinguish not_applicable from missing_evidence, and return JSON only. Do not output credentials, tokens, or raw sensitive values.",
        "user_prompt_template": "Vendor: {{vendor}}\nPlatform: {{platform}}\nPolicy controls:\n{{policy}}\nConfiguration (sanitized):\n{{config_text}}\nReturn JSON with: summary, passed_controls, failed_controls, unknown_controls, severity, remediation_plan.",
        "output_schema": "{\"summary\":\"string\",\"passed_controls\":[],\"failed_controls\":[],\"unknown_controls\":[],\"severity\":\"LOW|MEDIUM|HIGH|CRITICAL\",\"remediation_plan\":[]}",
        "temperature": 0.0,
        "max_tokens": 3072,
    },
    {
        "code": "CHANGE_PLAN",
        "name": "网络变更实施计划",
        "scene": "change_plan",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a network change manager. Turn the sanitized objective and current state into a cautious, reversible implementation plan. Include prerequisites, ordered steps, verification, rollback, and a risk level. Never propose destructive commands without an explicit confirmation gate and never invent unsupported syntax.",
        "user_prompt_template": "Vendor: {{vendor}}\nPlatform: {{platform}}\nObjective:\n{{objective}}\nCurrent state (sanitized):\n{{current_state}}\nConstraints:\n{{constraints}}\nReturn JSON with: summary, prerequisites, implementation_steps, verification_steps, rollback_steps, risks, approval_gates.",
        "output_schema": "{\"summary\":\"string\",\"prerequisites\":[],\"implementation_steps\":[],\"verification_steps\":[],\"rollback_steps\":[],\"risks\":[],\"approval_gates\":[]}",
        "temperature": 0.1,
        "max_tokens": 3072,
    },
    {
        "code": "RAG_ANSWER",
        "name": "知识库检索问答",
        "scene": "rag_answer",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a grounded enterprise network knowledge assistant. Answer only from the supplied sanitized context and citations. If evidence is insufficient or conflicts, say so clearly and ask for clarification. Return JSON only and do not fabricate a citation, command, version, or device detail.",
        "user_prompt_template": "Question:\n{{question}}\nRetrieved context (sanitized):\n{{context}}\nCitations:\n{{citations}}\nReturn JSON with: answer, confidence, citations_used, missing_information, follow_up_questions.",
        "output_schema": "{\"answer\":\"string\",\"confidence\":0,\"citations_used\":[],\"missing_information\":[],\"follow_up_questions\":[]}",
        "temperature": 0.2,
        "max_tokens": 3072,
    },
    {
        "code": "CAPACITY_ANALYSIS",
        "name": "容量趋势与阈值分析",
        "scene": "capacity_analysis",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a network capacity planning analyst. Analyze the sanitized time-window metrics and thresholds, state the calculation basis, and distinguish measured values from forecasts. Return JSON only; do not infer business identity or expose raw secrets.",
        "user_prompt_template": "Metrics (sanitized):\n{{metrics}}\nThresholds:\n{{threshold}}\nWindow:\n{{window}}\nReturn JSON with: summary, current_state, breached_thresholds, trend, forecast, actions, confidence.",
        "output_schema": "{\"summary\":\"string\",\"current_state\":[],\"breached_thresholds\":[],\"trend\":[],\"forecast\":[],\"actions\":[],\"confidence\":0}",
        "temperature": 0.1,
        "max_tokens": 2048,
    },
]


class PromptManager:
    """Prompt Center Manager."""

    def seed_initial_prompts(self) -> None:
        """Seed default prompts into ai_prompt table if empty."""
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                for p in SEED_PROMPTS:
                    cursor.execute("SELECT id FROM ai_prompt WHERE code = ?", (p["code"],))
                    if not cursor.fetchone():
                        p_id = f"prompt_{uuid.uuid4().hex[:12]}"
                        cursor.execute(
                            """
                            INSERT INTO ai_prompt (
                                id, code, name, scene, vendor, platform, system_prompt,
                                user_prompt_template, output_schema, temperature, max_tokens,
                                version, enabled, created_by, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                p_id, p["code"], p["name"], p["scene"], p.get("vendor", "all"),
                                p.get("platform", "all"), p["system_prompt"], p["user_prompt_template"],
                                p.get("output_schema", "{}"), p["temperature"], p["max_tokens"], 1, 1, "system", now_iso, now_iso
                            )
                        )
                        # Insert initial version
                        v_id = f"pv_{uuid.uuid4().hex[:12]}"
                        cursor.execute(
                            """
                            INSERT INTO ai_prompt_version (
                                id, prompt_id, version, system_prompt, user_prompt_template,
                                output_schema, temperature, max_tokens, created_by, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                v_id, p_id, 1, p["system_prompt"], p["user_prompt_template"],
                                p.get("output_schema", "{}"), p["temperature"], p["max_tokens"], "system", now_iso
                            )
                        )
                conn.commit()
        except Exception as exc:
            # Seeding is best-effort during startup, but a stable exception type
            # is useful for diagnosing migrations/schema drift without putting
            # prompt contents or connection details into application logs.
            logger.warning("Prompt seed initialization skipped: %s", type(exc).__name__)

    def get_prompt_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, code, name, scene, vendor, platform, system_prompt, user_prompt_template,
                       output_schema, temperature, max_tokens, version, enabled
                FROM ai_prompt WHERE code = ? AND enabled = 1
                """,
                (code,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "code": row[1],
                "name": row[2],
                "scene": row[3],
                "vendor": row[4],
                "platform": row[5],
                "system_prompt": row[6],
                "user_prompt_template": row[7],
                "output_schema": row[8],
                "temperature": row[9],
                "max_tokens": row[10],
                "version": row[11],
                "enabled": row[12],
            }


prompt_manager = PromptManager()
