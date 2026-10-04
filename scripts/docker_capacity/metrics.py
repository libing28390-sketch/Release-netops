"""Docker and host metrics collection for the bounded capacity runner.

The capacity runner deliberately keeps this module independent from Docker's
Python SDK.  Docker Engine is queried through its Unix socket, while the
small amount of runtime state that is not present in ``/stats`` is obtained
from the read-only ``docker inspect`` and ``docker events`` commands.

The collector is intentionally conservative about missing data: an absent
counter is represented by an empty CSV field/``None`` and is recorded in
``missing_metrics``.  In particular, the memory limit reported by the
Engine's stats endpoint is not used as a configured container limit because
the Engine commonly reports the host memory there for unlimited containers.
"""

from __future__ import annotations

import csv
import datetime as _datetime
import http.client
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Optional
from urllib.parse import quote


# Tests may replace this with a temporary directory.  Keeping it as a module
# constant also makes the collector behave predictably on Windows, where the
# normal /proc files are unavailable.
PROC_ROOT = Path("/proc")

STATS_TIMEOUT_SECONDS = 4.0
INSPECT_INTERVAL_SECONDS = 10.0

CONTAINER_CSV_COLUMNS = [
    "timestamp_utc",
    "phase",
    "container",
    "service",
    "role",
    "cpu_percent",
    "cpu_limit_cores",
    "cpu_limit_percent",
    "memory_usage_bytes",
    "memory_working_set_bytes",
    "memory_limit_bytes",
    "memory_percent",
    "net_rx_bytes",
    "net_tx_bytes",
    "net_rx_bytes_per_second",
    "net_tx_bytes_per_second",
    "block_read_bytes",
    "block_write_bytes",
    "block_read_bytes_per_second",
    "block_write_bytes_per_second",
    "pids",
    "cpu_throttled_periods_delta",
    "cpu_periods_delta",
    "cpu_throttled_ratio_percent",
    "cpu_throttled_seconds_delta",
    "oom_killed",
    "restart_count",
    "status",
    "error",
]

HOST_CSV_COLUMNS = [
    "timestamp_utc",
    "phase",
    "available_bytes",
    "total_bytes",
    "available_percent",
    "swap_total_bytes",
    "swap_free_bytes",
    "cpu_busy_seconds",
    "cpu_iowait_seconds",
    "cpu_busy_delta_seconds",
    "cpu_iowait_delta_seconds",
    "load_1m",
    "load_5m",
    "load_15m",
    "disk_free_bytes",
    "disk_total_bytes",
    "status",
    "error",
]


class _DockerHTTPError(RuntimeError):
    """An HTTP error returned by the Docker Engine socket."""

    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self.body = body
        super().__init__(f"docker HTTP {status}")


class _UnixHTTPConnection(http.client.HTTPConnection):
    """Small ``HTTPConnection`` adapter that connects to an AF_UNIX socket."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:  # pragma: no cover - the socket is exercised by integration users
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
        except Exception:
            sock.close()
            raise
        self.sock = sock


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _utc_since_arg() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            return float(value)
        return None
    if isinstance(value, str):
        try:
            result = float(value.strip())
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None
    return None


def _integer(value: Any, default: Optional[int] = None) -> Optional[int]:
    number = _number(value)
    if number is None:
        return default
    try:
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return default


def _positive_float(value: Any) -> Optional[float]:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _nested(mapping: Any, *keys: str) -> Any:
    current = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _nonnegative_delta(current: Optional[float], previous: Optional[float], reset: bool = False) -> Optional[float]:
    if current is None or previous is None or reset:
        return None
    delta = current - previous
    return delta if delta >= 0 else None


def _rate(current: Optional[float], previous: Optional[float], elapsed: Optional[float], reset: bool = False) -> Optional[float]:
    if elapsed is None or elapsed <= 0:
        return None
    delta = _nonnegative_delta(current, previous, reset=reset)
    return delta / elapsed if delta is not None else None


def _working_set(memory_stats: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """Return raw usage and cache-deducted working set in bytes."""

    usage = _number(memory_stats.get("usage"))
    if usage is None:
        return None, None
    cache = _number(memory_stats.get("cache"))
    if cache is None:
        nested_stats = memory_stats.get("stats")
        if isinstance(nested_stats, Mapping):
            cache = _number(nested_stats.get("cache"))
            if cache is None:
                cache = _number(nested_stats.get("inactive_file"))
            if cache is None:
                cache = _number(nested_stats.get("total_inactive_file"))
    if cache is None:
        # cgroup v2/Docker versions may expose inactive_file instead of cache.
        cache = _number(memory_stats.get("inactive_file"))
    if cache is None:
        cache = _number(memory_stats.get("total_inactive_file"))
    if cache is None:
        return usage, usage
    return usage, max(0.0, usage - max(0.0, cache))


def _sum_networks(networks: Any) -> tuple[Optional[float], Optional[float]]:
    if not isinstance(networks, Mapping):
        return None, None
    rx = 0.0
    tx = 0.0
    rx_found = False
    tx_found = False
    for network in networks.values():
        if not isinstance(network, Mapping):
            continue
        value = _number(network.get("rx_bytes"))
        if value is not None:
            rx += max(0.0, value)
            rx_found = True
        value = _number(network.get("tx_bytes"))
        if value is not None:
            tx += max(0.0, value)
            tx_found = True
    return (rx if rx_found else None, tx if tx_found else None)


def _sum_block_io(block_stats: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    entries = block_stats.get("io_service_bytes_recursive")
    if entries is None:
        entries = block_stats.get("io_service_bytes")
    if not isinstance(entries, list):
        return None, None
    read = 0.0
    write = 0.0
    read_found = False
    write_found = False
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        op = str(item.get("op") or "").strip().lower()
        value = _number(item.get("value"))
        if value is None:
            continue
        if op == "read":
            read += max(0.0, value)
            read_found = True
        elif op == "write":
            write += max(0.0, value)
            write_found = True
    return (read if read_found else None, write if write_found else None)


def _sanitize_stats(value: Any) -> Any:
    """Copy stats while dropping fields that could carry environment secrets."""

    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            if str(key).lower() in {"env", "environment", "config"}:
                continue
            result[str(key)] = _sanitize_stats(child)
        return result
    if isinstance(value, list):
        return [_sanitize_stats(child) for child in value]
    return value


def _stable_error(error: Any) -> str:
    if isinstance(error, _DockerHTTPError):
        return f"docker_http_{error.status}"
    if isinstance(error, subprocess.TimeoutExpired):
        return "command_timeout"
    if isinstance(error, OSError):
        return f"{type(error).__name__}: {str(error).splitlines()[0][:180]}"
    text = str(error).splitlines()[0] if str(error) else type(error).__name__
    return f"{type(error).__name__}: {text[:200]}"


class MetricsCollector:
    """Collect Docker container and host metrics into durable CSV/JSONL files."""

    def __init__(
        self,
        containers: dict[str, dict],
        output_dir: Path,
        interval: float = 2.0,
        socket_path: str = "/var/run/docker.sock",
        stop_callback: Optional[Callable[[str], None]] = None,
        min_host_available_bytes: int = 256 * 1024**2,
        min_host_available_percent: float = 10.0,
        max_container_memory_percent: float = 95.0,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.interval = max(0.05, float(interval))
        self.socket_path = str(socket_path)
        self.stop_callback = stop_callback
        self.min_host_available_bytes = max(0, int(min_host_available_bytes))
        self.min_host_available_percent = float(min_host_available_percent)
        self.max_container_memory_percent = float(max_container_memory_percent)

        self._lock = threading.RLock()
        self._containers: dict[str, dict[str, Any]] = {}
        self._states: dict[str, dict[str, Any]] = {}
        for container_id, metadata in (containers or {}).items():
            self._register_container_locked(str(container_id), metadata or {})

        self._phase = "init"
        self._stop_event = threading.Event()
        self._running = False
        self._sample_thread: Optional[threading.Thread] = None
        self._host_thread: Optional[threading.Thread] = None
        self._inspect_thread: Optional[threading.Thread] = None
        self._event_thread: Optional[threading.Thread] = None
        self._event_process: Optional[subprocess.Popen[str]] = None
        self._start_utc = ""

        self._container_file: Any = None
        self._container_writer: Any = None
        self._raw_file: Any = None
        self._host_file: Any = None
        self._host_writer: Any = None

        self._missing_metrics: list[str] = []
        self._stop_reasons: list[str] = []
        self._callback_reasons: set[str] = set()
        self._host_previous: Optional[dict[str, float]] = None
        self._host_summary: dict[str, Any] = {
            "samples": 0,
            "available_values": [],
            "available_percent_values": [],
            "swap_free_values": [],
            "disk_free_values": [],
            "load_1m_values": [],
            "load_5m_values": [],
            "load_15m_values": [],
            "cpu_busy_seconds": 0.0,
            "cpu_iowait_seconds": 0.0,
            "errors": [],
        }

    # ------------------------------------------------------------------
    # Lifecycle and registration
    # ------------------------------------------------------------------
    def _normalise_metadata(self, container_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
        memory_limit = _integer(metadata.get("memory_limit_bytes"), 0)
        if memory_limit is None or memory_limit < 0:
            memory_limit = 0
        initial_restart = _integer(metadata.get("initial_restart_count"), 0)
        if initial_restart is None or initial_restart < 0:
            initial_restart = 0
        initial_oom = bool(_bool(metadata.get("initial_oom_killed"), False))
        role = str(metadata.get("role") or "source")
        if role not in {"lab", "source", "generator"}:
            role = "source"
        return {
            "name": str(metadata.get("name") or container_id),
            "service": str(metadata.get("service") or metadata.get("name") or container_id),
            "role": role,
            "status": str(metadata.get("status") or "unknown"),
            "memory_limit_bytes": memory_limit,
            "cpu_limit_cores": _positive_float(metadata.get("cpu_limit_cores")),
            "initial_restart_count": initial_restart,
            "initial_oom_killed": initial_oom,
        }

    def _new_state(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        initial_restart = int(metadata.get("initial_restart_count") or 0)
        initial_oom = bool(metadata.get("initial_oom_killed"))
        return {
            "current_restart_count": initial_restart,
            "current_oom_killed": initial_oom,
            "status": str(metadata.get("status") or "unknown"),
            "runtime_seen": False,
            "running_sample_count": 0,
            "oom_seen": initial_oom,
            "oom_events": 0,
            "event_restart_count": 0,
            "last_sample_mono": None,
            "last_sample_restart_count": None,
            # Docker's one-shot stats response commonly omits ``precpu_stats``.
            # Keep the current counters from the previous response so CPU can
            # be calculated from adjacent samples instead of depending on the
            # daemon's optional embedded baseline.
            "last_cpu_total": None,
            "last_cpu_system": None,
            "cpu_unavailable_streak": 0,
            "last_net_rx": None,
            "last_net_tx": None,
            "last_block_read": None,
            "last_block_write": None,
            "last_throttled_periods": None,
            "last_periods": None,
            "last_throttled_time": None,
            "last_sample_phase": None,
            "phases": {},
            "samples": 0,
            "errors": [],
        }

    def _register_container_locked(self, container_id: str, metadata: Mapping[str, Any]) -> None:
        normalised = self._normalise_metadata(container_id, metadata)
        if container_id in self._containers:
            self._containers[container_id].update(normalised)
            return
        self._containers[container_id] = normalised
        self._states[container_id] = self._new_state(normalised)

    def add_container(self, container_id: str, metadata: dict) -> None:
        """Register a dynamically created runner/container for future samples."""

        with self._lock:
            self._register_container_locked(str(container_id), metadata or {})

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = str(phase or "unknown")

    def _ensure_output_files_locked(self) -> None:
        if self._container_file is not None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        container_path = self.output_dir / "container-stats.csv"
        host_path = self.output_dir / "host-stats.csv"
        raw_path = self.output_dir / "rawstats.jsonl"

        container_exists = container_path.exists() and container_path.stat().st_size > 0
        host_exists = host_path.exists() and host_path.stat().st_size > 0
        self._container_file = container_path.open("a", encoding="utf-8", newline="")
        self._container_writer = csv.DictWriter(self._container_file, fieldnames=CONTAINER_CSV_COLUMNS, extrasaction="ignore")
        if not container_exists:
            self._container_writer.writeheader()
        self._raw_file = raw_path.open("a", encoding="utf-8")
        self._host_file = host_path.open("a", encoding="utf-8", newline="")
        self._host_writer = csv.DictWriter(self._host_file, fieldnames=HOST_CSV_COLUMNS, extrasaction="ignore")
        if not host_exists:
            self._host_writer.writeheader()
        self._container_file.flush()
        self._host_file.flush()

    def start(self) -> "MetricsCollector":
        with self._lock:
            if self._running:
                return self
            self._ensure_output_files_locked()
            self._stop_event.clear()
            self._start_utc = _utc_since_arg()
            self._running = True

        self._start_events_reader()
        self._sample_thread = threading.Thread(target=self._sample_loop, name="capacity-container-metrics", daemon=True)
        self._host_thread = threading.Thread(target=self._host_loop, name="capacity-host-metrics", daemon=True)
        self._inspect_thread = threading.Thread(target=self._inspect_loop, name="capacity-container-inspect", daemon=True)
        self._sample_thread.start()
        self._host_thread.start()
        self._inspect_thread.start()
        return self

    def stop(self) -> None:
        """Stop background work and close outputs, bounded to a short grace period."""

        with self._lock:
            self._running = False
            self._stop_event.set()
            process = self._event_process
            self._event_process = None
        if process is not None:
            try:
                process.terminate()
            except Exception:
                pass
            try:
                process.wait(timeout=1.5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        deadline = time.monotonic() + 8.5
        threads = [self._sample_thread, self._host_thread, self._inspect_thread, self._event_thread]
        for thread in threads:
            if thread is None or thread is threading.current_thread():
                continue
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                break
            thread.join(timeout=min(remaining, 2.5))

        with self._lock:
            for handle_name in ("_container_file", "_raw_file", "_host_file"):
                handle = getattr(self, handle_name)
                if handle is not None:
                    try:
                        handle.flush()
                        handle.close()
                    except Exception:
                        pass
                    setattr(self, handle_name, None)
            self._container_writer = None
            self._host_writer = None

    # ------------------------------------------------------------------
    # Docker Engine stats and sampling
    # ------------------------------------------------------------------
    def _docker_get_json(self, path: str) -> Any:
        connection = _UnixHTTPConnection(self.socket_path, timeout=STATS_TIMEOUT_SECONDS)
        try:
            connection.request("GET", path, headers={"Host": "localhost", "Connection": "close"})
            response = connection.getresponse()
            body = response.read()
            if response.status >= 400:
                raise _DockerHTTPError(response.status, body.decode("utf-8", errors="replace")[:200])
            if not body:
                raise RuntimeError("empty docker response")
            return json.loads(body.decode("utf-8"))
        finally:
            connection.close()

    def _fetch_stats(self, container_id: str) -> Mapping[str, Any]:
        encoded = quote(container_id, safe="")
        primary = f"/containers/{encoded}/stats?stream=false&one-shot=true"
        fallback = f"/containers/{encoded}/stats?stream=false"
        try:
            result = self._docker_get_json(primary)
            if not isinstance(result, Mapping):
                raise RuntimeError("docker stats response is not an object")
            return result
        except Exception as first_error:
            try:
                result = self._docker_get_json(fallback)
                if not isinstance(result, Mapping):
                    raise RuntimeError("docker stats response is not an object")
                return result
            except Exception as second_error:
                raise RuntimeError(f"stats unavailable ({_stable_error(first_error)}; {_stable_error(second_error)})") from second_error

    def _cpu_online(self, stats: Mapping[str, Any]) -> float:
        online = _number(_nested(stats, "cpu_stats", "online_cpus"))
        if online is None or online <= 0:
            per_cpu = _nested(stats, "cpu_stats", "cpu_usage", "percpu_usage")
            online = float(len(per_cpu)) if isinstance(per_cpu, list) and per_cpu else float(os.cpu_count() or 1)
        return online

    def _cpu_values(self, stats: Mapping[str, Any]) -> tuple[Optional[float], Optional[float], Optional[float]]:
        current_total = _number(_nested(stats, "cpu_stats", "cpu_usage", "total_usage"))
        previous_total = _number(_nested(stats, "precpu_stats", "cpu_usage", "total_usage"))
        current_system = _number(_nested(stats, "cpu_stats", "system_cpu_usage"))
        previous_system = _number(_nested(stats, "precpu_stats", "system_cpu_usage"))
        online = self._cpu_online(stats)
        total_delta = _nonnegative_delta(current_total, previous_total)
        system_delta = _nonnegative_delta(current_system, previous_system)
        if total_delta is None or system_delta is None or system_delta <= 0:
            return None, current_total, current_system
        return total_delta / system_delta * online * 100.0, current_total, current_system

    def _throttle_values(self, stats: Mapping[str, Any]) -> tuple[Optional[float], Optional[float], Optional[float]]:
        throttling = _nested(stats, "cpu_stats", "throttling_data")
        if not isinstance(throttling, Mapping):
            return None, None, None
        return (
            _number(throttling.get("throttled_periods")),
            _number(throttling.get("periods")),
            _number(throttling.get("throttled_time")),
        )

    def _record_raw_locked(self, container_id: str, metadata: Mapping[str, Any], stats: Mapping[str, Any]) -> None:
        self._ensure_output_files_locked()
        payload = {
            "timestamp_utc": _utc_now(),
            "phase": self._phase,
            "container": metadata.get("name", container_id),
            "container_id": container_id,
            "stats": _sanitize_stats(stats),
        }
        self._raw_file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._raw_file.flush()

    def _csv_value(self, value: Any) -> Any:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            if not math.isfinite(value):
                return ""
            return round(value, 6)
        return value if value is not None else ""

    def _record_aggregate_locked(self, state: dict[str, Any], row: Mapping[str, Any]) -> None:
        state["samples"] += 1
        if row.get("error"):
            error = str(row["error"])
            if error not in state["errors"]:
                state["errors"].append(error)
        phase = str(row.get("phase") or "unknown")
        phase_state = state["phases"].setdefault(
            phase,
            {
                "samples": 0,
                "cpu_values": [],
                "memory_values": [],
                "working_set_values": [],
                "memory_percent_values": [],
                "cpu_throttled_periods": None,
                "cpu_periods": None,
                "cpu_throttled_seconds": None,
                "net_rx_values": [],
                "net_tx_values": [],
                "block_read_values": [],
                "block_write_values": [],
                "net_rx_delta_total": None,
                "net_tx_delta_total": None,
                "block_read_delta_total": None,
                "block_write_delta_total": None,
            },
        )
        phase_state["samples"] += 1
        for row_key, aggregate_key in (
            ("cpu_percent", "cpu_values"),
            ("memory_usage_bytes", "memory_values"),
            ("memory_working_set_bytes", "working_set_values"),
            ("memory_percent", "memory_percent_values"),
            ("net_rx_bytes", "net_rx_values"),
            ("net_tx_bytes", "net_tx_values"),
            ("block_read_bytes", "block_read_values"),
            ("block_write_bytes", "block_write_values"),
        ):
            value = _number(row.get(row_key))
            if value is not None:
                phase_state[aggregate_key].append(value)
        for row_key, aggregate_key in (
            ("cpu_throttled_periods_delta", "cpu_throttled_periods"),
            ("cpu_periods_delta", "cpu_periods"),
            ("cpu_throttled_seconds_delta", "cpu_throttled_seconds"),
        ):
            value = _number(row.get(row_key))
            if value is not None and value >= 0:
                if phase_state[aggregate_key] is None:
                    phase_state[aggregate_key] = 0.0
                phase_state[aggregate_key] += value
        for row_key, aggregate_key, counter_key in (
            ("_net_rx_phase_delta", "net_rx_delta_total", "net_rx_bytes"),
            ("_net_tx_phase_delta", "net_tx_delta_total", "net_tx_bytes"),
            ("_block_read_phase_delta", "block_read_delta_total", "block_read_bytes"),
            ("_block_write_phase_delta", "block_write_delta_total", "block_write_bytes"),
        ):
            counter = _number(row.get(counter_key))
            if counter is not None and phase_state[aggregate_key] is None:
                # A phase's first observation establishes its counter
                # baseline. It contributes zero bytes until a later sample
                # in the same phase supplies a non-negative delta.
                phase_state[aggregate_key] = 0.0
            delta = _number(row.get(row_key))
            if delta is not None and delta >= 0:
                if phase_state[aggregate_key] is None:
                    phase_state[aggregate_key] = 0.0
                phase_state[aggregate_key] += delta

    def _append_container_row_locked(self, row: dict[str, Any]) -> None:
        self._ensure_output_files_locked()
        self._container_writer.writerow({key: self._csv_value(row.get(key)) for key in CONTAINER_CSV_COLUMNS})
        self._container_file.flush()

    def _runtime_fields_locked(self, container_id: str) -> tuple[Optional[bool], Optional[int], str]:
        state = self._states[container_id]
        return state.get("current_oom_killed"), state.get("current_restart_count"), str(state.get("status") or "unknown")

    def _make_error_row_locked(self, container_id: str, error: Any) -> dict[str, Any]:
        metadata = self._containers[container_id]
        oom, restart_count, status = self._runtime_fields_locked(container_id)
        return {
            "timestamp_utc": _utc_now(),
            "phase": self._phase,
            "container": metadata["name"],
            "service": metadata["service"],
            "role": metadata["role"],
            "oom_killed": oom,
            "restart_count": restart_count,
            "status": status,
            "error": _stable_error(error),
        }

    def _record_stats_locked(self, container_id: str, stats: Mapping[str, Any], sample_mono: Optional[float] = None) -> dict[str, Any]:
        if container_id not in self._containers:
            self._register_container_locked(container_id, {})
        metadata = self._containers[container_id]
        state = self._states[container_id]
        now_mono = sample_mono if sample_mono is not None else time.monotonic()
        current_restart = state.get("current_restart_count")
        last_restart = state.get("last_sample_restart_count")
        reset_boundary = last_restart is not None and current_restart is not None and current_restart != last_restart
        elapsed = None
        if state.get("last_sample_mono") is not None and not reset_boundary:
            elapsed = now_mono - float(state["last_sample_mono"])

        if state.get("status") == "running":
            state["running_sample_count"] = int(state.get("running_sample_count") or 0) + 1
        else:
            state["running_sample_count"] = 0

        _embedded_cpu_percent, cpu_total, cpu_system = self._cpu_values(stats)
        last_cpu_total = _number(state.get("last_cpu_total"))
        last_cpu_system = _number(state.get("last_cpu_system"))
        cpu_counter_reset = (
            cpu_total is not None
            and last_cpu_total is not None
            and cpu_total < last_cpu_total
        ) or (
            cpu_system is not None
            and last_cpu_system is not None
            and cpu_system < last_cpu_system
        )
        cpu_percent = None
        if (
            not reset_boundary
            and not cpu_counter_reset
            and cpu_total is not None
            and cpu_system is not None
            and last_cpu_total is not None
            and last_cpu_system is not None
        ):
            cpu_total_delta = cpu_total - last_cpu_total
            cpu_system_delta = cpu_system - last_cpu_system
            if cpu_total_delta >= 0 and cpu_system_delta > 0:
                cpu_percent = cpu_total_delta / cpu_system_delta * self._cpu_online(stats) * 100.0
        cpu_limit = metadata.get("cpu_limit_cores")
        cpu_limit_percent = cpu_percent / (float(cpu_limit) * 100.0) * 100.0 if cpu_percent is not None and cpu_limit else None

        memory_stats = stats.get("memory_stats") if isinstance(stats.get("memory_stats"), Mapping) else {}
        memory_usage, memory_working_set = _working_set(memory_stats)
        memory_limit = int(metadata.get("memory_limit_bytes") or 0)
        memory_percent = memory_usage / memory_limit * 100.0 if memory_usage is not None and memory_limit > 0 else None

        net_rx, net_tx = _sum_networks(stats.get("networks"))
        block_read, block_write = _sum_block_io(stats.get("blkio_stats") if isinstance(stats.get("blkio_stats"), Mapping) else {})
        pids = _number(_nested(stats, "pids_stats", "current"))

        throttled_periods, periods, throttled_time = self._throttle_values(stats)
        throttled_periods_delta = _nonnegative_delta(throttled_periods, state.get("last_throttled_periods"), reset_boundary)
        periods_delta = _nonnegative_delta(periods, state.get("last_periods"), reset_boundary)
        throttled_time_delta = _nonnegative_delta(throttled_time, state.get("last_throttled_time"), reset_boundary)
        throttled_ratio = throttled_periods_delta / periods_delta * 100.0 if throttled_periods_delta is not None and periods_delta and periods_delta > 0 else None
        same_phase = state.get("last_sample_phase") == self._phase and not reset_boundary
        net_rx_phase_delta = _nonnegative_delta(net_rx, state.get("last_net_rx"), reset=not same_phase)
        net_tx_phase_delta = _nonnegative_delta(net_tx, state.get("last_net_tx"), reset=not same_phase)
        block_read_phase_delta = _nonnegative_delta(block_read, state.get("last_block_read"), reset=not same_phase)
        block_write_phase_delta = _nonnegative_delta(block_write, state.get("last_block_write"), reset=not same_phase)

        row = {
            "timestamp_utc": _utc_now(),
            "phase": self._phase,
            "container": metadata["name"],
            "service": metadata["service"],
            "role": metadata["role"],
            "cpu_percent": cpu_percent,
            "cpu_limit_cores": cpu_limit,
            "cpu_limit_percent": cpu_limit_percent,
            "memory_usage_bytes": memory_usage,
            "memory_working_set_bytes": memory_working_set,
            "memory_limit_bytes": memory_limit,
            "memory_percent": memory_percent,
            "net_rx_bytes": net_rx,
            "net_tx_bytes": net_tx,
            "net_rx_bytes_per_second": _rate(net_rx, state.get("last_net_rx"), elapsed, reset_boundary),
            "net_tx_bytes_per_second": _rate(net_tx, state.get("last_net_tx"), elapsed, reset_boundary),
            "block_read_bytes": block_read,
            "block_write_bytes": block_write,
            "block_read_bytes_per_second": _rate(block_read, state.get("last_block_read"), elapsed, reset_boundary),
            "block_write_bytes_per_second": _rate(block_write, state.get("last_block_write"), elapsed, reset_boundary),
            "pids": pids,
            "cpu_throttled_periods_delta": throttled_periods_delta,
            "cpu_periods_delta": periods_delta,
            "cpu_throttled_ratio_percent": throttled_ratio,
            "cpu_throttled_seconds_delta": throttled_time_delta / 1_000_000_000.0 if throttled_time_delta is not None else None,
            "oom_killed": state.get("current_oom_killed"),
            "restart_count": current_restart,
            "status": state.get("status") or "unknown",
            "error": None,
            "_net_rx_phase_delta": net_rx_phase_delta,
            "_net_tx_phase_delta": net_tx_phase_delta,
            "_block_read_phase_delta": block_read_phase_delta,
            "_block_write_phase_delta": block_write_phase_delta,
        }
        cpu_payload = stats.get("cpu_stats") if isinstance(stats.get("cpu_stats"), Mapping) else {}
        cpu_has_counters = (
            _number(_nested(cpu_payload, "cpu_usage", "total_usage")) is not None
            and _number(cpu_payload.get("system_cpu_usage")) is not None
        )
        if not cpu_has_counters:
            self._record_container_missing_locked(container_id, f"container:{container_id}:cpu")
            state["cpu_unavailable_streak"] = 0
        elif (
            cpu_percent is None
            and last_cpu_total is not None
            and last_cpu_system is not None
            and not reset_boundary
            and not cpu_counter_reset
        ):
            # A first sample, restart boundary, or counter reset establishes a
            # new baseline.  A repeated pair of counters without a positive
            # system delta is different: CPU has remained uncomputable during
            # stable running samples and should eventually be reported as
            # missing rather than silently looking healthy.
            state["cpu_unavailable_streak"] = int(state.get("cpu_unavailable_streak") or 0) + 1
            if state["cpu_unavailable_streak"] >= 2:
                self._record_container_missing_locked(container_id, f"container:{container_id}:cpu")
        else:
            state["cpu_unavailable_streak"] = 0
        if memory_usage is None:
            self._record_container_missing_locked(container_id, f"container:{container_id}:memory")
        if net_rx is None or net_tx is None:
            self._record_container_missing_locked(container_id, f"container:{container_id}:network")
        if block_read is None or block_write is None:
            self._record_container_missing_locked(container_id, f"container:{container_id}:block_io")
        if pids is None:
            self._record_container_missing_locked(container_id, f"container:{container_id}:pids")
        if throttled_periods is None or periods is None or throttled_time is None:
            self._record_container_missing_locked(container_id, f"container:{container_id}:cpu_throttling")
        self._record_raw_locked(container_id, metadata, stats)
        self._append_container_row_locked(row)
        self._record_aggregate_locked(state, row)

        # A missing counter resets its own baseline.  Carrying an old value
        # across a gap would turn the next sample into a fabricated rate.
        state["last_net_rx"] = net_rx
        state["last_net_tx"] = net_tx
        state["last_block_read"] = block_read
        state["last_block_write"] = block_write
        state["last_throttled_periods"] = throttled_periods
        state["last_periods"] = periods
        state["last_throttled_time"] = throttled_time
        # Do not carry a partial CPU baseline across a missing counter.  This
        # also makes the next complete response a clean first sample.
        if cpu_total is not None and cpu_system is not None:
            state["last_cpu_total"] = cpu_total
            state["last_cpu_system"] = cpu_system
        else:
            state["last_cpu_total"] = None
            state["last_cpu_system"] = None
        state["last_sample_mono"] = now_mono
        state["last_sample_restart_count"] = current_restart
        state["last_sample_phase"] = self._phase
        return row

    def record_stats(self, container_id: str, stats: Mapping[str, Any], sample_mono: Optional[float] = None) -> dict[str, Any]:
        """Record one already-decoded stats response (useful for unit tests)."""

        with self._lock:
            container_id = str(container_id)
            row = self._record_stats_locked(container_id, stats, sample_mono=sample_mono)
            metadata = self._containers[container_id]
            should_stop = metadata.get("role") == "lab" and row.get("memory_percent") is not None and row["memory_percent"] >= self.max_container_memory_percent
        if should_stop:
            self._request_stop(container_id, f"container_memory_percent_threshold:{container_id}")
        return row

    def _record_error_locked(self, container_id: str, error: Any) -> dict[str, Any]:
        if container_id not in self._containers:
            self._register_container_locked(container_id, {})
        if self._containers[container_id].get("role") == "generator":
            # A runner/helper is allowed to exit before its final stats call;
            # retaining the object for the final summary is not a metric
            # failure and should not add a synthetic error sample.
            return {}
        if self._states[container_id].get("status") != "running":
            # The container may have been registered between create and
            # start. Its stats endpoint is allowed to be absent during that
            # lifecycle window; wait for inspect to confirm running before
            # classifying a fetch failure as a real missing metric.
            return {}
        row = self._make_error_row_locked(container_id, error)
        self._append_container_row_locked(row)
        self._record_aggregate_locked(self._states[container_id], row)
        error_text = row["error"]
        if error_text not in self._states[container_id]["errors"]:
            self._states[container_id]["errors"].append(error_text)
        if self._states[container_id].get("status") == "running" and self._containers[container_id].get("role") != "generator":
            # A failed request is already a stable-runtime observation even
            # when no successful stats baseline exists yet.  Null fields in a
            # successful creation sample use the two-sample gate below.
            self._record_missing_locked(f"docker_stats:{container_id}")
        return row

    def _sample_container(self, container_id: str) -> None:
        try:
            stats = self._fetch_stats(container_id)
        except Exception as error:
            with self._lock:
                if container_id in self._containers:
                    self._record_error_locked(container_id, error)
            return
        with self._lock:
            if container_id not in self._containers:
                return
            row = self._record_stats_locked(container_id, stats)
            metadata = self._containers[container_id]
            memory_percent = row.get("memory_percent")
            should_stop = metadata.get("role") == "lab" and memory_percent is not None and memory_percent >= self.max_container_memory_percent
        if should_stop:
            self._request_stop(container_id, f"container_memory_percent_threshold:{container_id}")

    def _sample_all_once(self) -> None:
        with self._lock:
            container_ids = list(self._containers)
        if not container_ids:
            return
        workers: list[tuple[str, threading.Thread]] = []
        for container_id in container_ids:
            worker = threading.Thread(target=self._sample_container, args=(container_id,), daemon=True)
            workers.append((container_id, worker))
            worker.start()
        deadline = time.monotonic() + max(0.5, min(STATS_TIMEOUT_SECONDS * 2.5, self.interval + STATS_TIMEOUT_SECONDS))
        for _container_id, worker in workers:
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(timeout=remaining)

    def _sample_loop(self) -> None:
        while not self._stop_event.is_set():
            self._sample_all_once()
            self._stop_event.wait(self.interval)

    # ------------------------------------------------------------------
    # docker inspect/events and safety callbacks
    # ------------------------------------------------------------------
    def _record_missing_locked(self, metric: str) -> None:
        if metric not in self._missing_metrics:
            self._missing_metrics.append(metric)

    def _record_container_missing_locked(self, container_id: str, metric: str) -> None:
        # Helper/generator containers are intentionally short lived. Their
        # stats endpoint may disappear as soon as the runner exits; that is a
        # normal lifecycle event and must not make the whole stage incomplete.
        if self._containers.get(container_id, {}).get("role") == "generator":
            return
        state = self._states.get(container_id)
        if not state or state.get("status") != "running" or int(state.get("running_sample_count") or 0) < 2:
            return
        self._record_missing_locked(metric)

    def _record_missing(self, metric: str) -> None:
        with self._lock:
            self._record_missing_locked(metric)

    def _record_host_error_locked(self, error: Any) -> None:
        text = _stable_error(error)
        if text not in self._host_summary["errors"]:
            self._host_summary["errors"].append(text)

    def _request_stop(self, identifier: str, reason: str) -> None:
        with self._lock:
            if reason in self._callback_reasons:
                return
            self._callback_reasons.add(reason)
            if reason not in self._stop_reasons:
                self._stop_reasons.append(reason)
            callback = self.stop_callback
        if callback is None:
            return
        try:
            # The runner callback is a stop request sink; its argument is a
            # stable diagnostic reason rather than a Docker id.  The id is
            # already encoded in container-specific reasons where relevant.
            callback(reason)
        except Exception as error:
            with self._lock:
                self._record_host_error_locked(f"stop_callback:{_stable_error(error)}")

    def _inspect_once(self) -> None:
        with self._lock:
            container_ids = list(self._containers)
        if not container_ids:
            return
        try:
            result = subprocess.run(
                ["docker", "inspect", *container_ids],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception as error:
            self._record_missing("docker_inspect")
            with self._lock:
                self._record_host_error_locked(error)
            return
        if result.returncode != 0 or not result.stdout.strip():
            self._record_missing("docker_inspect")
            return
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError):
            self._record_missing("docker_inspect")
            return
        if isinstance(payload, Mapping):
            payload = [payload]
        if not isinstance(payload, list):
            self._record_missing("docker_inspect")
            return
        callbacks: list[tuple[str, str]] = []
        with self._lock:
            for item in payload:
                if not isinstance(item, Mapping):
                    continue
                actual_id = str(item.get("Id") or item.get("ID") or "")
                target_id = next((candidate for candidate in container_ids if candidate == actual_id or actual_id.startswith(candidate) or candidate.startswith(actual_id)), None)
                if target_id is None:
                    continue
                state_payload = item.get("State") if isinstance(item.get("State"), Mapping) else {}
                restart_count = _integer(item.get("RestartCount"), None)
                oom_killed = _bool(state_payload.get("OOMKilled"), None)
                status = str(state_payload.get("Status") or "unknown")
                state = self._states[target_id]
                previous_status = str(state.get("status") or "unknown")
                if restart_count is not None and restart_count >= 0:
                    state["current_restart_count"] = restart_count
                state["status"] = status
                state["runtime_seen"] = True
                if status != "running" or previous_status != "running":
                    state["running_sample_count"] = 0
                if status in {"exited", "dead"} and previous_status not in {"exited", "dead"}:
                    if self._containers[target_id].get("role") == "lab":
                        callbacks.append((target_id, f"container_unexpected_exit:{target_id}"))
                if oom_killed is not None:
                    old_oom = bool(state.get("oom_seen"))
                    state["current_oom_killed"] = oom_killed
                    if oom_killed and not old_oom:
                        state["oom_events"] += 1
                        callbacks.append((target_id, f"container_oom:{target_id}"))
                    state["oom_seen"] = oom_killed
        for identifier, reason in callbacks:
            self._request_stop(identifier, reason)

    def _inspect_loop(self) -> None:
        while not self._stop_event.is_set():
            self._inspect_once()
            self._stop_event.wait(INSPECT_INTERVAL_SECONDS)

    def _start_events_reader(self) -> None:
        try:
            self._event_process = subprocess.Popen(
                [
                    "docker",
                    "events",
                    "--since",
                    self._start_utc,
                    "--format",
                    "{{json .}}",
                    "--filter",
                    "type=container",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception as error:
            self._record_missing("docker_events")
            with self._lock:
                self._record_host_error_locked(error)
            return
        self._event_thread = threading.Thread(target=self._event_loop, name="capacity-docker-events", daemon=True)
        self._event_thread.start()

    def _event_loop(self) -> None:
        process = self._event_process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                if self._stop_event.is_set():
                    break
                self.process_event_line(line)
        except Exception as error:
            if not self._stop_event.is_set():
                with self._lock:
                    self._record_host_error_locked(error)
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

    def process_event_line(self, line: str | bytes) -> bool:
        try:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            event = json.loads(str(line))
        except (TypeError, ValueError):
            return False
        if not isinstance(event, Mapping):
            return False
        action = str(event.get("Action") or event.get("action") or event.get("status") or "").lower()
        actor = event.get("Actor") if isinstance(event.get("Actor"), Mapping) else {}
        event_id = str(event.get("id") or event.get("ID") or actor.get("ID") or "")
        if not event_id or action not in {"oom", "restart", "start", "die", "stop"}:
            return False
        with self._lock:
            target_id = next((candidate for candidate in self._containers if candidate == event_id or event_id.startswith(candidate) or candidate.startswith(event_id)), None)
            if target_id is None:
                return False
            state = self._states[target_id]
            state.setdefault("event_actions", []).append({"action": action, "id": event_id, "time": event.get("time") or event.get("Time")})
            if action == "restart":
                state["event_restart_count"] += 1
            if action == "oom":
                state["oom_events"] += 1
                state["current_oom_killed"] = True
                state["oom_seen"] = True
                role = self._containers[target_id].get("role")
            elif action == "die":
                role = self._containers[target_id].get("role")
            else:
                role = None
        if action == "oom":
            self._request_stop(target_id, f"container_oom:{target_id}")
        elif action == "die" and role == "lab":
            self._request_stop(target_id, f"container_unexpected_exit:{target_id}")
        return True

    # ------------------------------------------------------------------
    # Host metrics
    # ------------------------------------------------------------------
    def _read_meminfo(self) -> dict[str, int]:
        path = PROC_ROOT / "meminfo"
        values: dict[str, int] = {}
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            pieces = value.strip().split()
            if not pieces:
                continue
            number = _integer(pieces[0])
            if number is None:
                continue
            multiplier = 1024 if len(pieces) > 1 and pieces[1].lower() == "kb" else 1
            values[key.strip()] = number * multiplier
        return values

    def _read_proc_cpu(self) -> dict[str, float]:
        text = (PROC_ROOT / "stat").read_text(encoding="utf-8")
        line = next((item for item in text.splitlines() if item.startswith("cpu ")), "")
        fields = line.split()
        if len(fields) < 6:
            raise RuntimeError("cpu stat unavailable")
        numbers = [_number(item) for item in fields[1:]]
        ticks = [item for item in numbers if item is not None]
        if len(ticks) < 5:
            raise RuntimeError("cpu stat unavailable")
        idle = ticks[3]
        iowait = ticks[4]
        busy = sum(ticks[:3]) + sum(ticks[5:])
        hz = _number(os.sysconf("SC_CLK_TCK")) if hasattr(os, "sysconf") else None
        hz = hz if hz and hz > 0 else 100.0
        return {"busy_seconds": busy / hz, "iowait_seconds": iowait / hz}

    def _read_proc_load(self) -> tuple[float, float, float]:
        fields = (PROC_ROOT / "loadavg").read_text(encoding="utf-8").split()
        if len(fields) < 3:
            raise RuntimeError("loadavg unavailable")
        result = tuple(_number(item) for item in fields[:3])
        if any(item is None for item in result):
            raise RuntimeError("loadavg unavailable")
        return result  # type: ignore[return-value]

    def _sample_host_once(self) -> None:
        errors: list[str] = []
        available = total = swap_total = swap_free = None
        busy_seconds = iowait_seconds = None
        loads: tuple[float, float, float] | None = None
        disk_free = disk_total = None
        try:
            meminfo = self._read_meminfo()
            available = meminfo.get("MemAvailable")
            total = meminfo.get("MemTotal")
            swap_total = meminfo.get("SwapTotal")
            swap_free = meminfo.get("SwapFree")
            if available is None or total is None:
                self._record_missing("host_meminfo")
                errors.append("host_meminfo_unavailable")
        except Exception:
            self._record_missing("host_meminfo")
            errors.append("host_meminfo_unavailable")
        try:
            cpu = self._read_proc_cpu()
            busy_seconds = cpu["busy_seconds"]
            iowait_seconds = cpu["iowait_seconds"]
        except Exception:
            self._record_missing("host_proc_stat")
            errors.append("host_proc_stat_unavailable")
        try:
            loads = self._read_proc_load()
        except Exception:
            self._record_missing("host_loadavg")
            errors.append("host_loadavg_unavailable")
        try:
            usage = shutil.disk_usage(self.output_dir)
            disk_free = int(usage.free)
            disk_total = int(usage.total)
        except Exception:
            self._record_missing("host_disk")
            errors.append("host_disk_unavailable")

        available_percent = available / total * 100.0 if available is not None and total else None
        previous = self._host_previous
        busy_delta = _nonnegative_delta(busy_seconds, previous.get("busy_seconds") if previous else None)
        iowait_delta = _nonnegative_delta(iowait_seconds, previous.get("iowait_seconds") if previous else None)
        with self._lock:
            self._ensure_output_files_locked()
            row = {
                "timestamp_utc": _utc_now(),
                "phase": self._phase,
                "available_bytes": available,
                "total_bytes": total,
                "available_percent": available_percent,
                "swap_total_bytes": swap_total,
                "swap_free_bytes": swap_free,
                "cpu_busy_seconds": busy_seconds,
                "cpu_iowait_seconds": iowait_seconds,
                "cpu_busy_delta_seconds": busy_delta,
                "cpu_iowait_delta_seconds": iowait_delta,
                "load_1m": loads[0] if loads else None,
                "load_5m": loads[1] if loads else None,
                "load_15m": loads[2] if loads else None,
                "disk_free_bytes": disk_free,
                "disk_total_bytes": disk_total,
                "status": "ok" if not errors else ("unavailable" if all(value is None for value in (available, total, busy_seconds, loads, disk_free)) else "partial"),
                "error": ";".join(errors) if errors else None,
            }
            self._host_writer.writerow({key: self._csv_value(row.get(key)) for key in HOST_CSV_COLUMNS})
            self._host_file.flush()
            summary = self._host_summary
            summary["samples"] += 1
            for value, key in (
                (available, "available_values"),
                (available_percent, "available_percent_values"),
                (swap_free, "swap_free_values"),
                (disk_free, "disk_free_values"),
                (loads[0] if loads else None, "load_1m_values"),
                (loads[1] if loads else None, "load_5m_values"),
                (loads[2] if loads else None, "load_15m_values"),
            ):
                if value is not None:
                    summary[key].append(value)
            if busy_delta is not None:
                summary["cpu_busy_seconds"] += busy_delta
            if iowait_delta is not None:
                summary["cpu_iowait_seconds"] += iowait_delta
            for error in errors:
                self._record_host_error_locked(error)
            self._host_previous = {
                "busy_seconds": busy_seconds,
                "iowait_seconds": iowait_seconds,
            } if busy_seconds is not None and iowait_seconds is not None else None

        low_available = (available is not None and available < self.min_host_available_bytes) or (available_percent is not None and available_percent < self.min_host_available_percent)
        if low_available:
            with self._lock:
                lab_ids = [container_id for container_id, metadata in self._containers.items() if metadata.get("role") == "lab"]
            if lab_ids:
                for container_id in lab_ids:
                    self._request_stop(container_id, "host_available_below_threshold")
            else:
                self._request_stop("__host__", "host_available_below_threshold")

    def sample_host_once(self) -> None:
        """Collect one host sample synchronously (also useful in unit tests)."""

        self._sample_host_once()

    def _host_loop(self) -> None:
        while not self._stop_event.is_set():
            self._sample_host_once()
            self._stop_event.wait(self.interval)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    @staticmethod
    def _percentile(values: list[float], fraction: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
        return ordered[index]

    @staticmethod
    def _max_or_none(values: list[float]) -> Optional[float]:
        return max(values) if values else None

    @staticmethod
    def _min_or_none(values: list[float]) -> Optional[float]:
        return min(values) if values else None

    def _public_phase_summary(self, phase_state: Mapping[str, Any]) -> dict[str, Any]:
        periods = float(phase_state.get("cpu_periods") or 0.0)
        throttled_periods = float(phase_state.get("cpu_throttled_periods") or 0.0)
        ratio = throttled_periods / periods * 100.0 if periods > 0 else None
        return {
            "samples": int(phase_state.get("samples") or 0),
            "cpu_max_percent": self._max_or_none(list(phase_state.get("cpu_values") or [])),
            "cpu_p95_percent": self._percentile(list(phase_state.get("cpu_values") or []), 0.95),
            "memory_max_bytes": self._max_or_none(list(phase_state.get("memory_values") or [])),
            "memory_working_set_max_bytes": self._max_or_none(list(phase_state.get("working_set_values") or [])),
            "memory_max_percent": self._max_or_none(list(phase_state.get("memory_percent_values") or [])),
            "cpu_throttled_periods": throttled_periods if phase_state.get("cpu_throttled_periods") is not None else None,
            "cpu_periods": periods if phase_state.get("cpu_periods") is not None else None,
            "cpu_throttled_ratio_percent": ratio,
            "cpu_throttled_seconds": float(phase_state.get("cpu_throttled_seconds") or 0.0) if phase_state.get("cpu_throttled_seconds") is not None else None,
            "net_rx_total_bytes": phase_state.get("net_rx_delta_total"),
            "net_tx_total_bytes": phase_state.get("net_tx_delta_total"),
            "block_read_total_bytes": phase_state.get("block_read_delta_total"),
            "block_write_total_bytes": phase_state.get("block_write_delta_total"),
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            for handle in (self._container_file, self._raw_file, self._host_file):
                if handle is not None:
                    try:
                        handle.flush()
                    except Exception:
                        pass

            grouped: dict[str, dict[str, Any]] = {}
            for container_id, metadata in self._containers.items():
                state = self._states[container_id]
                name = str(metadata.get("name") or container_id)
                item = grouped.setdefault(
                    name,
                    {
                        "service": metadata.get("service"),
                        "role": metadata.get("role"),
                        "samples": 0,
                        "phases": {},
                        "oom_events": 0,
                        "restart_delta": 0,
                        "errors": [],
                    },
                )
                item["samples"] += int(state.get("samples") or 0)
                item["oom_events"] += int(state.get("oom_events") or 0)
                initial = int(metadata.get("initial_restart_count") or 0)
                current = int(state.get("current_restart_count") or 0)
                inspect_delta = max(0, current - initial)
                restart_delta = max(inspect_delta, int(state.get("event_restart_count") or 0))
                item["restart_delta"] += restart_delta
                for error in state.get("errors", []):
                    if error not in item["errors"]:
                        item["errors"].append(error)
                for phase, phase_state in state.get("phases", {}).items():
                    # A name collision can occur when Docker metadata has been
                    # reduced to a short name; combine its phase samples.
                    public = self._public_phase_summary(phase_state)
                    if phase not in item["phases"]:
                        item["phases"][phase] = public
                    else:
                        existing = item["phases"][phase]
                        existing["samples"] += public["samples"]
                        for key in ("cpu_max_percent", "memory_max_bytes", "memory_working_set_max_bytes", "memory_max_percent"):
                            values = [value for value in (existing.get(key), public.get(key)) if value is not None]
                            existing[key] = max(values) if values else None
                        for key in ("net_rx_total_bytes", "net_tx_total_bytes", "block_read_total_bytes", "block_write_total_bytes"):
                            values = [value for value in (existing.get(key), public.get(key)) if value is not None]
                            existing[key] = sum(values) if values else None
                        combined_cpu = []
                        if existing.get("cpu_p95_percent") is not None:
                            combined_cpu.append(existing["cpu_p95_percent"])
                        if public.get("cpu_p95_percent") is not None:
                            combined_cpu.append(public["cpu_p95_percent"])
                        existing["cpu_p95_percent"] = max(combined_cpu) if combined_cpu else None
                        for key in ("cpu_throttled_periods", "cpu_periods", "cpu_throttled_seconds"):
                            if existing.get(key) is None:
                                existing[key] = public.get(key)
                            elif public.get(key) is not None:
                                existing[key] += public[key]
                        periods = existing.get("cpu_periods")
                        throttled = existing.get("cpu_throttled_periods")
                        existing["cpu_throttled_ratio_percent"] = throttled / periods * 100.0 if periods else None

            host_summary = {
                "samples": self._host_summary["samples"],
                "minimum_available_bytes": self._min_or_none(self._host_summary["available_values"]),
                "minimum_available_percent": self._min_or_none(self._host_summary["available_percent_values"]),
                "minimum_swap_free_bytes": self._min_or_none(self._host_summary["swap_free_values"]),
                "minimum_disk_free_bytes": self._min_or_none(self._host_summary["disk_free_values"]),
                "maximum_load_1m": self._max_or_none(self._host_summary["load_1m_values"]),
                "maximum_load_5m": self._max_or_none(self._host_summary["load_5m_values"]),
                "maximum_load_15m": self._max_or_none(self._host_summary["load_15m_values"]),
                "cpu_busy_seconds": self._host_summary["cpu_busy_seconds"],
                "cpu_iowait_seconds": self._host_summary["cpu_iowait_seconds"],
                "errors": list(self._host_summary["errors"]),
            }
            critical_missing = []
            for metric in self._missing_metrics:
                if metric in {"host_meminfo", "host_proc_stat", "docker_inspect"}:
                    critical_missing.append(metric)
                    continue
                parts = metric.split(":")
                if len(parts) == 3 and parts[0] == "container":
                    container_id, field = parts[1], parts[2]
                    role = self._containers.get(container_id, {}).get("role")
                    if role in {"source", "lab"} and field in {"cpu", "memory"}:
                        critical_missing.append(metric)
                elif len(parts) == 2 and parts[0] == "docker_stats":
                    role = self._containers.get(parts[1], {}).get("role")
                    if role in {"source", "lab"}:
                        critical_missing.append(metric)
            return {
                "containers": grouped,
                "host": host_summary,
                "missing_metrics": list(self._missing_metrics),
                "critical_missing_metrics": critical_missing,
                "optional_missing_metrics": [item for item in self._missing_metrics if item not in critical_missing],
                "stop_reasons": list(self._stop_reasons),
            }


__all__ = ["MetricsCollector", "CONTAINER_CSV_COLUMNS", "HOST_CSV_COLUMNS", "PROC_ROOT"]
