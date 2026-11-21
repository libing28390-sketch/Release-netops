"""Bounded JSON-to-Prometheus normalization for vendor Dial-out messages."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable


_METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]{0,199}$")
_METRIC_KEY = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,159}$")
_LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,99}$")
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_DEPTH = 32
_MAX_POINTS_PER_MESSAGE = 10_000
_MAX_CLOCK_SKEW_MS = 5 * 60 * 1000


class TelemetryPayloadError(ValueError):
    def __init__(self, message: str, code: str = "PAYLOAD_INVALID") -> None:
        super().__init__(message)
        self.code = code


def _escape_label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')[:512]


def _lookup_path(document: Any, expression: str) -> Iterable[tuple[Any, dict[str, Any]]]:
    """Resolve a deliberately small JSON path grammar: ``a.b[*].c``."""
    normalized_expr = str(expression or "").replace("[*]", ".*").strip(".")
    tokens = [token for token in normalized_expr.split(".") if token]
    current: list[tuple[Any, dict[str, Any]]] = [(document, {})]
    for token in tokens:
        next_values: list[tuple[Any, dict[str, Any]]] = []
        if token == "*":
            for value, labels in current:
                if isinstance(value, list):
                    next_values.extend((item, {**labels, "index": index, "__object": item}) for index, item in enumerate(value))
                elif isinstance(value, dict):
                    next_values.extend((item, {**labels, "key": key, "__object": item}) for key, item in value.items())
        else:
            for value, labels in current:
                if isinstance(value, dict) and token in value:
                    next_values.append((value[token], labels))
        current = next_values
        if not current:
            break
    return current


def _timestamp_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = None
    if numeric is not None and math.isfinite(numeric) and numeric > 0:
        if numeric > 1e17:
            return int(numeric / 1e6)
        if numeric > 1e14:
            return int(numeric / 1e3)
        if numeric > 1e11:
            return int(numeric)
        if numeric > 1e8:
            return int(numeric * 1000)
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _resolve_object_path(value: Any, path: str) -> Any:
    if not path:
        return None
    resolved = list(_lookup_path(value, path))
    return resolved[0][0] if resolved else None


def normalize_message(
    *,
    payload: bytes,
    source_path: str,
    source_timestamp: Any,
    device: dict[str, Any],
    subscription: dict[str, Any],
) -> list[str]:
    if not isinstance(payload, bytes) or len(payload) > _MAX_JSON_BYTES:
        raise TelemetryPayloadError("telemetry JSON payload exceeds the configured byte limit")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelemetryPayloadError("telemetry payload is not valid UTF-8 JSON") from exc
    if not isinstance(document, (dict, list)):
        raise TelemetryPayloadError("telemetry JSON root must be an object or array")

    mappings = subscription.get("metric_mappings") or []
    if not isinstance(mappings, list):
        raise TelemetryPayloadError("subscription metric_mappings must be an array")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    sample_time = _timestamp_ms(source_timestamp)
    if sample_time is None:
        sample_time = now_ms
    elif abs(sample_time - now_ms) > _MAX_CLOCK_SKEW_MS:
        raise TelemetryPayloadError(
            "device timestamp is more than five minutes from collector time",
            "CLOCK_SKEW",
        )
    output: list[str] = []
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        expected_path = str(mapping.get("source_path") or "").strip()
        if expected_path and expected_path.casefold() != str(source_path or "").strip().casefold():
            continue
        metric_key = str(mapping.get("metric_key") or "").strip()
        source_field = str(mapping.get("source_field") or "").strip()
        if not _METRIC_KEY.fullmatch(metric_key) or not source_field:
            continue
        normalized_key = re.sub(r"[^a-zA-Z0-9_]", "_", metric_key).lower()
        metric_name = normalized_key if normalized_key.startswith("nexora_telemetry_") else f"nexora_telemetry_{normalized_key}"
        if not _METRIC_NAME.fullmatch(metric_name):
            continue
        values = list(_lookup_path(document, source_field))
        for value, wildcard_labels in values:
            if len(output) >= _MAX_POINTS_PER_MESSAGE:
                raise TelemetryPayloadError("telemetry message exceeds the sample count limit")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                continue
            transform = str(mapping.get("transform") or "identity").strip().casefold()
            transform_value = 1.0
            if transform.startswith("scale:"):
                try:
                    transform_value = float(transform.split(":", 1)[1])
                except ValueError:
                    raise TelemetryPayloadError("metric mapping contains an invalid scale transform") from None
            elif transform not in {"", "identity"}:
                raise TelemetryPayloadError("metric mapping transform is not supported by this decoder")
            normalized_value = float(value) * transform_value
            labels = {
                "tenant_id": device.get("tenant_id"),
                "asset_id": device.get("asset_id"),
                "device_id": device.get("device_id"),
                "subscription_id": subscription.get("id"),
                "hostname": device.get("hostname"),
                "vendor": device.get("vendor"),
                "platform": device.get("platform"),
                "source_type": "telemetry",
                "source_path": str(source_path or "")[:160],
            }
            configured_labels = mapping.get("labels") if isinstance(mapping.get("labels"), dict) else {}
            configured_labels = mapping.get("primary_key_mapping") if isinstance(mapping.get("primary_key_mapping"), dict) else configured_labels
            current_object = wildcard_labels.get("__object", document)
            for label_name, json_path in configured_labels.items():
                if not _LABEL_NAME.fullmatch(str(label_name)):
                    continue
                label_value = _resolve_object_path(current_object, str(json_path))
                if label_value is not None and isinstance(label_value, (str, int, float)):
                    labels[str(label_name)] = label_value
            for label_name, label_value in wildcard_labels.items():
                if str(label_name).startswith("__"):
                    continue
                safe_name = "telemetry_" + str(label_name)
                if _LABEL_NAME.fullmatch(safe_name):
                    labels.setdefault(safe_name, label_value)
            if mapping.get("unit"):
                labels["unit"] = str(mapping.get("unit"))[:64]
            labels = dict(list(sorted(labels.items()))[:20])
            rendered_labels = ",".join(
                f'{name}="{_escape_label(value)}"'
                for name, value in sorted(labels.items())
                if value not in (None, "")
            )
            output.append(f"{metric_name}{{{rendered_labels}}} {normalized_value:.15g} {sample_time}")
    return output
