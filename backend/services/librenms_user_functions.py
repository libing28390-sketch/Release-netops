"""Reviewed native equivalents for LibreNMS sensor user_func rules.

LibreNMS YAML may name PHP functions or OS class methods. Nexora never loads or
executes those PHP symbols; this module maps reviewed functions to a Python
allowlist and leaves unknown names explicitly unsupported.
"""

from __future__ import annotations

import math
import re
import struct
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping


SUPPORTED_LIBRENMS_USER_FUNCS = frozenset({
    "round",
    "fahrenheit_to_celsius",
    "datetoruntime",
    "mw_to_dbm",
    "hhmmsstominutes",
    "uw_to_dbm",
    "string_to_float",
    "ieee754_to_decimal",
    "normalizetransceivervalues",
    "normalizetransceivervaluescurrent",
    "offsetsfptemperature",
    "convertwattodbm",
    "cast",
    "motorstatus",
    "modestatus",
    "transferpumpstatus",
    "alarmstatus",
    "commstatus",
    "cec7commstatus",
    "cec7commalarmstatus",
    "cec7modestatus",
})


def _func_key(value: Any) -> str:
    token = str(value or "").strip().casefold()
    if "::" in token:
        token = token.rsplit("::", 1)[-1]
    return re.sub(r"[^a-z0-9_]", "", token)


def supports_librenms_user_func(value: Any) -> bool:
    return not value or _func_key(value) in SUPPORTED_LIBRENMS_USER_FUNCS


def _number(value: Any) -> float | None:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _round_half_up(value: float, places: int = 0) -> float:
    quantum = Decimal(1).scaleb(-places)
    try:
        return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return value


def _date_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip().strip('"')
        if not raw:
            return None
        normalized = raw.replace(",", " ").replace("/", "-")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            try:
                number = int(raw, 0)
            except (TypeError, ValueError):
                return None
            try:
                parsed = datetime.fromtimestamp(number, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def apply_librenms_user_func(
    name: Any,
    value: Any,
    *,
    raw_value: Any = None,
    index_suffix: Any = "",
    definition: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> float | None:
    """Apply one allowlisted LibreNMS transform, returning None on bad input."""
    key = _func_key(name)
    if not key:
        return _number(value)
    if key not in SUPPORTED_LIBRENMS_USER_FUNCS:
        return None

    number = _number(value)
    raw = value if raw_value is None else raw_value
    if key == "round":
        return _round_half_up(number) if number is not None else None
    if key == "fahrenheit_to_celsius":
        return _round_half_up((number - 32.0) / 1.8, 2) if number is not None else None
    if key == "datetoruntime":
        parsed = _date_value(raw)
        if parsed is None:
            return 0.0
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return float(int(abs((current.astimezone(timezone.utc) - parsed).total_seconds()) / 60.0))
    if key == "hhmmsstominutes":
        match = re.fullmatch(r"\s*(\d+):(\d{1,2}):(\d{1,2})\s*", str(raw or ""))
        if not match:
            return None
        hours, minutes, seconds = (int(part) for part in match.groups())
        return float(int(hours * 60 + minutes + seconds / 60.0))
    if key in {"mw_to_dbm", "uw_to_dbm"}:
        if number is None or number < 0:
            return None
        if number == 0:
            return -60.0
        return 10.0 * math.log10(number if key == "mw_to_dbm" else number / 1000.0)
    if key == "string_to_float":
        return _round_half_up(number, 2) if number is not None else None
    if key == "cast":
        if number is not None:
            return number
        prefix = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(raw or ""))
        return float(prefix.group(1)) if prefix else 0.0
    if key == "ieee754_to_decimal":
        if number is None:
            return None
        try:
            bits = int(number) & 0xFFFFFFFF
            return float(struct.unpack(">f", bits.to_bytes(4, "big"))[0])
        except (OverflowError, ValueError, struct.error):
            return None
    if key in {"normalizetransceivervalues", "normalizetransceivervaluescurrent"}:
        if number is None:
            return None
        text = str(value).strip()
        normalized = number / 100.0 if re.fullmatch(r"[+-]?\d+", text) else number
        if key == "normalizetransceivervaluescurrent":
            normalized *= 0.001
        return normalized
    if key == "offsetsfptemperature":
        return number - 128.0 if number is not None else None
    if key == "convertwattodbm":
        if number is None or number <= 0:
            return None
        return 10.0 * math.log10(number / 10_000_000.0) + 30.0
    if key in {
        "motorstatus", "modestatus", "transferpumpstatus", "alarmstatus",
        "commstatus", "cec7commstatus", "cec7commalarmstatus", "cec7modestatus",
    }:
        if number is None or not number.is_integer():
            return None
        masks = {
            "motorstatus": (1, 2),
            "modestatus": (4, 8, 16, 32),
            "transferpumpstatus": (64,),
            "alarmstatus": (128,),
            "commstatus": (256, 512),
            "cec7commstatus": (32, 64),
            "cec7commalarmstatus": (1,),
            "cec7modestatus": (2, 4, 8, 16),
        }
        raw_int = int(number)
        return float(sum(raw_int & mask for mask in masks[key]))
    return None


__all__ = [
    "SUPPORTED_LIBRENMS_USER_FUNCS",
    "supports_librenms_user_func",
    "apply_librenms_user_func",
]
