from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "format_redis_monitor.py"


def _format(text: str, timezone: str = "+08:00") -> str:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), f"--timezone={timezone}"],
        input=text,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return completed.stdout


def test_redis_monitor_epoch_is_rendered_in_requested_timezone_with_microseconds():
    output = _format('1789210633.197223 [0 127.0.0.1:58396] "ping"\n')

    assert output == '2026-09-12 18:57:13.197223+08:00 [0 127.0.0.1:58396] "ping"\n'


def test_non_monitor_and_integer_epoch_lines_are_preserved_or_formatted():
    output = _format('healthcheck: passing\n1789210633 [0 lua] "set" "x" "1"\n')

    assert output == 'healthcheck: passing\n2026-09-12 18:57:13.000000+08:00 [0 lua] "set" "x" "1"\n'


def test_iana_timezone_is_supported_when_zone_database_is_available():
    output = _format('1789210633.197223 [0 lua] "ping"\n', "Asia/Shanghai")

    assert output == '2026-09-12 18:57:13.197223+08:00 [0 lua] "ping"\n'
