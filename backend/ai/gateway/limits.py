"""Bounded AI concurrency and provider circuit state.

The gateway is the single egress path, so limits live here rather than in a
provider adapter.  Semaphores are process-local safety valves; durable usage
and cost accounting remains in ``ai_usage_daily``.  A deployment with more
than one worker must configure an external rate limiter in front of the API
as well, but every worker still fails closed locally.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from ai.gateway.exceptions import AICircuitOpenException, AIQuotaExceededException
from ai.services.metrics import ai_metrics
from core.config import settings


@dataclass
class _Circuit:
    failures: int = 0
    opened_until: float = 0.0


class AILimitManager:
    def __init__(self) -> None:
        self.provider_limit = max(1, int(getattr(settings, "AI_PROVIDER_MAX_CONCURRENCY", 8)))
        self.tenant_limit = max(1, int(getattr(settings, "AI_TENANT_MAX_CONCURRENCY", 4)))
        self.user_limit = max(1, int(getattr(settings, "AI_USER_MAX_CONCURRENCY", 2)))
        self.acquire_timeout = max(0.1, float(getattr(settings, "AI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", 10.0)))
        self.failure_threshold = max(1, int(getattr(settings, "AI_CIRCUIT_FAILURE_THRESHOLD", 3)))
        self.cooldown_seconds = max(1.0, float(getattr(settings, "AI_CIRCUIT_COOLDOWN_SECONDS", 30.0)))
        self._providers: dict[str, asyncio.Semaphore] = {}
        self._tenants: dict[str, asyncio.Semaphore] = {}
        self._users: dict[str, asyncio.Semaphore] = {}
        self._circuits: dict[str, _Circuit] = {}

    def _semaphore(self, pool: dict[str, asyncio.Semaphore], key: str, limit: int) -> asyncio.Semaphore:
        semaphore = pool.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(limit)
            pool[key] = semaphore
        return semaphore

    def _check_circuit(self, provider_id: str) -> None:
        circuit = self._circuits.get(provider_id)
        if not circuit:
            return
        now = time.monotonic()
        if circuit.opened_until > now:
            ai_metrics.limit_event(provider_id, "circuit_open")
            raise AICircuitOpenException()
        if circuit.opened_until:
            circuit.opened_until = 0.0
            circuit.failures = 0

    @asynccontextmanager
    async def slot(self, *, provider_id: str, tenant_id: str, user_id: str | None) -> AsyncIterator[None]:
        self._check_circuit(provider_id)
        provider = self._semaphore(self._providers, provider_id, self.provider_limit)
        tenant = self._semaphore(self._tenants, tenant_id, self.tenant_limit)
        user_key = user_id or "anonymous"
        user = self._semaphore(self._users, f"{tenant_id}:{user_key}", self.user_limit)
        acquired: list[asyncio.Semaphore] = []
        try:
            for semaphore in (provider, tenant, user):
                try:
                    await asyncio.wait_for(semaphore.acquire(), timeout=self.acquire_timeout)
                except asyncio.TimeoutError as exc:
                    ai_metrics.limit_event(provider_id, "concurrency_timeout")
                    raise AIQuotaExceededException() from exc
                acquired.append(semaphore)
            yield
        finally:
            for semaphore in reversed(acquired):
                semaphore.release()

    def record_success(self, provider_id: str) -> None:
        circuit = self._circuits.setdefault(provider_id, _Circuit())
        circuit.failures = 0
        circuit.opened_until = 0.0

    def record_failure(self, provider_id: str) -> None:
        circuit = self._circuits.setdefault(provider_id, _Circuit())
        circuit.failures += 1
        if circuit.failures >= self.failure_threshold:
            circuit.opened_until = time.monotonic() + self.cooldown_seconds

    def reset_provider(self, provider_id: str) -> None:
        """Forget circuit failures after an operator changes Provider config."""
        self._circuits.pop(str(provider_id), None)


ai_limits = AILimitManager()
