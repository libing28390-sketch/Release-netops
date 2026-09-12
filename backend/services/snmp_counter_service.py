"""SNMP counter arithmetic and durable baseline helpers.

Counters are monotonically increasing values, not gauges.  The only safe rate
is derived from two valid samples and the actual elapsed time.  This module is
kept free of network code so the arithmetic can be tested independently of a
device and reused by both model-defined metrics and interface telemetry.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection


VALID_COUNTER_BITS = (32, 64)
MIN_COUNTER_INTERVAL_SEC = 1.0
MAX_COUNTER_INTERVAL_SEC = 24 * 60 * 60.0


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_counter_bits(bits: Any) -> int:
    try:
        normalized = int(bits)
    except (TypeError, ValueError) as exc:
        raise ValueError("counter_bits must be 32 or 64; it cannot be guessed") from exc
    if normalized not in VALID_COUNTER_BITS:
        raise ValueError("counter_bits must be exactly 32 or 64")
    return normalized


def calculate_counter_delta(
    current: Any,
    previous: Any,
    elapsed_sec: Any,
    counter_bits: Any,
    *,
    max_rate_per_sec: float | None = None,
    current_uptime_cs: int | None = None,
    previous_uptime_cs: int | None = None,
) -> dict[str, Any]:
    """Calculate one counter delta with explicit wrap/reset quality.

    A negative delta is accepted as a single wrap only when the previous
    value was near the modulus ceiling and the current value is near zero, or
    when a configured physical maximum makes the candidate plausible.  A
    reboot/uptime decrease always wins over wrap detection and produces a
    baseline sample instead of a false spike.
    """
    bits = validate_counter_bits(counter_bits)
    now = _finite_number(current)
    old = _finite_number(previous)
    elapsed = _finite_number(elapsed_sec)
    if now is None or now < 0:
        return {"status": "invalid", "delta": None, "rate_per_sec": None, "counter_bits": bits}
    if old is None:
        return {"status": "baseline", "delta": None, "rate_per_sec": None, "counter_bits": bits}
    if old < 0:
        return {"status": "invalid", "delta": None, "rate_per_sec": None, "counter_bits": bits}
    if elapsed is None or elapsed < MIN_COUNTER_INTERVAL_SEC or elapsed > MAX_COUNTER_INTERVAL_SEC:
        return {"status": "interval_abnormal", "delta": None, "rate_per_sec": None, "counter_bits": bits}

    # sysUpTime is expressed in centiseconds.  It is optional because some
    # restricted SNMP views do not expose it, but if present it is decisive.
    if current_uptime_cs is not None and previous_uptime_cs is not None:
        try:
            if int(current_uptime_cs) < int(previous_uptime_cs):
                return {"status": "device_restart", "delta": None, "rate_per_sec": None, "counter_bits": bits}
        except (TypeError, ValueError):
            pass

    delta = now - old
    wrapped = False
    if delta < 0:
        modulus = float(1 << bits)
        candidate = now + modulus - old
        max_rate = _finite_number(max_rate_per_sec)
        if max_rate is not None and max_rate >= 0 and max_rate * elapsed >= modulus:
            # More than one wrap could have occurred between samples.  There
            # is no information in two values alone to distinguish that from
            # a reset, so fail closed instead of manufacturing a rate.
            return {
                "status": "multiple_wraps_possible",
                "delta": None,
                "rate_per_sec": None,
                "counter_bits": bits,
            }
        plausible_by_rate = (
            max_rate is not None
            and max_rate >= 0
            and candidate <= max_rate * elapsed * 1.25
        )
        plausible_by_position = old >= modulus * 0.75 and now <= modulus * 0.25
        if not plausible_by_rate and not plausible_by_position:
            return {
                "status": "ambiguous_wrap_or_reset",
                "delta": None,
                "rate_per_sec": None,
                "counter_bits": bits,
            }
        delta = candidate
        wrapped = True

    if max_rate_per_sec is not None:
        max_rate = _finite_number(max_rate_per_sec)
        if max_rate is not None and max_rate >= 0 and delta > max_rate * elapsed * 1.25:
            return {"status": "implausible_rate", "delta": None, "rate_per_sec": None, "counter_bits": bits}

    return {
        "status": "wrapped" if wrapped else "ok",
        "delta": int(delta),
        "rate_per_sec": float(delta / elapsed),
        "counter_bits": bits,
        "wrapped": wrapped,
    }


def load_counter_sample(device_id: str, profile_id: str, metric_name: str) -> dict[str, Any] | None:
    if not device_id or not profile_id or not metric_name:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM snmp_metric_counter_samples "
            "WHERE device_id = ? AND profile_id = ? AND metric_name = ?",
            (device_id, profile_id, metric_name),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["values"] = json.loads(item.get("values_json") or "{}")
        except (TypeError, ValueError):
            item["values"] = {}
        return item
    except Exception:
        # The collector must not fail the whole device poll when an older
        # database has not applied the additive migration yet.
        return None
    finally:
        conn.close()


def save_counter_sample(
    *,
    device_id: str,
    profile_id: str,
    metric_name: str,
    oid: str,
    config_hash: str,
    counter_bits: int,
    values: dict[str, int | float],
    sampled_at: str,
    device_uptime_cs: int | None = None,
) -> None:
    if not device_id or not profile_id or not metric_name or not values:
        return
    now = _utc_now()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO snmp_metric_counter_samples
                (device_id, profile_id, metric_name, oid, config_hash,
                 counter_bits, values_json, sampled_at, device_uptime_cs, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, profile_id, metric_name) DO UPDATE SET
                oid = excluded.oid,
                config_hash = excluded.config_hash,
                counter_bits = excluded.counter_bits,
                values_json = excluded.values_json,
                sampled_at = excluded.sampled_at,
                device_uptime_cs = excluded.device_uptime_cs,
                updated_at = excluded.updated_at
            """,
            (
                device_id,
                profile_id,
                metric_name,
                oid,
                config_hash,
                int(counter_bits),
                json.dumps(values, separators=(",", ":"), ensure_ascii=False),
                sampled_at,
                device_uptime_cs,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def load_interface_counter_sample(device_id: str, profile_id: str) -> dict[str, Any] | None:
    """Load the last IF-MIB snapshot for one device/template pair."""
    if not device_id or not profile_id:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM snmp_interface_counter_samples "
            "WHERE device_id = ? AND profile_id = ?",
            (device_id, profile_id),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item['values'] = json.loads(item.get('values_json') or '{}')
        except (TypeError, ValueError):
            item['values'] = {}
        return item
    except Exception:
        # Older databases can start before the additive migration is applied;
        # the process-local baseline remains a safe fallback in that case.
        return None
    finally:
        conn.close()


def save_interface_counter_sample(
    *,
    device_id: str,
    profile_id: str,
    config_hash: str,
    values: dict[str, Any],
    sampled_at: str,
    device_uptime_cs: int | None = None,
) -> None:
    """Persist a complete interface snapshot without storing credentials."""
    if not device_id or not profile_id or not values:
        return
    now = _utc_now()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO snmp_interface_counter_samples
                (device_id, profile_id, config_hash, values_json, sampled_at,
                 device_uptime_cs, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, profile_id) DO UPDATE SET
                config_hash = excluded.config_hash,
                values_json = excluded.values_json,
                sampled_at = excluded.sampled_at,
                device_uptime_cs = excluded.device_uptime_cs,
                updated_at = excluded.updated_at
            """,
            (
                device_id,
                profile_id,
                config_hash,
                json.dumps(values, separators=(',', ':'), ensure_ascii=False),
                sampled_at,
                device_uptime_cs,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


__all__ = [
    "VALID_COUNTER_BITS",
    "calculate_counter_delta",
    "load_interface_counter_sample",
    "load_counter_sample",
    "save_interface_counter_sample",
    "save_counter_sample",
    "validate_counter_bits",
]
