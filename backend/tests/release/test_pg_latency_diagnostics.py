from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/diagnostics/nexora_pg_latency.py"
WRAPPER = ROOT / "scripts/diagnostics/collect_nexora_pg_latency.sh"
BASH = Path(r"C:\Program Files\Git\bin\bash.exe") if Path(r"C:\Program Files\Git\bin\bash.exe").exists() else Path("bash")
spec = importlib.util.spec_from_file_location("pg_latency_diagnostic", HELPER)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)
REPORTER_CLASS = diagnostic.Reporter


def test_database_errors_do_not_expose_sql_or_credentials(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic, "Reporter", lambda: REPORTER_CLASS(output=sys.stdout))
    monkeypatch.setattr(diagnostic, "record_runtime", lambda reporter: None)

    def fail():
        raise RuntimeError("postgresql://someone:SECRET@host/prod; SELECT 'PRIVATE_VALUE'")

    monkeypatch.setattr(diagnostic, "connect_database", fail)
    assert diagnostic.main(["1", "1", "0"]) == 2
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err
    assert "PRIVATE_VALUE" not in captured.out + captured.err
    assert "RuntimeError" in captured.out


def test_plan_filter_and_output_values_are_removed():
    plan = [{"Plan": {"Node Type": "Index Scan", "Plan Rows": 7,
                      "Index Cond": "tenant_id = 'SECRET'", "Output": ["PRIVATE"],
                      "Plans": [{"Node Type": "Seq Scan", "Filter": "ip = 'PRIVATE'"}]}}]
    sanitized = diagnostic.safe_plan(plan)
    assert sanitized[0]["Plan"]["Plan Rows"] == 7
    assert sanitized[0]["Plan"]["Plans"][0]["Node Type"] == "Seq Scan"
    assert "SECRET" not in json.dumps(sanitized)
    assert "PRIVATE" not in json.dumps(sanitized)


def test_optional_plans_include_exact_runtime_mib_symbol_lookup(monkeypatch):
    statements = []
    output = io.StringIO()

    def explain(_connection, statement, params=None):
        statements.append((statement, params))
        return [{"QUERY PLAN": [{"Plan": {"Node Type": "Seq Scan"}}]}]

    monkeypatch.setattr(diagnostic, "read_rows", explain)
    diagnostic.record_plans(object(), REPORTER_CLASS(output))

    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert any(row.get("target") == "mib_symbol_exact" for row in records)
    exact_statement, exact_params = next(
        (sql, params) for sql, params in statements
        if "LOWER(n.node_name)=LOWER(%s)" in sql
    )
    normalized = " ".join(exact_statement.upper().split())
    assert normalized.startswith("EXPLAIN (FORMAT JSON) SELECT")
    assert "ANALYZE" not in normalized
    assert "JOIN SNMP_MIBS M ON M.ID=N.MIB_ID" in normalized
    assert exact_params == ("ifName", "Cisco")


def test_snmp_inventory_metrics_are_aggregate_only():
    fleet_sql = " ".join(diagnostic.FLEET_SQL.lower().split())
    sensor_sql = " ".join(diagnostic.HARDWARE_SENSOR_COUNTS_SQL.lower().split())

    assert "devices_with_snmp_binding" in fleet_sql
    assert "coalesce(d.snmp_community,'')" in fleet_sql
    assert "count(distinct device_id)" in sensor_sql
    assert "active_sensor_count" in sensor_sql
    assert "select *" not in fleet_sql + sensor_sql
    assert "snmp_community from" not in fleet_sql


def test_live_probe_does_not_read_response_body():
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            pytest.fail("Diagnostic must not read application response bodies")

    class Opener:
        def open(self, url, timeout):
            assert timeout == diagnostic.HTTP_TIMEOUT_SECONDS == 6
            return Response()

    output = io.StringIO()
    diagnostic.probe_live(Opener(), "http://example.invalid/health", "backend", REPORTER_CLASS(output))
    row = json.loads(output.getvalue())
    assert row["http_status"] == 200
    assert row["elapsed_ms"] >= 0


def test_blocked_database_sample_does_not_delay_live_probes(monkeypatch):
    output = io.StringIO()
    entered = threading.Event()
    released = threading.Event()
    concurrent_probe = threading.Event()

    class Connection:
        def close(self):
            assert released.is_set()

    def rows(connection, query, params=None):
        if query == diagnostic.ACTIVITY_SQL:
            entered.set()
            assert concurrent_probe.wait(timeout=2), "HTTP sampling waited for PG"
            released.set()
            return [{"json_build_object": {"activity": []}}]
        return [{"devices_total": 0}]

    def probe(opener, url, label, reporter):
        assert entered.wait(timeout=2)
        concurrent_probe.set()
        reporter.emit("live", target=label, http_status=200)

    monkeypatch.setattr(diagnostic, "Reporter", lambda: REPORTER_CLASS(output))
    monkeypatch.setattr(diagnostic, "record_runtime", lambda reporter: None)
    monkeypatch.setattr(diagnostic, "connect_database", Connection)
    monkeypatch.setattr(diagnostic, "read_rows", rows)
    monkeypatch.setattr(diagnostic, "record_counters", lambda *args: None)
    monkeypatch.setattr(diagnostic, "record_statements", lambda *args: None)
    monkeypatch.setattr(diagnostic, "record_cgroup", lambda *args: None)
    monkeypatch.setattr(diagnostic, "probe_live", probe)
    assert diagnostic.main(["4", "1", "0"]) == 0
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert {row["target"] for row in records if row["kind"] == "live"} == {
        label for label, _url, _interval in diagnostic.probe_target_specs()
    }


def test_probe_targets_match_read_only_ui_gets_without_fabricated_auth():
    targets = diagnostic.probe_target_specs()
    by_label = {label: (url, interval) for label, url, interval in targets}

    for label in (
        "asset_form_racks_direct", "asset_form_racks_nginx",
        "asset_form_validate_u_direct", "asset_form_validate_u_nginx",
        "asset_form_sites_direct", "asset_form_sites_nginx",
        "asset_form_credentials_direct", "asset_form_credentials_nginx",
        "asset_list_summary_direct", "asset_list_summary_nginx",
        "asset_list_page_1_direct", "asset_list_page_1_nginx",
        "grafana_auth_gate_direct", "grafana_auth_gate_nginx",
    ):
        assert label in by_label
        assert by_label[label][1] == diagnostic.API_PROBE_INTERVAL_SECONDS

    dashboard_labels = {
        label for label in by_label if label.startswith("grafana_dashboard_")
    }
    assert dashboard_labels == {
        f"grafana_dashboard_{uid}" for uid in diagnostic.GRAFANA_DASHBOARD_UIDS
    }
    assert all("/api/grafana/session" not in url for url, _ in by_label.values())
    validate_url = by_label["asset_form_validate_u_direct"][0]
    assert "/api/racks/validate-u?" in validate_url
    assert "rack=__pg_latency_diagnostic__" in validate_url
    assert not any("token=" in url or "secret=" in url for url, _ in by_label.values())
    assert all(interval > 0 for _label, _url, interval in targets)


@pytest.mark.parametrize("duration, interval, plans", [
    ("0", "1", "0"), ("601", "1", "0"), ("1", "0", "0"),
    ("1", "11", "0"), ("1", "1", "2"), ("1; touch injected", "1", "0"),
])
def test_invalid_wrapper_settings_fail_before_docker(tmp_path, duration, interval, plans):
    environment = os.environ.copy()
    environment.update(DURATION_SECONDS=duration, SAMPLE_SECONDS=interval, COLLECT_PLANS=plans)
    result = subprocess.run(
        [str(BASH), "-c", 'docker() { echo unexpected; }; export -f docker; source "$1" "$2"',
         "diagnostic", str(WRAPPER), str(tmp_path / "output.jsonl")],
        env=environment, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 2
    assert "unexpected" not in result.stdout
    assert not (tmp_path / "output.jsonl").exists()


def test_wrapper_preserves_existing_output(tmp_path):
    output = tmp_path / "output.jsonl"
    output.write_text("existing", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(DURATION_SECONDS="1", SAMPLE_SECONDS="1", COLLECT_PLANS="0")
    result = subprocess.run(
        [str(BASH), "-c", 'docker() { echo unexpected; }; export -f docker; source "$1" "$2"',
         "diagnostic", str(WRAPPER), str(output)],
        env=environment, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode != 0
    assert "unexpected" not in result.stdout
    assert output.read_text(encoding="utf-8") == "existing"
