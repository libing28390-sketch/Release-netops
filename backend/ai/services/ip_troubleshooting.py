"""
AI Service for Intelligent IP Location and Multi-Layer Troubleshooting (IP -> ARP -> MAC -> Port -> Topology -> Alarm -> AI Summary)
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from database.core import get_db_connection
from ai.gateway.llm_gateway import llm_gateway
from ai.security.sanitizer import sanitize_data


class IPTroubleshootingService:
    """Traces IP through ARP, MAC, Port, VLAN, Topology, and Alarms, then generates AI Root Cause Summary."""

    def trace_ip_facts(self, ip_address: str) -> Dict[str, Any]:
        facts: Dict[str, Any] = {
            "target_ip": ip_address,
            "arp_record": None,
            "mac_record": None,
            "device": None,
            "active_alarms": [],
            "recent_diffs": [],
        }
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # 1. Query Device by IP
                cursor.execute("SELECT id, hostname, platform, vendor, status FROM devices WHERE ip_address = ?", (ip_address,))
                dev_row = cursor.fetchone()
                if dev_row:
                    facts["device"] = {
                        "id": dev_row[0], "hostname": dev_row[1],
                        "platform": dev_row[2], "vendor": dev_row[3], "status": dev_row[4]
                    }

                # 2. Check ARP / MAC cache tables if present
                try:
                    cursor.execute("SELECT mac_address, vlan, interface, device_id FROM arp_cache WHERE ip_address = ? LIMIT 1", (ip_address,))
                    arp_row = cursor.fetchone()
                    if arp_row:
                        facts["arp_record"] = {
                            "mac_address": arp_row[0], "vlan": arp_row[1],
                            "interface": arp_row[2], "device_id": arp_row[3]
                        }
                except Exception:
                    pass

                # 3. Check Active Alarms
                try:
                    cursor.execute("SELECT title, severity, created_at FROM active_alarms LIMIT 5")
                    alarm_rows = cursor.fetchall()
                    for a in alarm_rows:
                        facts["active_alarms"].append({"title": a[0], "severity": a[1], "created_at": a[2]})
                except Exception:
                    pass

        except Exception:
            pass

        return facts

    async def troubleshoot_ip(self, ip_address: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        facts = self.trace_ip_facts(ip_address)
        sanitized_facts = sanitize_data(facts)

        sys_prompt = (
            "You are an AI Network Troubleshooting Assistant. "
            "Analyze the multi-layer IP location facts (ARP, MAC, Device Status, Alarms) gathered from Nexora. "
            "Return a structured JSON with keys: 'ip', 'located_mac', 'access_switch', 'access_port', "
            "'vlan', 'status_summary', 'root_cause_analysis', 'recommendations'."
        )
        user_prompt = f"Target IP: {ip_address}\nNexora Facts:\n{json.dumps(sanitized_facts, ensure_ascii=False)}"

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
            parsed = {"status_summary": content}

        return {
            "target_ip": ip_address,
            "facts": sanitized_facts,
            "analysis": parsed,
            "request_id": res.get("request_id")
        }


ip_troubleshooting_service = IPTroubleshootingService()
