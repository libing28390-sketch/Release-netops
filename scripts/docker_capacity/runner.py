#!/usr/bin/env python3
"""In-container workload runner for the Nexora capacity lab.

The host side lab passes one JSON document on stdin and invokes this module as
``prepare``, ``check`` or ``run``.  This file deliberately keeps the command
line contract small: stdout contains exactly one redacted JSON object.  All
credentials, bearer tokens, DSNs and response bodies stay in process memory.

The runner is also useful as a library.  The public helpers are intentionally
dependency-light so the protocol and scheduler tests can run on a developer
machine without the production container's optional clients installed.
"""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import hashlib
import http.client
import json
import math
import os
import queue
import random
import re
import secrets
import socket
import statistics
import string
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional


SUPPORTED_SERVICES = (
    "netops",
    "nginx",
    "db",
    "redis",
    "victoriametrics",
    "vmagent",
    "snmp-exporter",
    "grafana",
    "cadvisor",
    "docker-socket-proxy",
    "seaweedfs",
)

DATASET_FIELDS = (
    "rows",
    "redis_keys",
    "objects",
    "object_bytes",
    "series",
    "history_points",
    "interfaces",
)

CREDENTIAL_FIELDS = (
    "db_user",
    "db_password",
    "db_name",
    "app_username",
    "app_password",
    "redis_password",
    "grafana_user",
    "grafana_password",
    "s3_access_key",
    "s3_secret_key",
    "s3_bucket",
)

TARGET_FIELDS = tuple(SUPPORTED_SERVICES)
ALERT_STORM_SERVICE = "alert-storm"
VIRTUAL_SERVICES = frozenset({ALERT_STORM_SERVICE})
ALERT_STORM_AUXILIARY_SERVICES = frozenset({
    "alert-redis", "alert-notify-critical", "alert-notify-normal", "alert-notify-relay",
})
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SAFE_DB_NAME_RE = re.compile(r"^nexora_capacity_[0-9a-f]{32}$")
SAFE_BUCKET_RE = re.compile(r"^nexora-capacity-[0-9a-f]{32}$")

DEFAULT_TIMEOUT = 5.0
MAX_ERROR_SAMPLES = 8
MAX_LATENCY_SAMPLES = 4096
VM_PUSH_METRIC = "nexora_capacity_push"
VM_SEED_METRIC = "nexora_capacity_value"
REDIS_KEY_PREFIX = "nexora:capacity:"


class CapacityError(Exception):
    """Stable, redacted runner error.

    ``detail`` is never populated with an exception string from a dependency.
    The command line uses only ``code`` and a short fixed message.
    """

    def __init__(self, code: str, message: str = "capacity operation failed") -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclasses.dataclass(frozen=True)
class ValidatedConfig:
    raw: Mapping[str, Any]
    run_id: str
    services: tuple[str, ...]
    available_services: tuple[str, ...]
    duration_seconds: float
    rps: float
    concurrency: int
    timeout_seconds: float
    insecure_tls: bool
    dataset: Mapping[str, int]
    credentials: Mapping[str, str]
    targets: Mapping[str, str]
    query_window_seconds: int
    snmp_ports: tuple[int, ...]
    snmp_auth: str
    snmp_module: str
    alert_count: int

    def redacted(self) -> dict[str, Any]:
        """Return the subset safe to include in a result document."""

        return {
            "run_id": self.run_id,
            "services": list(self.services),
            "available_services": list(self.available_services),
            "duration_seconds": self.duration_seconds,
            "rps": self.rps,
            "concurrency": self.concurrency,
            "timeout_seconds": self.timeout_seconds,
            "insecure_tls": self.insecure_tls,
            "dataset": dict(self.dataset),
            "query_window_seconds": self.query_window_seconds,
            "snmp_ports": list(self.snmp_ports),
            "snmp_auth": self.snmp_auth,
            "snmp_module": self.snmp_module,
            "alert_count": self.alert_count,
        }


def _as_int(value: Any, field: str, *, minimum: int = 1, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CapacityError("invalid_config", f"{field} must be an integer")
    if int(value) != value or not minimum <= int(value) <= maximum:
        raise CapacityError("invalid_config", f"{field} is outside the supported range")
    return int(value)


def _as_float(value: Any, field: str, *, minimum: float = 0.000001, maximum: float = 100_000.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CapacityError("invalid_config", f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise CapacityError("invalid_config", f"{field} is outside the supported range")
    return result


def validate_config(config: Mapping[str, Any]) -> ValidatedConfig:
    """Validate and normalize the stdin contract before any external writes."""

    if not isinstance(config, Mapping):
        raise CapacityError("invalid_config", "configuration must be a JSON object")

    run_id = config.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise CapacityError("invalid_config", "run_id must be 32 lowercase hexadecimal characters")

    services_value = config.get("services")
    if not isinstance(services_value, list) or not services_value:
        raise CapacityError("invalid_config", "services must be a non-empty list")
    services: list[str] = []
    for service in services_value:
        if not isinstance(service, str) or service not in (*SUPPORTED_SERVICES, *VIRTUAL_SERVICES):
            raise CapacityError("invalid_config", "services contains an unsupported service")
        if service in services:
            raise CapacityError("invalid_config", "services must not contain duplicates")
        services.append(service)

    available_value = config.get("available_services", services)
    if not isinstance(available_value, list) or not available_value:
        raise CapacityError("invalid_config", "available_services must be a non-empty list")
    available_services: list[str] = []
    for service in available_value:
        if not isinstance(service, str) or service not in (
            *SUPPORTED_SERVICES, *VIRTUAL_SERVICES, *ALERT_STORM_AUXILIARY_SERVICES,
        ):
            raise CapacityError("invalid_config", "available_services contains an unsupported service")
        if service in available_services:
            raise CapacityError("invalid_config", "available_services must not contain duplicates")
        available_services.append(service)
    if not set(services).issubset(set(available_services)):
        raise CapacityError("invalid_config", "services must be included in available_services")
    if ALERT_STORM_SERVICE in services and "netops" not in services:
        raise CapacityError("invalid_config", "alert-storm requires the isolated NetOps service")

    duration_seconds = _as_float(config.get("duration_seconds", 120), "duration_seconds", maximum=86_400)
    rps = _as_float(config.get("rps", 20), "rps", maximum=100_000)
    concurrency = _as_int(config.get("concurrency", 16), "concurrency", maximum=2048)
    timeout_seconds = _as_float(config.get("timeout_seconds", DEFAULT_TIMEOUT), "timeout_seconds", maximum=3_600)

    insecure_tls = config.get("insecure_tls", True)
    if not isinstance(insecure_tls, bool):
        raise CapacityError("invalid_config", "insecure_tls must be boolean")

    dataset_value = config.get("dataset")
    if not isinstance(dataset_value, Mapping):
        raise CapacityError("invalid_config", "dataset must be an object")
    dataset: dict[str, int] = {}
    for field in DATASET_FIELDS:
        dataset[field] = _as_int(dataset_value.get(field), f"dataset.{field}", maximum=10_000_000)
    # Protect the generator itself from accidental, unbounded allocations.
    if dataset["object_bytes"] > 16 * 1024 * 1024:
        raise CapacityError("invalid_config", "dataset.object_bytes is too large")
    if dataset["series"] * dataset["history_points"] > 2_000_000:
        raise CapacityError("invalid_config", "dataset time-series seed is too large")

    credentials_value = config.get("credentials")
    if not isinstance(credentials_value, Mapping):
        raise CapacityError("invalid_config", "credentials must be an object")
    credentials: dict[str, str] = {}
    for field in CREDENTIAL_FIELDS:
        value = credentials_value.get(field)
        if not isinstance(value, str) or not value:
            raise CapacityError("invalid_config", "credentials contains a missing value")
        credentials[field] = value
    if credentials["db_name"] != f"nexora_capacity_{run_id}" or not SAFE_DB_NAME_RE.fullmatch(credentials["db_name"]):
        raise CapacityError("unsafe_database_target", "database name is not an isolated capacity database")
    if credentials["s3_bucket"] != f"nexora-capacity-{run_id}" or not SAFE_BUCKET_RE.fullmatch(credentials["s3_bucket"]):
        raise CapacityError("unsafe_storage_target", "bucket name is not an isolated capacity bucket")

    targets_value = config.get("targets")
    if not isinstance(targets_value, Mapping):
        raise CapacityError("invalid_config", "targets must be an object")
    targets: dict[str, str] = {}
    for field in TARGET_FIELDS:
        value = targets_value.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CapacityError("invalid_config", "targets contains a missing endpoint")
        targets[field] = value.strip()

    query_window_seconds = _as_int(config.get("query_window_seconds", 1800), "query_window_seconds", maximum=7 * 86_400)
    ports_value = config.get("snmp_ports")
    if not isinstance(ports_value, list) or not ports_value:
        raise CapacityError("invalid_config", "snmp_ports must be a non-empty list")
    ports = tuple(_as_int(port, "snmp_ports", maximum=65_535) for port in ports_value)
    if len(set(ports)) != len(ports):
        raise CapacityError("invalid_config", "snmp_ports must not contain duplicates")
    snmp_auth = config.get("snmp_auth", "capacity_v2")
    snmp_module = config.get("snmp_module", "capacity_ifmib")
    if not isinstance(snmp_auth, str) or not snmp_auth or not isinstance(snmp_module, str) or not snmp_module:
        raise CapacityError("invalid_config", "snmp_auth and snmp_module must be non-empty strings")
    alert_count = _as_int(config.get("alert_count", 0), "alert_count", minimum=0, maximum=5000)
    if alert_count and ALERT_STORM_SERVICE not in services:
        raise CapacityError("invalid_config", "alert_count requires alert-storm mode")

    return ValidatedConfig(
        raw=config,
        run_id=run_id,
        services=tuple(services),
        available_services=tuple(available_services),
        duration_seconds=duration_seconds,
        rps=rps,
        concurrency=concurrency,
        timeout_seconds=timeout_seconds,
        insecure_tls=insecure_tls,
        dataset=dataset,
        credentials=credentials,
        targets=targets,
        query_window_seconds=query_window_seconds,
        snmp_ports=ports,
        snmp_auth=snmp_auth,
        snmp_module=snmp_module,
        alert_count=alert_count,
    )


def _redact_exception(exc: BaseException, fallback: str = "dependency_error") -> CapacityError:
    """Map arbitrary dependency failures to stable codes without echoing data."""

    if isinstance(exc, CapacityError):
        return exc
    name = type(exc).__name__.lower()
    if "timeout" in name or "timeout" in str(exc).lower():
        return CapacityError("timeout", "dependency request timed out")
    if isinstance(exc, (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError)):
        return CapacityError("connection_error", "dependency connection failed")
    return CapacityError(fallback, "dependency operation failed")


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _target_host_port(target: str, default_port: int) -> tuple[str, int]:
    value = target.strip()
    if "://" in value:
        parsed = urllib.parse.urlsplit(value)
        if not parsed.hostname:
            raise CapacityError("invalid_target", "target host is missing")
        return parsed.hostname, parsed.port or default_port
    if value.startswith("[") and "]" in value:
        host, _, suffix = value[1:].partition("]")
        port = int(suffix[1:]) if suffix.startswith(":") else default_port
        return host, port
    if value.count(":") == 1:
        host, port_value = value.rsplit(":", 1)
        if port_value.isdigit():
            return host, int(port_value)
    return value, default_port


@dataclasses.dataclass
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_ms: float

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        return None


def http_request(
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    body: bytes | str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    verify_tls: bool = True,
) -> HttpResponse:
    """Make a proxy-free request with redirects disabled.

    httpx is preferred in the production image.  The stdlib fallback keeps
    this module and its loopback tests runnable in a minimal Python install.
    """

    request_headers = {str(k): str(v) for k, v in (headers or {}).items()}
    payload = body.encode("utf-8") if isinstance(body, str) else body
    started = time.perf_counter()
    try:
        try:
            import httpx  # type: ignore
        except ImportError:
            httpx = None
        if httpx is not None:
            with httpx.Client(
                verify=verify_tls,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.request(method, url, headers=request_headers, content=payload)
                return HttpResponse(
                    int(response.status_code),
                    dict(response.headers),
                    bytes(response.content),
                    (time.perf_counter() - started) * 1000,
                )

        handlers: list[Any] = [_NoRedirect(), urllib.request.ProxyHandler({})]
        if url.lower().startswith("https://") and not verify_tls:
            import ssl

            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(url, data=payload, headers=request_headers, method=method.upper())
        try:
            with opener.open(request, timeout=timeout) as response:
                return HttpResponse(
                    int(response.status),
                    dict(response.headers),
                    response.read(),
                    (time.perf_counter() - started) * 1000,
                )
        except urllib.error.HTTPError as response:
            # HTTPError is still a real response and is needed for the 401/403
            # rejection checks.  Do not expose its body in a result.
            return HttpResponse(
                int(response.code),
                dict(response.headers),
                response.read(64 * 1024),
                (time.perf_counter() - started) * 1000,
            )
    except Exception as exc:
        raise _redact_exception(exc, "http_error") from None


class HttpClient:
    """One proxy-free keep-alive client owned by one worker thread."""

    def __init__(self, *, timeout: float, verify_tls: bool) -> None:
        self.timeout = timeout
        self.verify_tls = verify_tls
        self._client: Any = None
        self._opener: Any = None
        try:
            import httpx  # type: ignore

            self._client = httpx.Client(
                verify=verify_tls,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            )
        except ImportError:
            handlers: list[Any] = [_NoRedirect(), urllib.request.ProxyHandler({})]
            if not verify_tls:
                import ssl

                handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
            self._opener = urllib.request.build_opener(*handlers)

    def request(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None, body: bytes | str | None = None) -> HttpResponse:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        started = time.perf_counter()
        try:
            if self._client is not None:
                response = self._client.request(method, url, headers=dict(headers or {}), content=payload)
                return HttpResponse(
                    int(response.status_code),
                    dict(response.headers),
                    bytes(response.content),
                    (time.perf_counter() - started) * 1000,
                )
            request = urllib.request.Request(url, data=payload, headers=dict(headers or {}), method=method.upper())
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    return HttpResponse(
                        int(response.status),
                        dict(response.headers),
                        response.read(),
                        (time.perf_counter() - started) * 1000,
                    )
            except urllib.error.HTTPError as response:
                return HttpResponse(
                    int(response.code),
                    dict(response.headers),
                    response.read(64 * 1024),
                    (time.perf_counter() - started) * 1000,
                )
        except Exception as exc:
            raise _redact_exception(exc, "http_error") from None

    def close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()


def _json_body(response: HttpResponse, *, require_object: bool = False) -> Any:
    if response.status_code in (401, 403):
        error = CapacityError("unauthorized", "dependency rejected credentials")
        error.status_code = response.status_code  # type: ignore[attr-defined]
        raise error
    if response.status_code < 200 or response.status_code >= 300:
        error = CapacityError(f"http_{response.status_code}", "dependency returned an HTTP error")
        error.status_code = response.status_code  # type: ignore[attr-defined]
        raise error
    try:
        value = json.loads(response.body.decode("utf-8"))
    except Exception:
        raise CapacityError("invalid_json", "dependency returned invalid JSON") from None
    if require_object and not isinstance(value, dict):
        raise CapacityError("invalid_json", "dependency returned an unexpected JSON shape")
    if isinstance(value, dict) and ("error" in value or "errors" in value):
        raise CapacityError("semantic_error", "dependency returned a semantic error")
    return value


def _success_status(response: HttpResponse, allowed: Iterable[int] = (200, 204)) -> None:
    if response.status_code in (401, 403):
        error = CapacityError("unauthorized", "dependency rejected credentials")
        error.status_code = response.status_code  # type: ignore[attr-defined]
        raise error
    if response.status_code not in tuple(allowed):
        error = CapacityError(f"http_{response.status_code}", "dependency returned an unexpected status")
        error.status_code = response.status_code  # type: ignore[attr-defined]
        raise error


def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _bearer(token: Optional[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


class Reservoir:
    """Bounded latency sample using reservoir sampling."""

    def __init__(self, limit: int = MAX_LATENCY_SAMPLES) -> None:
        self.limit = max(32, int(limit))
        self.values: list[float] = []
        self.count = 0
        self.maximum = 0.0
        self._random = random.Random(secrets.randbits(64))

    def add(self, value: float) -> None:
        value = max(0.0, float(value))
        self.count += 1
        self.maximum = max(self.maximum, value)
        if len(self.values) < self.limit:
            self.values.append(value)
        else:
            index = self._random.randrange(self.count)
            if index < self.limit:
                self.values[index] = value

    def percentiles(self) -> dict[str, float]:
        if not self.values:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
        values = sorted(self.values)

        def percentile(fraction: float) -> float:
            if len(values) == 1:
                return round(values[0], 3)
            position = fraction * (len(values) - 1)
            lower = int(position)
            upper = min(lower + 1, len(values) - 1)
            return round(values[lower] + (values[upper] - values[lower]) * (position - lower), 3)

        return {
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": round(self.maximum, 3),
        }


@dataclasses.dataclass
class ScenarioOutcome:
    success: bool
    latency_ms: float = 0.0
    error_code: Optional[str] = None
    status_code: Optional[int] = None


class Scenario:
    """Base class for one service's request factory."""

    name = "scenario"

    def __init__(self, cfg: ValidatedConfig, context: "RuntimeContext") -> None:
        self.cfg = cfg
        self.context = context

    def prepare_worker(self) -> Any:
        return None

    def close_worker(self, worker: Any) -> None:
        close = getattr(worker, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        raise NotImplementedError


class HttpScenario(Scenario):
    def prepare_worker(self) -> HttpClient:
        return HttpClient(timeout=self.cfg.timeout_seconds, verify_tls=not self.cfg.insecure_tls)

    def close_worker(self, worker: Any) -> None:
        close = getattr(worker, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        client: Optional[HttpClient] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: bytes | str | None = None,
        allowed: Iterable[int] = (200,),
        semantic: Optional[Callable[[HttpResponse], None]] = None,
    ) -> ScenarioOutcome:
        started = time.perf_counter()
        try:
            if client is None:
                response = http_request(
                    method,
                    url,
                    headers=headers,
                    body=body,
                    timeout=self.cfg.timeout_seconds,
                    verify_tls=not self.cfg.insecure_tls,
                )
            else:
                response = client.request(method, url, headers=headers, body=body)
            _success_status(response, allowed)
            if semantic:
                semantic(response)
            return ScenarioOutcome(True, (time.perf_counter() - started) * 1000, status_code=response.status_code)
        except Exception as exc:
            error = _redact_exception(exc, "request_failed")
            status = getattr(exc, "status_code", None)
            return ScenarioOutcome(False, (time.perf_counter() - started) * 1000, error.code, status)


class NetopsScenario(HttpScenario):
    name = "netops"

    def prepare_worker(self) -> dict[str, Any]:
        return {"token": self.context.token, "client": HttpClient(timeout=self.cfg.timeout_seconds, verify_tls=not self.cfg.insecure_tls)}

    def close_worker(self, worker: Any) -> None:
        if isinstance(worker, Mapping):
            client = worker.get("client")
            if client is not None:
                client.close()

    def request(self, worker: Mapping[str, Any], *, check: bool = False) -> ScenarioOutcome:
        token = worker.get("token")
        choice = 0 if check else random.randrange(3)
        if choice == 0:
            page = random.randint(1, max(1, self.cfg.dataset["rows"] // 100))
            path = f"/api/devices?page={page}&page_size=100"
        elif choice == 1:
            path = "/api/alerts/summary"
        else:
            path = "/api/topology/links?limit=5000"

        def semantic(response: HttpResponse) -> None:
            value = _json_body(response)
            if isinstance(value, dict) and ("error" in value or "errors" in value or "detail" in value):
                raise CapacityError("semantic_error", "NetOps returned a semantic error")

        return self._request(
            "GET",
            _join_url(self.cfg.targets["netops"], path),
            client=worker.get("client"),
            headers={"Accept": "application/json", **_bearer(token)},
            allowed=(200,),
            semantic=semantic,
        )


class AlertStormScenario(HttpScenario):
    """Read the real alerts desk APIs against run-scoped synthetic alert rows."""

    name = ALERT_STORM_SERVICE

    def prepare_worker(self) -> dict[str, Any]:
        return {
            "token": self.context.token,
            "client": HttpClient(timeout=self.cfg.timeout_seconds, verify_tls=not self.cfg.insecure_tls),
        }

    def close_worker(self, worker: Any) -> None:
        if isinstance(worker, Mapping):
            client = worker.get("client")
            if client is not None:
                client.close()

    def request(self, worker: Mapping[str, Any], *, check: bool = False) -> ScenarioOutcome:
        token = worker.get("token")
        use_summary = not check and random.random() < 0.25
        path = "/api/alerts/summary" if use_summary else "/api/alerts?status=all_active&page=1&page_size=100"

        def semantic(response: HttpResponse) -> None:
            value = _json_body(response, require_object=True)
            if use_summary:
                count = value.get("open_count")
            else:
                count = value.get("total")
            if isinstance(count, bool) or not isinstance(count, int) or count != self.cfg.alert_count:
                raise CapacityError("alert_dataset_mismatch", "isolated alert count did not match the stage")

        return self._request(
            "GET",
            _join_url(self.cfg.targets["netops"], path),
            client=worker.get("client"),
            headers={"Accept": "application/json", **_bearer(token)},
            allowed=(200,),
            semantic=semantic,
        )


class NginxScenario(HttpScenario):
    name = "nginx"

    _asset_re = re.compile(r"(?:src|href)=[\"']([^\"']+\.(?:js|css)(?:\?[^\"']*)?)[\"']", re.I)

    def prepare_worker(self) -> dict[str, Any]:
        return {
            "token": self.context.token,
            "assets": [],
            "client": HttpClient(timeout=self.cfg.timeout_seconds, verify_tls=not self.cfg.insecure_tls),
        }

    def close_worker(self, worker: Any) -> None:
        if isinstance(worker, Mapping):
            client = worker.get("client")
            if client is not None:
                client.close()

    def request(self, worker: MutableMapping[str, Any], *, check: bool = False) -> ScenarioOutcome:
        token = worker.get("token")
        assets = worker.get("assets") or []
        # The first request warms the HTML/static manifest.  Thereafter keep a
        # stable 50% static, 30% API, 20% homepage mix so an open-loop run
        # exercises both the proxy and the asset path.
        choice = 0.9 if check else (random.random() if assets else 0.9)
        if assets and choice < 0.5:
            asset = random.choice(worker["assets"])
            if asset.startswith("http://") or asset.startswith("https://"):
                url = asset
            else:
                url = _join_url(self.cfg.targets["nginx"], asset)
            return self._request("GET", url, client=worker.get("client"), headers={"Accept": "*/*"}, allowed=(200,))

        if not check and choice < 0.8:
            return self._request(
                "GET",
                _join_url(self.cfg.targets["nginx"], "/api/devices?page=1&page_size=100"),
                client=worker.get("client"),
                headers={"Accept": "application/json", **_bearer(token)},
                allowed=(200,),
                semantic=lambda response: _json_body(response),
            )

        def home_semantic(response: HttpResponse) -> None:
            html = response.text
            assets = [match.group(1) for match in self._asset_re.finditer(html)]
            if not assets:
                raise CapacityError("static_asset_missing", "Nginx HTML contains no JavaScript or CSS asset")
            worker["assets"] = assets[:16]

        return self._request(
            "GET",
            _join_url(self.cfg.targets["nginx"], "/"),
            client=worker.get("client"),
            headers={"Accept": "text/html,*/*", **_bearer(token)},
            allowed=(200,),
            semantic=home_semantic,
        )


class DbScenario(Scenario):
    name = "db"

    def prepare_worker(self) -> Any:
        return DatabaseConnection(self.cfg)

    def close_worker(self, worker: Any) -> None:
        if worker is not None:
            with contextlib.suppress(Exception):
                worker.close()

    def request(self, worker: "DatabaseConnection", *, check: bool = False) -> ScenarioOutcome:
        started = time.perf_counter()
        try:
            worker.request(index_only=check or random.random() < 0.45)
            return ScenarioOutcome(True, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            error = _redact_exception(exc, "db_query_failed")
            return ScenarioOutcome(False, (time.perf_counter() - started) * 1000, error.code)


class RedisScenario(Scenario):
    name = "redis"

    def prepare_worker(self) -> Any:
        return RedisConnection(self.cfg)

    def close_worker(self, worker: Any) -> None:
        if worker is not None:
            with contextlib.suppress(Exception):
                worker.close()

    def request(self, worker: "RedisConnection", *, check: bool = False) -> ScenarioOutcome:
        started = time.perf_counter()
        try:
            worker.request(check=check)
            return ScenarioOutcome(True, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            error = _redact_exception(exc, "redis_command_failed")
            return ScenarioOutcome(False, (time.perf_counter() - started) * 1000, error.code)


class VictoriaMetricsScenario(HttpScenario):
    name = "victoriametrics"

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        end = int(time.time())
        start = end - self.cfg.query_window_seconds
        query = urllib.parse.quote(f'{VM_SEED_METRIC}{{run_id="{self.cfg.run_id}"}}', safe="")
        url = _join_url(self.cfg.targets[self.name], f"/api/v1/query_range?query={query}&start={start}&end={end}&step=60")

        def semantic(response: HttpResponse) -> None:
            value = _json_body(response, require_object=True)
            data = value.get("data")
            if value.get("status") != "success" or not isinstance(data, dict) or not data.get("result"):
                raise CapacityError("semantic_error", "VictoriaMetrics returned no successful data")

        return self._request("GET", url, client=worker, allowed=(200,), semantic=semantic)


class VmagentScenario(HttpScenario):
    name = "vmagent"

    def _body(self) -> str:
        now = int(time.time() * 1000)
        # A fixed series-id pool prevents accidental cardinality growth during
        # an open-loop run while still exercising batching and remote write.
        lines = [
            f'{VM_PUSH_METRIC}{{run_id="{self.cfg.run_id}",series_id="{i}"}} {i + 1} {now}'
            for i in range(min(16, self.cfg.dataset["series"]))
        ]
        return "\n".join(lines) + "\n"

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        return self._request(
            "POST",
            _join_url(self.cfg.targets[self.name], "/api/v1/import/prometheus"),
            client=worker,
            headers={"Content-Type": "text/plain; version=0.0.4"},
            body=self._body(),
            allowed=(200, 204),
        )


class SnmpExporterScenario(HttpScenario):
    name = "snmp-exporter"

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        port = self.cfg.snmp_ports[0] if check else random.choice(self.cfg.snmp_ports)
        query = urllib.parse.urlencode(
            {
                "target": f"snmp-simulator:{port}",
                "auth": self.cfg.snmp_auth,
                "module": self.cfg.snmp_module,
            }
        )

        def semantic(response: HttpResponse) -> None:
            text = response.text
            if "ifInOctets" not in text or "ifOutOctets" not in text:
                raise CapacityError("semantic_error", "SNMP exporter response lacks interface counters")
            if "error" in text.lower() and "error 0" not in text.lower():
                raise CapacityError("semantic_error", "SNMP exporter returned an error metric")

        return self._request("GET", _join_url(self.cfg.targets[self.name], f"/snmp?{query}"), client=worker, allowed=(200,), semantic=semantic)


class GrafanaScenario(HttpScenario):
    name = "grafana"

    def _payload(self) -> str:
        now = datetime.now(timezone.utc)
        start = now.timestamp() - self.cfg.query_window_seconds
        end = now.timestamp()
        payload = {
            "from": str(int(start * 1000)),
            "to": str(int(end * 1000)),
            "queries": [
                {
                    "refId": "A",
                    "datasource": {"type": "prometheus", "uid": "victoriametrics"},
                    "expr": f'topk(100, {VM_SEED_METRIC}{{run_id="{self.cfg.run_id}"}})',
                    "format": "time_series",
                    "intervalMs": 60_000,
                    "maxDataPoints": 1_000,
                }
            ],
        }
        return json.dumps(payload, separators=(",", ":"))

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        auth = _basic_auth(self.cfg.credentials["grafana_user"], self.cfg.credentials["grafana_password"])

        def has_samples(value: Any) -> bool:
            if isinstance(value, list):
                return bool(value) and any(has_samples(item) for item in value)
            if isinstance(value, dict):
                for key in ("values", "points", "datapoints"):
                    if key in value and isinstance(value[key], list) and value[key]:
                        return True
                return any(has_samples(item) for item in value.values())
            return False

        def semantic(response: HttpResponse) -> None:
            value = _json_body(response, require_object=True)
            if value.get("error") or value.get("errors"):
                raise CapacityError("semantic_error", "Grafana returned an error")
            frames = value.get("results") or value.get("data")
            if frames is None:
                raise CapacityError("semantic_error", "Grafana response has no data")
            if not has_samples(frames):
                raise CapacityError("semantic_error", "Grafana returned no time-series samples")
            encoded = json.dumps(frames, separators=(",", ":")).lower()
            if '"error"' in encoded or "frameerror" in encoded:
                raise CapacityError("semantic_error", "Grafana returned a frame error")

        return self._request(
            "POST",
            _join_url(self.cfg.targets[self.name], "/api/ds/query"),
            client=worker,
            headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": auth},
            body=self._payload(),
            allowed=(200,),
            semantic=semantic,
        )


class CadvisorScenario(HttpScenario):
    name = "cadvisor"

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        def semantic(response: HttpResponse) -> None:
            body = response.text
            if "container_cpu" not in body or "container_memory" not in body:
                raise CapacityError("semantic_error", "cAdvisor metrics lack CPU or memory samples")

        return self._request("GET", _join_url(self.cfg.targets[self.name], "/metrics"), client=worker, allowed=(200,), semantic=semantic)


class SocketProxyScenario(HttpScenario):
    name = "docker-socket-proxy"

    def request(self, worker: Any, *, check: bool = False) -> ScenarioOutcome:
        path = "/containers/json" if check or random.random() < 0.6 else "/info"
        return self._request(
            "GET",
            _join_url(self.cfg.targets[self.name], path),
            client=worker,
            headers={"Accept": "application/json"},
            allowed=(200,),
            semantic=lambda response: _json_body(response),
        )


class SeaweedScenario(Scenario):
    name = "seaweedfs"

    def prepare_worker(self) -> Any:
        return S3Connection(self.cfg)

    def close_worker(self, worker: Any) -> None:
        if worker is not None:
            with contextlib.suppress(Exception):
                worker.close()

    def request(self, worker: "S3Connection", *, check: bool = False) -> ScenarioOutcome:
        started = time.perf_counter()
        try:
            worker.request(check=check)
            return ScenarioOutcome(True, (time.perf_counter() - started) * 1000)
        except Exception as exc:
            error = _redact_exception(exc, "s3_operation_failed")
            return ScenarioOutcome(False, (time.perf_counter() - started) * 1000, error.code)


SCENARIO_TYPES: dict[str, type[Scenario]] = {
    "netops": NetopsScenario,
    ALERT_STORM_SERVICE: AlertStormScenario,
    "nginx": NginxScenario,
    "db": DbScenario,
    "redis": RedisScenario,
    "victoriametrics": VictoriaMetricsScenario,
    "vmagent": VmagentScenario,
    "snmp-exporter": SnmpExporterScenario,
    "grafana": GrafanaScenario,
    "cadvisor": CadvisorScenario,
    "docker-socket-proxy": SocketProxyScenario,
    "seaweedfs": SeaweedScenario,
}


class RuntimeContext:
    def __init__(self, cfg: ValidatedConfig) -> None:
        self.cfg = cfg
        self.token: Optional[str] = None

    def login(self) -> None:
        """Create one app session for the current process; never return it."""

        try:
            response = http_request(
                "POST",
                _join_url(self.cfg.targets["netops"], "/api/login"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                body=json.dumps(
                    {
                        "username": self.cfg.credentials["app_username"],
                        "password": self.cfg.credentials["app_password"],
                    },
                    separators=(",", ":"),
                ),
                timeout=self.cfg.timeout_seconds,
                verify_tls=not self.cfg.insecure_tls,
            )
        except Exception as exc:
            error = _redact_exception(exc, "login_failed")
            if error.code == "timeout":
                raise CapacityError("api_login_timeout", "NetOps API login request timed out") from exc
            raise error from exc
        value = _json_body(response, require_object=True)
        token = value.get("token")
        if not isinstance(token, str) or not token:
            if value.get("mfa_required"):
                raise CapacityError("mfa_required", "capacity user unexpectedly requires MFA")
            raise CapacityError("login_failed", "login response did not include a session token")
        self.token = token


def _dsn_database_name(dsn: str) -> Optional[str]:
    try:
        parsed = urllib.parse.urlsplit(dsn)
        if parsed.scheme and parsed.path:
            return urllib.parse.unquote(parsed.path.lstrip("/"))
        match = re.search(r"(?:^|\s)dbname=([^\s]+)", dsn)
        return match.group(1).strip("'\"") if match else None
    except Exception:
        return None


class DatabaseConnection:
    """Small psycopg2 wrapper; imports the driver only in the container."""

    def __init__(self, cfg: ValidatedConfig, *, admin: bool = False, database: Optional[str] = None) -> None:
        self.cfg = cfg
        self.connection = _connect_pg(cfg, admin=admin, database=database)

    def close(self) -> None:
        self.connection.close()

    def request(self, *, index_only: bool = False) -> None:
        cur = self.connection.cursor()
        run_id = self.cfg.run_id
        try:
            if index_only:
                row_id = random.randrange(self.cfg.dataset["rows"])
                cur.execute(
                    "SELECT id, payload, value FROM nexora_capacity.benchmark_rows "
                    "WHERE run_id = %s AND id = %s",
                    (run_id, row_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise CapacityError("db_data_missing", "benchmark row is missing")
            elif random.random() < 0.35:
                cur.execute(
                    "SELECT COUNT(*), COALESCE(AVG(value), 0) FROM nexora_capacity.benchmark_rows WHERE run_id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
                if not row or int(row[0]) < self.cfg.dataset["rows"]:
                    raise CapacityError("db_data_missing", "benchmark aggregate is incomplete")
            elif random.random() < 0.5:
                offset = random.randrange(self.cfg.dataset["rows"])
                cur.execute(
                    "SELECT id, payload, value FROM nexora_capacity.benchmark_rows "
                    "WHERE run_id = %s ORDER BY id LIMIT 100 OFFSET %s",
                    (run_id, offset),
                )
                if not cur.fetchall():
                    raise CapacityError("db_data_missing", "benchmark page is empty")
            else:
                row_id = random.randrange(self.cfg.dataset["rows"])
                self.connection.autocommit = False
                cur.execute(
                    "SELECT value FROM nexora_capacity.benchmark_rows WHERE run_id = %s AND id = %s FOR UPDATE",
                    (run_id, row_id),
                )
                if cur.fetchone() is None:
                    raise CapacityError("db_data_missing", "benchmark write row is missing")
                cur.execute(
                    "UPDATE nexora_capacity.benchmark_rows SET value = value + 1 WHERE run_id = %s AND id = %s",
                    (run_id, row_id),
                )
            self.connection.commit()
        except Exception:
            with contextlib.suppress(Exception):
                self.connection.rollback()
            raise
        finally:
            cur.close()


def _connect_pg(cfg: ValidatedConfig, *, admin: bool = False, database: Optional[str] = None) -> Any:
    try:
        import psycopg2  # type: ignore
    except ImportError:
        raise CapacityError("missing_dependency", "PostgreSQL client is unavailable") from None

    credentials = cfg.credentials
    db_name = database or credentials["db_name"]
    env_dsn = os.environ.get("CAPACITY_DATABASE_URL", "").strip()
    # A generic DATABASE_URL is accepted only when it names this test DB.  This
    # prevents an accidentally inherited production DSN from being written.
    if env_dsn and not admin and _dsn_database_name(env_dsn) == db_name:
        try:
            return psycopg2.connect(env_dsn, connect_timeout=max(1, int(cfg.timeout_seconds)))
        except Exception as exc:
            raise _redact_exception(exc, "db_connect_failed") from None

    host, port = _target_host_port(cfg.targets["db"], 5432)
    user = os.environ.get("CAPACITY_DB_ADMIN_USER" if admin else "CAPACITY_DB_USER", "") or credentials["db_user"]
    password = os.environ.get("CAPACITY_DB_ADMIN_PASSWORD" if admin else "CAPACITY_DB_PASSWORD", "") or credentials["db_password"]
    if admin:
        env_db_name = os.environ.get("CAPACITY_DB_ADMIN_DB", "postgres")
    else:
        env_db_name = db_name
    try:
        return psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=env_db_name,
            connect_timeout=max(1, int(cfg.timeout_seconds)),
            application_name=f"nexora-capacity-{cfg.run_id[:8]}",
        )
    except Exception as exc:
        raise _redact_exception(exc, "db_connect_failed") from None


def _db_table_columns(connection: Any, table_name: str, schema: str = "public") -> set[str]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
            (schema, table_name),
        )
        return {str(row[0]) for row in cursor.fetchall()}
    finally:
        cursor.close()


def _insert_rows(connection: Any, table: str, columns: list[str], rows: list[tuple[Any, ...]], *, page_size: int = 500) -> None:
    """Insert rows with parameter placeholders and bounded batches."""

    if not rows:
        return
    placeholders = ",".join(["%s"] * len(columns))
    statement = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    cursor = connection.cursor()
    try:
        for offset in range(0, len(rows), page_size):
            cursor.executemany(statement, rows[offset : offset + page_size])
    finally:
        cursor.close()


def _capacity_device_rows(cfg: ValidatedConfig, columns: set[str]) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Build API fixtures without scheduling background probes to fake IPs."""

    allowed_device_values: dict[str, Any] = {
        "id": None,
        "hostname": None,
        # The app starts its normal A-Loop in the isolated NetOps container.
        # Null IPs keep API fixtures out of its reachability probes; SNMP
        # traffic is exercised separately against the internal simulator.
        "ip_address": None,
        "platform": "linux",
        "status": "active",
        "compliance": "unknown",
        "sn": None,
        "model": "capacity-simulator",
        "version": "capacity",
        "role": "network_device",
        "site": "capacity-lab",
        "uptime": "0",
        "connection_method": "snmp",
        "username": "capacity",
        "password": "capacity-lab-placeholder",
        "cpu_usage": 25,
        "memory_usage": 40,
        "snmp_community": "capacity_lab_only",
        "snmp_port": cfg.snmp_ports[0],
        "tenant_id": "tenant-default",
    }
    selected_columns = [name for name in allowed_device_values if name in columns]
    rows: list[tuple[Any, ...]] = []
    for index in range(cfg.dataset["rows"]):
        values = dict(allowed_device_values)
        values["id"] = f"capacity-{cfg.run_id}-{index}"
        values["hostname"] = f"capacity-{cfg.run_id[:8]}-{index:05d}"
        values["sn"] = f"capacity-{cfg.run_id[:8]}-{index:05d}"
        rows.append(tuple(values[name] for name in selected_columns))
    return selected_columns, rows


def _prepare_database(cfg: ValidatedConfig) -> dict[str, Any]:
    """Seed isolated PostgreSQL data after the app migrations have completed."""

    connection: Optional[DatabaseConnection] = None
    try:
        try:
            connection = DatabaseConnection(cfg)
        except CapacityError as first_error:
            # The lab may start a stock PostgreSQL with only its admin account.
            # Create the test database once, then reconnect with the supplied
            # capacity credentials.  We never attempt this for a non-test name.
            if first_error.code not in {"db_connect_failed", "connection_error"}:
                raise
            admin_conn = DatabaseConnection(cfg, admin=True, database="postgres")
            try:
                admin_conn.connection.autocommit = True
                cur = admin_conn.connection.cursor()
                try:
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg.credentials["db_name"],))
                    if cur.fetchone() is None:
                        cur.execute(f'CREATE DATABASE "{cfg.credentials["db_name"]}"')
                finally:
                    cur.close()
            finally:
                admin_conn.close()
            connection = DatabaseConnection(cfg)

        conn = connection.connection
        cursor = conn.cursor()
        try:
            cursor.execute("CREATE SCHEMA IF NOT EXISTS nexora_capacity")
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS nexora_capacity.benchmark_rows (
                    id BIGINT NOT NULL,
                    run_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    value BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (run_id, id)
                )"""
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_capacity_benchmark_run_value "
                "ON nexora_capacity.benchmark_rows (run_id, value)"
            )
            cursor.execute("DELETE FROM nexora_capacity.benchmark_rows WHERE run_id = %s", (cfg.run_id,))
            conn.commit()
        finally:
            cursor.close()

        benchmark_rows = [
            (index, cfg.run_id, f"capacity-payload-{index:08d}", index % 100_003)
            for index in range(cfg.dataset["rows"])
        ]
        _insert_rows(conn, "nexora_capacity.benchmark_rows", ["id", "run_id", "payload", "value"], benchmark_rows)
        conn.commit()

        # A database-only scenario deliberately does not start the NetOps
        # application.  Its fresh PostgreSQL instance therefore has no
        # migrated devices/users tables; benchmark data is still valid and is
        # sufficient for the direct SQL workload.
        if "netops" not in cfg.available_services:
            return {
                "database": True,
                "devices": 0,
                "benchmark_rows": cfg.dataset["rows"],
                "capacity_user": False,
            }

        device_columns = _db_table_columns(conn, "devices")
        if not {"id", "hostname"}.issubset(device_columns):
            raise CapacityError("db_schema_missing", "devices table is not ready")
        device_columns_to_insert, device_rows = _capacity_device_rows(cfg, device_columns)

        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM devices WHERE id LIKE %s", (f"capacity-{cfg.run_id}-%",))
            conn.commit()
        finally:
            cursor.close()
        _insert_rows(conn, "devices", device_columns_to_insert, device_rows)
        conn.commit()

        user_columns = _db_table_columns(conn, "users")
        if not {"id", "username", "password"}.issubset(user_columns):
            raise CapacityError("db_schema_missing", "users table is not ready")
        try:
            import bcrypt  # type: ignore
        except ImportError:
            raise CapacityError("missing_dependency", "password hash client is unavailable") from None
        password_hash = bcrypt.hashpw(cfg.credentials["app_password"].encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        user_values: dict[str, Any] = {
            "id": f"capacity-user-{cfg.run_id}",
            "username": cfg.credentials["app_username"],
            "password": password_hash,
            "role": "Administrator",
            "status": "active",
            "role_profile": "System Administrator",
            "tenant_id": "tenant-default",
            "role_id": "role-admin",
            "scope_type": "global",
            "scope_ids_json": "[]",
            "mfa_enabled": 0,
            "display_name": "Capacity Lab",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        user_columns = [name for name in user_values if name in user_columns]
        user_row = tuple(user_values[name] for name in user_columns)
        cursor = conn.cursor()
        try:
            # The isolated DB has one capacity user.  Update by username to
            # make prepare idempotent while preserving unrelated users.
            cursor.execute("DELETE FROM users WHERE username = %s", (cfg.credentials["app_username"],))
            _insert_rows(conn, "users", user_columns, [user_row])
            conn.commit()
        finally:
            cursor.close()
        return {
            "database": True,
            "devices": cfg.dataset["rows"],
            "benchmark_rows": cfg.dataset["rows"],
            "capacity_user": True,
        }
    except CapacityError:
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.connection.rollback()
        raise
    except Exception as exc:
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.connection.rollback()
        raise _redact_exception(exc, "db_prepare_failed") from None
    finally:
        if connection is not None:
            connection.close()


class RedisConnection:
    def __init__(self, cfg: ValidatedConfig) -> None:
        self.cfg = cfg
        try:
            import redis  # type: ignore
        except ImportError:
            raise CapacityError("missing_dependency", "Redis client is unavailable") from None
        target = cfg.targets["redis"]
        if "://" in target:
            self.client = redis.Redis.from_url(
                target,
                username="nexora",
                password=cfg.credentials["redis_password"],
                decode_responses=False,
                socket_timeout=cfg.timeout_seconds,
                socket_connect_timeout=cfg.timeout_seconds,
                health_check_interval=0,
            )
        else:
            host, port = _target_host_port(target, 6379)
            self.client = redis.Redis(
                host=host,
                port=port,
                username="nexora",
                password=cfg.credentials["redis_password"],
                decode_responses=False,
                socket_timeout=cfg.timeout_seconds,
                socket_connect_timeout=cfg.timeout_seconds,
                health_check_interval=0,
            )

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def request(self, *, check: bool = False) -> None:
        client = self.client
        key = f"{REDIS_KEY_PREFIX}{self.cfg.run_id}:value:{random.randrange(self.cfg.dataset['redis_keys'])}"
        if check:
            result = client.get(key)
            if result is None:
                raise CapacityError("redis_data_missing", "seeded Redis key is missing")
            return
        selector = random.random()
        if selector < 0.30:
            if client.get(key) is None:
                raise CapacityError("redis_data_missing", "seeded Redis key is missing")
        elif selector < 0.70:
            client.set(key, f"value-{self.cfg.run_id}".encode("utf-8"), ex=3600)
        elif selector < 0.90:
            client.incr(f"{REDIS_KEY_PREFIX}{self.cfg.run_id}:counter")
        else:
            script = (
                "local current = redis.call('GET', KEYS[1]); "
                "if not current then current = '0' end; "
                "local next = tonumber(current) + 1; "
                "redis.call('SET', KEYS[1], next, 'EX', ARGV[1]); return next"
            )
            client.eval(script, 1, f"{REDIS_KEY_PREFIX}{self.cfg.run_id}:rate", 3600)


def _redis_prepare(cfg: ValidatedConfig) -> dict[str, Any]:
    connection = RedisConnection(cfg)
    try:
        pipeline = connection.client.pipeline(transaction=False)
        prefix = f"{REDIS_KEY_PREFIX}{cfg.run_id}:value:"
        value = f"value-{cfg.run_id}".encode("utf-8")
        for index in range(cfg.dataset["redis_keys"]):
            pipeline.set(f"{prefix}{index}", value, ex=3600)
            if (index + 1) % 500 == 0:
                pipeline.execute()
                pipeline = connection.client.pipeline(transaction=False)
        pipeline.execute()
        connection.client.set(f"{REDIS_KEY_PREFIX}{cfg.run_id}:counter", 0, ex=3600)
        connection.client.set(f"{REDIS_KEY_PREFIX}{cfg.run_id}:rate", 0, ex=3600)
        return {"redis": True, "keys": cfg.dataset["redis_keys"]}
    except CapacityError:
        raise
    except Exception as exc:
        raise _redact_exception(exc, "redis_prepare_failed") from None
    finally:
        connection.close()


class S3Connection:
    def __init__(self, cfg: ValidatedConfig) -> None:
        self.cfg = cfg
        try:
            import boto3  # type: ignore
            from botocore.config import Config  # type: ignore
        except ImportError:
            raise CapacityError("missing_dependency", "S3 client is unavailable") from None
        endpoint = cfg.targets["seaweedfs"]
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=cfg.credentials["s3_access_key"],
            aws_secret_access_key=cfg.credentials["s3_secret_key"],
            region_name="us-east-1",
            verify=not cfg.insecure_tls,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 2, "mode": "standard"},
                connect_timeout=cfg.timeout_seconds,
                read_timeout=cfg.timeout_seconds,
                proxies={},
            ),
        )
        self.bucket = cfg.credentials["s3_bucket"]
        self.sample_key = f"capacity/{cfg.run_id}/object-00000.bin"

    def close(self) -> None:
        # boto3 clients do not require a close on old versions.
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def request(self, *, check: bool = False) -> None:
        key = self.sample_key
        if not check:
            index = random.randrange(self.cfg.dataset["objects"])
            key = f"capacity/{self.cfg.run_id}/object-{index:05d}.bin"
        index = int(key.rsplit("-", 1)[-1].split(".", 1)[0])
        payload = _object_payload(self.cfg.run_id, index, self.cfg.dataset["object_bytes"])
        self.client.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType="application/octet-stream")
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"].read(self.cfg.dataset["object_bytes"] + 1)
        if body != payload:
            raise CapacityError("s3_data_mismatch", "object content did not match the seeded payload")


def _object_payload(run_id: str, index: int, length: int) -> bytes:
    seed = hashlib.sha256(f"{run_id}:{index}".encode("ascii")).digest()
    repeats = (length + len(seed) - 1) // len(seed)
    return (seed * repeats)[:length]


def _s3_prepare(cfg: ValidatedConfig) -> dict[str, Any]:
    connection = S3Connection(cfg)
    try:
        try:
            connection.client.create_bucket(Bucket=connection.bucket)
        except Exception as exc:
            error_text = str(exc).lower()
            if "already" not in error_text and "exists" not in error_text and "bucketalreadyowned" not in error_text:
                raise
        for index in range(cfg.dataset["objects"]):
            connection.client.put_object(
                Bucket=connection.bucket,
                Key=f"capacity/{cfg.run_id}/object-{index:05d}.bin",
                Body=_object_payload(cfg.run_id, index, cfg.dataset["object_bytes"]),
                ContentType="application/octet-stream",
            )
        return {"s3": True, "bucket": True, "objects": cfg.dataset["objects"]}
    except CapacityError:
        raise
    except Exception as exc:
        raise _redact_exception(exc, "s3_prepare_failed") from None
    finally:
        connection.close()


def _vm_request(cfg: ValidatedConfig, method: str, path: str, *, body: bytes | str | None = None) -> HttpResponse:
    return http_request(
        method,
        _join_url(cfg.targets["victoriametrics"], path),
        headers={"Content-Type": "text/plain; version=0.0.4"} if body is not None else {},
        body=body,
        timeout=cfg.timeout_seconds,
        verify_tls=not cfg.insecure_tls,
    )


def _seed_victoria_metrics(cfg: ValidatedConfig) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    chunk: list[str] = []
    count = 0
    max_lines = 2_000
    for series_id in range(cfg.dataset["series"]):
        for point in range(cfg.dataset["history_points"]):
            timestamp = now_ms - (cfg.dataset["history_points"] - point) * 60_000
            value = (series_id % 1000) + point
            chunk.append(f'{VM_SEED_METRIC}{{run_id="{cfg.run_id}",series_id="{series_id}"}} {value} {timestamp}')
            if len(chunk) >= max_lines:
                response = _vm_request(cfg, "POST", "/api/v1/import/prometheus", body="\n".join(chunk) + "\n")
                _success_status(response, (200, 204))
                count += len(chunk)
                chunk.clear()
    if chunk:
        response = _vm_request(cfg, "POST", "/api/v1/import/prometheus", body="\n".join(chunk) + "\n")
        _success_status(response, (200, 204))
        count += len(chunk)
    return {"victoriametrics": True, "series": cfg.dataset["series"], "points": count}


def _seed_vmagent_push(cfg: ValidatedConfig) -> None:
    body = VmagentScenario(cfg, RuntimeContext(cfg))._body()
    response = http_request(
        "POST",
        _join_url(cfg.targets["vmagent"], "/api/v1/import/prometheus"),
        headers={"Content-Type": "text/plain; version=0.0.4"},
        body=body,
        timeout=cfg.timeout_seconds,
        verify_tls=not cfg.insecure_tls,
    )
    _success_status(response, (200, 204))


def prepare(cfg: ValidatedConfig) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "passed", "command": "prepare", "run_id": cfg.run_id, "dataset": dict(cfg.dataset), "prepared": {}}
    # Database/user seeding is independent from external storage and only
    # occurs after the test DB name has passed the prefix/run-id guard.
    if "db" in cfg.available_services or "netops" in cfg.available_services or "nginx" in cfg.available_services:
        result["prepared"]["db"] = _prepare_database(cfg)
    if "redis" in cfg.available_services:
        result["prepared"]["redis"] = _redis_prepare(cfg)
    if "seaweedfs" in cfg.available_services:
        result["prepared"]["seaweedfs"] = _s3_prepare(cfg)
    if "victoriametrics" in cfg.available_services:
        result["prepared"]["victoriametrics"] = _seed_victoria_metrics(cfg)
    return result


def _make_context(cfg: ValidatedConfig) -> RuntimeContext:
    context = RuntimeContext(cfg)
    if "netops" in cfg.services or "nginx" in cfg.services:
        context.login()
    return context


def _scenario_result(name: str, stats: "ScenarioStats") -> dict[str, Any]:
    completed = stats.completed
    # Throughput belongs to the open-loop deadline window.  Drain time is
    # reported independently so a slow shutdown cannot dilute the achieved
    # rate used by the host-side threshold logic.
    elapsed = max(stats.schedule_finished_at - stats.started_at, 0.000001)
    return {
        "schedule_mode": "open_loop",
        "schedule_seconds": round(elapsed, 3),
        "scheduled": stats.scheduled,
        "completed": completed,
        "successful": stats.successful,
        "errors": stats.errors,
        "achieved_rps": round(completed / elapsed, 3),
        "success_rps": round(stats.successful / elapsed, 3),
        "dropped": stats.dropped,
        "schedule_missed": stats.schedule_missed,
        "deadline_missed": stats.deadline_missed,
        "drain_seconds": round(max(stats.drain_finished_at - stats.schedule_finished_at, 0.0), 3),
        "latency_ms": stats.latency.percentiles(),
        "status_counts": dict(stats.status_counts),
        "error_samples": list(stats.error_samples),
        "status": "passed" if stats.errors == 0 and stats.successful == stats.completed else "failed",
    }


class ScenarioStats:
    def __init__(self) -> None:
        self.scheduled = 0
        self.completed = 0
        self.successful = 0
        self.errors = 0
        self.dropped = 0
        self.schedule_missed = 0
        self.deadline_missed = 0
        self.status_counts: Counter[str] = Counter()
        self.error_samples: list[str] = []
        self.latency = Reservoir()
        self.started_at = time.monotonic()
        self.schedule_finished_at = self.started_at
        self.drain_finished_at = self.started_at
        self.finished_at = self.started_at
        self.lock = threading.Lock()

    def add_scheduled(self) -> None:
        with self.lock:
            self.scheduled += 1

    def add_dropped(self, *, missed: bool = True) -> None:
        with self.lock:
            self.dropped += 1
            if missed:
                self.schedule_missed += 1

    def add_outcome(self, outcome: ScenarioOutcome, *, deadline_missed: bool) -> None:
        with self.lock:
            self.completed += 1
            self.status_counts[str(outcome.status_code or ("success" if outcome.success else "error"))] += 1
            if deadline_missed:
                self.deadline_missed += 1
            if outcome.success:
                self.successful += 1
                self.latency.add(outcome.latency_ms)
            else:
                self.errors += 1
                if outcome.error_code and len(self.error_samples) < MAX_ERROR_SAMPLES:
                    self.error_samples.append(outcome.error_code)


@dataclasses.dataclass
class ScheduledTask:
    scheduled_at: float


class ScenarioExecutor:
    """Bounded open-loop scheduler for one scenario."""

    def __init__(self, scenario: Scenario, *, duration: float, rps: float, concurrency: int, timeout: float, check: bool = False) -> None:
        self.scenario = scenario
        self.duration = duration
        self.rps = rps
        self.concurrency = concurrency
        self.timeout = timeout
        self.check = check
        self.stats = ScenarioStats()
        self.tasks: queue.Queue[Optional[ScheduledTask]] = queue.Queue(maxsize=max(1, concurrency * 2))
        self.stop_event = threading.Event()
        self.workers: list[threading.Thread] = []
        self.worker_contexts: dict[int, Any] = {}

    def _worker(self) -> None:
        worker_context = None
        setup_error: Optional[CapacityError] = None
        try:
            worker_context = self.scenario.prepare_worker()
        except Exception as exc:
            setup_error = _redact_exception(exc, "worker_setup_failed")
        self.worker_contexts[threading.get_ident()] = worker_context
        try:
            while not self.stop_event.is_set():
                try:
                    task = self.tasks.get(timeout=0.05)
                except queue.Empty:
                    continue
                if task is None:
                    self.tasks.task_done()
                    return
                try:
                    queue_wait = max(0.0, time.monotonic() - task.scheduled_at)
                    if setup_error is not None:
                        outcome = ScenarioOutcome(False, error_code=setup_error.code)
                    else:
                        outcome = self.scenario.request(worker_context, check=self.check)
                    # Successful latency is end-to-end from its scheduled
                    # open-loop deadline, including time spent waiting in the
                    # bounded queue.  Failed requests remain excluded from
                    # latency percentiles, but retain the same deadline test.
                    if queue_wait > 0:
                        outcome = ScenarioOutcome(
                            outcome.success,
                            latency_ms=outcome.latency_ms + queue_wait * 1000.0,
                            error_code=outcome.error_code,
                            status_code=outcome.status_code,
                        )
                    self.stats.add_outcome(
                        outcome,
                        deadline_missed=(outcome.latency_ms / 1000.0) > self.timeout,
                    )
                except Exception as exc:
                    error = _redact_exception(exc, "worker_failed")
                    self.stats.add_outcome(ScenarioOutcome(False, error_code=error.code), deadline_missed=False)
                finally:
                    self.tasks.task_done()
        finally:
            self.scenario.close_worker(worker_context)

    def run(self) -> ScenarioStats:
        self.stats.started_at = time.monotonic()
        self.workers = [threading.Thread(target=self._worker, name=f"capacity-{self.scenario.name}-{i}", daemon=True) for i in range(self.concurrency)]
        for worker in self.workers:
            worker.start()

        interval = 1.0 / self.rps
        deadline = time.monotonic() + self.duration
        next_due = time.monotonic()
        try:
            while time.monotonic() < deadline and not self.stop_event.is_set():
                now = time.monotonic()
                if now < next_due:
                    time.sleep(min(next_due - now, 0.01))
                    continue
                self.stats.add_scheduled()
                try:
                    self.tasks.put_nowait(ScheduledTask(next_due))
                except queue.Full:
                    self.stats.add_dropped()
                next_due += interval
                # If the scheduler was paused for a long interval, report each
                # missed slot without constructing an unbounded catch-up queue.
                if next_due < now - interval:
                    missed = max(0, int((now - next_due) / interval))
                    if missed:
                        with self.stats.lock:
                            self.stats.schedule_missed += missed
                            self.stats.dropped += missed
                    next_due = now + interval
        finally:
            self.stats.schedule_finished_at = time.monotonic()
            for _ in self.workers:
                with contextlib.suppress(queue.Full):
                    self.tasks.put_nowait(None)
            self.tasks.join()
            self.stop_event.set()
            for worker in self.workers:
                worker.join(timeout=max(self.timeout + 0.5, 1.0))
            self.stats.drain_finished_at = time.monotonic()
            self.stats.finished_at = self.stats.drain_finished_at
        return self.stats


def _alert_storm_prefix(cfg: ValidatedConfig) -> str:
    return f"capacity-alert:{cfg.run_id}:"


def _seed_alert_storm(cfg: ValidatedConfig) -> dict[str, Any]:
    """Replace only this run's synthetic alert/outbox rows in its guarded test DB."""
    if ALERT_STORM_SERVICE not in cfg.services or cfg.alert_count < 1:
        raise CapacityError("invalid_alert_storm_stage", "alert-storm and a positive alert_count are required")
    prefix = _alert_storm_prefix(cfg)
    event_prefix = f"capacity_alert:{cfg.run_id}:"
    connection = _connect_pg(cfg)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "DELETE FROM alert_activity WHERE alert_id IN "
                "(SELECT id FROM alert_events WHERE LEFT(dedupe_key, LENGTH(%s::text)) = %s)",
                (event_prefix, event_prefix),
            )
            cursor.execute(
                "DELETE FROM alert_delivery_attempts WHERE delivery_id IN "
                "(SELECT id FROM alert_delivery_outbox WHERE delivery_key LIKE %s)",
                (prefix + "%",),
            )
            cursor.execute("DELETE FROM alert_delivery_outbox WHERE delivery_key LIKE %s", (prefix + "%",))
            cursor.execute(
                "DELETE FROM alert_events WHERE LEFT(dedupe_key, LENGTH(%s::text)) = %s",
                (event_prefix, event_prefix),
            )

            created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            events: list[tuple[Any, ...]] = []
            outbox: list[tuple[Any, ...]] = []
            activity: list[tuple[Any, ...]] = []
            for index in range(cfg.alert_count):
                alert_id = f"capacity-alert-{cfg.run_id[:12]}-{cfg.alert_count}-{index:05d}"
                event_key = f"capacity_alert:{cfg.run_id}:{cfg.alert_count}:{index:05d}"
                severity = "critical" if index % 4 == 0 else "warning"
                title = f"Synthetic capacity alert {index:05d}"
                message = f"Isolated alert stress run {cfg.run_id[:8]}, item {index:05d}"
                delivery_id = f"capacity-delivery-{cfg.run_id[:12]}-{cfg.alert_count}-{index:05d}"
                delivery_key = prefix + f"{cfg.alert_count}:{index:05d}"
                payload = json.dumps({
                    "alert_id": alert_id,
                    "tenant_id": "tenant-default",
                    "event_kind": "active",
                    "severity": severity,
                    "title": title,
                    "message": message,
                    "synthetic_capacity_run": cfg.run_id,
                }, ensure_ascii=False, allow_nan=False)
                events.append((alert_id, event_key, "capacity_stress", severity, title, message,
                               None, None, created_at, None, "open", None, None, None, "", created_at))
                outbox.append((delivery_id, delivery_key, payload, alert_id,
                               "critical" if severity == "critical" else "normal"))
                activity_metadata = json.dumps({
                    "channel": "workspace",
                    "status": "pending",
                    "synthetic_capacity_run": cfg.run_id,
                }, ensure_ascii=False, allow_nan=False)
                activity.append((f"capacity-alert-activity-{cfg.run_id[:8]}-{cfg.alert_count}-{index:05d}", alert_id,
                                  "NOTIFICATION_QUEUED", None, "queued", activity_metadata, created_at))

            _insert_rows(
                connection,
                "alert_events",
                ["id", "dedupe_key", "source", "severity", "title", "message", "device_id",
                 "interface_name", "created_at", "resolved_at", "workflow_status", "assignee",
                 "ack_by", "ack_at", "note", "updated_at"],
                events,
                page_size=250,
            )
            cursor.execute("SAVEPOINT capacity_outbox_seed")
            try:
                statement = (
                    "INSERT INTO alert_delivery_outbox "
                    "(id, delivery_key, channel, payload, alert_id, tenant_id, event_kind, destination_key, priority) "
                    "VALUES (%s, %s, 'workspace', %s::jsonb, %s, 'tenant-default', 'active', 'workspace', %s)"
                )
                for offset in range(0, len(outbox), 250):
                    cursor.executemany(statement, outbox[offset:offset + 250])
                activity_statement = (
                    "INSERT INTO alert_activity "
                    "(id, alert_id, event_type, actor_id, note, metadata_json, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
                )
                for offset in range(0, len(activity), 250):
                    cursor.executemany(activity_statement, activity[offset:offset + 250])
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT capacity_outbox_seed")
                raise
            connection.commit()
        finally:
            cursor.close()
        return {"alerts_seeded": cfg.alert_count, "outbox_seeded": cfg.alert_count,
                "run_prefix": prefix, "channels": ["workspace"], "external_notifications": False}
    except CapacityError:
        with contextlib.suppress(Exception):
            connection.rollback()
        raise
    except Exception as exc:
        with contextlib.suppress(Exception):
            connection.rollback()
        raise _redact_exception(exc, "alert_storm_seed_failed") from None
    finally:
        connection.close()


def _alert_outbox_snapshot(cfg: ValidatedConfig) -> dict[str, Any]:
    connection = _connect_pg(cfg)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status='pending') AS pending, "
                "COUNT(*) FILTER (WHERE status='processing') AS processing, "
                "COUNT(*) FILTER (WHERE status='succeeded') AS succeeded, "
                "COUNT(*) FILTER (WHERE status='failed') AS failed, "
                "COALESCE(EXTRACT(EPOCH FROM clock_timestamp()-MIN(created_at)), 0) AS batch_age_seconds, "
                "COALESCE(MAX(EXTRACT(EPOCH FROM clock_timestamp()-created_at)) "
                "FILTER (WHERE status IN ('pending','processing')), 0) AS oldest_active_age_seconds "
                "FROM alert_delivery_outbox WHERE delivery_key LIKE %s",
                (_alert_storm_prefix(cfg) + "%",),
            )
            row = cursor.fetchone()
            if not row:
                raise CapacityError("alert_queue_snapshot_missing", "outbox snapshot was unavailable")
            column_names = [str(item[0]) for item in cursor.description]
            values = dict(zip(column_names, row))
            float_fields = {"oldest_active_age_seconds", "batch_age_seconds"}
            return {key: (float(value) if key in float_fields else int(value))
                    for key, value in values.items()}
        finally:
            cursor.close()
    except CapacityError:
        raise
    except Exception as exc:
        raise _redact_exception(exc, "alert_queue_snapshot_failed") from None
    finally:
        connection.close()


def alert_storm(cfg: ValidatedConfig) -> dict[str, Any]:
    """Read a pre-seeded synthetic alert batch and drain its isolated Celery outbox."""
    started_at = time.monotonic()
    snapshot = _alert_outbox_snapshot(cfg)
    if (snapshot["total"] != cfg.alert_count
            or snapshot["pending"] + snapshot["processing"] + snapshot["succeeded"] + snapshot["failed"] != cfg.alert_count):
        raise CapacityError("alert_dataset_mismatch", "isolated alert outbox does not match the requested stage")
    queue_state: dict[str, Any] = {"snapshot": snapshot, "drained_seconds": None, "error": None}
    queue_stop = threading.Event()

    def watch_outbox() -> None:
        while not queue_stop.is_set():
            try:
                current = _alert_outbox_snapshot(cfg)
                queue_state["snapshot"] = current
                if current["pending"] + current["processing"] == 0:
                    if queue_state["drained_seconds"] is None:
                        queue_state["drained_seconds"] = round(current["batch_age_seconds"], 3)
            except Exception as exc:
                queue_state["error"] = getattr(exc, "code", "alert_queue_snapshot_failed")
                return
            queue_stop.wait(2.0)

    monitor = threading.Thread(target=watch_outbox, name="alert-storm-outbox-monitor", daemon=True)
    monitor.start()
    context = _make_context(cfg)
    scenario = AlertStormScenario(cfg, context)
    stats = ScenarioExecutor(
        scenario,
        duration=cfg.duration_seconds,
        rps=cfg.rps,
        concurrency=min(max(1, cfg.concurrency), 4),
        timeout=cfg.timeout_seconds,
    ).run()
    deadline = time.monotonic() + 60.0
    while (queue_state["drained_seconds"] is None and queue_state["error"] is None
           and time.monotonic() < deadline):
        time.sleep(0.25)
    queue_stop.set()
    monitor.join(timeout=3)
    final_snapshot = _alert_outbox_snapshot(cfg)
    scenario_result = _scenario_result(scenario.name, stats)
    passed = (
        scenario_result["status"] == "passed"
        and final_snapshot["total"] == cfg.alert_count
        and final_snapshot["succeeded"] == cfg.alert_count
        and final_snapshot["pending"] == 0
        and final_snapshot["processing"] == 0
        and final_snapshot["failed"] == 0
        and queue_state["error"] is None
        and queue_state["drained_seconds"] is not None
    )
    return {
        "status": "passed" if passed else "failed",
        "command": ALERT_STORM_SERVICE,
        "run_id": cfg.run_id,
        "dataset": {"alerts": cfg.alert_count, "workspace_outbox_tasks": cfg.alert_count},
        "api": scenario_result,
        "outbox": {**final_snapshot, "drained_seconds": queue_state["drained_seconds"],
                   "monitor_error": queue_state["error"]},
        "external_notifications": False,
        "delivery_semantics": "workspace notifications are disabled; succeeded means the isolated task completed without provider I/O",
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def seed_alert_storm(cfg: ValidatedConfig) -> dict[str, Any]:
    """Create only run-scoped workspace outbox rows in the isolated test DB."""
    return {"status": "passed", "command": "seed-alert-storm", "run_id": cfg.run_id,
            "seed": _seed_alert_storm(cfg)}


def _single_check(scenario: Scenario, *, retry_deadline: Optional[float] = None) -> tuple[dict[str, Any], ScenarioOutcome]:
    """Run one real request, recreating its client between transient attempts."""

    outcome = ScenarioOutcome(False, error_code="check_not_run")
    while True:
        worker = None
        try:
            worker = scenario.prepare_worker()
            outcome = scenario.request(worker, check=True)
        except Exception as exc:
            error = _redact_exception(exc, "check_failed")
            outcome = ScenarioOutcome(False, error_code=error.code, status_code=getattr(error, "status_code", None))
        finally:
            scenario.close_worker(worker)
        if outcome.success or retry_deadline is None or time.monotonic() >= retry_deadline:
            break
        time.sleep(min(0.75, max(0.05, retry_deadline - time.monotonic())))

    stats = ScenarioStats()
    stats.scheduled = stats.completed = 1
    stats.successful = 1 if outcome.success else 0
    stats.errors = 0 if outcome.success else 1
    stats.status_counts[str(outcome.status_code or ("success" if outcome.success else "error"))] = 1
    if outcome.success:
        stats.latency.add(outcome.latency_ms)
    elif outcome.error_code:
        stats.error_samples.append(outcome.error_code)
    stats.schedule_finished_at = stats.drain_finished_at = stats.finished_at = time.monotonic()
    return _scenario_result(scenario.name, stats), outcome


def _vm_check(cfg: ValidatedConfig, metric: str = VM_PUSH_METRIC) -> dict[str, Any]:
    # Verification needs one bounded sample, not the complete 10k-series
    # history.  The workload's range query above still exercises the real
    # seeded cardinality; this check only proves that the write is visible.
    query = urllib.parse.quote(f'{metric}{{run_id="{cfg.run_id}",series_id="0"}}', safe="")
    path = f"/api/v1/query?query={query}"
    last_code = ""
    for _ in range(31):
        try:
            response = _vm_request(cfg, "GET", path)
            value = _json_body(response, require_object=True)
            data = value.get("data") if isinstance(value, dict) else None
            result = data.get("result") if isinstance(data, dict) else None
            if value.get("status") == "success" and result:
                return {"victoriametrics_push_visible": True}
            last_code = "vm_no_result"
        except CapacityError as exc:
            last_code = exc.code
        time.sleep(1.0)
    return {"victoriametrics_push_visible": False, "error": last_code or "vm_no_result"}


def _seed_vm_verification_sample(cfg: ValidatedConfig) -> None:
    """Keep the final instant-query verification fresh after long test runs."""
    timestamp_ms = int(time.time() * 1000)
    body = f'{VM_SEED_METRIC}{{run_id="{cfg.run_id}",series_id="0"}} 1 {timestamp_ms}\n'
    response = _vm_request(cfg, "POST", "/api/v1/import/prometheus", body=body)
    _success_status(response, (200, 204))


def check(cfg: ValidatedConfig) -> dict[str, Any]:
    started = time.monotonic()
    context = _make_context(cfg)
    scenarios: dict[str, Any] = {}
    checks: dict[str, Any] = {}
    retry_deadline = time.monotonic() + min(45.0, max(5.0, cfg.timeout_seconds * 3.0))
    for name in cfg.services:
        scenario = SCENARIO_TYPES[name](cfg, context)
        result, outcome = _single_check(scenario, retry_deadline=retry_deadline)
        scenarios[name] = result
        checks[name] = {"ok": outcome.success, **({"error": outcome.error_code} if not outcome.success else {})}

    # check sends one vmagent write itself even if vmagent was not included in
    # the selected pressure set so that the remote-write visibility check is
    # meaningful for the complete isolated lab.
    if "vmagent" in cfg.available_services:
        try:
            _seed_vmagent_push(cfg)
            checks["vmagent_push"] = {"ok": True}
        except CapacityError as exc:
            checks["vmagent_push"] = {"ok": False, "error": exc.code}
    if "vmagent" in cfg.available_services:
        vm_check = _vm_check(cfg, VM_PUSH_METRIC)
        checks["victoriametrics_query"] = {
            "ok": vm_check.get("victoriametrics_push_visible") is True,
            **({"error": vm_check["error"]} if isinstance(vm_check.get("error"), str) else {}),
        }
    elif "victoriametrics" in cfg.available_services:
        try:
            _seed_vm_verification_sample(cfg)
            vm_check = _vm_check(cfg, VM_SEED_METRIC)
        except CapacityError as exc:
            vm_check = {"victoriametrics_push_visible": False, "error": exc.code}
        checks["victoriametrics_query"] = {
            "ok": vm_check.get("victoriametrics_push_visible") is True,
            **({"error": vm_check["error"]} if isinstance(vm_check.get("error"), str) else {}),
        }
    if "snmp-exporter" in cfg.services:
        checks["snmp_interface_counters"] = {
            "ok": scenarios["snmp-exporter"].get("successful", 0) > 0,
        }
    if "grafana" in cfg.services:
        checks["grafana_data"] = {"ok": scenarios["grafana"].get("successful", 0) > 0}
    if "seaweedfs" in cfg.services:
        checks["s3_readable"] = {"ok": scenarios["seaweedfs"].get("successful", 0) > 0}
    all_ok = all(bool(value.get("ok", value)) for value in checks.values()) if checks else True
    return {
        "status": "passed" if all_ok else "failed",
        "command": "check",
        "run_id": cfg.run_id,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "scenarios": scenarios,
        "dataset": dict(cfg.dataset),
        "checks": checks,
    }


def run(cfg: ValidatedConfig) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "status": "passed",
        "command": "run",
        "run_id": cfg.run_id,
        "elapsed_seconds": 0.0,
        "scenarios": {},
        "dataset": dict(cfg.dataset),
        "checks": {},
    }
    try:
        context = _make_context(cfg)
    except Exception as exc:
        error = _redact_exception(exc, "session_failed")
        result["status"] = "failed"
        result["error"] = error.code
        for name in cfg.services:
            result["scenarios"][name] = {
                "schedule_mode": "open_loop",
                "schedule_seconds": 0.0,
                "scheduled": 0,
                "completed": 0,
                "successful": 0,
                "errors": 1,
                "achieved_rps": 0.0,
                "success_rps": 0.0,
                "dropped": 0,
                "schedule_missed": 0,
                "deadline_missed": 0,
                "drain_seconds": 0.0,
                "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0},
                "status_counts": {"error": 1},
                "error_samples": [error.code],
                "status": "failed",
            }
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        return result
    executors: list[ScenarioExecutor] = []
    try:
        for name in cfg.services:
            executor = ScenarioExecutor(
                SCENARIO_TYPES[name](cfg, context),
                duration=cfg.duration_seconds,
                rps=cfg.rps,
                concurrency=cfg.concurrency,
                timeout=cfg.timeout_seconds,
            )
            executors.append(executor)
        threads: list[threading.Thread] = []
        stats_by_name: dict[str, ScenarioStats] = {}

        def execute(executor: ScenarioExecutor) -> None:
            try:
                stats_by_name[executor.scenario.name] = executor.run()
            except Exception as exc:
                error = _redact_exception(exc, "scenario_failed")
                stats = ScenarioStats()
                stats.scheduled = stats.completed = stats.errors = 1
                stats.status_counts["error"] = 1
                stats.error_samples.append(error.code)
                stats.schedule_finished_at = stats.drain_finished_at = stats.finished_at = time.monotonic()
                stats_by_name[executor.scenario.name] = stats

        for executor in executors:
            thread = threading.Thread(target=execute, args=(executor,), name=f"capacity-scenario-{executor.scenario.name}")
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        for name in cfg.services:
            result["scenarios"][name] = _scenario_result(name, stats_by_name[name])
        result["status"] = "passed" if all(item["status"] == "passed" for item in result["scenarios"].values()) else "failed"
    except Exception as exc:
        error = _redact_exception(exc, "run_failed")
        result["status"] = "failed"
        result["error"] = error.code
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def _read_stdin_json() -> Mapping[str, Any]:
    try:
        raw = sys.stdin.read()
        value = json.loads(raw)
    except Exception:
        raise CapacityError("invalid_json", "stdin did not contain valid JSON") from None
    if not isinstance(value, Mapping):
        raise CapacityError("invalid_config", "stdin JSON must be an object")
    return value


def _emit(value: Mapping[str, Any]) -> None:
    # Compact JSON and one final newline are intentional: the host parser can
    # consume exactly one record and no dependency output leaks to stdout.
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    sys.stdout.flush()


def _safe_failure_location(exc: BaseException) -> dict[str, Any]:
    """Expose only a safe exception class and the innermost runner.py frame.

    Exception messages and full tracebacks can contain URLs, credentials, or
    response data, so they must never be included in runner output.
    """

    frames = traceback.extract_tb(exc.__traceback__)
    runner_name = os.path.basename(__file__)
    runner_frames = [frame for frame in frames if os.path.basename(frame.filename) == runner_name]
    if not runner_frames:
        return {}
    frame = runner_frames[-1]
    exception_type = type(exc).__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", exception_type):
        exception_type = "Exception"
    function = frame.name if re.fullmatch(r"(?:[A-Za-z_][A-Za-z0-9_]{0,119}|<[^<>\r\n]{1,80}>)", frame.name) else "unknown"
    return {
        "failure_type": exception_type,
        "failure_site": {"file": runner_name, "function": function, "line": int(frame.lineno)},
    }


def main(argv: Optional[list[str]] = None) -> int:
    command = (argv or sys.argv[1:])
    if len(command) != 1 or command[0] not in {"prepare", "check", "run", "seed-alert-storm", "alert-storm"}:
        _emit({"status": "failed", "command": command[0] if command else "", "error": "invalid_command"})
        return 2
    try:
        cfg = validate_config(_read_stdin_json())
        if command[0] == "prepare":
            result = prepare(cfg)
        elif command[0] == "check":
            result = check(cfg)
        elif command[0] == "alert-storm":
            result = alert_storm(cfg)
        elif command[0] == "seed-alert-storm":
            result = seed_alert_storm(cfg)
        else:
            result = run(cfg)
        _emit(result)
        return 0 if command[0] == "run" or result.get("status") == "passed" else 1
    except Exception as exc:
        error = _redact_exception(exc, "runner_failed")
        result = {"status": "failed", "command": command[0], "error": error.code}
        if error.code == "runner_failed":
            result.update(_safe_failure_location(exc))
        _emit(result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
