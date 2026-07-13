from typing import Dict, Type
from services.normalizers.base import BaseNormalizer
from services.normalizers.cisco import CiscoNormalizer
from services.normalizers.huawei import HuaweiNormalizer

class NormalizerFactory:
    """Factory to fetch vendor-specific command output normalizers."""
    
    _normalizers: Dict[str, Type[BaseNormalizer]] = {
        "cisco_ios": CiscoNormalizer,
        "huawei_vrp": HuaweiNormalizer
    }

    @classmethod
    def get_normalizer(cls, platform: str) -> BaseNormalizer:
        """Resolve the normalizer class for the given platform."""
        platform_lower = str(platform).strip().lower()
        
        # Fallbacks for platform variations
        if "cisco" in platform_lower:
            platform_lower = "cisco_ios"
        elif "huawei" in platform_lower:
            platform_lower = "huawei_vrp"
            
        normalizer_cls = cls._normalizers.get(platform_lower)
        if not normalizer_cls:
            raise ValueError(
                f"Unsupported normalizer platform '{platform}'. "
                "Vendor-specific output will not be parsed with Cisco rules."
            )
            
        return normalizer_cls()
