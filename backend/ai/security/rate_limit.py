"""
AI Rate Limiter supporting Redis sliding window / daily quota with in-memory fallback.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Dict, Tuple
from core.config import settings

logger = logging.getLogger(__name__)

# In-memory fallback tracking: key -> (count, reset_timestamp)
_IN_MEMORY_QUOTA: Dict[str, Tuple[int, float]] = {}
_IN_MEMORY_LOCK = threading.Lock()

try:
    import redis
    # Short timeouts: a slow or unreachable Redis must not stall AI requests.
    _redis_client = redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
except Exception:
    _redis_client = None


class AIRateLimiter:
    """Rate limiter for AI endpoints."""

    async def is_allowed_async(self, user_id: str, scene: str, max_per_day: int = 200) -> Tuple[bool, int]:
        """Same as ``is_allowed`` without blocking the event loop on Redis I/O."""
        return await asyncio.to_thread(self.is_allowed, user_id, scene, max_per_day)

    def is_allowed(self, user_id: str, scene: str, max_per_day: int = 200) -> Tuple[bool, int]:
        """
        Check if request is allowed.
        Returns (allowed, remaining_quota).
        """
        key = f"ai:ratelimit:{user_id or 'anon'}:{scene}"
        
        # 1. Try Redis
        if _redis_client:
            try:
                new_val = int(_redis_client.incr(key))
                if new_val == 1 or _redis_client.ttl(key) < 0:
                    _redis_client.expire(key, 86400)
                if new_val > max_per_day:
                    return False, 0
                return True, max(0, max_per_day - new_val)
            except Exception as exc:
                # Redis errors can include a connection URL; never log the
                # exception text or credentials.
                logger.debug(
                    "Redis rate limit error, falling back to memory: %s",
                    type(exc).__name__,
                )

        # 2. In-memory fallback
        now = time.time()
        with _IN_MEMORY_LOCK:
            if len(_IN_MEMORY_QUOTA) > 4096:
                expired_keys = [k for k, (_, exp) in _IN_MEMORY_QUOTA.items() if now > exp]
                for k in expired_keys:
                    _IN_MEMORY_QUOTA.pop(k, None)
            if key in _IN_MEMORY_QUOTA:
                cnt, expire_at = _IN_MEMORY_QUOTA[key]
                if now > expire_at:
                    _IN_MEMORY_QUOTA[key] = (1, now + 86400)
                    return True, max_per_day - 1
                if cnt >= max_per_day:
                    return False, 0
                _IN_MEMORY_QUOTA[key] = (cnt + 1, expire_at)
                return True, max_per_day - (cnt + 1)
            _IN_MEMORY_QUOTA[key] = (1, now + 86400)
            return True, max_per_day - 1


ai_rate_limiter = AIRateLimiter()
