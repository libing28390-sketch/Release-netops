from typing import Dict, Type, Any
from .drivers.base_driver import BaseDriver

class DriverRegistry:
    """驱动注册中心 (支持插件化扩展)"""
    _registry: Dict[str, Type[BaseDriver]] = {}
    _asset_type_aliases = {
        # CMDB asset types describe inventory records; the execution engine
        # registers the corresponding network capability as ``network``.
        "network_device": "network",
    }

    @classmethod
    def register(cls, asset_type: str):
        """装饰器注册机制"""
        def decorator(driver_cls: Type[BaseDriver]):
            cls._registry[asset_type] = driver_cls
            return driver_cls
        return decorator

    @classmethod
    def get_driver(cls, asset_type: str, device_info: Dict[str, Any]) -> BaseDriver:
        # 兼容性处理：如果没传 asset_type，尝试从 device_info 推断
        if not asset_type:
            asset_type = device_info.get("asset_type", "network")
        asset_type = str(asset_type or "").strip().lower()
        asset_type = cls._asset_type_aliases.get(asset_type, asset_type)

        driver_cls = cls._registry.get(asset_type)
        if not driver_cls:
            raise ValueError(f"No driver found for asset_type: {asset_type}")
        return driver_cls(device_info)
