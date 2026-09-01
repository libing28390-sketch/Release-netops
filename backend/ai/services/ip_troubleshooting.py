"""
AI Service for Intelligent IP Location and Multi-Layer Troubleshooting (IP -> ARP -> MAC -> Port -> Topology -> Alarm -> AI Summary)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from database.core import get_db_connection
from ai.security.sanitizer import sanitize_data


class IPTroubleshootingService:
    """Trace IP evidence locally and render a deterministic read-only result.

    IP addresses are operational identifiers and therefore may be classified as
    ``CONFIDENTIAL`` by the security gateway.  This path intentionally does not
    send the target or the evidence snapshot to an external model.  Natural
    language synthesis can be added later only behind an approved local-model
    route.
    """

    def trace_ip_facts(
        self,
        ip_address: str,
        *,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant = tenant_id or "tenant-default"
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
                cursor.execute(
                    """
                    SELECT id, hostname, platform, vendor, status
                    FROM devices
                    WHERE ip_address = ? AND tenant_id = ?
                    ORDER BY id
                    LIMIT 1
                    """,
                    (ip_address, tenant),
                )
                dev_row = cursor.fetchone()
                if dev_row:
                    facts["device"] = {
                        "id": dev_row[0], "hostname": dev_row[1],
                        "platform": dev_row[2], "vendor": dev_row[3], "status": dev_row[4]
                    }

                # 2. Prefer the normalized ARP table used by the current
                # schema.  The short-lived arp_cache is retained as a
                # fallback for installations that have not yet projected it.
                try:
                    cursor.execute(
                        """
                        SELECT a.mac_address, a.vlan_id, a.interface_name,
                               a.device_id, a.last_updated
                        FROM arp_table a
                        JOIN devices d ON d.id = a.device_id
                        WHERE a.ip_address = ?
                          AND d.tenant_id = ?
                        ORDER BY a.last_updated DESC
                        LIMIT 1
                        """,
                        (ip_address, tenant),
                    )
                    arp_row = cursor.fetchone()
                    if arp_row:
                        facts["arp_record"] = {
                            "mac_address": arp_row[0],
                            "vlan": arp_row[1],
                            "interface": arp_row[2],
                            "device_id": arp_row[3],
                            "last_updated": arp_row[4],
                        }
                except Exception:
                    try:
                        # arp_cache predates tenant scoping.  Never use this
                        # unscoped compatibility table for a non-default
                        # tenant; the normalized arp_table above is the
                        # authoritative tenant-scoped source.
                        if tenant != "tenant-default":
                            raise LookupError("unscoped arp_cache is not eligible for this tenant")
                        cursor.execute(
                            """
                            SELECT mac, vlan_id, source_device_id, cached_at
                            FROM arp_cache
                            WHERE target_ip = ?
                            LIMIT 1
                            """,
                            (ip_address,),
                        )
                        arp_row = cursor.fetchone()
                        if arp_row:
                            facts["arp_record"] = {
                                "mac_address": arp_row[0],
                                "vlan": arp_row[1],
                                "interface": None,
                                "device_id": arp_row[2],
                                "last_updated": arp_row[3],
                                "source": "arp_cache",
                            }
                    except Exception:
                        pass

                # 3. Check Active Alarms
                try:
                    device_id = (facts.get("device") or {}).get("id")
                    if device_id:
                        cursor.execute(
                            """
                            SELECT title, severity, created_at
                            FROM alert_events
                            WHERE resolved_at IS NULL AND device_id = ?
                            ORDER BY created_at DESC
                            LIMIT 5
                            """,
                            (device_id,),
                        )
                        alarm_rows = cursor.fetchall()
                        for a in alarm_rows:
                            facts["active_alarms"].append(
                                {"title": a[0], "severity": a[1], "created_at": a[2]}
                            )
                except Exception:
                    pass

        except Exception:
            pass

        return facts

    @staticmethod
    def _render_local_analysis(facts: Dict[str, Any]) -> Dict[str, Any]:
        arp = facts.get("arp_record") or {}
        device = facts.get("device") or {}
        alarms = facts.get("active_alarms") or []
        has_location = bool(arp or device)
        if has_location:
            status_summary = "已从本地 CMDB/ARP 快照找到定位线索，结果需要结合实时采集确认。"
            root_cause = "当前证据支持目标 IP 与本地网络设备或 ARP 记录存在关联，未执行写操作。"
        else:
            status_summary = "本地 CMDB/ARP 快照暂未找到目标 IP 的确定性定位证据。"
            root_cause = "缺少当前 ARP 或设备地址证据，不能据此推断接入交换机和物理端口。"
        if alarms:
            status_summary += f"发现 {len(alarms)} 条未恢复告警，建议结合告警时间核对。"
        recommendations = [
            "刷新目标网段的 ARP/MAC 采集后重新定位。",
            "将历史快照与设备当前 MAC 表、接口状态和 LLDP 邻居进行交叉核对。",
        ]
        if not has_location:
            recommendations.insert(0, "确认目标 IP 属于当前租户和已纳管网段。")
        return {
            "ip": facts.get("target_ip"),
            "located_mac": arp.get("mac_address"),
            "access_switch": device.get("hostname"),
            "access_port": arp.get("interface"),
            "vlan": arp.get("vlan"),
            "status_summary": status_summary,
            "root_cause_analysis": root_cause,
            "recommendations": recommendations,
            "analysis_source": "local_deterministic",
            "external_egress": False,
        }

    async def troubleshoot_ip(
        self,
        ip_address: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Keep user_id in the public signature for API compatibility.  The
        # operation is local-only and does not invoke a provider or gateway.
        del user_id
        facts = self.trace_ip_facts(ip_address, tenant_id=tenant_id)
        sanitized_facts = sanitize_data(facts)
        return {
            "target_ip": ip_address,
            "facts": sanitized_facts,
            "analysis": self._render_local_analysis(sanitized_facts),
            "analysis_source": "local_deterministic",
            "execution_mode": "local_sensitive_identifier",
            "external_egress": False,
            "request_id": None,
        }


ip_troubleshooting_service = IPTroubleshootingService()
