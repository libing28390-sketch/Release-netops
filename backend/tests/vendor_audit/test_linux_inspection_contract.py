from __future__ import annotations

import subprocess
from pathlib import Path

from services import inspection_service
from database.seed import get_default_items, std_scripts


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FacetConnection:
    def __init__(self):
        self.queries: list[str] = []

    def execute(self, sql, _params=()):
        self.queries.append(" ".join(str(sql).split()))
        normalized = self.queries[-1].lower()
        if "select count(*) as total from inspection_items" in normalized:
            return _Result([{"total": 3}])
        if "select coalesce(category" in normalized:
            return _Result([
                {"facet_value": "Network", "total": 7},
                {"facet_value": "Server", "total": 3},
            ])
        if "select coalesce(method" in normalized:
            return _Result([
                {"facet_value": "Shell", "total": 3},
                {"facet_value": "SNMP", "total": 1},
            ])
        if "order by category asc, name asc limit" in normalized:
            return _Result([{"id": "server-1", "category": "Server", "method": "Shell"}])
        raise AssertionError(f"unexpected inspection-items query: {sql}")

    def close(self):
        return None


def test_paginated_inspection_items_return_full_catalog_facets(monkeypatch) -> None:
    connection = _FacetConnection()
    monkeypatch.setattr(inspection_service, "get_db_connection", lambda: connection)

    result = inspection_service.list_inspection_items(
        category="Server",
        method="Shell",
        page=1,
        page_size=20,
    )

    assert result["total"] == 3
    assert result["items"] == [{"id": "server-1", "category": "Server", "method": "Shell"}]
    assert result["facets"] == {
        "all": 10,
        "categories": {"Network": 7, "Server": 3},
        "methods": {"SHELL": 3, "SNMP": 1},
    }

    category_query = next(query for query in connection.queries if "select coalesce(category" in query.lower())
    method_query = next(query for query in connection.queries if "select coalesce(method" in query.lower())
    assert "lower(coalesce(category" not in category_query.lower()
    assert "lower(coalesce(method" in category_query.lower()
    assert "lower(coalesce(category" in method_query.lower()
    assert "lower(coalesce(method" not in method_query.lower()


def test_linux_builtin_items_bind_one_script_per_metric() -> None:
    items = {
        item[0]: item
        for item in get_default_items("2026-09-07T20:00:00+08:00")
        if item[3] == "Server"
    }
    script_ids = [item[8] for item in items.values()]

    assert len(script_ids) == len(set(script_ids))
    assert "std_linux_integrated" not in script_ids
    assert items["srv_tcp_retrans_pct"][7:9] == (
        "std_linux_tcp_retrans_pct",
        "std_linux_tcp_retrans_pct",
    )

    scripts = {item[0]: item[2] for item in std_scripts}
    assert set(script_ids).issubset(scripts)


def test_linux_tcp_retransmission_output_is_compatible_and_windowed() -> None:
    scripts = {item[0]: item[2] for item in std_scripts}
    standalone = scripts["std_linux_tcp_retrans_pct"]
    comprehensive = scripts["insp_linux_full"]

    for content in (standalone, comprehensive):
        assert "OutSegs" in content
        assert "RetransSegs" in content
        assert "sleep 1" in content
        assert "tcp_retrans_pct" in content

    assert 'echo "tcp_retrans_pct: ${tcp_retrans_pct:-0}"' in comprehensive
    assert 'echo "tcp_retrans: ${tcp_retrans_pct:-0}"' in comprehensive


def test_linux_inspection_skips_inode_usage_when_filesystem_reports_dash() -> None:
    scripts = {item[0]: item[2] for item in std_scripts}
    comprehensive = scripts["insp_linux_full"]
    start = comprehensive.index("df_i_out=$(df -iP")
    end_marker = 'done <<< "$df_i_out"'
    end = comprehensive.index(end_marker, start) + len(end_marker)
    inode_loop = comprehensive[start:end]
    simulated_script = """#!/bin/bash
INODE_CRIT_PCT=90
INODE_WARN_PCT=80
disk_status=SUCCESS
inode_level=OK
inode_messages=
df() {
    printf '%s\\n' \\
        'Filesystem Inodes IUsed IFree IUse% Mounted on' \\
        'overlay - - - - /' \\
        'ext4 1000 950 50 95% /data' \\
        'tmpfs 1000 1 999 1% /run'
}
""" + inode_loop + """
printf 'disk_status=%s\\n' "$disk_status"
"""

    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash = str(git_bash) if git_bash.is_file() else "bash"
    result = subprocess.run(
        [bash, "-c", simulated_script],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0
    assert "integer expression expected" not in result.stderr
    assert "disk_status=ERROR" in result.stdout
