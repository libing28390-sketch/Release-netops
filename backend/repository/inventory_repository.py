from typing import Optional, List
from database.core import get_db_connection
from domain.models import Interface
from core.interface_utils import normalize_interface_name
import logging

_logger = logging.getLogger(__name__)

class InventoryRepository:
    def __init__(self, conn=None):
        self._conn = conn
        self._owns_conn = conn is None

    def _get_conn(self):
        if self._conn:
            return self._conn
        return get_db_connection()

    def _close_conn(self, conn):
        if self._owns_conn and conn:
            conn.close()

    def get_interface(self, interface_id: str) -> Optional[Interface]:
        """Fetch a single interface by its primary key id."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM interfaces WHERE id = ?",
                (interface_id,)
            ).fetchone()
            if not row:
                return None
            
            r = dict(row)
            # Map allowed_vlans back to list of ints
            allowed_vlans = []
            if r.get("allowed_vlans"):
                try:
                    allowed_vlans = [int(v.strip()) for v in r["allowed_vlans"].split(",") if v.strip().isdigit()]
                except Exception:
                    pass

            return Interface(
                device_id=r["device_id"],
                name_raw=r["name_raw"],
                name_display=r["name_display"],
                interface_type=r["interface_type"],
                description=r.get("description", ""),
                speed=r.get("speed"),
                bandwidth=r.get("bandwidth"),
                mtu=r.get("mtu", 1500),
                mac=r.get("mac_address"),
                admin_status=r.get("admin_status", "down"),
                oper_status=r.get("oper_status", "down"),
                last_change=r.get("last_change"),
                is_l3=bool(r.get("is_l3", False)),
                vrf_id=r.get("vrf_id"),
                primary_ip=r.get("primary_ip"),
                parent_interface_id=r.get("parent_interface_id"),
                lag_id=r.get("lag_id"),
                vlan_mode=r.get("vlan_mode", "access"),
                access_vlan=r.get("access_vlan"),
                native_vlan=r.get("native_vlan"),
                allowed_vlans=allowed_vlans
            )
        except Exception as exc:
            _logger.error(f"Error fetching interface {interface_id}: {exc}", exc_info=True)
            return None
        finally:
            self._close_conn(conn)

    def list_interfaces(self, device_id: Optional[str] = None) -> List[Interface]:
        """Fetch interfaces, optionally filtered by device_id."""
        conn = self._get_conn()
        try:
            if device_id:
                rows = conn.execute(
                    "SELECT * FROM interfaces WHERE device_id = ? ORDER BY name_display",
                    (device_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM interfaces ORDER BY device_id, name_display"
                ).fetchall()
            
            res = []
            for row in rows:
                r = dict(row)
                allowed_vlans = []
                if r.get("allowed_vlans"):
                    try:
                        allowed_vlans = [int(v.strip()) for v in r["allowed_vlans"].split(",") if v.strip().isdigit()]
                    except Exception:
                        pass
                res.append(Interface(
                    device_id=r["device_id"],
                    name_raw=r["name_raw"],
                    name_display=r["name_display"],
                    interface_type=r["interface_type"],
                    description=r.get("description", ""),
                    speed=r.get("speed"),
                    bandwidth=r.get("bandwidth"),
                    mtu=r.get("mtu", 1500),
                    mac=r.get("mac_address"),
                    admin_status=r.get("admin_status", "down"),
                    oper_status=r.get("oper_status", "down"),
                    last_change=r.get("last_change"),
                    is_l3=bool(r.get("is_l3", False)),
                    vrf_id=r.get("vrf_id"),
                    primary_ip=r.get("primary_ip"),
                    parent_interface_id=r.get("parent_interface_id"),
                    lag_id=r.get("lag_id"),
                    vlan_mode=r.get("vlan_mode", "access"),
                    access_vlan=r.get("access_vlan"),
                    native_vlan=r.get("native_vlan"),
                    allowed_vlans=allowed_vlans
                ))
            return res
        except Exception as exc:
            _logger.error(f"Error listing interfaces: {exc}", exc_info=True)
            return []
        finally:
            self._close_conn(conn)

    def save_interface(self, interface: Interface) -> None:
        """Upsert interface details into the database."""
        conn = self._get_conn()
        try:
            # We map allowed_vlans list to comma-separated string
            allowed_vlans_str = ",".join(str(v) for v in interface.allowed_vlans) if interface.allowed_vlans else ""
            normalized_name = normalize_interface_name(interface.name_display or interface.name_raw)
            existing = conn.execute(
                "SELECT id, interface_name FROM interfaces WHERE device_id = ? ORDER BY id",
                (interface.device_id,),
            ).fetchall()
            existing_id = next(
                (
                    row["id"] for row in existing
                    if normalize_interface_name(row["interface_name"]) == normalized_name
                ),
                None,
            ) if normalized_name else None
            interface_id = existing_id or f"{interface.device_id}:{normalized_name or interface.name_display}"
            
            # Use standard SQL REPLACE or INSERT OR REPLACE logic
            conn.execute(
                """
                INSERT INTO interfaces (
                    id, device_id, interface_name, name_raw, name_display, interface_type, description, 
                    speed, bandwidth, mtu, mac_address, admin_status, oper_status, is_l3, 
                    vrf_id, primary_ip, parent_interface_id, lag_id, vlan_mode, 
                    access_vlan, native_vlan, allowed_vlans
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    name_raw = EXCLUDED.name_raw,
                    name_display = EXCLUDED.name_display,
                    description = EXCLUDED.description,
                    speed = EXCLUDED.speed,
                    bandwidth = EXCLUDED.bandwidth,
                    mtu = EXCLUDED.mtu,
                    mac_address = EXCLUDED.mac_address,
                    admin_status = EXCLUDED.admin_status,
                    oper_status = EXCLUDED.oper_status,
                    is_l3 = EXCLUDED.is_l3,
                    vrf_id = EXCLUDED.vrf_id,
                    primary_ip = EXCLUDED.primary_ip,
                    parent_interface_id = EXCLUDED.parent_interface_id,
                    lag_id = EXCLUDED.lag_id,
                    vlan_mode = EXCLUDED.vlan_mode,
                    access_vlan = EXCLUDED.access_vlan,
                    native_vlan = EXCLUDED.native_vlan,
                    allowed_vlans = EXCLUDED.allowed_vlans
                """,
                (
                    interface_id, interface.device_id, interface.name_raw, interface.name_raw, interface.name_display,
                    interface.interface_type, interface.description, interface.speed, interface.bandwidth,
                    interface.mtu, interface.mac, interface.admin_status, interface.oper_status,
                    interface.is_l3, interface.vrf_id, interface.primary_ip,
                    interface.parent_interface_id, interface.lag_id, interface.vlan_mode,
                    interface.access_vlan, interface.native_vlan, allowed_vlans_str
                )
            )
            if self._owns_conn:
                conn.commit()
        except Exception as exc:
            _logger.error(f"Error saving interface {interface.device_id}:{interface.name_display}: {exc}", exc_info=True)
            if self._owns_conn:
                conn.rollback()
            raise exc
        finally:
            self._close_conn(conn)

    def save_status_history(self, interface_id: str, old_status: str, new_status: str, reason: str = "") -> None:
        """Record status transitions timeline."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO interface_status_history (interface_id, old_status, new_status, reason)
                VALUES (?, ?, ?, ?)
                """,
                (interface_id, old_status, new_status, reason)
            )
            if self._owns_conn:
                conn.commit()
        except Exception as exc:
            _logger.error(f"Error saving status history for {interface_id}: {exc}", exc_info=True)
            if self._owns_conn:
                conn.rollback()
        finally:
            self._close_conn(conn)

    def save_statistics_history(self, interface_id: str, rx_bps: int, tx_bps: int, 
                                 rx_util: float, tx_util: float, in_errors: int, 
                                 out_errors: int, crc_errors: int, drops: int) -> None:
        """Record statistics time-series counters timeline."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO interface_statistics_history (
                    interface_id, rx_bps, tx_bps, rx_utilization, tx_utilization, 
                    input_errors, output_errors, crc_errors, drops
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (interface_id, rx_bps, tx_bps, rx_util, tx_util, in_errors, out_errors, crc_errors, drops)
            )
            if self._owns_conn:
                conn.commit()
        except Exception as exc:
            _logger.error(f"Error saving statistics history for {interface_id}: {exc}", exc_info=True)
            if self._owns_conn:
                conn.rollback()
        finally:
            self._close_conn(conn)

    def save_optical_history(self, interface_id: str, rx_dbm: float, tx_dbm: float, 
                             temperature: float, voltage: float, bias_current: float) -> None:
        """Record transceiver physical diagnostics timeline."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO interface_optical_history (
                    interface_id, rx_dbm, tx_dbm, temperature, voltage, bias_current
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (interface_id, rx_dbm, tx_dbm, temperature, voltage, bias_current)
            )
            if self._owns_conn:
                conn.commit()
        except Exception as exc:
            _logger.error(f"Error saving optical history for {interface_id}: {exc}", exc_info=True)
            if self._owns_conn:
                conn.rollback()
        finally:
            self._close_conn(conn)

    def get_status_timeline(self, interface_id: str, limit: int = 50) -> List[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM interface_status_history WHERE interface_id = ? ORDER BY ts DESC LIMIT ?",
                (interface_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_conn(conn)

    def get_statistics_timeline(self, interface_id: str, limit: int = 50) -> List[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM interface_statistics_history WHERE interface_id = ? ORDER BY ts DESC LIMIT ?",
                (interface_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_conn(conn)

    def get_optical_timeline(self, interface_id: str, limit: int = 50) -> List[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM interface_optical_history WHERE interface_id = ? ORDER BY ts DESC LIMIT ?",
                (interface_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._close_conn(conn)

    def get_inventory_summary(self) -> dict:
        """Get summary stats for dashboard counters."""
        conn = self._get_conn()
        try:
            dev_cnt = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            intf_cnt = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0]
            up_cnt = conn.execute("SELECT COUNT(*) FROM interfaces WHERE oper_status = 'up'").fetchone()[0]
            err_cnt = conn.execute("SELECT SUM(crc_errors) FROM interfaces WHERE crc_errors IS NOT NULL").fetchone()[0] or 0
            
            return {
                "devices_count": dev_cnt,
                "interfaces_count": intf_cnt,
                "interfaces_up_count": up_cnt,
                "interfaces_down_count": intf_cnt - up_cnt,
                "total_crc_errors": err_cnt
            }
        finally:
            self._close_conn(conn)
