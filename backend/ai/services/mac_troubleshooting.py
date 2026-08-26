"""
AI Service for Intelligent MAC Location and Uplink Path Analysis
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from database.core import get_db_connection
from ai.gateway.llm_gateway import llm_gateway
from ai.security.sanitizer import sanitize_data


class MACTroubleshootingService:
    """Normalizes MAC addresses and traces MAC location through Nexora switches and VLANs."""

    def normalize_mac(self, mac: str) -> str:
        clean = re.sub(r'[^a-fA-F0-9]', '', mac).lower()
        if len(clean) == 12:
            return f"{clean[:4]}.{clean[4:8]}.{clean[8:12]}"
        return mac

    def trace_mac_facts(self, raw_mac: str) -> Dict[str, Any]:
        norm_mac = self.normalize_mac(raw_mac)
        facts: Dict[str, Any] = {
            "raw_mac": raw_mac,
            "normalized_mac": norm_mac,
            "mac_entry": None,
            "associated_ip": None,
        }
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT ip_address, vlan, interface, device_id FROM arp_cache WHERE LOWER(mac_address) LIKE ? LIMIT 1", (f"%{norm_mac}%",))
                    row = cursor.fetchone()
                    if row:
                        facts["mac_entry"] = {
                            "ip_address": row[0], "vlan": row[1],
                            "interface": row[2], "device_id": row[3]
                        }
                        facts["associated_ip"] = row[0]
                except Exception:
                    pass
        except Exception:
            pass
        return facts

    async def troubleshoot_mac(self, raw_mac: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        facts = self.trace_mac_facts(raw_mac)
        sanitized_facts = sanitize_data(facts)

        sys_prompt = (
            "You are an AI Network Location Assistant. "
            "Analyze the MAC address facts from Nexora and explain the port location and uplink path. "
            "Return JSON with keys: 'normalized_mac', 'associated_ip', 'located_switch', "
            "'located_port', 'vlan', 'path_summary', 'recommendations'."
        )
        user_prompt = f"Target MAC: {raw_mac}\nFacts:\n{json.dumps(sanitized_facts, ensure_ascii=False)}"

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="troubleshooting",
            messages=messages,
            response_format={"type": "json_object"},
            user_id=user_id
        )

        content = res.get("content", "")
        parsed = {}
        try:
            clean_json = content.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.startswith("```"): clean_json = clean_json[3:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            parsed = json.loads(clean_json.strip())
        except Exception:
            parsed = {"path_summary": content}

        return {
            "mac": raw_mac,
            "facts": sanitized_facts,
            "analysis": parsed,
            "request_id": res.get("request_id")
        }


mac_troubleshooting_service = MACTroubleshootingService()
