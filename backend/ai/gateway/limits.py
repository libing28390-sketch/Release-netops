"""Bounded AI concurrency and provider circuit state.

The gateway is the single egress path, so limits live here rather than in a
provider adapter.  Semaphores are process-local safety valves; durable usage
and cost accounting remains in ``ai_usage_daily``.  A deployment with more
than one worker must configure an external rate limiter in front of the API
as well, but every worker still fails closed locally.

Circuit breaker
---------------
* closed     -- requests flow; each *request* that finally fails (after its
                own retries) counts one failure.
* open       -- after ``failure_threshold`` consecutive failed requests, every
                request is refused for ``cooldown_seconds``.
* half-open  -- after the cooldown exactly one probe request is let through.
                Success closes the circuit, failure reopens it for another
                cooldown.  Other requests keep getting AI_PROVIDER_CIRCUIT_OPEN
                while the probe is in flight, so a recovering provider is not
                hit by a burst of queued traffic.
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
    probe_in_flight: bool = False
    probe_started_at: float = 0.0


class AILimitManager:
    def __init__(self) -> None:
        self.provider_limit = max(1, int(getattr(settings, "AI_PROVIDER_MAX_CONCURRENCY", 8)))
        self.tenant_limit = max(1, int(getattr(settings, "AI_TENANT_MAX_CONCURRENCY", 4)))
        self.user_limit = max(1, int(getattr(settings, "AI_USER_MAX_CONCURRENCY", 2)))
        self.acquire_timeout = max(0.1, float(getattr(settings, "AI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", 10.0)))
        self.failure_threshold = max(1, int(getattr(settings, "AI_CIRCUIT_FAILURE_THRESHOLD", 3)))
        self.cooldown_seconds = max(1.0, float(getattr(settings, "AI_CIRCUIT_COOLDOWN_SECONDS", 30.0)))
        # A probe that never reports back (process crash, lost task) must not
        # keep the circuit half-open forever.
        self.probe_timeout_seconds = max(1.0, float(getattr(settings, "AI_CIRCUIT_PROBE_TIMEOUT_SECONDS", 120.0)))
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

    def _check_circuit(self, provider_id: str) -> bool:
        """Raise AICircuitOpenException while the circuit is open.

        Returns True when the caller has just become the half-open probe; the
        caller must then report the outcome (``record_success`` /
        ``record_failure``) or call ``release_probe``.
        """
        circuit = self._circuits.get(provider_id)
        if not circuit or not circuit.opened_until:
            return False
        now = time.monotonic()
        if circuit.opened_until > now:
            ai_metrics.limit_event(provider_id, "circuit_open")
            raise AICircuitOpenException()
        if circuit.probe_in_flight and now - circuit.probe_started_at < self.probe_timeout_seconds:
            ai_metrics.limit_event(provider_id, "circuit_half_open")
            raise AICircuitOpenException()
        circuit.probe_in_flight = True
        circuit.probe_started_at = now
        ai_metrics.limit_event(provider_id, "circuit_probe")
        return True

    def acquire_circuit(self, provider_id: str) -> bool:
        """Check the circuit once per request (before its retry loop)."""
        return self._check_circuit(provider_id)

    def release_probe(self, provider_id: str) -> None:
        """Give up the half-open probe without an outcome (e.g. auth error, abort)."""
        circuit = self._circuits.get(provider_id)
        if circuit is not None and circuit.probe_in_flight:
            circuit.probe_in_flight = False
            circuit.probe_started_at = 0.0

    @asynccontextmanager
    async def slot(
        self,
        *,
        provider_id: str,
        tenant_id: str,
        user_id: str | None,
        check_circuit: bool = True,
    ) -> AsyncIterator[None]:
        # The gateway checks the circuit once per request via acquire_circuit
        # and passes check_circuit=False for each retry attempt, so a request's
        # own retries are never refused by the probe it holds.
        if check_circuit:
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
        circuit.probe_in_flight = False
        circuit.probe_started_at = 0.0

    def record_failure(self, provider_id: str) -> None:
        """Count one failed *request* (call once, after its retries are spent)."""
        circuit = self._circuits.setdefault(provider_id, _Circuit())
        circuit.failures += 1
        now = time.monotonic()
        if circuit.probe_in_flight or circuit.opened_until:
            # The half-open probe failed (or a late failure arrived while
            # open): back to open for a full cooldown.
            circuit.opened_until = now + self.cooldown_seconds
            circuit.probe_in_flight = False
            circuit.probe_started_at = 0.0
        elif circuit.failures >= self.failure_threshold:
            circuit.opened_until = now + self.cooldown_seconds
            ai_metrics.limit_event(provider_id, "circuit_opened")

    def reset_provider(self, provider_id: str) -> None:
        """Forget circuit failures after an operator changes Provider config."""
        self._circuits.pop(str(provider_id), None)


ai_limits = AILimitManager()
