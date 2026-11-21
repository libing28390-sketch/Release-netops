"""Bounded read-only PG/live sampling; stdin entry point inside nexora-netops.

No application imports, raw SQL, query parameters, HTTP bodies or credentials
are logged. Optional EXPLAIN does not use ANALYZE or execute application SQL.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import urllib.error
import urllib.request

APPLICATION_NAME = "nexora_pg_latency_diagnostic"
HTTP_TIMEOUT_SECONDS = 6
HEALTH_PROBE_INTERVAL_SECONDS = 5
API_PROBE_INTERVAL_SECONDS = 15
DASHBOARD_PROBE_INTERVAL_SECONDS = 30
BACKEND_BASE_URL = "http://127.0.0.1:8003"
NGINX_BASE_URL = "https://nginx"
ASSET_FORM_API_PATHS = (
    ("asset_form_racks", "/api/racks"),
    ("asset_form_validate_u", "/api/racks/validate-u?rack=__pg_latency_diagnostic__&start_u=1&u_height=1"),
    ("asset_form_sites", "/api/cmdb/sites"),
    ("asset_form_credentials", "/api/credentials"),
    ("asset_list_summary", "/api/assets/summary"),
    ("asset_list_page_1", "/api/assets?page=1&page_size=20"),
)
GRAFANA_DASHBOARD_UIDS = (
    "nexora-network-overview", "nexora-network-device",
    "nexora-network-wireless", "nexora-network-interface",
    "nexora-monitoring-health", "nexora-network-outbound",
    "nexora-linux-metrics", "nexora-windows-metrics",
    "nexora-platform-health", "nexora-outbound-probe-quality",
    "nexora-alert-operations",
)
TABLES = (
    "devices", "physical_assets", "sessions", "users", "snmp_mib_nodes",
    "interface_telemetry_raw", "interface_telemetry_1m", "alert_events",
)
# These labels are deliberately coarse. A matching table name is an
# investigation lead; it does not prove which application invoked a query.
QUERY_FAMILY = """CASE
 WHEN query ~* '\\minterface_telemetry_raw\\M' THEN
   CASE WHEN query ~* '^\\s*insert' THEN 'raw_rollup'
        WHEN query ~* '^\\s*delete' THEN 'raw_retention' ELSE 'raw_access' END
 WHEN query ~* '\\msnmp_mib_nodes\\M' THEN 'mib_nodes'
 WHEN query ~* '\\mphysical_assets\\M' THEN 'physical_assets'
 WHEN query ~* '\\m(sessions|user_sessions)\\M' THEN 'session_auth'
 WHEN query ~* '\\malert_[a-z_]+\\M' THEN 'alerts'
 WHEN query ~* '\\mtopology_[a-z_]+\\M' THEN 'topology'
 WHEN query ~* '\\mdevices\\M' THEN 'devices'
 ELSE 'other' END"""
ACTIVITY_SQL = f"""
SELECT json_build_object(
 'db_observed_at', clock_timestamp(),
 'connections', (SELECT json_agg(c) FROM (
   SELECT state, count(*) AS count FROM pg_stat_activity
   WHERE datname=current_database() AND application_name<>%s
   GROUP BY state) c),
 'activity', (SELECT json_agg(a) FROM (
   SELECT pid, state, wait_event_type, wait_event, query_id::text,
     CASE WHEN state='active' THEN
       round(extract(epoch FROM clock_timestamp()-query_start)::numeric*1000, 1)
       ELSE NULL END AS active_query_age_ms,
     round(extract(epoch FROM clock_timestamp()-xact_start)::numeric*1000, 1)
       AS transaction_age_ms,
     round(extract(epoch FROM clock_timestamp()-state_change)::numeric*1000, 1)
       AS state_age_ms,
     pg_blocking_pids(pid) AS blocking_pids, {QUERY_FAMILY} AS query_family
   FROM pg_stat_activity
   WHERE datname=current_database() AND application_name<>%s
     AND state IN ('active', 'idle in transaction', 'idle in transaction (aborted)')
   ORDER BY (state='active') DESC, query_start LIMIT 64) a))
"""
DB_COUNTER_SQL = """
SELECT stats_reset, numbackends, xact_commit, xact_rollback, blks_read, blks_hit,
       blk_read_time, blk_write_time, temp_files, temp_bytes, deadlocks
FROM pg_stat_database WHERE datname=current_database()
"""
TABLE_COUNTER_SQL = """
SELECT relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch,
       n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables WHERE relname=ANY(%s) ORDER BY relname
"""
FLEET_SQL = """
SELECT count(*) AS devices_total,
 count(*) FILTER (WHERE d.ip_address IS NOT NULL AND d.ip_address<>'') AS a_loop_eligible,
 count(*) FILTER (WHERE d.status='online') AS b_loop_eligible,
 count(*) FILTER (WHERE COALESCE(d.snmp_metric_profile_id,'')<>'') AS explicit_snmp_profiles,
 count(*) FILTER (WHERE COALESCE(d.snmp_community,'')<>''
   OR COALESCE(d.snmp_credential_id,'')<>''
   OR COALESCE(pa.snmp_credential_id,'')<>'') AS devices_with_snmp_binding
FROM devices d LEFT JOIN physical_assets pa ON pa.id=d.asset_id
"""
HARDWARE_SENSOR_COUNTS_SQL = """
SELECT count(*) FILTER (WHERE enabled IS TRUE AND lifecycle_status <> 'retired') AS active_sensor_count,
       count(DISTINCT device_id) FILTER (
         WHERE enabled IS TRUE AND lifecycle_status <> 'retired'
       ) AS devices_with_active_sensors
FROM snmp_hardware_sensors
"""
ASSIGNMENT_SQL = """
SELECT interval_seconds, scrape_timeout_seconds, count(*) AS assignment_count,
       count(DISTINCT asset_id) AS configured_assets
FROM monitoring_collection_assignments WHERE enabled=1
GROUP BY interval_seconds, scrape_timeout_seconds
ORDER BY interval_seconds, scrape_timeout_seconds
"""
STATEMENT_SQL = f"""
SELECT queryid::text, userid, calls, total_exec_time, mean_exec_time,
       max_exec_time, rows, shared_blks_hit, shared_blks_read,
       temp_blks_written, {QUERY_FAMILY} AS query_family
FROM pg_stat_statements
WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database())
  AND query NOT ILIKE '%%nexora_pg_latency_diagnostic%%'
ORDER BY total_exec_time DESC LIMIT 200
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Reporter:
    def __init__(self, output=sys.stdout):
        self.output = output
        self.lock = threading.Lock()

    def emit(self, kind, **fields):
        with self.lock:
            self.output.write(json.dumps(
                {"kind": kind, "observed_at": utc_now(), **fields},
                ensure_ascii=True, default=str,
            ) + "\n")
            self.output.flush()


def connect_database():
    import psycopg2
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if urlparse(database_url).scheme not in {"postgresql", "postgres"}:
        raise ValueError("PostgreSQL DATABASE_URL required")
    connection = psycopg2.connect(
        database_url, application_name=APPLICATION_NAME, connect_timeout=3,
        options="-c default_transaction_read_only=on -c statement_timeout=2000 "
                "-c lock_timeout=500 -c idle_in_transaction_session_timeout=3000",
        keepalives=1, keepalives_idle=2, keepalives_interval=1,
        keepalives_count=2, tcp_user_timeout=5000,
    )
    connection.autocommit = True
    return connection


def read_rows(connection, query, params=None):
    from psycopg2.extras import RealDictCursor
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def record_counters(connection, reporter, stage):
    reporter.emit("database_counters", stage=stage,
                  rows=read_rows(connection, DB_COUNTER_SQL))
    reporter.emit("table_counters", stage=stage,
                  rows=read_rows(connection, TABLE_COUNTER_SQL, (list(TABLES),)))


def record_statements(connection, reporter, stage):
    try:
        available = read_rows(connection, "SELECT to_regclass('pg_stat_statements') IS NOT NULL AS available")[0]["available"]
        if not available:
            reporter.emit("sql_cost_unavailable", stage=stage, reason="extension_not_enabled")
            return
        info = read_rows(connection, "SELECT stats_reset, dealloc FROM pg_stat_statements_info")
        reporter.emit("sql_cost_snapshot", stage=stage, reset_info=info,
                      rows=read_rows(connection, STATEMENT_SQL), limit=200)
    except Exception as exc:
        reporter.emit("sql_cost_unavailable", stage=stage, error_type=type(exc).__name__)


def record_runtime(reporter):
    hashes = {}
    for name in (
        "main.py", "database/core.py", "engine/orchestrator.py", "api/assets.py",
        "services/background_monitor_service.py", "services/notification_service.py",
    ):
        path = Path("/app/backend") / name
        if path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    settings = {}
    for key in ("WORKERS", "DB_POOL_SIZE", "DB_POOL_MIN_SIZE", "DB_POOL_OVERFLOW_MAX"):
        value = os.environ.get(key)
        settings[key] = int(value) if value and value.isdecimal() and len(value) < 8 else None
    provider = os.environ.get("MONITORING_METRIC_BACKEND", "").strip().lower()
    settings["metric_backend"] = provider if provider in {
        "native", "shadow", "victoriametrics",
    } else ("unset" if not provider else "other")
    reporter.emit("runtime", settings=settings, source_lf_sha256=hashes)


def record_cgroup(reporter):
    values = {}
    for name in ("cpu.stat", "memory.events", "memory.current", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        if path.is_file():
            lines = path.read_text().splitlines()
            values[name] = {
                parts[0]: int(parts[1]) for parts in (line.split() for line in lines)
                if len(parts) == 2 and parts[1].isdecimal()
            } if name.endswith((".stat", ".events")) else (
                int(lines[0]) if lines and lines[0].isdecimal() else None
            )
    reporter.emit("backend_cgroup", values=values)


def probe_live(opener, url, label, reporter):
    started_at = utc_now()
    started = time.perf_counter()
    fields = {}
    try:
        with opener.open(url, timeout=HTTP_TIMEOUT_SECONDS) as response:
            # Status/headers establish handler response; do not fetch/log bodies.
            fields["http_status"] = response.status
    except urllib.error.HTTPError as exc:
        fields.update(http_status=exc.code, error_type=type(exc).__name__)
        exc.close()
    except Exception as exc:
        fields["error_type"] = type(exc).__name__
    reporter.emit("live", target=label, started_at=started_at,
                  elapsed_ms=round((time.perf_counter()-started)*1000, 1), **fields)


def timed_loop(stop, deadline, interval, action, reporter, label, initial_delay=0):
    if initial_delay and stop.wait(min(initial_delay, max(0, deadline-time.monotonic()))):
        return
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            action()
        except Exception as exc:
            reporter.emit("sample_error", target=label, error_type=type(exc).__name__)
        # Slow operations skip missed samples; never accumulate an unbounded queue.
        # Keep a quiet gap after each completed probe, even when the request
        # itself is slow; retries must not turn into a tight loop.
        stop.wait(min(interval, max(0, deadline-time.monotonic())))


# Drop predicates, output expressions and constants from plans. EXPLAIN output
# otherwise may expose tenant IDs, addresses or other bound application values.
PLAN_FIELDS = {
    "Node Type", "Parent Relationship", "Join Type", "Strategy", "Partial Mode",
    "Startup Cost", "Total Cost", "Plan Rows", "Plan Width", "Workers Planned",
    "Parallel Aware", "Async Capable", "Relation Name", "Index Name",
}


def safe_plan(value):
    if isinstance(value, list):
        return [safe_plan(item) for item in value]
    if isinstance(value, dict):
        return {key: safe_plan(item) for key, item in value.items()
                if key in PLAN_FIELDS or key in {"Plan", "Plans"}}
    return value


def record_plans(connection, reporter):
    # SELECT half of the real maintenance INSERT; this estimates the source
    # scan/aggregation only, not the write/conflict/retention cost.
    cutoff = (datetime.now(timezone.utc)-timedelta(hours=2)).replace(microsecond=0).isoformat()
    sql = """EXPLAIN (FORMAT JSON)
      SELECT substr(ts,1,16)||':00+00:00' AS ts_minute, device_id, interface_name,
        COUNT(*), AVG(in_bps), MAX(in_bps), AVG(out_bps), MAX(out_bps),
        AVG(bw_in_pct), MAX(bw_in_pct), AVG(bw_out_pct), MAX(bw_out_pct),
        SUM(COALESCE(in_pkts,0)), SUM(COALESCE(out_pkts,0)),
        SUM(COALESCE(in_errors,0)+COALESCE(out_errors,0)),
        SUM(COALESCE(in_discards,0)+COALESCE(out_discards,0)),
        SUM(COALESCE(fcs_errors,0))
      FROM interface_telemetry_raw
      WHERE ts >= %s AND LOWER(COALESCE(status,''))='up'
      GROUP BY ts_minute, device_id, interface_name"""
    try:
        rows = read_rows(connection, sql, (cutoff,))
        reporter.emit("estimated_plan", target="raw_rollup_select_only",
                      analyze=False, plan=safe_plan(rows[0]["QUERY PLAN"]))
    except Exception as exc:
        reporter.emit("plan_unavailable", target="raw_rollup_select_only",
                      error_type=type(exc).__name__)

    plans = (
        ("raw_retention_select", """SELECT ts FROM interface_telemetry_raw
          WHERE ts < %s LIMIT 100""", ((datetime.now(timezone.utc)-
             timedelta(hours=48)).replace(microsecond=0).isoformat(),)),
        ("credential_device_binding", """SELECT id FROM devices
          WHERE credential_id=%s OR admin_credential_id=%s ORDER BY hostname""",
         ("__pg_latency_diagnostic_probe__", "__pg_latency_diagnostic_probe__")),
        ("mib_symbol_contains", """SELECT n.oid FROM snmp_mib_nodes n
          JOIN snmp_mibs m ON n.mib_id=m.id WHERE m.is_active=1 AND
          (LOWER(n.node_name) LIKE %s OR LOWER(n.description) LIKE %s OR
           LOWER(m.name) LIKE %s)
          ORDER BY CASE WHEN LOWER(n.node_name)=%s THEN 0
            WHEN LOWER(n.node_name) LIKE %s THEN 1 ELSE 2 END, n.oid LIMIT 50""",
         ("%ifname%", "%ifname%", "%ifname%", "ifname", "ifname%")),
        ("mib_symbol_exact", """SELECT n.oid, m.vendor, n.node_name
          FROM snmp_mib_nodes n JOIN snmp_mibs m ON m.id=n.mib_id
          WHERE m.is_active=1 AND LOWER(n.node_name)=LOWER(%s)
            AND TRIM(COALESCE(n.oid, ''))<>''
          ORDER BY CASE WHEN LOWER(TRIM(COALESCE(m.vendor, '')))=LOWER(%s)
                          THEN 0
                        WHEN LOWER(TRIM(COALESCE(m.vendor, '')))='standard'
                          THEN 1 ELSE 2 END, m.name LIMIT 8""",
         ("ifName", "Cisco")),
    )
    for name, statement, params in plans:
        try:
            rows = read_rows(connection, "EXPLAIN (FORMAT JSON) "+statement, params)
            reporter.emit("estimated_plan", target=name, analyze=False,
                          plan=safe_plan(rows[0]["QUERY PLAN"]))
        except Exception as exc:
            reporter.emit("plan_unavailable", target=name,
                          error_type=type(exc).__name__)


def probe_target_specs():
    """Read-only URLs used by dashboard and asset-management UI flows."""
    targets = [
        ("backend_direct", f"{BACKEND_BASE_URL}/api/health/live",
         HEALTH_PROBE_INTERVAL_SECONDS),
        ("nginx_proxy", f"{NGINX_BASE_URL}/api/health/live",
         HEALTH_PROBE_INTERVAL_SECONDS),
        ("grafana_health", "http://grafana:3000/api/health",
         HEALTH_PROBE_INTERVAL_SECONDS),
        ("victoriametrics_health", "http://victoriametrics:8428/health",
         HEALTH_PROBE_INTERVAL_SECONDS),
    ]
    for label, path in ASSET_FORM_API_PATHS:
        targets.extend((
            (f"{label}_direct", f"{BACKEND_BASE_URL}{path}",
             API_PROBE_INTERVAL_SECONDS),
            (f"{label}_nginx", f"{NGINX_BASE_URL}{path}",
             API_PROBE_INTERVAL_SECONDS),
        ))
    targets.extend((
        ("grafana_auth_gate_direct", f"{BACKEND_BASE_URL}/api/grafana/auth",
         API_PROBE_INTERVAL_SECONDS),
        ("grafana_auth_gate_nginx", f"{NGINX_BASE_URL}/api/grafana/auth",
         API_PROBE_INTERVAL_SECONDS),
    ))
    for uid in GRAFANA_DASHBOARD_UIDS:
        query = "orgId=1&refresh=30s&from=now-6h&to=now&theme=light&kiosk"
        url = f"{NGINX_BASE_URL}/grafana/d/{uid}/{uid}?{query}"
        targets.append((f"grafana_dashboard_{uid}", url,
                        DASHBOARD_PROBE_INTERVAL_SECONDS))
    return tuple(targets)


def main(argv):
    reporter = Reporter()
    connection = None
    stop = threading.Event()
    threads = []
    try:
        duration, interval, plans = (int(value) for value in argv)
        if not (1 <= duration <= 600 and 1 <= interval <= 10 and plans in (0, 1)):
            raise ValueError("Invalid sample settings")
        record_runtime(reporter)
        connection = connect_database()
        reporter.emit("database_settings", rows=read_rows(connection, """
            SELECT current_setting('server_version') AS server_version,
              current_setting('default_transaction_read_only') AS read_only,
              current_setting('statement_timeout') AS statement_timeout,
              current_setting('compute_query_id') AS compute_query_id,
              current_setting('track_io_timing') AS track_io_timing,
              current_setting('work_mem') AS work_mem,
              current_setting('shared_buffers') AS shared_buffers,
              current_setting('max_connections') AS max_connections,
              pg_postmaster_start_time() AS db_started_at
        """))
        record_counters(connection, reporter, "initial")
        record_statements(connection, reporter, "initial")
        try:
            reporter.emit("fleet_counts", rows=read_rows(connection, FLEET_SQL))
        except Exception as exc:
            reporter.emit("fleet_counts_unavailable", error_type=type(exc).__name__)
        try:
            reporter.emit("hardware_sensor_counts",
                          rows=read_rows(connection, HARDWARE_SENSOR_COUNTS_SQL))
        except Exception as exc:
            reporter.emit("hardware_sensor_counts_unavailable",
                          error_type=type(exc).__name__)
        try:
            reporter.emit("v1_assignments", rows=read_rows(connection, ASSIGNMENT_SQL))
        except Exception as exc:
            reporter.emit("v1_assignments_unavailable", error_type=type(exc).__name__)
        deadline = time.monotonic()+duration
        reporter.emit("window_start", duration_seconds=duration, sample_seconds=interval)
        reporter.emit("probe_config", request_timeout_seconds=HTTP_TIMEOUT_SECONDS,
                      health_interval_seconds=HEALTH_PROBE_INTERVAL_SECONDS,
                      api_interval_seconds=API_PROBE_INTERVAL_SECONDS,
                      dashboard_interval_seconds=DASHBOARD_PROBE_INTERVAL_SECONDS,
                      sends_authorization_header=False)
        pg_tick = [0]

        def pg_action():
            rows = read_rows(connection, ACTIVITY_SQL, (APPLICATION_NAME, APPLICATION_NAME))
            reporter.emit("pg_activity", sample=rows[0]["json_build_object"])
            if pg_tick[0] % max(1, 5//interval) == 0:
                record_counters(connection, reporter, "during")
                record_cgroup(reporter)
            pg_tick[0] += 1

        targets = [("pg", pg_action, interval, 0)]
        for index, (label, url, probe_interval) in enumerate(probe_target_specs()):
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
            )
            targets.append((label, lambda opener=opener, url=url, label=label:
                            probe_live(opener, url, label, reporter),
                            probe_interval, min(index * 0.12, 3.0)))
        for label, action, probe_interval, initial_delay in targets:
            thread = threading.Thread(
                target=timed_loop,
                args=(stop, deadline, probe_interval, action, reporter, label, initial_delay),
                name=label, daemon=True,
            )
            thread.start()
            threads.append(thread)
        stop.wait(max(0, deadline-time.monotonic()))
        stop.set()
        for thread in threads:
            thread.join(timeout=6)
        if any(thread.is_alive() for thread in threads):
            reporter.emit("incomplete", reason="sampler_shutdown_timeout")
            return 2
        reporter.emit("window_end")
        record_counters(connection, reporter, "final")
        record_statements(connection, reporter, "final")
        if plans:
            record_plans(connection, reporter)
        reporter.emit("finished", diagnostic_queries_included_in_database_counters=True)
        return 0
    except KeyboardInterrupt:
        reporter.emit("interrupted")
        return 130
    except Exception as exc:
        # Database exception messages can embed SQL/DSNs; report type only.
        reporter.emit("collector_error", error_type=type(exc).__name__)
        return 2
    finally:
        stop.set()
        # A daemon thread may still own the connection; do not race its cursor.
        if connection is not None and not any(thread.is_alive() for thread in threads):
            connection.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
