from typing import Dict, Any, Type
from .base import BaseDriver
from .netmiko_driver import NetmikoDriver
from .scrapli_driver import ScrapliDriver
from .mock_driver import MockDriver

class DriverFactory:
    """驱动工厂类"""
    
    _drivers = {
        'netmiko': NetmikoDriver,
        'scrapli': ScrapliDriver,
        'mock': MockDriver,
    }

    @classmethod
    def get_driver(cls, driver_type: str, device_info: Dict[str, Any]) -> BaseDriver:
        driver_class = cls._drivers.get(driver_type.lower())
        if not driver_class:
            raise ValueError(f"Unsupported driver type: {driver_type}")
        return driver_class(device_info)
