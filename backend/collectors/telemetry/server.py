"""Independent gRPC Dial-out receiver for Huawei and H3C network devices.

The receiver loads asset-to-peer authorization from the shared monitoring
artifact volume. Device names in telemetry payloads are informational only;
asset identity comes exclusively from the authenticated transport peer map.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

try:
    import grpc
except ImportError:  # pragma: no cover - allow ReceiverState unit tests without grpcio installed
    grpc = None  # type: ignore[assignment]
import httpx

from collectors.telemetry.normalizer import TelemetryPayloadError, normalize_message
from collectors.telemetry.wire import (
    ProtobufWireError,
    decode_h3c_v2_dialout,
    decode_h3c_v3_data,
    decode_h3c_v3_envelope,
    decode_huawei_service_args,
    encode_h3c_v2_response,
    encode_h3c_v3_response,
    encode_huawei_service_args,
    fields,
)

logger = logging.getLogger("telemetry.receiver")
_CONFIG = Path(os.environ.get("TELEMETRY_RECEIVER_CONFIG", "/etc/nexora-collector/runtime/telemetry/receiver.json"))
_CONFIG_LIMIT_BYTES = 8 * 1024 * 1024
_MAX_BATCH_SAMPLES = 1000
_MAX_BATCH_BYTES = 1024 * 1024
_MAX_GRPC_MESSAGE_BYTES = 4 * 1024 * 1024
_MAX_GLOBAL_FRAGMENT_BYTES = 32 * 1024 * 1024
_MAX_GLOBAL_SERIES = 25_000
_MAX_GLOBAL_SAMPLE_RATE = 5_000.0


class ReceiverState:
    def __init__(self) -> None:
        self.config: dict[str, Any] = {"sources": [], "accept_insecure": False}
        self.limits: dict[str, float] = {
            "series": float(_MAX_GLOBAL_SERIES),
            "samples_per_second": _MAX_GLOBAL_SAMPLE_RATE,
        }
        self.config_mtime_ns = -1
        self.accepted_messages = 0
        self.rejected_messages = 0
        self.forwarded_samples = 0
        self.write_failures = 0
        self.last_error_code = ""
        self.started_at = time.time()
        self.lock = asyncio.Lock()
        self.subscription_stats: dict[str, dict[str, Any]] = {}
        self.series_by_subscription: dict[str, set[str]] = {}
        self.global_series: set[str] = set()
        self.latest_timestamp_by_series: dict[str, int] = {}
        self.last_counter_value_by_series: dict[str, float] = {}
        self.counter_offset_by_series: dict[str, float] = {}
        self.counter_bits_by_subscription: dict[str, dict[str, int]] = {}
        self.global_sample_tokens = _MAX_GLOBAL_SAMPLE_RATE * 2
        self.global_sample_tokens_updated = time.monotonic()
        self.subscription_sample_buckets: dict[str, dict[str, float]] = {}
        self.fragment_buffered_bytes = 0

    def reload_config(self) -> None:
        try:
            stat = _CONFIG.stat()
            if stat.st_size > _CONFIG_LIMIT_BYTES:
                self.config = {"sources": [], "accept_insecure": False}
                self.config_mtime_ns = stat.st_mtime_ns
                self.last_error_code = "CONFIG_TOO_LARGE"
                return
            if stat.st_mtime_ns == self.config_mtime_ns:
                return
            body = _CONFIG.read_bytes()
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("sources", []), list):
                raise ValueError("invalid receiver configuration")
            self.config = payload
            configured_limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
            self.limits = {
                "series": float(max(1, int(configured_limits.get("series") or _MAX_GLOBAL_SERIES))),
                "samples_per_second": max(1.0, float(configured_limits.get("samples_per_second") or _MAX_GLOBAL_SAMPLE_RATE)),
            }
            self.global_sample_tokens = min(
                self.global_sample_tokens,
                self.limits["samples_per_second"] * 2,
            )
            self.config_mtime_ns = stat.st_mtime_ns
            self.last_error_code = ""
            counter_bits_by_subscription: dict[str, dict[str, int]] = {}
            for source in self.config.get("sources", []):
                for subscription in source.get("subscriptions", []):
                    subscription_id = str(subscription.get("id") or "")
                    if subscription_id:
                        self.subscription_stats.setdefault(subscription_id, {
                            "last_received_at": None, "last_valid_at": None,
                            "sample_rate": 0.0, "samples_since_status": 0,
                            "dropped_samples": 0, "error_code": "",
                            "last_status_at": time.monotonic(),
                            "state": "AWAITING_DEVICE", "interval_seconds": int(subscription.get("interval_seconds") or 5),
                        })
                    counter_metrics: dict[str, int] = {}
                    for mapping in subscription.get("metric_mappings", []):
                        if not isinstance(mapping, dict):
                            continue
                        try:
                            if str(mapping.get("value_type") or "").casefold() != "counter" or not mapping.get("counter_bits"):
                                continue
                            bits = int(mapping["counter_bits"])
                            if not 1 <= bits <= 64:
                                continue
                            metric_key = re.sub(r"[^a-zA-Z0-9_]", "_", str(mapping.get("metric_key") or "")).lower()
                            metric_name = metric_key if metric_key.startswith("nexora_telemetry_") else f"nexora_telemetry_{metric_key}"
                            counter_metrics[metric_name] = bits
                        except (TypeError, ValueError):
                            continue
                    counter_bits_by_subscription[subscription_id] = counter_metrics
            self.counter_bits_by_subscription = counter_bits_by_subscription
        except FileNotFoundError:
            self.config = {"sources": [], "accept_insecure": False}
            self.limits = {"series": float(_MAX_GLOBAL_SERIES), "samples_per_second": _MAX_GLOBAL_SAMPLE_RATE}
            self.config_mtime_ns = -1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self.config = {"sources": [], "accept_insecure": False}
            self.limits = {"series": float(_MAX_GLOBAL_SERIES), "samples_per_second": _MAX_GLOBAL_SAMPLE_RATE}
            try:
                self.config_mtime_ns = _CONFIG.stat().st_mtime_ns
            except OSError:
                self.config_mtime_ns = -1
            self.last_error_code = "CONFIG_INVALID"
            logger.error("Telemetry receiver configuration could not be loaded")

    def accept_samples(self, subscription: dict[str, Any], samples: list[str]) -> list[str]:
        subscription_id = str(subscription.get("id") or "")
        if not subscription_id:
            return []
        stats = self.subscription_stats.setdefault(subscription_id, {
            "last_received_at": None, "last_received_mono": None,
            "last_valid_at": None, "last_valid_mono": None,
            "sample_rate": 0.0, "samples_since_status": 0,
            "dropped_samples": 0, "error_code": "",
            "clock_skew_ms": None,
            "last_status_at": time.monotonic(), "state": "AWAITING_DEVICE",
            "interval_seconds": int(subscription.get("interval_seconds") or 5),
        })
        now = time.monotonic()
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        stats["last_received_at"] = now_iso
        stats["last_received_mono"] = now
        stats["interval_seconds"] = int(subscription.get("interval_seconds") or 5)
        fingerprints = self.series_by_subscription.setdefault(subscription_id, set())
        reservation = int(subscription.get("reserved_series") or 0)
        max_series = max(1, int(self.limits.get("series") or _MAX_GLOBAL_SERIES))
        sample_rate_limit = max(1.0, float(self.limits.get("samples_per_second") or _MAX_GLOBAL_SAMPLE_RATE))
        limit = min(max_series, reservation) if reservation > 0 else max_series
        now = time.monotonic()
        elapsed = max(0.0, now - self.global_sample_tokens_updated)
        self.global_sample_tokens = min(
            sample_rate_limit * 2,
            self.global_sample_tokens + elapsed * sample_rate_limit,
        )
        self.global_sample_tokens_updated = now
        reserved_rate = max(0.0, float(subscription.get("reserved_sample_rate") or 0))
        bucket = self.subscription_sample_buckets.get(subscription_id)
        if bucket is None:
            burst = max(10.0, reserved_rate * 5)
            bucket = {"tokens": burst, "updated": now, "burst": burst}
            self.subscription_sample_buckets[subscription_id] = bucket
        else:
            burst = max(10.0, reserved_rate * 5)
            bucket["tokens"] = min(
                burst,
                bucket["tokens"] + max(0.0, now - bucket["updated"]) * reserved_rate,
            )
            bucket["updated"] = now
            bucket["burst"] = burst
        accepted: list[str] = []
        rate_limited_samples = 0
        series_limited = 0
        out_of_order_samples = 0
        now_ms = int(time.time() * 1000)
        counter_metrics = self.counter_bits_by_subscription.get(subscription_id, {})
        for line in samples:
            identity, raw_value_text, timestamp_text = line.rsplit(" ", 2)
            timestamp_ms = int(timestamp_text)
            raw_value = float(raw_value_text)
            fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            is_new = fingerprint not in fingerprints
            previous_timestamp = self.latest_timestamp_by_series.get(fingerprint)
            if previous_timestamp is not None and timestamp_ms <= previous_timestamp:
                out_of_order_samples += 1
                continue
            is_rate_limited = self.global_sample_tokens < 1 or (
                reserved_rate > 0 and bucket["tokens"] < 1
            )
            if is_rate_limited:
                rate_limited_samples += 1
                continue
            if is_new and (len(fingerprints) >= limit or len(self.global_series) >= max_series):
                series_limited += 1
                continue
            self.global_sample_tokens -= 1
            if reserved_rate > 0:
                bucket["tokens"] -= 1
            metric_name = identity.split("{", 1)[0]
            counter_bits = counter_metrics.get(metric_name)
            offset = self.counter_offset_by_series.get(fingerprint, 0.0)
            if counter_bits:
                previous_value = self.last_counter_value_by_series.get(fingerprint)
                modulus = float(1 << counter_bits)
                if previous_value is not None and raw_value < previous_value:
                    if previous_value >= modulus * 0.9 and raw_value <= modulus * 0.1:
                        offset += modulus
                        self.counter_offset_by_series[fingerprint] = offset
                self.last_counter_value_by_series[fingerprint] = raw_value
            adjusted_value = raw_value + offset if counter_bits else raw_value
            accepted.append(f"{identity} {adjusted_value:.15g} {timestamp_text}")
            self.latest_timestamp_by_series[fingerprint] = timestamp_ms
            stats["clock_skew_ms"] = timestamp_ms - now_ms
            if is_new:
                fingerprints.add(fingerprint)
                self.global_series.add(fingerprint)
        dropped = rate_limited_samples + series_limited + out_of_order_samples
        if dropped:
            stats["dropped_samples"] += dropped
            stats["error_code"] = (
                "SAMPLE_RATE_LIMIT_EXCEEDED" if rate_limited_samples else
                "OUT_OF_ORDER_SAMPLE" if out_of_order_samples else
                "SERIES_LIMIT_EXCEEDED"
            )
        elif accepted:
            stats["error_code"] = ""
        if accepted:
            stats["last_valid_at"] = now_iso
            stats["last_valid_mono"] = now
            stats["samples_since_status"] += len(accepted)
        stats["active_series"] = len(fingerprints)
        return accepted

    def status_snapshot(self) -> list[dict[str, Any]]:
        self.reload_config()
        now = time.monotonic()
        rows: list[dict[str, Any]] = []
        live_subscription_ids: set[str] = set()
        for source in self.config.get("sources", []):
            for subscription in source.get("subscriptions", []):
                subscription_id = str(subscription.get("id") or "")
                if not subscription_id:
                    continue
                live_subscription_ids.add(subscription_id)
                interval = max(1, int(subscription.get("interval_seconds") or 5))
                stats = self.subscription_stats.setdefault(subscription_id, {
                    "last_received_at": None, "last_received_mono": None,
                    "last_valid_at": None, "last_valid_mono": None,
                    "sample_rate": 0.0, "samples_since_status": 0,
                    "dropped_samples": 0, "error_code": "",
                    "last_status_at": now, "state": "AWAITING_DEVICE",
                    "interval_seconds": interval, "active_series": 0,
                })
                elapsed = max(1.0, now - float(stats.get("last_status_at") or now))
                stats["sample_rate"] = float(stats.get("samples_since_status") or 0) / elapsed
                stats["samples_since_status"] = 0
                stats["last_status_at"] = now
                last_received = stats.get("last_received_mono")
                last_valid = stats.get("last_valid_mono")
                connection_state = "AWAITING_DEVICE" if last_received is None else (
                    "CONNECTED" if now - last_received <= interval * 3 else "ERROR"
                )
                data_state = ("INVALID" if stats.get("error_code") else "NO_DATA") if last_valid is None else (
                    "FRESH" if now - last_valid <= interval * 3 else "STALE"
                )
                if stats.get("error_code") and data_state == "FRESH":
                    data_state = "PARTIAL"
                rows.append({
                    "subscription_id": subscription_id,
                    "last_received_at": stats.get("last_received_at"),
                    "last_valid_at": stats.get("last_valid_at"),
                    "active_series": int(stats.get("active_series") or 0),
                    "sample_rate": max(0.0, float(stats.get("sample_rate") or 0)),
                    "dropped_samples": int(stats.get("dropped_samples") or 0),
                    "clock_skew_ms": stats.get("clock_skew_ms"),
                    "error_code": str(stats.get("error_code") or ""),
                    "connection_state": connection_state,
                    "data_state": data_state,
                })
        for stale_id in set(self.subscription_stats) - live_subscription_ids:
            self.subscription_stats.pop(stale_id, None)
            self.subscription_sample_buckets.pop(stale_id, None)
            fingerprints = self.series_by_subscription.pop(stale_id, set())
            self.global_series.difference_update(fingerprints)
            for fingerprint in fingerprints:
                self.latest_timestamp_by_series.pop(fingerprint, None)
                self.last_counter_value_by_series.pop(fingerprint, None)
                self.counter_offset_by_series.pop(fingerprint, None)
            self.counter_bits_by_subscription.pop(stale_id, None)
        return rows


STATE = ReceiverState()


def _peer_ip(context: grpc.aio.ServicerContext) -> str:
    peer = str(context.peer() or "")
    for prefix in ("ipv4:", "ipv6:"):
        if peer.startswith(prefix):
            address = peer[len(prefix):].rsplit(":", 1)[0]
            if address.startswith("[") and address.endswith("]"):
                address = address[1:-1]
            return address
    return ""


def _peer_cert_id(context: grpc.aio.ServicerContext) -> set[str]:
    try:
        auth = context.auth_context() or {}
    except Exception:
        return set()
    identities: set[str] = set()
    for key in ("x509_common_name", "x509_subject_alternative_name"):
        for value in auth.get(key, ()):
            if isinstance(value, bytes):
                identities.add(value.decode("utf-8", "replace"))
    for value in auth.get("x509_pem_cert", ()):
        if isinstance(value, bytes):
            identities.add("sha256:" + hashlib.sha256(value).hexdigest())
            try:
                der = ssl.PEM_cert_to_DER_cert(value.decode("ascii"))
                identities.add("sha256:" + hashlib.sha256(der).hexdigest())
            except (UnicodeDecodeError, ValueError):
                pass
    return identities


def _resolve_source(context: grpc.aio.ServicerContext, vendor: str, protocol: str) -> dict[str, Any] | None:
    STATE.reload_config()
    remote_ip = _peer_ip(context)
    certificate_ids = _peer_cert_id(context)
    is_secure = bool(certificate_ids)
    allow_insecure = str(STATE.config.get("accept_insecure", "false")).strip().casefold() in {"1", "true", "yes", "on"}
    if not is_secure and not allow_insecure:
        return None
    for source in STATE.config.get("sources", []):
        if not isinstance(source, dict) or not source.get("enabled", True):
            continue
        if str(source.get("vendor") or "").casefold() != vendor.casefold():
            continue
        if str(source.get("protocol") or "").casefold() != protocol.casefold():
            continue
        if is_secure:
            allowed_ids = {str(value) for value in source.get("certificate_ids", [])}
            if not certificate_ids.intersection(allowed_ids):
                continue
            allowed_ips = {str(value) for value in source.get("allowed_source_ips", [])}
            if allowed_ips and (not remote_ip or remote_ip not in allowed_ips):
                continue
        else:
            allowed_ips = {str(value) for value in source.get("allowed_source_ips", [])}
            if not remote_ip or remote_ip not in allowed_ips:
                continue
        return source
    return None


async def _forward(samples: list[str]) -> None:
    if not samples:
        return
    url = os.environ.get("TELEMETRY_REMOTE_WRITE_URL", "http://vmagent:8429/api/v1/import/prometheus")
    timeout = httpx.Timeout(5.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        for offset in range(0, len(samples), _MAX_BATCH_SAMPLES):
            batch: list[str] = []
            size = 0
            for line in samples[offset:offset + _MAX_BATCH_SAMPLES]:
                encoded_size = len(line.encode("utf-8")) + 1
                if batch and size + encoded_size > _MAX_BATCH_BYTES:
                    response = await client.post(url, content=("\n".join(batch) + "\n").encode("utf-8"),
                                                 headers={"Content-Type": "text/plain; version=0.0.4"})
                    response.raise_for_status()
                    STATE.forwarded_samples += len(batch)
                    batch, size = [], 0
                if encoded_size > _MAX_BATCH_BYTES:
                    raise ValueError("single telemetry sample exceeds the write batch limit")
                batch.append(line)
                size += encoded_size
            if batch:
                response = await client.post(url, content=("\n".join(batch) + "\n").encode("utf-8"),
                                             headers={"Content-Type": "text/plain; version=0.0.4"})
                response.raise_for_status()
                STATE.forwarded_samples += len(batch)


def _source_subscriptions(source: dict[str, Any], path: str) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for subscription in source.get("subscriptions", []):
        if not isinstance(subscription, dict) or not subscription.get("enabled", False):
            continue
        path_filters = subscription.get("path_filters") or []
        if path_filters and not any(str(item).casefold() == path.casefold() for item in path_filters):
            continue
        matched.append(subscription)
    return matched


async def _accept_message(context, *, vendor: str, protocol: str, source_path: str,
                          payload: bytes, source_time: Any = None) -> None:
    source = _resolve_source(context, vendor, protocol)
    if source is None:
        STATE.rejected_messages += 1
        STATE.last_error_code = "SOURCE_UNAUTHORIZED"
        await context.abort(grpc.StatusCode.PERMISSION_DENIED, "source is not authorized")
    subscriptions = _source_subscriptions(source, source_path)
    if not subscriptions:
        STATE.rejected_messages += 1
        STATE.last_error_code = "SUBSCRIPTION_UNMAPPED"
        return
    for subscription in subscriptions:
        try:
            samples = normalize_message(
                payload=payload,
                source_path=source_path,
                source_timestamp=source_time,
                device=source,
                subscription=subscription,
            )
        except TelemetryPayloadError as exc:
            STATE.rejected_messages += 1
            STATE.last_error_code = exc.code
            subscription_id = str(subscription.get("id") or "")
            now_mono = time.monotonic()
            stats = STATE.subscription_stats.setdefault(subscription_id, {
                "last_received_at": None, "last_received_mono": None,
                "last_valid_at": None, "last_valid_mono": None,
                "sample_rate": 0.0, "samples_since_status": 0,
                "dropped_samples": 0, "error_code": "",
                "clock_skew_ms": None, "last_status_at": now_mono,
                "state": "AWAITING_DEVICE",
            })
            stats["last_received_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            stats["last_received_mono"] = now_mono
            stats["interval_seconds"] = int(subscription.get("interval_seconds") or 5)
            stats["error_code"] = exc.code
            continue
        samples = STATE.accept_samples(subscription, samples)
        if samples:
            try:
                await _forward(samples)
            except httpx.HTTPError:
                STATE.write_failures += 1
                stats = STATE.subscription_stats.get(str(subscription.get("id") or ""), {})
                stats["error_code"] = "REMOTE_WRITE_FAILED"
                raise
    STATE.accepted_messages += 1
    STATE.last_error_code = ""


async def _push_runtime_status() -> None:
    token_path = Path(os.environ.get("TELEMETRY_STATUS_TOKEN_FILE", "/run/telemetry-control/status.token"))
    endpoint = os.environ.get("TELEMETRY_STATUS_URL", "http://netops:8003/api/monitoring/telemetry/internal/status")
    while True:
        await asyncio.sleep(10)
        token = ""
        try:
            token = token_path.read_text(encoding="ascii").strip()
        except OSError:
            continue
        config = STATE.config
        collector_id = str(config.get("collector_id") or "")
        if not collector_id:
            continue
        items = STATE.status_snapshot()
        if not items:
            continue
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0), trust_env=False) as client:
                for offset in range(0, len(items), 500):
                    body = {"collector_id": collector_id, "items": items[offset:offset + 500]}
                    response = await client.post(endpoint, json=body, headers={"X-Telemetry-Token": token})
                    response.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Telemetry receiver runtime status update failed")


async def _huawei_data_publish(request_iterator: AsyncIterator[bytes], context: grpc.aio.ServicerContext):
    try:
        async for request in request_iterator:
            try:
                encoding, payload = decode_huawei_service_args(request)
                if encoding == "packed_data_json":
                    document = json.loads(payload.decode("utf-8"))
                    records = document.get("telemetry", []) if isinstance(document, dict) else []
                    if not isinstance(records, list):
                        raise ProtobufWireError("Huawei packed_data_json telemetry must be an array")
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        path = str(record.get("sensor_path") or "")
                        body = json.dumps(record, separators=(",", ":")).encode("utf-8")
                        await _accept_message(context, vendor="Huawei", protocol="huawei_grpc_dialout_json",
                                              source_path=path, payload=body,
                                              source_time=record.get("msg_timestamp"))
                else:
                    document = json.loads(payload.decode("utf-8"))
                    if not isinstance(document, dict):
                        raise ProtobufWireError("Huawei data_json must contain an object")
                    path = str(document.get("sensor_path") or document.get("path") or "")
                    await _accept_message(context, vendor="Huawei", protocol="huawei_grpc_dialout_json",
                                          source_path=path, payload=payload,
                                          source_time=document.get("msg_timestamp") or document.get("timestamp"))
            except (ProtobufWireError, ValueError, UnicodeDecodeError):
                STATE.rejected_messages += 1
                STATE.last_error_code = "PAYLOAD_INVALID"
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid telemetry payload")
            except httpx.HTTPError:
                STATE.write_failures += 1
                STATE.last_error_code = "REMOTE_WRITE_FAILED"
                await context.abort(grpc.StatusCode.UNAVAILABLE, "telemetry write unavailable")
            yield encode_huawei_service_args()
    except asyncio.CancelledError:
        raise


async def _h3c_dialout(request_iterator: AsyncIterator[bytes], context: grpc.aio.ServicerContext):
    try:
        async for request in request_iterator:
            try:
                producer, device_name, path, payload = decode_h3c_v2_dialout(request)
                document = json.loads(payload.decode("utf-8"))
                if not isinstance(document, dict):
                    raise ProtobufWireError("H3C jsonData must contain an object")
                source_time = document.get("Timestamp") or document.get("timestamp")
                await _accept_message(context, vendor="H3C", protocol="h3c_grpc_dialout_json_v2",
                                      source_path=path, payload=payload, source_time=source_time)
            except (ProtobufWireError, ValueError, UnicodeDecodeError):
                STATE.rejected_messages += 1
                STATE.last_error_code = "PAYLOAD_INVALID"
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid H3C telemetry payload")
            except httpx.HTTPError:
                STATE.write_failures += 1
                STATE.last_error_code = "REMOTE_WRITE_FAILED"
                await context.abort(grpc.StatusCode.UNAVAILABLE, "telemetry write unavailable")
        return encode_h3c_v2_response()
    except asyncio.CancelledError:
        raise


async def _h3c_v3_dialout(request_iterator: AsyncIterator[bytes], context: grpc.aio.ServicerContext):
    fragments: dict[int, tuple[float, int, bytearray]] = {}
    try:
        async for request in request_iterator:
            try:
                now = time.monotonic()
                for key, value in list(fragments.items()):
                    if now - value[0] > 5.0:
                        fragments.pop(key, None)
                        STATE.fragment_buffered_bytes = max(0, STATE.fragment_buffered_bytes - len(value[2]))
                request_id, total_size, payload = decode_h3c_v3_envelope(request)
                if total_size:
                    if total_size > _MAX_GRPC_MESSAGE_BYTES or not request_id or not payload:
                        raise ProtobufWireError("invalid H3C fragment declaration")
                    existing = fragments.get(request_id)
                    if existing is None:
                        if len(fragments) >= 8:
                            raise ProtobufWireError("H3C fragment queue is full")
                        existing = (now, total_size, bytearray())
                    elif existing[1] != total_size:
                        fragments.pop(request_id, None)
                        STATE.fragment_buffered_bytes = max(0, STATE.fragment_buffered_bytes - len(existing[2]))
                        raise ProtobufWireError("H3C fragment totalSize changed")
                    if STATE.fragment_buffered_bytes + len(payload) > _MAX_GLOBAL_FRAGMENT_BYTES:
                        prior = fragments.pop(request_id, None)
                        if prior:
                            STATE.fragment_buffered_bytes = max(0, STATE.fragment_buffered_bytes - len(prior[2]))
                        raise ProtobufWireError("global H3C fragment buffer is full")
                    existing[2].extend(payload)
                    STATE.fragment_buffered_bytes += len(payload)
                    if len(existing[2]) > total_size:
                        fragments.pop(request_id, None)
                        STATE.fragment_buffered_bytes = max(0, STATE.fragment_buffered_bytes - len(existing[2]))
                        raise ProtobufWireError("H3C fragment exceeds totalSize")
                    if len(existing[2]) < total_size:
                        fragments[request_id] = existing
                        yield encode_h3c_v3_response(request_id)
                        continue
                    payload = bytes(existing[2])
                    fragments.pop(request_id, None)
                    STATE.fragment_buffered_bytes = max(0, STATE.fragment_buffered_bytes - len(existing[2]))
                records = decode_h3c_v3_data(payload)
                for path, timestamp, record_payload in records:
                    await _accept_message(context, vendor="H3C", protocol="h3c_grpc_dialout_json_v3",
                                          source_path=path, payload=record_payload, source_time=timestamp)
                yield encode_h3c_v3_response(request_id)
            except (ProtobufWireError, ValueError, UnicodeDecodeError):
                STATE.rejected_messages += 1
                STATE.last_error_code = "PAYLOAD_INVALID"
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid H3C three-layer JSON payload")
            except httpx.HTTPError:
                STATE.write_failures += 1
                STATE.last_error_code = "REMOTE_WRITE_FAILED"
                await context.abort(grpc.StatusCode.UNAVAILABLE, "telemetry write unavailable")
    finally:
        for value in fragments.values():
            STATE.fragment_buffered_bytes = max(0, STATE.fragment_buffered_bytes - len(value[2]))


async def _http_health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request = await asyncio.wait_for(reader.readline(), timeout=2.0)
        method, path, _ = request.decode("ascii", "replace").strip().split(" ", 2)
        while await reader.readline() not in (b"\r\n", b"\n", b""):
            pass
        if method != "GET" or path not in {"/health", "/metrics"}:
            status, body, content_type = "404 Not Found", b"not found\n", "text/plain"
        elif path == "/health":
            STATE.reload_config()
            body, content_type = b"ok\n", "text/plain"
            status = "200 OK"
        else:
            uptime = max(0, time.time() - STATE.started_at)
            rows = [
                "# HELP nexora_telemetry_receiver_messages_total Messages accepted by the independent receiver.",
                "# TYPE nexora_telemetry_receiver_messages_total counter",
                f"nexora_telemetry_receiver_messages_total{{status=\"accepted\"}} {STATE.accepted_messages}",
                f"nexora_telemetry_receiver_messages_total{{status=\"rejected\"}} {STATE.rejected_messages}",
                "# HELP nexora_telemetry_receiver_samples_total Normalized samples forwarded to vmagent.",
                "# TYPE nexora_telemetry_receiver_samples_total counter",
                f"nexora_telemetry_receiver_samples_total {STATE.forwarded_samples}",
                "# HELP nexora_telemetry_receiver_write_failures_total Failed writes to vmagent.",
                "# TYPE nexora_telemetry_receiver_write_failures_total counter",
                f"nexora_telemetry_receiver_write_failures_total {STATE.write_failures}",
                "# HELP nexora_telemetry_receiver_uptime_seconds Receiver process uptime.",
                "# TYPE nexora_telemetry_receiver_uptime_seconds gauge",
                f"nexora_telemetry_receiver_uptime_seconds {uptime:.0f}",
            ]
            body, content_type = ("\n".join(rows) + "\n").encode(), "text/plain; version=0.0.4"
            status = "200 OK"
        writer.write(f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii") + body)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _load_server_credentials() -> grpc.ServerCredentials | None:
    cert_path = os.environ.get("TELEMETRY_SERVER_CERT_FILE", "")
    key_path = os.environ.get("TELEMETRY_SERVER_KEY_FILE", "")
    ca_path = os.environ.get("TELEMETRY_CLIENT_CA_FILE", "")
    provided = [bool(cert_path), bool(key_path), bool(ca_path)]
    if not any(provided):
        return None
    if not all(provided):
        raise RuntimeError("TLS receiver requires server cert, server key and client CA together")
    root = Path(ca_path).read_bytes()
    key = Path(key_path).read_bytes()
    cert = Path(cert_path).read_bytes()
    return grpc.ssl_server_credentials(
        [(key, cert)],
        root_certificates=root,
        require_client_auth=True,
    )


async def serve() -> None:
    STATE.reload_config()
    grpc_host = os.environ.get("TELEMETRY_GRPC_BIND", "0.0.0.0:10051")
    metrics_host = os.environ.get("TELEMETRY_HEALTH_BIND", "0.0.0.0:10052")
    options = [
        ("grpc.max_receive_message_length", _MAX_GRPC_MESSAGE_BYTES),
        ("grpc.max_send_message_length", 64 * 1024),
        ("grpc.max_concurrent_streams", 64),
    ]
    server = grpc.aio.server(options=options)
    raw = dict(
        request_deserializer=lambda value: value,
        response_serializer=lambda value: value,
    )
    method_handlers = {
        "dataPublish": grpc.stream_stream_rpc_method_handler(_huawei_data_publish, **raw),
    }
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler("huawei_dialout.gRPCDataservice", method_handlers),))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        "grpc_dialout.GRPCDialout",
        {"Dialout": grpc.stream_unary_rpc_method_handler(_h3c_dialout,
                                                         request_deserializer=lambda value: value,
                                                         response_serializer=lambda value: value)},
    ),))
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        "grpc_dialout_v3.gRPCDialoutV3",
        {"DialoutV3": grpc.stream_stream_rpc_method_handler(_h3c_v3_dialout, **raw)},
    ),))
    credentials = _load_server_credentials()
    if credentials is None and not bool(STATE.config.get("accept_insecure")):
        logger.warning("No TLS configured; receiver rejects unauthenticated sources unless an explicit IP allowlist is present")
    bound_port = server.add_insecure_port(grpc_host) if credentials is None else server.add_secure_port(grpc_host, credentials)
    if not bound_port:
        raise RuntimeError("Telemetry gRPC bind failed")
    await server.start()
    metrics_address, metrics_port = metrics_host.rsplit(":", 1)
    metrics_address = metrics_address.strip("[]")
    health_server = await asyncio.start_server(_http_health, metrics_address, int(metrics_port))
    status_task = asyncio.create_task(_push_runtime_status(), name="telemetry-runtime-status")
    async with health_server:
        try:
            await asyncio.gather(server.wait_for_termination(), health_server.serve_forever(), status_task)
        finally:
            status_task.cancel()
            await server.stop(grace=10)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
