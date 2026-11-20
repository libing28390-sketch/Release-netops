#!/usr/bin/env python3
"""Format Redis MONITOR's Unix timestamps for human-readable log viewing.

Usage:
    redis-cli MONITOR | python3 scripts/format_redis_monitor.py --timezone=+08:00

The formatter only transforms lines that begin with a MONITOR epoch timestamp.
All remaining text, including Redis' redacted AUTH entries, is passed through.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_MONITOR_LINE = re.compile(r"^(?P<epoch>-?\d{9,}(?:\.\d+)?) (?P<message>.*)$")
_FIXED_OFFSET = re.compile(r"^(?P<sign>[+-])(?P<hours>\d{2}):(?P<minutes>\d{2})$")


def _parse_timezone(value: str):
    """Resolve either an IANA time zone or a fixed UTC offset such as +08:00."""
    match = _FIXED_OFFSET.fullmatch(value.strip())
    if match:
        hours = int(match.group("hours"))
        minutes = int(match.group("minutes"))
        if hours > 23 or minutes > 59:
            raise ValueError("fixed timezone offset must be between -23:59 and +23:59")
        offset = timedelta(hours=hours, minutes=minutes)
        if match.group("sign") == "-":
            offset = -offset
        return timezone(offset, name=value.strip())
    try:
        return ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {value}") from exc


def _format_monitor_line(line: str, zone) -> str:
    match = _MONITOR_LINE.match(line)
    if not match:
        return line

    epoch = match.group("epoch")
    whole, separator, fraction = epoch.partition(".")
    try:
        microseconds = int((fraction + "000000")[:6]) if separator else 0
        timestamp = datetime.fromtimestamp(int(whole), tz=zone).replace(microsecond=microseconds)
    except (OverflowError, OSError, ValueError):
        return line

    readable = timestamp.isoformat(sep=" ", timespec="microseconds")
    return f"{readable} {match.group('message')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timezone",
        default="+08:00",
        help="IANA zone or fixed UTC offset (default: +08:00)",
    )
    args = parser.parse_args()
    try:
        zone = _parse_timezone(args.timezone)
    except ValueError as exc:
        parser.error(str(exc))

    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        print(_format_monitor_line(line, zone), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
