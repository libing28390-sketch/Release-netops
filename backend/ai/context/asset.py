"""
Asset Context Provider for querying device hardware, role, site, and tags
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from database.core import get_db_connection


class AssetContextProvider:
    """Fetch asset metadata context for a device."""

    def get_context(self, device_id: Any) -> Dict[str, Any]:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, hostname, ip_address, platform, vendor, role, site_id, status "
                    "FROM devices WHERE id = ? OR hostname = ? OR ip_address = ?",
                    (str(device_id), str(device_id), str(device_id))
                )
                row = cursor.fetchone()
                if not row:
                    return {"device_id": device_id, "found": False}
                
                return {
                    "found": True,
                    "id": row[0],
                    "hostname": row[1],
                    "ip_address": row[2],
                    "platform": row[3],
                    "vendor": row[4] if len(row) > 4 else "Unknown",
                    "role": row[5] if len(row) > 5 else "Network Device",
                    "site_id": row[6] if len(row) > 6 else None,
                    "status": row[7] if len(row) > 7 else "online",
                }
        except Exception:
            return {"device_id": device_id, "found": False}


asset_context_provider = AssetContextProvider()
