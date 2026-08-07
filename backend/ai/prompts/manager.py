"""
Prompt Center Manager for Prompt CRUD, Versioning, and Initial Seed Prompts
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection

SEED_PROMPTS = [
    {
        "code": "COMMAND_EXPLAIN",
        "name": "CLI 命令解释与巡检分析",
        "scene": "command_explain",
        "vendor": "all",
        "platform": "all",
        "system_prompt": "You are a senior network operations engineer. Analyze the provided network CLI command and output. Return a structured JSON object with keys: 'command_purpose', 'summary', 'important_fields', 'abnormalities', 'recommendations'.",
        "user_prompt_template": "Command: {{command}}\nVendor: {{vendor}}\nPlatform: {{platform}}\nOutput:\n{{output}}",
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
        "temperature": 0.2,
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
                                "{}", p["temperature"], p["max_tokens"], 1, 1, "system", now_iso, now_iso
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
                                "{}", p["temperature"], p["max_tokens"], "system", now_iso
                            )
                        )
                conn.commit()
        except Exception as exc:
            pass

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
