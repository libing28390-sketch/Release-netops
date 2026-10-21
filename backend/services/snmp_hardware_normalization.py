"""Shared numeric normalization for SNMP hardware measurements.

This module contains only measurement-level conversions and canonical range
checks. It deliberately does not choose sensors, aggregate rows, or interpret
device/profile-specific status codes.
"""

from __future__ import annotations

import math
from typing import Any


PERCENT_MIN = 0.0
PERCENT_MAX = 100.0
TEMPERATURE_MIN_CELSIUS = -80.0
TEMPERATURE_MAX_CELSIUS = 200.0


def _finite_number(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_scaled_value(value: Any, scale: Any = 1.0, offset: Any = 0.0) -> float | None:
    """Apply a positive scale and finite offset to one numeric SNMP value."""
    number = _finite_number(value)
    factor = _finite_number(scale)
    adjustment = _finite_number(offset)
    if number is None or factor is None or adjustment is None or factor <= 0:
        return None
    normalized = number * factor + adjustment
    return normalized if math.isfinite(normalized) else None


def normalize_percentage(value: Any, scale: Any = 1.0, offset: Any = 0.0) -> float | None:
    """Scale a percentage reading and enforce the canonical inclusive 0..100 range."""
    normalized = normalize_scaled_value(value, scale, offset)
    if normalized is None or not PERCENT_MIN <= normalized <= PERCENT_MAX:
        return None
    return normalized


def normalize_temperature_celsius(value: Any, scale: Any = 1.0, offset: Any = 0.0) -> float | None:
    """Scale a Celsius reading and reject unsupported/sentinel values."""
    normalized = normalize_scaled_value(value, scale, offset)
    if normalized is None or not TEMPERATURE_MIN_CELSIUS <= normalized <= TEMPERATURE_MAX_CELSIUS:
        return None
    return normalized


__all__ = [
    "PERCENT_MIN",
    "PERCENT_MAX",
    "TEMPERATURE_MIN_CELSIUS",
    "TEMPERATURE_MAX_CELSIUS",
    "normalize_scaled_value",
    "normalize_percentage",
    "normalize_temperature_celsius",
]
