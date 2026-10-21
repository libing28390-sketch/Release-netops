from abc import ABC, abstractmethod
from domain.models import Device, Interface, Neighbor
from typing import List, Dict, Any

class BaseNormalizer(ABC):
    """
    Abstract base class for all vendor-specific output normalizers.
    Decodes raw vendor CLI stdout (e.g. Cisco show, Huawei display) 
    into standard domain entities.
    """
    
    @abstractmethod
    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        """Parse raw device version output into a Device domain object."""
        pass

    @abstractmethod
    def parse_interfaces(self, device_id: str, raw_interfaces: str, raw_ip_brief: str = "") -> List[Interface]:
        """Parse raw interface configuration and state output into a list of Interface domain objects."""
        pass

    @abstractmethod
    def parse_neighbors(self, device_id: str, raw_lldp: str) -> List[Neighbor]:
        """Parse LLDP neighbor detail outputs into a list of Neighbor domain objects."""
        pass
