from typing import List, Optional
from repository.inventory_repository import InventoryRepository
from domain.models import Interface
import logging

_logger = logging.getLogger(__name__)

class InventorySynchronizer:
    def __init__(self, repo: Optional[InventoryRepository] = None):
        self.repo = repo or InventoryRepository()

    def sync_interfaces(self, device_id: str, parsed_interfaces: List[Interface]) -> dict:
        """
        Synchronize a list of discovered interfaces for a device.
        Detects deltas, records status changes/flaps in status timeline,
        and updates current interface asset properties.
        """
        added = 0
        updated = 0
        flapped = 0
        
        for interface in parsed_interfaces:
            interface_id = f"{device_id}:{interface.name_display}"
            try:
                old_interface = self.repo.get_interface(interface_id)
                
                if not old_interface:
                    # Brand new interface discovered
                    self.repo.save_interface(interface)
                    self.repo.save_status_history(
                        interface_id=interface_id,
                        old_status="None",
                        new_status=interface.oper_status,
                        reason="Interface discovered"
                    )
                    added += 1
                else:
                    # Delta detection
                    has_changes = (
                        old_interface.admin_status != interface.admin_status or
                        old_interface.oper_status != interface.oper_status or
                        old_interface.description != interface.description or
                        old_interface.speed != interface.speed or
                        old_interface.mac != interface.mac or
                        old_interface.primary_ip != interface.primary_ip or
                        old_interface.vlan_mode != interface.vlan_mode or
                        old_interface.access_vlan != interface.access_vlan or
                        old_interface.native_vlan != interface.native_vlan or
                        set(old_interface.allowed_vlans) != set(interface.allowed_vlans)
                    )
                    
                    # Log state flapping transitions
                    if old_interface.oper_status != interface.oper_status:
                        self.repo.save_status_history(
                            interface_id=interface_id,
                            old_status=old_interface.oper_status,
                            new_status=interface.oper_status,
                            reason="Operational state transition during synchronization resync"
                        )
                        flapped += 1
                        
                    if has_changes:
                        self.repo.save_interface(interface)
                        updated += 1
            except Exception as exc:
                _logger.error(f"Failed to synchronize interface {interface_id}: {exc}", exc_info=True)
                
        return {
            "device_id": device_id,
            "interfaces_added": added,
            "interfaces_updated": updated,
            "interfaces_flapped": flapped
        }

    def record_interface_telemetry(self, interface_id: str, 
                                   rx_bps: int, tx_bps: int, 
                                   rx_util: float, tx_util: float, 
                                   in_errors: int, out_errors: int, 
                                   crc_errors: int, drops: int) -> None:
        """Record a time-series telemetry snapshot into the statistics timeline."""
        try:
            self.repo.save_statistics_history(
                interface_id=interface_id,
                rx_bps=rx_bps,
                tx_bps=tx_bps,
                rx_util=rx_util,
                tx_util=tx_util,
                in_errors=in_errors,
                out_errors=out_errors,
                crc_errors=crc_errors,
                drops=drops
            )
        except Exception as exc:
            _logger.error(f"Failed to record statistics telemetry for {interface_id}: {exc}", exc_info=True)

    def record_optical_diagnostics(self, interface_id: str, 
                                   rx_dbm: float, tx_dbm: float, 
                                   temperature: float, voltage: float, 
                                   bias_current: float) -> None:
        """Record transceiver metrics into the optical timeline."""
        try:
            self.repo.save_optical_history(
                interface_id=interface_id,
                rx_dbm=rx_dbm,
                tx_dbm=tx_dbm,
                temperature=temperature,
                voltage=voltage,
                bias_current=bias_current
            )
        except Exception as exc:
            _logger.error(f"Failed to record optical diagnostics for {interface_id}: {exc}", exc_info=True)
