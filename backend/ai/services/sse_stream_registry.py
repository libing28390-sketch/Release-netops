"""Bounded in-process replay and idempotency state for Copilot SSE streams.

The durable conversation/task boundary is handled by the later API-008/009
work.  API-007 only needs a short-lived transport window: reconnecting with
the same tenant/user/request fingerprint replays events after ``last_event_id``
and never appends the same token or assistant message twice.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


MAX_STREAMS = 256
MAX_EVENTS = 4096
MAX_EVENT_BYTES = 2 * 1024 * 1024
STREAM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
EVENT_ID_RE = re.compile(r"^id:\s*([^:]+):(\d+)\s*$", re.MULTILINE)


class SSEStreamConflict(ValueError):
    """Raised when a stream id is reused outside its tenant/user/request."""

    code = "SSE_STREAM_CONFLICT"


class SSEStreamReplayExpired(ValueError):
    """Raised when the requested event is older than the bounded replay window."""

    code = "SSE_REPLAY_WINDOW_EXPIRED"


def request_fingerprint(payload: dict[str, Any]) -> str:
    """Hash only the normalized request shape; never store its raw text."""

    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def split_sse_events(chunk: str) -> list[str]:
    """Split a generator chunk that may contain meta plus citation events."""

    return [part.strip() for part in str(chunk or "").split("\n\n") if part.strip()]


def event_sequence(event: str) -> tuple[str, int] | None:
    match = EVENT_ID_RE.search(str(event or ""))
    if not match:
        return None
    return match.group(1), int(match.group(2))


def event_payload(event: str) -> dict[str, Any]:
    for line in str(event or "").splitlines():
        if line.startswith("data:"):
            try:
                decoded = json.loads(line.split(":", 1)[1].strip())
            except (TypeError, ValueError):
                return {}
            return decoded if isinstance(decoded, dict) else {}
    return {}


def event_type(event: str) -> str | None:
    for line in str(event or "").splitlines():
        if line.startswith("event:"):
            return line.split(":", 1)[1].strip() or None
    return None


@dataclass
class SSEStreamState:
    stream_id: str
    tenant_id: str
    user_id: str
    fingerprint: str
    events: dict[int, str] = field(default_factory=dict)
    event_bytes: int = 0
    replay_floor: int = 1
    active: bool = True
    completed: bool = False
    user_message_persisted: bool = False
    assistant_message_persisted: bool = False
    assistant_content: str = ""
    last_activity: float = field(default_factory=time.monotonic)

    @property
    def last_event_id(self) -> int:
        return max(self.events, default=0)


class SSEStreamRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._streams: dict[str, SSEStreamState] = {}

    def open(
        self,
        *,
        stream_id: str | None,
        tenant_id: str,
        user_id: str,
        fingerprint: str,
        last_event_id: int = 0,
    ) -> SSEStreamState:
        requested = str(stream_id or "").strip() or f"sse_{uuid.uuid4().hex}"
        if not STREAM_ID_RE.fullmatch(requested):
            raise SSEStreamConflict("stream_id is invalid")
        with self._lock:
            existing = self._streams.get(requested)
            if existing is not None:
                if (existing.tenant_id, existing.user_id, existing.fingerprint) != (tenant_id, user_id, fingerprint):
                    raise SSEStreamConflict("stream_id is bound to another request scope")
                if existing.active:
                    raise SSEStreamConflict("stream is already active")
                if last_event_id < existing.replay_floor - 1:
                    raise SSEStreamReplayExpired("requested event is outside the replay window")
                existing.active = True
                existing.last_activity = time.monotonic()
                return existing
            if last_event_id:
                raise SSEStreamReplayExpired("stream replay state is unavailable")
            if len(self._streams) >= MAX_STREAMS:
                oldest = min(self._streams.values(), key=lambda item: item.last_activity)
                self._streams.pop(oldest.stream_id, None)
            state = SSEStreamState(
                stream_id=requested,
                tenant_id=str(tenant_id or "tenant-default"),
                user_id=str(user_id or "anonymous"),
                fingerprint=fingerprint,
            )
            self._streams[requested] = state
            return state

    def record(self, state: SSEStreamState, event: str) -> bool:
        """Store a new sequence once and return whether it should be delivered."""

        identity = event_sequence(event)
        if identity is None:
            return True
        stream_id, sequence = identity
        if stream_id != state.stream_id:
            raise SSEStreamConflict("event stream_id mismatch")
        payload = event_payload(event)
        with self._lock:
            state.last_activity = time.monotonic()
            if sequence in state.events:
                return False
            state.events[sequence] = event
            state.event_bytes += len(event.encode("utf-8"))
            if event_type(event) == "token":
                # Only token events become the persisted assistant answer;
                # progress/detail payloads must never be concatenated.
                state.assistant_content += str(payload.get("content") or "")
            while len(state.events) > MAX_EVENTS or state.event_bytes > MAX_EVENT_BYTES:
                oldest = min(state.events)
                removed = state.events.pop(oldest)
                state.event_bytes -= len(removed.encode("utf-8"))
                state.replay_floor = oldest + 1
            return True

    def replay(self, state: SSEStreamState, *, after: int = 0) -> list[str]:
        with self._lock:
            if after < state.replay_floor - 1:
                raise SSEStreamReplayExpired("requested event is outside the replay window")
            return [state.events[key] for key in sorted(state.events) if key > after]

    def complete(self, state: SSEStreamState) -> None:
        with self._lock:
            state.completed = True
            state.active = False
            state.last_activity = time.monotonic()

    def close(self, state: SSEStreamState) -> None:
        with self._lock:
            state.active = False
            state.last_activity = time.monotonic()

    def clear(self) -> None:
        with self._lock:
            self._streams.clear()


sse_stream_registry = SSEStreamRegistry()


__all__ = [
    "MAX_EVENTS", "MAX_EVENT_BYTES", "SSEStreamConflict", "SSEStreamReplayExpired",
    "SSEStreamState", "SSEStreamRegistry", "event_payload", "event_sequence",
    "event_type", "request_fingerprint", "split_sse_events", "sse_stream_registry",
]
