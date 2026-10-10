"""
Unified AIContextBuilder orchestrating context aggregation for network devices and incidents.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from ai.context.asset import asset_context_provider
from ai.security.sanitizer import sanitize_data


class AIContextBuilder:
    """Aggregates multi-dimensional network operational context."""

    async def build(
        self,
        device_id: Optional[Any] = None,
        include: Optional[List[str]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        include_set = set(include) if include else {"asset"}
        context: Dict[str, Any] = {}

        if "asset" in include_set and device_id:
            context["asset"] = asset_context_provider.get_context(device_id)

        if extra_context:
            context["extra"] = extra_context

        # Sanitize everything before returning context block
        return sanitize_data(context)


ai_context_builder = AIContextBuilder()
