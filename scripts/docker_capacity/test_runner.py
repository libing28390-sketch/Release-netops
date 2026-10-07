"""Focused stdlib tests for the capacity runner and SNMP protocol.

These tests intentionally use loopback fixtures only.  They exercise the
request transport's proxy/redirect/error rules, bounded scheduler accounting,
configuration safety checks, and a real UDP BER exchange with the simulator.
Run with ``python3.11 -m unittest test_runner`` from this directory.
"""

from __future__ import annotations

import json
import io
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

try:
    import runner
    import snmp_simulator
except ImportError:  # Running as ``python -m unittest scripts/docker_capacity/test_runner.py``.
    from scripts.docker_capacity import runner, snmp_simulator


RUN_ID = "0123456789abcdef0123456789abcdef"


def make_config(**overrides):
    config = {
        "run_id": RUN_ID,
        "services": ["netops", "snmp-exporter"],
        "available_services": ["netops", "db", "snmp-exporter", "victoriametrics", "vmagent"],
        "duration_seconds": 1,
        "rps": 5,
        "concurrency": 2,
        "timeout_seconds": 1,
        "insecure_tls": True,
        "dataset": {
            "rows": 10,
            "redis_keys": 10,
            "objects": 2,
            "object_bytes": 64,
            "series": 4,
            "history_points": 3,
            "interfaces": 2,
        },
        "credentials": {
            "db_user": "capacity",
            "db_password": "db-secret",
            "db_name": f"nexora_capacity_{RUN_ID}",
            "app_username": "capacity",
            "app_password": "app-secret",
            "redis_password": "redis-secret",
            "grafana_user": "admin",
            "grafana_password": "grafana-secret",
            "s3_access_key": "s3-access",
            "s3_secret_key": "s3-secret",
            "s3_bucket": f"nexora-capacity-{RUN_ID}",
        },
        "targets": {service: "http://127.0.0.1:1" for service in runner.SUPPORTED_SERVICES},
        "query_window_seconds": 30,
        "snmp_ports": [1161, 1162],
        "snmp_auth": "capacity_v2",
        "snmp_module": "capacity_ifmib",
    }
    config.update(overrides)
    return config


class _HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler API
        if self.path == "/ok":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        elif self.path == "/unauth":
            self.send_response(401)
            self.end_headers()
        else:
            self.send_response(500)
            self.end_headers()

    def log_message(self, *_args):
        return


class HttpTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _HttpHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def test_proxy_is_bypassed_and_success_is_json(self):
        with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"}):
            response = runner.http_request("GET", self.base + "/ok", timeout=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(runner._json_body(response), {"ok": True})

    def test_redirect_is_not_implicit_success(self):
        response = runner.http_request("GET", self.base + "/redirect", timeout=1)
        self.assertEqual(response.status_code, 302)
        with self.assertRaises(runner.CapacityError) as raised:
            runner._success_status(response, (200,))
        self.assertEqual(raised.exception.code, "http_302")

    def test_unauthorized_and_server_error_are_failures(self):
        unauthorized = runner.http_request("GET", self.base + "/unauth", timeout=1)
        server_error = runner.http_request("GET", self.base + "/bad", timeout=1)
        with self.assertRaises(runner.CapacityError) as raised:
            runner._success_status(unauthorized, (200,))
        self.assertEqual(raised.exception.code, "unauthorized")
        with self.assertRaises(runner.CapacityError) as raised:
            runner._success_status(server_error, (200,))
        self.assertEqual(raised.exception.code, "http_500")


class SchedulerTests(unittest.TestCase):
    def test_open_loop_stats_are_bounded_and_distinguish_success_latency(self):
        class FakeScenario:
            name = "fake"

            def prepare_worker(self):
                return object()

            def close_worker(self, _worker):
                return None

            def request(self, _worker, *, check=False):
                return runner.ScenarioOutcome(True, latency_ms=0.1, status_code=200)

        executor = runner.ScenarioExecutor(FakeScenario(), duration=0.08, rps=50, concurrency=2, timeout=1)
        stats = executor.run()
        self.assertGreater(stats.scheduled, 0)
        self.assertEqual(stats.errors, 0)
        self.assertEqual(stats.successful, stats.completed)
        self.assertLessEqual(len(stats.latency.values), runner.MAX_LATENCY_SAMPLES)
        self.assertGreaterEqual(stats.schedule_finished_at, stats.started_at)

    def test_queue_wait_is_in_success_latency_and_missed_slots_are_dropped(self):
        class SlowScenario:
            name = "slow"

            def prepare_worker(self):
                return object()

            def close_worker(self, _worker):
                return None

            def request(self, _worker, *, check=False):
                import time

                time.sleep(0.025)
                return runner.ScenarioOutcome(True, latency_ms=0.1, status_code=200)

        executor = runner.ScenarioExecutor(SlowScenario(), duration=0.09, rps=100, concurrency=1, timeout=1)
        stats = executor.run()
        self.assertGreater(stats.dropped, 0)
        self.assertGreater(stats.latency.maximum, 20.0)


class NginxMixTests(unittest.TestCase):
    def test_static_api_and_home_branches_are_reachable(self):
        cfg = runner.validate_config(make_config(services=["nginx"], available_services=["nginx"]))
        scenario = runner.NginxScenario(cfg, runner.RuntimeContext(cfg))
        worker = {"token": "opaque", "assets": ["/assets/main.js"], "client": object()}
        success = runner.ScenarioOutcome(True, latency_ms=1.0, status_code=200)
        with mock.patch.object(scenario, "_request", return_value=success) as request:
            with mock.patch.object(runner.random, "random", return_value=0.25):
                scenario.request(worker)
            self.assertIn("/assets/main.js", request.call_args.args[1])
            request.reset_mock()
            with mock.patch.object(runner.random, "random", return_value=0.60):
                scenario.request(worker)
            self.assertIn("/api/devices", request.call_args.args[1])
            request.reset_mock()
            with mock.patch.object(runner.random, "random", return_value=0.90):
                scenario.request(worker)
            self.assertTrue(request.call_args.args[1].endswith("/"))


class QueryScenarioTests(unittest.TestCase):
    def test_victoria_range_requires_nonempty_result(self):
        cfg = runner.validate_config(make_config(services=["victoriametrics"], available_services=["victoriametrics"]))
        scenario = runner.VictoriaMetricsScenario(cfg, runner.RuntimeContext(cfg))

        class Client:
            def __init__(self, body):
                self.body = body

            def request(self, *_args, **_kwargs):
                return runner.HttpResponse(200, {}, self.body, 1.0)

        good = scenario.request(Client(b'{"status":"success","data":{"result":[{"values":[[1,2]]}]}}'))
        empty = scenario.request(Client(b'{"status":"success","data":{"result":[]}}'))
        self.assertTrue(good.success)
        self.assertFalse(empty.success)
        self.assertEqual(empty.error_code, "semantic_error")

    def test_grafana_query_is_bounded_and_requires_samples(self):
        cfg = runner.validate_config(make_config(services=["grafana"], available_services=["grafana", "victoriametrics"]))
        scenario = runner.GrafanaScenario(cfg, runner.RuntimeContext(cfg))

        class Client:
            def __init__(self):
                self.body = ""
                self.headers = {}

            def request(self, _method, _url, *, headers=None, body=None):
                self.body = body
                self.headers = dict(headers or {})
                return runner.HttpResponse(200, {}, b'{"results":{"A":{"frames":[{"data":{"values":[[1],[2]]}}]}}}', 1.0)

        client = Client()
        outcome = scenario.request(client)
        self.assertTrue(outcome.success)
        self.assertIn("topk(100", client.body)
        self.assertTrue(client.headers["Authorization"].startswith("Basic "))


class ConfigAndSnmpTests(unittest.TestCase):
    def test_database_and_bucket_are_run_scoped(self):
        cfg = runner.validate_config(make_config())
        self.assertEqual(cfg.credentials["db_name"], f"nexora_capacity_{RUN_ID}")
        with self.assertRaises(runner.CapacityError) as raised:
            runner.validate_config(make_config(credentials={**make_config()["credentials"], "db_name": "netops"}))
        self.assertEqual(raised.exception.code, "unsafe_database_target")

    def test_capacity_api_devices_do_not_enter_background_reachability_probes(self):
        cfg = runner.validate_config(make_config())
        columns, rows = runner._capacity_device_rows(
            cfg, {"id", "hostname", "ip_address", "status", "sn"}
        )

        self.assertEqual(len(rows), cfg.dataset["rows"])
        ip_index = columns.index("ip_address")
        self.assertTrue(all(row[ip_index] is None for row in rows))

    def test_database_only_prepare_does_not_require_app_migrations(self):
        class Cursor:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=None):
                self.statements.append((statement, params))

            def executemany(self, statement, rows):
                self.statements.append((statement, len(rows)))

            def fetchone(self):
                return None

            def fetchall(self):
                return []

            def close(self):
                return None

        class Connection:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.autocommit = False

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                return None

            def rollback(self):
                return None

            def close(self):
                return None

        class Database:
            def __init__(self, cfg):
                self.connection = Connection()

            def close(self):
                self.connection.close()

        cfg = runner.validate_config(make_config(services=["db"], available_services=["db"]))
        with mock.patch.object(runner, "DatabaseConnection", Database):
            result = runner._prepare_database(cfg)
        self.assertEqual(result["devices"], 0)
        self.assertFalse(result["capacity_user"])
        self.assertEqual(result["benchmark_rows"], cfg.dataset["rows"])

    def test_udp_ber_get_returns_interface_counter(self):
        port = 32161 + (os.getpid() % 1000)
        server = snmp_simulator.SimulatorServer(interfaces=2, ports=[port], bind="127.0.0.1")
        server.start()
        try:
            pdu = snmp_simulator.tlv(
                0xA0,
                snmp_simulator.encode_integer(7)
                + snmp_simulator.encode_integer(0)
                + snmp_simulator.encode_integer(0)
                + snmp_simulator.tlv(
                    0x30,
                    snmp_simulator.tlv(
                        0x30,
                        snmp_simulator.encode_oid(snmp_simulator.OID_IF_IN_OCTETS + (1,))
                        + snmp_simulator.tlv(0x05, b""),
                    ),
                ),
            )
            packet = snmp_simulator.tlv(
                0x30,
                snmp_simulator.encode_integer(1)
                + snmp_simulator.tlv(0x04, snmp_simulator.DEFAULT_COMMUNITY.encode())
                + pdu,
            )
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1)
            try:
                sock.sendto(packet, ("127.0.0.1", port))
                response, _ = sock.recvfrom(2048)
            finally:
                sock.close()
            self.assertIn(snmp_simulator.encode_oid(snmp_simulator.OID_IF_IN_OCTETS + (1,)), response)
            self.assertIn(b"capacity_lab_only", response)
        finally:
            server.close()

    def test_getnext_getbulk_and_end_of_mib(self):
        getnext = snmp_simulator.Request(
            1, snmp_simulator.DEFAULT_COMMUNITY, 0xA1, 1, 0, 0, (snmp_simulator.OID_IF_TABLE,)
        )
        next_bindings = snmp_simulator.build_bindings(getnext, interfaces=2, port=1161)
        self.assertEqual(next_bindings[0][0], snmp_simulator.OID_IF_INDEX + (1,))
        self.assertEqual(next_bindings[0][1], 0x02)

        bulk = snmp_simulator.Request(
            1, snmp_simulator.DEFAULT_COMMUNITY, 0xA5, 2, 0, 4, (snmp_simulator.OID_IF_INDEX,)
        )
        bulk_bindings = snmp_simulator.build_bindings(bulk, interfaces=2, port=1161)
        self.assertEqual(len(bulk_bindings), 4)
        self.assertEqual(bulk_bindings[0][0], snmp_simulator.OID_IF_INDEX + (1,))
        self.assertEqual(bulk_bindings[1][0], snmp_simulator.OID_IF_INDEX + (2,))

        last = snmp_simulator._supported_oids(2)[-1]
        exhausted = snmp_simulator.Request(
            1, snmp_simulator.DEFAULT_COMMUNITY, 0xA1, 3, 0, 0, (last,)
        )
        end_binding = snmp_simulator.build_bindings(exhausted, interfaces=2, port=1161)[0]
        self.assertEqual(end_binding[1], 0x82)


class RunnerFailureDiagnosticsTests(unittest.TestCase):
    def test_netops_login_timeout_has_operation_specific_safe_code(self):
        cfg = runner.validate_config(make_config(services=["netops"]))
        context = runner.RuntimeContext(cfg)
        with mock.patch.object(runner, "http_request", side_effect=TimeoutError("password=fixture-secret")):
            with self.assertRaises(runner.CapacityError) as raised:
                context.login()

        self.assertEqual(raised.exception.code, "api_login_timeout")
        self.assertNotIn("fixture-secret", str(raised.exception))

    def test_unexpected_exception_reports_safe_type_and_runner_location(self):
        output = io.StringIO()
        secret_text = "password=do-not-print"
        with mock.patch.object(runner, "_read_stdin_json", return_value=make_config()), \
             mock.patch.object(runner, "check", side_effect=ValueError(secret_text)), \
             mock.patch("sys.stdout", output):
            exit_code = runner.main(["check"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error"], "runner_failed")
        self.assertEqual(payload["failure_type"], "ValueError")
        self.assertEqual(payload["failure_site"]["file"], "runner.py")
        self.assertEqual(payload["failure_site"]["function"], "main")
        self.assertNotIn(secret_text, output.getvalue())

    def test_victoriametrics_preflight_result_is_normalized_before_check_aggregation(self):
        cfg = runner.validate_config(
            make_config(
                services=["netops"],
                available_services=["netops", "db", "redis", "victoriametrics"],
            )
        )
        with mock.patch.object(runner, "_make_context", return_value=mock.sentinel.context), \
             mock.patch.object(runner, "_single_check", return_value=(
                 {"status": "passed", "successful": 1}, runner.ScenarioOutcome(True, status_code=200)
             )), \
             mock.patch.object(runner, "_seed_vm_verification_sample") as seed_sample, \
             mock.patch.object(runner, "_vm_check", return_value={"victoriametrics_push_visible": True}):
            result = runner.check(cfg)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["checks"]["victoriametrics_query"], {"ok": True})
        seed_sample.assert_called_once_with(cfg)

    def test_victoriametrics_preflight_failure_keeps_stable_error_code(self):
        cfg = runner.validate_config(
            make_config(
                services=["netops"],
                available_services=["netops", "db", "redis", "victoriametrics"],
            )
        )
        with mock.patch.object(runner, "_make_context", return_value=mock.sentinel.context), \
             mock.patch.object(runner, "_single_check", return_value=(
                 {"status": "passed", "successful": 1}, runner.ScenarioOutcome(True, status_code=200)
             )), \
             mock.patch.object(runner, "_seed_vm_verification_sample"), \
             mock.patch.object(runner, "_vm_check", return_value={
                 "victoriametrics_push_visible": False, "error": "vm_no_result"
             }):
            result = runner.check(cfg)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["checks"]["victoriametrics_query"], {"ok": False, "error": "vm_no_result"})


if __name__ == "__main__":
    unittest.main()
