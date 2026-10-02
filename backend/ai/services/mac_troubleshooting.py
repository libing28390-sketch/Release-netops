"""
AI Service for Intelligent MAC Location and Uplink Path Analysis
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from database.core import get_db_connection
from ai.security.sanitizer import sanitize_data


class MACTroubleshootingService:
    """Trace MAC evidence locally and render a deterministic read-only result.

    MAC addresses are operational identifiers and may be classified as
    ``CONFIDENTIAL``.  This service deliberately stays local so a cloud
    provider can never receive the target or the evidence snapshot.
    """

    def normalize_mac(self, mac: str) -> str:
        clean = re.sub(r'[^a-fA-F0-9]', '', mac).lower()
        if len(clean) == 12:
            return f"{clean[:4]}.{clean[4:8]}.{clean[8:12]}"
        return mac

    def trace_mac_facts(
        self,
        raw_mac: str,
        *,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        norm_mac = self.normalize_mac(raw_mac)
        compact_mac = re.sub(r"[^a-fA-F0-9]", "", raw_mac).lower()
        tenant = tenant_id or "tenant-default"
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
                    cursor.execute(
                        """
                        SELECT a.ip_address, a.vlan_id, a.interface_name,
                               a.device_id, d.hostname, a.last_updated
                        FROM arp_table a
                        JOIN devices d ON d.id = a.device_id
                        WHERE lower(replace(replace(replace(a.mac_address, ':', ''), '-', ''), '.', '')) = ?
                          AND d.tenant_id = ?
                        ORDER BY a.last_updated DESC
                        LIMIT 1
                        """,
                        (compact_mac, tenant),
                    )
                    row = cursor.fetchone()
                    if row:
                        facts["mac_entry"] = {
                            "ip_address": row[0],
                            "vlan": row[1],
                            "interface": row[2],
                            "device_id": row[3],
                            "device_hostname": row[4],
                            "last_updated": row[5],
                        }
                        facts["associated_ip"] = row[0]
                except Exception:
                    pass

                if not facts["mac_entry"]:
                    # A MAC-table record is useful even when ARP projection is
                    # stale or absent.  Compare normalized values in Python so
                    # all common Cisco/Huawei/H3C formats are supported.
                    try:
                        rows = cursor.execute(
                            """
                            SELECT m.mac_address, m.vlan_id, m.interface_name,
                                   m.device_id, d.hostname, m.last_updated
                            FROM mac_table m
                            JOIN devices d ON d.id = m.device_id
                            WHERE d.tenant_id = ?
                            ORDER BY m.last_updated DESC
                            LIMIT 500
                            """,
                            (tenant,),
                        ).fetchall()
                        for item in rows:
                            if re.sub(r"[^a-fA-F0-9]", "", str(item[0] or "")).lower() != compact_mac:
                                continue
                            facts["mac_entry"] = {
                                "mac_address": item[0],
                                "vlan": item[1],
                                "interface": item[2],
                                "device_id": item[3],
                                "device_hostname": item[4],
                                "last_updated": item[5],
                            }
                            break
                    except Exception:
                        pass
        except Exception:
            pass
        return facts

    @staticmethod
    def _render_local_analysis(facts: Dict[str, Any]) -> Dict[str, Any]:
        entry = facts.get("mac_entry") or {}
        has_location = bool(entry)
        if has_location:
            path_summary = "已从本地 ARP/MAC 快照找到端口定位线索，结果需要结合实时采集确认。"
            recommendations = [
                "刷新目标交换机的 MAC 表后重新核对接口。",
                "结合接口状态、VLAN 和 LLDP 邻居确认实际接入链路。",
            ]
        else:
            path_summary = "本地 ARP/MAC 快照暂未找到目标 MAC 的确定性端口证据。"
            recommendations = [
                "确认目标 MAC 属于当前租户和已纳管网络。",
                "刷新交换机 MAC 表与 ARP 采集后重新定位。",
            ]
        return {
            "normalized_mac": facts.get("normalized_mac"),
            "associated_ip": facts.get("associated_ip") or entry.get("ip_address"),
            "located_switch": entry.get("device_hostname") or entry.get("device_id"),
            "located_port": entry.get("interface"),
            "vlan": entry.get("vlan"),
            "path_summary": path_summary,
            "recommendations": recommendations,
            "analysis_source": "local_deterministic",
            "external_egress": False,
        }

    async def troubleshoot_mac(
        self,
        raw_mac: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Keep user_id in the public signature for API compatibility.  The
        # operation is local-only and does not invoke a provider or gateway.
        del user_id
        facts = self.trace_mac_facts(raw_mac, tenant_id=tenant_id)
        sanitized_facts = sanitize_data(facts)
        return {
            "mac": raw_mac,
            "facts": sanitized_facts,
            "analysis": self._render_local_analysis(sanitized_facts),
            "analysis_source": "local_deterministic",
            "execution_mode": "local_sensitive_identifier",
            "external_egress": False,
            "request_id": None,
        }


mac_troubleshooting_service = MACTroubleshootingService()
