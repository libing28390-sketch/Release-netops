#!/usr/bin/env python3
"""Small, dependency-free HTTP load test for a Nexora NetOps deployment.

Examples:
  python3 scripts/load_test.py --base-url http://127.0.0.1:5150
  python3 scripts/load_test.py --base-url https://nexora.example.com \
      --requests 2000 --concurrency 50 --timeout 10
  python3 scripts/load_test.py --base-url http://127.0.0.1:5150 \
      --duration 120 --concurrency 30 --json-out /tmp/nexora-load.json

The default endpoints are read-only and do not change devices or production
data. Run this against a staging deployment first, especially for a duration
test or a high concurrency value.
"""

from __future__ import annotations

import argparse
import json
import statistics
import ssl
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINTS = (
    "/api/health/live",
    "/api/health",
    "/api/devices",
    "/api/templates",
)


@dataclass
class Sample:
    endpoint: str
    status: int | None
    elapsed_ms: float
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5150",
        help="Deployment URL, including the scheme (default: %(default)s)",
    )
    volume = parser.add_mutually_exclusive_group()
    volume.add_argument("--requests", type=int, help="Total requests to send")
    volume.add_argument("--duration", type=float, help="Run continuously for N seconds")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent workers (default: %(default)s)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds (default: %(default)s)")
    parser.add_argument("--warmup", type=int, default=5, help="Warmup requests before measuring (default: %(default)s)")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification for a self-signed test certificate")
    parser.add_argument("--progress-interval", type=float, default=10.0, help="Print progress every N seconds; 0 disables it (default: %(default)s)")
    parser.add_argument(
        "--docker-container",
        action="append",
        dest="docker_containers",
        help="Collect local docker stats for this container; repeat for netops/nginx/db",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="Read-only path to test; repeat to test multiple paths (default: built-in API paths)",
    )
    parser.add_argument("--json-out", type=Path, help="Write the complete summary as JSON")
    args = parser.parse_args()

    if args.requests is None and args.duration is None:
        args.requests = 200
    if args.requests is not None and args.requests <= 0:
        parser.error("--requests must be greater than zero")
    if args.duration is not None and args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if args.concurrency <= 0:
        parser.error("--concurrency must be greater than zero")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.progress_interval < 0:
        parser.error("--progress-interval cannot be negative")
    if args.warmup < 0:
        parser.error("--warmup cannot be negative")
    return args


def normalize_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def request_once(url: str, endpoint: str, timeout: float, insecure: bool = False) -> Sample:
    started = time.perf_counter()
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "nexora-load-test/1.0",
            "Connection": "close",
        },
    )
    try:
        context = ssl._create_unverified_context() if insecure and url.lower().startswith("https://") else None
        with urlopen(request, timeout=timeout, context=context) as response:
            response.read()
            return Sample(endpoint, response.status, (time.perf_counter() - started) * 1000)
    except HTTPError as exc:
        return Sample(endpoint, exc.code, (time.perf_counter() - started) * 1000, f"HTTP {exc.code}")
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return Sample(endpoint, None, (time.perf_counter() - started) * 1000, str(reason))
    except Exception as exc:  # Keep one unexpected client error from stopping the run.
        return Sample(endpoint, None, (time.perf_counter() - started) * 1000, repr(exc))


def collect_docker_stats(containers: list[str]) -> dict | None:
    """Collect one local Docker stats snapshot without requiring third-party packages."""
    if not containers:
        return None
    try:
        completed = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or f"docker stats exited {completed.returncode}"}
    rows = []
    for line in completed.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return {"containers": rows}


def warmup(base_url: str, endpoints: Iterable[str], count: int, timeout: float, insecure: bool) -> None:
    endpoint_list = list(endpoints)
    for index in range(count):
        endpoint = endpoint_list[index % len(endpoint_list)]
        request_once(normalize_url(base_url, endpoint), endpoint, timeout, insecure)


def run_load(base_url: str, endpoints: list[str], args: argparse.Namespace) -> tuple[list[Sample], float, int, list[dict]]:
    results: list[Sample] = []
    resource_snapshots: list[dict] = []
    result_lock = threading.Lock()
    issue_lock = threading.Lock()
    issued = 0
    deadline = time.perf_counter() + args.duration if args.duration is not None else None

    def worker() -> None:
        nonlocal issued
        while True:
            with issue_lock:
                if args.requests is not None:
                    if issued >= args.requests:
                        return
                elif deadline is not None and time.perf_counter() >= deadline:
                    return
                request_number = issued
                issued += 1

            endpoint = endpoints[request_number % len(endpoints)]
            sample = request_once(normalize_url(base_url, endpoint), endpoint, args.timeout, args.insecure)
            with result_lock:
                results.append(sample)

    started = time.perf_counter()
    stop_reporter = threading.Event()

    def report_progress() -> None:
        if args.progress_interval <= 0:
            return
        while not stop_reporter.wait(args.progress_interval):
            elapsed = time.perf_counter() - started
            with issue_lock:
                issued_snapshot = issued
            with result_lock:
                completed_snapshot = len(results)
                latency_snapshot = [item.elapsed_ms for item in results]
                error_snapshot = sum(
                    1 for item in results
                    if item.error is not None or item.status is None or item.status >= 400
                )
            p95 = percentile(latency_snapshot, 0.95)
            rps = completed_snapshot / elapsed if elapsed else 0.0
            print(
                f"[progress] elapsed={elapsed:.0f}s issued={issued_snapshot} "
                f"completed={completed_snapshot} in_flight={issued_snapshot - completed_snapshot} "
                f"rps={rps:.2f} errors={error_snapshot} p95={p95:.2f}ms",
                file=sys.stderr,
                flush=True,
            )
            if args.docker_containers:
                snapshot = collect_docker_stats(args.docker_containers)
                if snapshot is not None:
                    snapshot["elapsed_seconds"] = round(elapsed, 3)
                    resource_snapshots.append(snapshot)
                    print(f"[docker] {json.dumps(snapshot, ensure_ascii=False)}", file=sys.stderr, flush=True)

    reporter = threading.Thread(target=report_progress, name="nexora-load-progress", daemon=True)
    reporter.start()
    try:
        with ThreadPoolExecutor(max_workers=args.concurrency, thread_name_prefix="nexora-load") as executor:
            futures = [executor.submit(worker) for _ in range(args.concurrency)]
            for future in futures:
                future.result()
    finally:
        stop_reporter.set()
        reporter.join(timeout=max(1.0, args.progress_interval + 1.0))
    return results, time.perf_counter() - started, issued, resource_snapshots


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def build_summary(samples: list[Sample], elapsed_s: float, issued: int, args: argparse.Namespace) -> dict:
    latencies = [sample.elapsed_ms for sample in samples]
    errors = [sample for sample in samples if sample.error is not None or sample.status is None or sample.status >= 400]
    status_counts: dict[str, int] = {}
    endpoint_stats: dict[str, dict[str, float | int]] = {}
    for sample in samples:
        key = str(sample.status) if sample.status is not None else "error"
        status_counts[key] = status_counts.get(key, 0) + 1
        stats = endpoint_stats.setdefault(sample.endpoint, {"requests": 0, "errors": 0})
        stats["requests"] += 1
        if sample.error is not None or sample.status is None or sample.status >= 400:
            stats["errors"] += 1

    summary = {
        "base_url": args.base_url.rstrip("/"),
        "requests_issued": issued,
        "responses_received": len(samples),
        "concurrency": args.concurrency,
        "insecure_tls": args.insecure,
        "progress_interval_seconds": args.progress_interval,
        "elapsed_seconds": round(elapsed_s, 3),
        "throughput_rps": round(len(samples) / elapsed_s, 2) if elapsed_s else 0.0,
        "error_count": len(errors),
        "error_rate_percent": round((len(errors) / len(samples)) * 100, 2) if samples else 100.0,
        "status_counts": status_counts,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else 0.0,
            "mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "endpoint_stats": endpoint_stats,
        "sample_errors": [asdict(sample) for sample in errors[:20]],
    }
    if getattr(args, "docker_containers", None):
        summary["docker_stats_snapshots"] = getattr(args, "docker_stats_snapshots", [])
    return summary


def print_summary(summary: dict) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["error_count"]:
        print("\nRESULT: FAIL (server errors, timeouts, or connection failures detected)")
        return
    print("\nRESULT: PASS (no client errors or HTTP 5xx responses detected)")


def main() -> int:
    args = parse_args()
    endpoints = args.endpoints or list(DEFAULT_ENDPOINTS)
    base_url = args.base_url.rstrip("/")

    print(f"Warmup: {args.warmup} request(s)")
    warmup(base_url, endpoints, args.warmup, args.timeout, args.insecure)
    mode = f"{args.requests} requests" if args.requests is not None else f"{args.duration:g}s duration"
    print(f"Load: {mode}, concurrency={args.concurrency}, endpoints={', '.join(endpoints)}")
    samples, elapsed_s, issued, docker_stats_snapshots = run_load(base_url, endpoints, args)
    args.docker_stats_snapshots = docker_stats_snapshots
    summary = build_summary(samples, elapsed_s, issued, args)
    print_summary(summary)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON report: {args.json_out}")
    return 1 if summary["error_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
