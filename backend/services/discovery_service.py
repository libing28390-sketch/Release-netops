import logging
from typing import Dict, Any, List, Optional
from database.core import get_db_connection
from repository.inventory_repository import InventoryRepository
from services.inventory_synchronizer import InventorySynchronizer
from services.normalizers.factory import NormalizerFactory
from drivers.factory import DriverFactory
from domain.models import Device, Interface, Neighbor

_logger = logging.getLogger(__name__)

class DiscoveryService:
    def __init__(self, repo: Optional[InventoryRepository] = None, sync: Optional[InventorySynchronizer] = None):
        self.repo = repo or InventoryRepository()
        self.sync = sync or InventorySynchronizer(self.repo)

    def discover_device(self, device_id: str) -> dict:
        """
        Execute active CLI discovery for a device ID, parse outputs via 
        Vendor Normalizers, and synchronize results to the Repository SSoT.
        """
        conn = get_db_connection()
        try:
            # 1. Fetch device connection details from DB
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not row:
                raise ValueError(f"Device {device_id} not found in database CMDB")
            
            device_info = dict(row)
            platform = device_info.get("platform") or "cisco_ios"
            driver_type = device_info.get("connection_method") or "netmiko"
            
            # Map platform to commands
            if "huawei" in platform.lower():
                cmd_version = "display version"
                cmd_interfaces = "display interface"
                cmd_brief = "display ip interface brief"
                cmd_lldp = "display lldp neighbor verbose"
            else: # default Cisco
                cmd_version = "show version"
                cmd_interfaces = "show interfaces"
                cmd_brief = "show ip interface brief"
                cmd_lldp = "show lldp neighbors detail"
                
            # 2. Connect via Driver and run commands
            _logger.info(f"Connecting to device {device_id} ({device_info.get('ip_address')}) via {driver_type}")
            driver = DriverFactory.get_driver(driver_type, device_info)
            
            with driver:
                res_ver = driver.send_command(cmd_version)
                res_int = driver.send_command(cmd_interfaces)
                res_brf = driver.send_command(cmd_brief)
                res_lldp = driver.send_command(cmd_lldp)
                
            # Check execution success (allow empty output for non-critical commands)
            raw_version = res_ver.output if res_ver.success else ""
            raw_interfaces = res_int.output if res_int.success else ""
            raw_brief = res_brf.output if res_brf.success else ""
            raw_lldp = res_lldp.output if res_lldp.success else ""
            
            # 3. Resolve Normalizer and parse outputs
            normalizer = NormalizerFactory.get_normalizer(platform)
            
            # Parse Device Info
            device_obj: Device = normalizer.parse_device_info(device_id, raw_version)
            # Inject IP address from CMDB
            device_obj.ip_address = device_info.get("ip_address") or ""
            
            # Parse Interfaces
            interfaces: List[Interface] = normalizer.parse_interfaces(device_id, raw_interfaces, raw_brief)
            
            # Parse Neighbors
            neighbors: List[Neighbor] = normalizer.parse_neighbors(device_id, raw_lldp)
            
            # 4. Synchronize parsed Domain Objects to the database Repository
            _logger.info(f"Starting database synchronization for device {device_id}")
            
            # Update Device static details in CMDB
            conn.execute(
                """
                UPDATE devices SET 
                    hostname = ?,
                    vendor = ?,
                    platform = ?,
                    serial_number = ?,
                    model = ?,
                    os_version = ?,
                    uptime = ?
                WHERE id = ?
                """,
                (
                    device_obj.hostname, device_obj.vendor, device_obj.platform,
                    device_obj.sn, device_obj.model, device_obj.version,
                    device_obj.uptime, device_id
                )
            )
            conn.commit()
            
            # Sync Interfaces via InventorySynchronizer (delta changes and status logging)
            sync_res = self.sync.sync_interfaces(device_id, interfaces)
            
            # Save LLDP neighbors
            # Clean up old neighbors first to avoid duplicates
            conn.execute("DELETE FROM topology_links WHERE source_device_id = ?", (device_id,))
            for n in neighbors:
                # Find target device by hostname or ID
                target_row = conn.execute(
                    "SELECT id FROM devices WHERE hostname = ? OR id = ?",
                    (n.remote_device, n.remote_device)
                ).fetchone()
                if not target_row:
                    _logger.warning(f"Neighbor target device '{n.remote_device}' not found in CMDB, skipping link entry creation")
                    continue
                
                target_device_id = target_row["id"]
                link_key = f"{device_id}:{n.local_interface}-{target_device_id}:{n.remote_interface}"
                
                # Fetch source and target interface IDs if they exist
                src_intf_id = f"{device_id}:{n.local_interface}"
                tgt_intf_id = f"{target_device_id}:{n.remote_interface}"
                
                # Ensure source and target interface stubs exist in DB to prevent FK violations
                src_intf_row = conn.execute("SELECT id FROM interfaces WHERE id = ?", (src_intf_id,)).fetchone()
                if not src_intf_row:
                    conn.execute(
                        "INSERT INTO interfaces (id, device_id, interface_name, name_raw, name_display, interface_type, admin_status, oper_status) VALUES (?, ?, ?, ?, ?, 'physical', 'up', 'up')",
                        (src_intf_id, device_id, n.local_interface, n.local_interface, n.local_interface)
                    )
                
                tgt_intf_row = conn.execute("SELECT id FROM interfaces WHERE id = ?", (tgt_intf_id,)).fetchone()
                if not tgt_intf_row:
                    conn.execute(
                        "INSERT INTO interfaces (id, device_id, interface_name, name_raw, name_display, interface_type, admin_status, oper_status) VALUES (?, ?, ?, ?, ?, 'physical', 'up', 'up')",
                        (tgt_intf_id, target_device_id, n.remote_interface, n.remote_interface, n.remote_interface)
                    )
                
                conn.execute(
                    """
                    INSERT INTO topology_links (
                        id, link_key, source_device_id, source_interface_id, source_port, source_port_normalized,
                        target_device_id, target_interface_id, target_port, target_port_normalized,
                        discovery_source, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'lldp', 'up')
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        link_key, link_key, device_id, src_intf_id, n.local_interface, n.local_interface,
                        target_device_id, tgt_intf_id, n.remote_interface, n.remote_interface
                    )
                )
            conn.commit()
            
            return {
                "success": True,
                "device_id": device_id,
                "hostname": device_obj.hostname,
                "interfaces_sync": sync_res,
                "neighbors_count": len(neighbors)
            }
            
        except Exception as exc:
            _logger.error(f"Discovery failed on device {device_id}: {exc}", exc_info=True)
            return {
                "success": False,
                "device_id": device_id,
                "error": str(exc)
            }
        finally:
            conn.close()
