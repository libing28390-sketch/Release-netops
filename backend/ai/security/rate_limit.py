"""
AI Rate Limiter supporting Redis sliding window / daily quota with in-memory fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Tuple
from core.config import settings

logger = logging.getLogger(__name__)

# In-memory fallback tracking: key -> (count, reset_timestamp)
_IN_MEMORY_QUOTA: Dict[str, Tuple[int, float]] = {}

try:
    import redis
    _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
except Exception:
    _redis_client = None


class AIRateLimiter:
    """Rate limiter for AI endpoints."""

    def is_allowed(self, user_id: str, scene: str, max_per_day: int = 200) -> Tuple[bool, int]:
        """
        Check if request is allowed.
        Returns (allowed, remaining_quota).
        """
        key = f"ai:ratelimit:{user_id or 'anon'}:{scene}"
        
        # 1. Try Redis
        if _redis_client:
            try:
                current = _redis_client.get(key)
                if current is None:
                    _redis_client.set(key, 1, ex=86400)
                    return True, max_per_day - 1
                
                val = int(current)
                if val >= max_per_day:
                    return False, 0
                
                _redis_client.incr(key)
                return True, max_per_day - (val + 1)
            except Exception as exc:
                # Redis errors can include a connection URL; never log the
                # exception text or credentials.
                logger.debug(
                    "Redis rate limit error, falling back to memory: %s",
                    type(exc).__name__,
                )

        # 2. In-memory fallback
        now = time.time()
        if key in _IN_MEMORY_QUOTA:
            cnt, expire_at = _IN_MEMORY_QUOTA[key]
            if now > expire_at:
                _IN_MEMORY_QUOTA[key] = (1, now + 86400)
                return True, max_per_day - 1
            if cnt >= max_per_day:
                return False, 0
            _IN_MEMORY_QUOTA[key] = (cnt + 1, expire_at)
            return True, max_per_day - (cnt + 1)
        else:
            _IN_MEMORY_QUOTA[key] = (1, now + 86400)
            return True, max_per_day - 1


ai_rate_limiter = AIRateLimiter()
