"""Low-cardinality in-process AI operational metrics.

Only counters and timings are retained. Prompts, provider bodies, credentials
and tool payloads never enter this object.
"""

from __future__ import annotations

from copy import deepcopy
from collections import Counter, defaultdict
from threading import Lock
from typing import Any


_JOB_EVENT_ALLOWLIST = frozenset({
    "enqueued", "claimed", "succeeded", "failed", "retry_scheduled",
    "retry_created", "lease_acquired", "lease_held", "lease_lost",
    "lease_expired", "lease_error", "document_failed",
})


class AIMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests = Counter()
        self.requests_by_scene = Counter()
        self.latencies_ms: defaultdict[str, list[int]] = defaultdict(list)
        self.provider_requests = Counter()
        self.provider_status = Counter()
        self.provider_latencies_ms: defaultdict[str, list[int]] = defaultdict(list)
        self.provider_tokens: defaultdict[str, Counter] = defaultdict(Counter)
        self.provider_costs: defaultdict[str, float] = defaultdict(float)
        self.provider_limits = Counter()
        self.fallbacks = Counter()
        self.intent = Counter()
        self.retrieval = Counter()
        self.clarification = Counter()
        # Import/Reindex operational signals intentionally contain only
        # low-cardinality event names and aggregate queue gauges.  Job IDs,
        # tenant IDs, worker IDs and error bodies never enter this object.
        self.job_events = Counter()
        self.job_queues: dict[str, dict[str, Any]] = {}
        self.tools = Counter()
        self.agents = Counter()

    def request_started(self, scene: str) -> None:
        with self._lock:
            self.requests["started"] += 1
            self.requests_by_scene[str(scene or "unknown")] += 1

    def request_finished(self, scene: str, *, status: str, latency_ms: int = 0) -> None:
        with self._lock:
            self.requests[str(status or "unknown")] += 1
            self.latencies_ms[str(scene or "unknown")].append(max(0, int(latency_ms or 0)))

    @staticmethod
    def _provider_key(provider_id: str | None, model_id: str | None) -> str:
        provider = str(provider_id or "unknown")[:96]
        model = str(model_id or "unknown")[:128]
        return f"{provider}:{model}"

    def provider_finished(
        self,
        provider_id: str | None,
        model_id: str | None,
        *,
        status: str,
        latency_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: float = 0.0,
        error_code: str | None = None,
    ) -> None:
        """Record bounded provider outcome metrics without payload data."""

        if not provider_id:
            return
        key = self._provider_key(provider_id, model_id)
        normalized_status = str(status or "unknown")[:32]
        with self._lock:
            self.provider_requests[key] += 1
            self.provider_status[f"{key}:{normalized_status}"] += 1
            values = self.provider_latencies_ms[key]
            values.append(max(0, int(latency_ms or 0)))
            if len(values) > 1000:
                del values[:-1000]
            tokens = self.provider_tokens[key]
            tokens["input"] += max(0, int(input_tokens or 0))
            tokens["output"] += max(0, int(output_tokens or 0))
            self.provider_costs[key] += max(0.0, float(estimated_cost or 0.0))
            code = str(error_code or "")[:64]
            if code in {"AI_RATE_LIMIT", "AI_QUOTA_EXCEEDED", "AI_PROVIDER_CIRCUIT_OPEN"}:
                self.provider_limits[f"{provider_id}:{code}"] += 1

    def provider_cost(self, provider_id: str | None, model_id: str | None, amount: float) -> None:
        if not provider_id:
            return
        key = self._provider_key(provider_id, model_id)
        with self._lock:
            self.provider_costs[key] += max(0.0, float(amount or 0.0))

    def limit_event(self, provider_id: str | None, kind: str) -> None:
        if not provider_id:
            return
        with self._lock:
            self.provider_limits[f"{str(provider_id)[:96]}:{str(kind or 'unknown')[:48]}"] += 1

    def fallback_event(self, scene: str, primary_provider_id: str | None, fallback_model_id: str | None, *, status: str) -> None:
        key = f"{str(scene or 'unknown')[:64]}:{str(primary_provider_id or 'unknown')[:96]}:{str(fallback_model_id or 'unknown')[:128]}:{str(status or 'unknown')[:24]}"
        with self._lock:
            self.fallbacks[key] += 1

    def intent_observed(self, status: str, intent: str | None = None) -> None:
        """Record low-cardinality intent parser outcomes without payloads."""

        allowed_statuses = {
            "deterministic",
            "llm_success",
            "schema_retry_started",
            "schema_retry_succeeded",
            "schema_retry_failed",
            "provider_error",
        }
        normalized_status = str(status or "unknown").strip().lower()
        if normalized_status not in allowed_statuses:
            normalized_status = "unknown"
        normalized_intent = str(intent or "unknown").strip().lower()
        if normalized_intent not in {
            "asset_analysis", "device_search", "ip_location", "mac_location",
            "alarm_search", "config_search", "troubleshooting", "general_qa",
            "knowledge", "unknown",
        }:
            normalized_intent = "unknown"
        with self._lock:
            self.intent[f"{normalized_status}:{normalized_intent}"] += 1

    def retrieval_observed(
        self,
        *,
        no_match: bool = False,
        wrong_vendor: bool = False,
        version_conflict: bool = False,
        low_confidence: bool = False,
        error: bool = False,
    ) -> None:
        """Record bounded retrieval quality signals, never query contents."""

        with self._lock:
            self.retrieval["queries"] += 1
            for name, active in (
                ("no_match", no_match),
                ("wrong_vendor", wrong_vendor),
                ("version_conflict", version_conflict),
                ("low_confidence", low_confidence),
                ("errors", error),
            ):
                if active:
                    self.retrieval[name] += 1

    def clarification_observed(self, status: str, request_kind: str | None = None) -> None:
        """Record low-cardinality configuration-scope guard outcomes."""

        normalized_status = str(status or "unknown").strip().lower()
        if normalized_status not in {"required", "allowed", "disabled"}:
            normalized_status = "unknown"
        normalized_kind = str(request_kind or "none").strip().lower()
        if normalized_kind not in {
            "configuration_reference",
            "configuration_change",
            "running_config_export",
            "read_only_command",
            "none",
        }:
            normalized_kind = "unknown"
        with self._lock:
            self.clarification[f"{normalized_status}:{normalized_kind}"] += 1

    def job_event(self, job_kind: str, event: str) -> None:
        """Record one bounded Import/Reindex lifecycle event.

        ``job_kind`` and ``event`` are labels only; callers must not pass job
        identifiers or exception text.  Keeping this contract here makes it
        safe for the gateway metrics endpoint to expose the counters.
        """

        kind = str(job_kind or "unknown").strip().lower()[:24]
        name = str(event or "unknown").strip().lower()[:48]
        if kind not in {"import", "reindex"}:
            kind = "unknown"
        if name not in _JOB_EVENT_ALLOWLIST:
            name = "unknown"
        with self._lock:
            self.job_events[f"{kind}:{name}"] += 1

    def set_job_queue_snapshot(self, job_kind: str, snapshot: dict[str, Any]) -> None:
        """Store an aggregate queue gauge for the next metrics response.

        Only the documented numeric gauge fields are copied.  This prevents a
        future caller from accidentally putting IDs, SQL or error details into
        the low-cardinality metrics payload.
        """

        kind = str(job_kind or "unknown").strip().lower()[:24]
        if kind not in {"import", "reindex"}:
            return
        allowed = {
            "queued", "retry_wait", "running", "succeeded", "completed",
            "failed", "cancelled", "backlog", "lease_anomalies",
            "lease_expired", "document_failures",
        }
        safe: dict[str, int] = {}
        for key in allowed:
            try:
                safe[key] = max(0, int(snapshot.get(key, 0) or 0))
            except (TypeError, ValueError):
                safe[key] = 0
        with self._lock:
            self.job_queues[kind] = safe

    def _job_snapshot(self) -> dict[str, Any]:
        return {
            "events": dict(self.job_events),
            "queues": deepcopy(self.job_queues),
        }

    def tool_finished(self, name: str, *, status: str) -> None:
        with self._lock:
            self.tools[f"{name}:{status}"] += 1

    def agent_finished(self, status: str) -> None:
        with self._lock:
            self.agents[str(status or "unknown")] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            by_scene = {}
            for scene, values in self.latencies_ms.items():
                ordered = sorted(values)
                p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
                by_scene[scene] = {
                    "requests": int(self.requests_by_scene.get(scene, 0)),
                    "avg_latency_ms": round(sum(values) / len(values), 2) if values else 0,
                    "p95_latency_ms": ordered[p95_index] if ordered else 0,
                }
            providers = {}
            for key, request_count in self.provider_requests.items():
                values = sorted(self.provider_latencies_ms.get(key, []))
                p95_index = min(len(values) - 1, max(0, int(len(values) * 0.95) - 1)) if values else 0
                success_count = int(self.provider_status.get(f"{key}:success", 0))
                error_count = max(0, int(request_count) - success_count)
                tokens = self.provider_tokens.get(key, {})
                providers[key] = {
                    "requests": int(request_count),
                    "success": success_count,
                    "errors": error_count,
                    "error_rate": round(error_count / request_count, 4) if request_count else 0,
                    "avg_latency_ms": round(sum(values) / len(values), 2) if values else 0,
                    "p95_latency_ms": values[p95_index] if values else 0,
                    "input_tokens": int(tokens.get("input", 0)),
                    "output_tokens": int(tokens.get("output", 0)),
                    "estimated_cost_usd": round(self.provider_costs.get(key, 0.0), 6),
                }
            return {
                "requests": dict(self.requests),
                "by_scene": by_scene,
                "providers": providers,
                "limits": dict(self.provider_limits),
                "fallbacks": dict(self.fallbacks),
                "intent": dict(self.intent),
                "retrieval": {
                    "queries": int(self.retrieval.get("queries", 0)),
                    "no_match": int(self.retrieval.get("no_match", 0)),
                    "no_match_rate": round(self.retrieval.get("no_match", 0) / self.retrieval.get("queries", 1), 4) if self.retrieval.get("queries") else 0,
                    "wrong_vendor": int(self.retrieval.get("wrong_vendor", 0)),
                    "version_conflict": int(self.retrieval.get("version_conflict", 0)),
                    "low_confidence": int(self.retrieval.get("low_confidence", 0)),
                    "errors": int(self.retrieval.get("errors", 0)),
                },
                "clarification": dict(self.clarification),
                "jobs": self._job_snapshot(),
                "tools": dict(self.tools),
                "agents": dict(self.agents),
                "cache": {"hits": 0, "misses": 0, "note": "No provider-side prompt cache is enabled by default."},
            }


ai_metrics = AIMetrics()
