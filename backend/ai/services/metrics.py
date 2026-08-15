"""Low-cardinality in-process AI operational metrics.

Only counters and timings are retained. Prompts, provider bodies, credentials
and tool payloads never enter this object.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from threading import Lock
from typing import Any


class AIMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.requests = Counter()
        self.requests_by_scene = Counter()
        self.latencies_ms: defaultdict[str, list[int]] = defaultdict(list)
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
            return {
                "requests": dict(self.requests),
                "by_scene": by_scene,
                "tools": dict(self.tools),
                "agents": dict(self.agents),
                "cache": {"hits": 0, "misses": 0, "note": "No provider-side prompt cache is enabled by default."},
            }


ai_metrics = AIMetrics()
