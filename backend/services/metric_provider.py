"""Metric Provider abstraction for the native -> shadow -> VM migration."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlencode, urlparse, urlunparse
from urllib.request import Request, ProxyHandler, build_opener

logger = logging.getLogger(__name__)


def _default_connection_factory():
    from database import get_db_connection
    return get_db_connection()

ALLOWED_METRICS = {
    "cpu_usage_percent", "memory_usage_percent", "temperature_celsius",
    "interface_admin_status", "interface_oper_status", "interface_speed_bps",
    "interface_rx_bps", "interface_tx_bps", "interface_in_errors_rate",
    "interface_out_errors_rate", "interface_in_discards_rate", "interface_out_discards_rate",
    "device_uptime_seconds", "in_bps", "out_bps", "bw_in_pct", "bw_out_pct",
    "wireless_ap_online_count", "wireless_client_online_count",
}

CANONICAL_PROMQL = {
    "device_uptime_seconds": "sysUpTime",
    "cpu_usage_percent": "cpu_usage_percent",
    "memory_usage_percent": "memory_usage_percent",
    "temperature_celsius": "temperature_celsius",
    "wireless_ap_online_count": "wireless_ap_online_count",
    "wireless_client_online_count": "wireless_client_online_count",
    "interface_admin_status": "ifAdminStatus",
    "interface_oper_status": "ifOperStatus",
    "interface_speed_bps": "ifHighSpeed * 1000000",
    "interface_rx_bps": "rate(ifHCInOctets[5m]) * 8",
    "interface_tx_bps": "rate(ifHCOutOctets[5m]) * 8",
    "interface_in_errors_rate": "rate(ifInErrors[5m])",
    "interface_out_errors_rate": "rate(ifOutErrors[5m])",
    "interface_in_discards_rate": "rate(ifInDiscards[5m])",
    "interface_out_discards_rate": "rate(ifOutDiscards[5m])",
}


def counter_delta(current: int | float | None, previous: int | float | None, *, bits: int = 64) -> int | None:
    """Return a safe monotonic counter delta, including genuine wrap-around."""
    if current is None or previous is None or bits not in {32, 64}:
        return None
    try:
        current_i, previous_i = int(current), int(previous)
    except (TypeError, ValueError):
        return None
    if current_i < 0 or previous_i < 0:
        return None
    if current_i >= previous_i:
        return current_i - previous_i
    modulus = 1 << bits
    # A value near zero after a value near the modulus is a rollover.  A
    # backwards jump in the middle of the range is normally a device reset;
    # discard it rather than manufacturing a huge rate.
    if previous_i >= int(modulus * 0.75) and current_i <= int(modulus * 0.25):
        return modulus - previous_i + current_i
    return None


def counter_rate(current: int | float | None, previous: int | float | None, elapsed_seconds: float, *, bits: int = 64) -> float | None:
    if elapsed_seconds <= 0:
        return None
    delta = counter_delta(current, previous, bits=bits)
    return None if delta is None else delta / float(elapsed_seconds)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_result(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


class MetricProvider(ABC):
    """Backend-neutral query contract used by API and UI."""

    name: str = "unknown"

    @abstractmethod
    def instant(self, *, query: str, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def range(
        self,
        *,
        query: str,
        start: datetime,
        end: datetime,
        step_seconds: int,
        asset_id: str | None = None,
        metric_key: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def latest(self, *, asset_id: str, metric_key: str) -> dict[str, Any]:
        return self.instant(query=metric_key, asset_id=asset_id, metric_key=metric_key)

    def availability(self, *, asset_id: str, metric_key: str, window_seconds: int = 300) -> dict[str, Any]:
        end = datetime.now(timezone.utc)
        response = self.range(
            query=metric_key,
            start=end - timedelta(seconds=window_seconds),
            end=end,
            step_seconds=max(1, min(window_seconds, 60)),
            asset_id=asset_id,
            metric_key=metric_key,
        )
        values = response.get("data") or response.get("result") or []
        return {"available": bool(values), "sample_count": len(values) if isinstance(values, list) else 0, "provider": self.name}


class NativeMetricProvider(MetricProvider):
    """Read the existing PostgreSQL telemetry tables during migration."""

    name = "native"

    def __init__(self, connection_factory: Callable[[], Any] | None = None):
        self.connection_factory = connection_factory or _default_connection_factory

    @staticmethod
    def _metric_column(metric_key: str) -> tuple[str, str]:
        metric = str(metric_key or "").strip()
        if metric not in ALLOWED_METRICS:
            raise ValueError(f"Unsupported metric key: {metric}")
        if metric in {"wireless_ap_online_count", "wireless_client_online_count"}:
            return "wireless", metric
        if metric in {"cpu_usage_percent", "memory_usage_percent", "temperature_celsius"}:
            return "device", {"cpu_usage_percent": "cpu_usage", "memory_usage_percent": "memory_usage", "temperature_celsius": "temp"}[metric]
        mapping = {
            "in_bps": "avg_in_bps", "interface_rx_bps": "avg_in_bps",
            "out_bps": "avg_out_bps", "interface_tx_bps": "avg_out_bps",
            "bw_in_pct": "avg_bw_in_pct", "bw_out_pct": "avg_bw_out_pct",
            "interface_in_errors_rate": "err_delta_sum",
            "interface_out_errors_rate": "err_delta_sum",
            "interface_in_discards_rate": "discard_delta_sum",
            "interface_out_discards_rate": "discard_delta_sum",
        }
        return "interface", mapping.get(metric, metric)

    def instant(self, *, query: str, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        key = metric_key or query
        if key in {"wireless_ap_online_count", "wireless_client_online_count"}:
            return {"provider": self.name, "metric_key": key, "data": []}
        if key in {"interface_admin_status", "interface_oper_status", "interface_speed_bps"}:
            if not asset_id:
                return {"provider": self.name, "metric_key": key, "data": []}
            conn = self.connection_factory()
            try:
                column = {"interface_admin_status": "admin_status", "interface_oper_status": "oper_status", "interface_speed_bps": "speed"}[key]
                rows = conn.execute(f"SELECT device_id, interface_name, {column} AS value FROM interfaces WHERE device_id = ? ORDER BY interface_name", (asset_id,)).fetchall()
                data = []
                for row in rows:
                    raw_value = row["value"]
                    if key != "interface_speed_bps":
                        normalized = str(raw_value or "").strip().lower()
                        raw_value = 1 if normalized in {"up", "enabled", "1", "true"} else 2 if normalized in {"down", "disabled", "0", "false"} else 0
                    data.append({"asset_id": asset_id, "interface_name": row["interface_name"], "value": _float(raw_value)})
                return {"provider": self.name, "metric_key": key, "data": data}
            finally:
                conn.close()
        source, column = self._metric_column(key)
        if not asset_id:
            return {"provider": self.name, "metric_key": key, "data": []}
        conn = self.connection_factory()
        try:
            if source == "device":
                row = conn.execute(f"SELECT id, {column} AS value FROM devices WHERE id = ?", (asset_id,)).fetchone()
                data = [] if not row else [{"asset_id": asset_id, "value": _float(row["value"] if hasattr(row, "keys") else row[1])}]
            else:
                # Keep the lookup bounded and use the latest native rollup.
                row = conn.execute(
                    f"SELECT device_id, ts_minute, {column} AS value FROM interface_telemetry_1m WHERE device_id = ? ORDER BY ts_minute DESC LIMIT 1",
                    (asset_id,),
                ).fetchone()
                data = [] if not row else [{"asset_id": asset_id, "timestamp": row["ts_minute"], "value": _float(row["value"])}]
            return {"provider": self.name, "metric_key": key, "data": data}
        finally:
            conn.close()

    def range(self, *, query: str, start: datetime, end: datetime, step_seconds: int, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        key = metric_key or query
        if key in {"wireless_ap_online_count", "wireless_client_online_count"}:
            return {"provider": self.name, "metric_key": key, "step_seconds": step_seconds, "data": []}
        if key in {"interface_admin_status", "interface_oper_status", "interface_speed_bps"}:
            return self.instant(query=key, asset_id=asset_id, metric_key=key)
        source, column = self._metric_column(key)
        if not asset_id:
            return {"provider": self.name, "metric_key": key, "data": []}
        conn = self.connection_factory()
        try:
            start_s, end_s = _utc(start).isoformat(), _utc(end).isoformat()
            if source == "device":
                # Device snapshots are not historically dense; current values
                # are still returned as a single point for provider parity.
                row = conn.execute(f"SELECT id, {column} AS value FROM devices WHERE id = ?", (asset_id,)).fetchone()
                data = [] if not row else [{"asset_id": asset_id, "timestamp": end_s, "value": _float(row["value"])}]
            else:
                rows = conn.execute(
                    f"SELECT device_id, ts_minute, {column} AS value FROM interface_telemetry_1m WHERE device_id = ? AND ts_minute >= ? AND ts_minute <= ? ORDER BY ts_minute ASC",
                    (asset_id, start_s, end_s),
                ).fetchall()
                rate_metric = key in {
                    "interface_in_errors_rate", "interface_out_errors_rate",
                    "interface_in_discards_rate", "interface_out_discards_rate",
                }
                data = [{
                    "asset_id": asset_id,
                    "timestamp": row["ts_minute"],
                    "value": (_float(row["value"]) / max(1, int(step_seconds))) if rate_metric and _float(row["value"]) is not None else _float(row["value"]),
                } for row in rows]
            return {"provider": self.name, "metric_key": key, "step_seconds": step_seconds, "data": data}
        finally:
            conn.close()


def extract_instant_metric_value(result_data: Any) -> float | None:
    """Extract a scalar float value from Prometheus/VictoriaMetrics instant query result data."""
    if not isinstance(result_data, list) or not result_data:
        return None
    values: list[float] = []
    for item in result_data:
        if isinstance(item, Mapping):
            val_pair = item.get("value")
            if isinstance(val_pair, (list, tuple)) and len(val_pair) > 1:
                try:
                    val = float(val_pair[1])
                    if val == val:  # not NaN
                        values.append(val)
                except (ValueError, TypeError):
                    pass
    if not values:
        return None
    return round(max(values), 1)


class VictoriaMetricsMetricProvider(MetricProvider):
    """Query VictoriaMetrics through its internal HTTP API."""

    name = "victoriametrics"

    def __init__(self, base_url: str | None = None, *, timeout_seconds: float = 5.0, opener=None):
        raw = (base_url or os.environ.get("VICTORIAMETRICS_URL") or "http://victoriametrics:8428").strip().rstrip("/")
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname:
            raise ValueError("VICTORIAMETRICS_URL must be an http(s) URL without embedded credentials")
        configured_hosts = {item.strip().lower().rstrip(".") for item in str(os.environ.get("VICTORIAMETRICS_ALLOWED_HOSTS", "victoriametrics,localhost,127.0.0.1")).split(",") if item.strip()}
        if parsed.hostname.lower().rstrip(".") not in configured_hosts:
            raise ValueError("VICTORIAMETRICS_URL host is not allowlisted")
        if parsed.port not in (None, 8428):
            raise ValueError("VICTORIAMETRICS_URL must use port 8428")
        self.base_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        self.timeout_seconds = timeout_seconds
        # Bypass ambient HTTP(S)_PROXY variables.  VM is an internal service;
        # only the explicitly allowlisted host and port above are reachable.
        self.opener = opener or build_opener(ProxyHandler({})).open

    def _request(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "nexora-monitoring/1"}, method="GET")
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                body = response.read()
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("VictoriaMetrics returned a non-object response")
            return payload
        except Exception as exc:
            logger.warning("VictoriaMetrics query failed: %s", exc)
            return {"status": "error", "errorType": type(exc).__name__, "error": str(exc), "data": []}

    @staticmethod
    def _selector(query: str, asset_id: str | None) -> str:
        key = str(query or "").strip()
        escaped = str(asset_id or "").replace('\\', '\\\\').replace('"', '\\"')
        is_regex = bool(asset_id and "|" in asset_id)
        match_op = "=~" if is_regex else "="
        selector = f'{{asset_id{match_op}"{escaped}"}}' if asset_id else ""

        if key == "cpu_usage_percent":
            candidates = (
                "cpmCPUTotal1minRev",
                "hh3cEntityExtCpuUsage",
                "hwEntityCpuUsage",
                "ruijieCpuCostRate",
                "jnxOperatingCPU",
                "fnSysCpuUsage",
                "zteCpuRate",
                "mpCpuUtilization5Min",
                "dptechCpuUsage",
                "hillstoneCPUUtilization",
                "sangforCpuUsage",
                "dcnCpuUsage",
                "cpu_usage_percent",
            )
            return " or ".join(f"{name}{selector}" for name in candidates)

        if key == "memory_usage_percent":
            candidates = (
                "hh3cEntityExtMemUsage",
                "hwEntityMemUsage",
                "ruijieMemoryPoolCurrentUtilization",
                "jnxOperatingBuffer",
                "fnSysMemUsage",
                "zteMemRate",
                "mpMemoryUtilization",
                "dptechMemUsage",
                "hillstoneMemoryUtilization",
                "sangforMemUsage",
                "dcnMemUsage",
                "memory_usage_percent",
            )
            return " or ".join(f"{name}{selector}" for name in candidates)

        if key == "temperature_celsius":
            candidates = (
                "hh3cEntityExtTemperature",
                "hwEntityTemperature",
                "ruijieDeviceTemperature",
                "jnxOperatingTemp",
                "entSensorValue",
                "zteTemperature",
                "mpTemperature",
                "dptechTemperature",
                "dcnTemperature",
                "temperature_celsius",
            )
            return " or ".join(f"{name}{selector}" for name in candidates)

        if key == "wireless_ap_online_count":
            candidates = (
                "hwWlanCurOnlineApNum",
                "hh3cDot11CurrOnlineAPNum",
                "ruijieApcOnlineApNum",
                "ruijieApcTotalApNum",
                "cLApTotalUpAPs",
                "wlsxSysExtAccessPointsNum",
                "ruckusZDTotalNumAP",
                "wireless_ap_online_count",
            )
            return " or ".join(f"{name}{selector}" for name in candidates)

        if key == "wireless_client_online_count":
            candidates = (
                "hwWlanCurAssocUserNum",
                "hh3cDot11CurrAssocUserNum",
                "ruijieApcTotalStaNum",
                "cLSysTotalNumOfClients",
                "wlsxSysExtStationsNum",
                "ruckusZDTotalNumSta",
                "wireless_client_online_count",
            )
            return " or ".join(f"{name}{selector}" for name in candidates)

        metric = CANONICAL_PROMQL.get(key)
        if metric is None:
            if not key or not re.fullmatch(r"[A-Za-z_:][A-Za-z0-9_:]*", key):
                raise ValueError("Metric query contains unsupported characters")
            metric = key
        if not asset_id:
            return metric
        # Apply the stable asset selector inside rate() expressions; a label
        # matcher appended after the expression would be invalid PromQL.
        for raw_metric in ("ifHCInOctets", "ifHCOutOctets", "ifInErrors", "ifOutErrors", "ifInDiscards", "ifOutDiscards"):
            metric = metric.replace(f"{raw_metric}[", f"{raw_metric}{selector}[")
        if metric == CANONICAL_PROMQL.get(key):
            if "{" not in metric and " " not in metric:
                metric = f"{metric}{selector}"
            elif metric.startswith("ifHighSpeed"):
                metric = metric.replace("ifHighSpeed", f"ifHighSpeed{selector}", 1)
            elif "{" not in metric:
                # Gauge expressions without a known raw selector are kept
                # bounded to a canonical metric name.
                metric = f"{metric}{selector}"
        return metric

    def instant(self, *, query: str, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        selector = self._selector(query, asset_id)
        payload = self._request("/api/v1/query", {"query": selector})
        return {"provider": self.name, "metric_key": metric_key or query, "data": payload.get("data", {}).get("result", []) if isinstance(payload.get("data"), dict) else [], "status": payload.get("status", "error"), "error": payload.get("error")}

    def range(self, *, query: str, start: datetime, end: datetime, step_seconds: int, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        selector = self._selector(query, asset_id)
        payload = self._request("/api/v1/query_range", {"query": selector, "start": _utc(start).timestamp(), "end": _utc(end).timestamp(), "step": int(step_seconds)})
        return {"provider": self.name, "metric_key": metric_key or query, "data": payload.get("data", {}).get("result", []) if isinstance(payload.get("data"), dict) else [], "status": payload.get("status", "error"), "error": payload.get("error")}


class ShadowMetricProvider(MetricProvider):
    """Expose the native result while recording VM parity observations."""

    name = "shadow"

    def __init__(self, primary: MetricProvider, shadow: MetricProvider, *, tolerance: float = 0.05, sink: Callable[[dict[str, Any]], None] | None = None):
        self.primary = primary
        self.shadow = shadow
        self.tolerance = max(0.0, float(tolerance))
        self.sink = sink

    def _compare(self, native: dict[str, Any], vm: dict[str, Any], *, asset_id: str | None, metric_key: str | None) -> dict[str, Any]:
        native_values = native.get("data") or []
        vm_values = vm.get("data") or []
        def value(items: Any) -> float | None:
            if not isinstance(items, list) or not items:
                return None
            item = items[-1]
            if isinstance(item, Mapping):
                if "value" in item: return _float(item.get("value"))
                if isinstance(item.get("value"), list) and len(item["value"]) > 1: return _float(item["value"][1])
                if isinstance(item.get("values"), list) and item["values"]: return _float(item["values"][-1][1])
            return None
        left, right = value(native_values), value(vm_values)
        delta = None if left is None or right is None else abs(left - right)
        allowed = self.tolerance * max(abs(left or 0.0), 1.0)
        comparison = {"asset_id": asset_id, "metric_key": metric_key, "native_value": left, "vm_value": right, "delta": delta, "tolerance": allowed, "status": "MATCH" if delta is not None and delta <= allowed else "MISMATCH", "sampled_at": datetime.now(timezone.utc).isoformat()}
        if self.sink:
            self.sink(comparison)
        return comparison

    def instant(self, *, query: str, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        native = self.primary.instant(query=query, asset_id=asset_id, metric_key=metric_key)
        vm = self.shadow.instant(query=query, asset_id=asset_id, metric_key=metric_key)
        comparison = self._compare(native, vm, asset_id=asset_id, metric_key=metric_key or query)
        native["provider"] = self.name
        native["shadow"] = comparison
        return native

    def range(self, *, query: str, start: datetime, end: datetime, step_seconds: int, asset_id: str | None = None, metric_key: str | None = None) -> dict[str, Any]:
        native = self.primary.range(query=query, start=start, end=end, step_seconds=step_seconds, asset_id=asset_id, metric_key=metric_key)
        vm = self.shadow.range(query=query, start=start, end=end, step_seconds=step_seconds, asset_id=asset_id, metric_key=metric_key)
        comparison = self._compare(native, vm, asset_id=asset_id, metric_key=metric_key or query)
        native["provider"] = self.name
        native["shadow"] = comparison
        return native

    def compare_metrics(self, *, asset_id: str, metric_keys: tuple[str, ...] | list[str] = ()) -> list[dict[str, Any]]:
        """Run the PoC parity set in one call (CPU, memory, oper, traffic, errors)."""
        keys = tuple(metric_keys) or (
            "cpu_usage_percent", "memory_usage_percent", "interface_oper_status",
            "interface_rx_bps", "interface_in_errors_rate",
        )
        results = []
        for metric_key in keys:
            result = self.instant(query=metric_key, asset_id=asset_id, metric_key=metric_key)
            if result.get("shadow"):
                results.append(result["shadow"])
        return results


def persist_shadow_comparison(connection: Any, comparison: Mapping[str, Any]) -> None:
    """Persist a secret-free comparison row for the migration audit trail."""
    connection.execute(
        """INSERT INTO monitoring_shadow_comparisons
           (id, asset_id, metric_key, native_value, vm_value, delta, tolerance,
            status, sampled_at, details_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            f"shadow-{uuid.uuid4().hex[:20]}",
            str(comparison.get("asset_id") or ""),
            str(comparison.get("metric_key") or ""),
            comparison.get("native_value"), comparison.get("vm_value"),
            comparison.get("delta"), comparison.get("tolerance") or 0,
            str(comparison.get("status") or "UNKNOWN"),
            str(comparison.get("sampled_at") or datetime.now(timezone.utc).isoformat()),
            json.dumps({"provider": "shadow"}, ensure_ascii=False),
        ),
    )


def _default_shadow_sink(comparison: Mapping[str, Any]) -> None:
    """Best-effort durable sink used by the API's shadow mode."""
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            persist_shadow_comparison(conn, comparison)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Unable to persist monitoring shadow comparison", exc_info=True)


def provider_from_environment(*, connection_factory: Callable[[], Any] | None = None, mode: str | None = None) -> MetricProvider:
    mode = str(mode or os.environ.get("MONITORING_METRIC_BACKEND", "native")).strip().lower()
    native = NativeMetricProvider(connection_factory)
    if mode == "victoriametrics":
        return VictoriaMetricsMetricProvider()
    if mode == "shadow":
        return ShadowMetricProvider(native, VictoriaMetricsMetricProvider(), sink=_default_shadow_sink)
    if mode != "native":
        logger.warning("Unknown MONITORING_METRIC_BACKEND=%s; using native", mode)
    return native
