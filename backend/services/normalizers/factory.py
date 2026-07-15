from typing import Dict, Type
from services.normalizers.base import BaseNormalizer
from services.normalizers.arista import AristaNormalizer
from services.normalizers.cisco import CiscoNormalizer
from services.normalizers.h3c import H3CNormalizer
from services.normalizers.huawei import HuaweiNormalizer
from services.normalizers.juniper import JuniperNormalizer
from services.normalizers.ruijie import RuijieNormalizer

class NormalizerFactory:
    """Factory to fetch vendor-specific command output normalizers."""
    
    _normalizers: Dict[str, Type[BaseNormalizer]] = {
        "cisco_ios": CiscoNormalizer,
        "huawei_vrp": HuaweiNormalizer,
        "h3c_comware": H3CNormalizer,
        "juniper_junos": JuniperNormalizer,
        "arista_eos": AristaNormalizer,
        "ruijie_rgos": RuijieNormalizer,
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
        elif "h3c" in platform_lower or "comware" in platform_lower:
            platform_lower = "h3c_comware"
        elif "juniper" in platform_lower or "junos" in platform_lower:
            platform_lower = "juniper_junos"
        elif "arista" in platform_lower or platform_lower == "eos":
            platform_lower = "arista_eos"
        elif "ruijie" in platform_lower or "rgos" in platform_lower:
            platform_lower = "ruijie_rgos"
            
        normalizer_cls = cls._normalizers.get(platform_lower)
        if not normalizer_cls:
            raise ValueError(
                f"Unsupported normalizer platform '{platform}'. "
                "Vendor-specific output will not be parsed with Cisco rules."
            )
            
        return normalizer_cls()
