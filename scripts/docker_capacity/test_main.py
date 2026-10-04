"""Focused controller checks; Docker is always replaced with a local fake."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace

import lab
import main
import metrics


RUN_ID = "a" * 32


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.resources = {}
        self.volumes = {}
        self.networks = {}
        self.sources = {}
        for service in lab.SERVICES:
            self.sources["nexora-" + service] = {
                "Id": "source-" + service, "Image": "sha256:local-" + service,
                "Name": "/nexora-" + service, "Config": {"Env": ["WORKERS=1", "POSTGRES_PASSWORD=not-for-the-report"]},
                "HostConfig": {"Memory": 2147483648 if service == "netops" else 0,
                               "NanoCpus": 2000000000 if service == "netops" else 0},
                "State": {"Status": "running", "ExitCode": 0}, "RestartCount": 0,
                "Mounts": [{"Source": "PRODUCTION-VOLUME", "Destination": "/var/lib/postgresql"}] if service == "db" else [],
            }

    def __call__(self, *args, stdin=None, env=None, timeout=60):
        self.calls.append((args, env))
        if args[:2] == ("context", "inspect"):
            return json.dumps([{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}])
        if args[0] == "info":
            return json.dumps({"OSType": "linux", "NCPU": 4, "MemTotal": 8 * 1024**3})
        if args[0] == "inspect":
            names = args[3:] if args[1:3] == ("--type", "container") else args[1:]
            items = []
            for name in names:
                item = self.sources.get(name) or self.resources.get(name)
                if not item:
                    raise lab.DockerError("NOT_FOUND")
                items.append(item)
            return json.dumps(items)
        if args[:2] == ("image", "inspect"):
            return "[]"
        if args[0] in ("volume", "network"):
            table = self.volumes if args[0] == "volume" else self.networks
            name = args[-1]
            if args[1] == "create":
                table[name] = {"Name": name, "Labels": {lab.LABEL: RUN_ID}}
                return name
            if args[1] == "inspect":
                if name not in table:
                    raise lab.DockerError("NOT_FOUND")
                return json.dumps([table[name]])
            if args[1] == "rm":
                table.pop(name)
                return name
        if args[0] == "create":
            name = args[args.index("--name") + 1]
            container_id = "id-" + name
            memory = int(args[args.index("--memory") + 1]) if "--memory" in args else 0
            cpu = float(args[args.index("--cpus") + 1]) if "--cpus" in args else 0
            self.resources[container_id] = {"Id": container_id, "Name": "/" + name,
                "Config": {"Labels": {lab.LABEL: RUN_ID}}, "RestartCount": 0,
                "State": {"Status": "running", "ExitCode": 0, "OOMKilled": False},
                "HostConfig": {"Memory": memory, "NanoCpus": int(cpu * 1e9)}}
            return container_id
        if args[0] == "rm":
            self.resources.pop(args[-1])
        return ""


class FakeMetrics:
    fail_stop = False
    missing = False
    optional_missing = False

    def __init__(self, containers, output, **kwargs):
        self.containers = dict(containers)
        self.phases = []

    def add_container(self, container_id, metadata):
        self.containers[container_id] = metadata

    def set_phase(self, phase):
        self.phases.append(phase)

    def start(self):
        pass

    def stop(self):
        if self.fail_stop:
            raise RuntimeError("fixture metric stop failure")

    def summary(self):
        return {"containers": {},
                "missing_metrics": (["fixture_missing"] if self.missing else []) + (["fixture_optional"] if self.optional_missing else []),
                "critical_missing_metrics": ["fixture_missing"] if self.missing else [],
                "optional_missing_metrics": ["fixture_optional"] if self.optional_missing else []}


class ControllerTests(unittest.TestCase):
    def test_dry_run_never_calls_docker(self):
        with patch("lab.docker", side_effect=AssertionError("must not access Docker")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main.main(["--dry-run"]), 0)

    def test_dependency_closure(self):
        self.assertIn("db", lab.required_services(["nginx"]))
        self.assertIn("grafana", lab.required_services(["nginx"]))
        self.assertIn("cadvisor", lab.required_services(["vmagent"]))
        self.assertEqual(lab.required_services(["db"]), ["db"])

    def test_effective_limits(self):
        info = {"HostConfig": {"Memory": 1234, "MemorySwap": -1, "CpuQuota": 150000,
                              "CpuPeriod": 100000, "PidsLimit": 99, "CpusetCpus": "0-1"}}
        self.assertEqual(lab.cpu_limit(info), 1.5)
        flags = lab.inherited_limits(info)
        self.assertIn("--memory", flags)
        self.assertIn("--cpu-quota", flags)
        self.assertIn("--pids-limit", flags)
        self.assertNotIn("--memory", lab.inherited_limits({"HostConfig": {"Memory": 0}}))

    def test_full_stack_uses_owned_volumes_limits_and_no_pull(self):
        fake = FakeDocker()
        dataset = dict(rows=100, redis_keys=100, objects=1, object_bytes=1024,
                       series=100, history_points=2, interfaces=2)
        with tempfile.TemporaryDirectory() as directory, patch("lab.docker", fake), patch.dict("os.environ", {"DOCKER_HOST": ""}):
            test_lab = lab.CapacityLab(RUN_ID, Path(directory), list(lab.SERVICES), dataset, 2, 2, 1024**3)
            host = test_lab.discover()
            self.assertNotIn("not-for-the-report", json.dumps(test_lab.inventory()))
            test_lab.build(host)
            creates = [args for args, _env in fake.calls if args[0] == "create"]
            self.assertEqual(len(creates), 13)  # 11 services, simulator, volume initializer
            self.assertTrue(all("--pull=never" in args for args in creates))
            self.assertTrue(all("PRODUCTION-VOLUME" not in " ".join(args) for args in creates))
            netops_args = next(a for a in creates if a[a.index("--name") + 1].endswith("-netops"))
            self.assertEqual(netops_args[netops_args.index("--memory") + 1], "2147483648")
            self.assertEqual(netops_args[netops_args.index("--cpus") + 1], "2.0")
            netops_env = next(e for a, e in fake.calls if a == netops_args)
            self.assertEqual(netops_env["POSTGRES_USER"], test_lab.credentials["db_user"])
            self.assertIn("@db:5432/", netops_env["DATABASE_URL"])
            self.assertNotIn("not-for-the-report", netops_env["DATABASE_URL"])
            self.assertTrue(any(a[:2] == ("network", "create") and "--internal" in a for a, _e in fake.calls))
            all_argv = " ".join(" ".join(a) for a, _e in fake.calls)
            self.assertNotIn(test_lab.credentials["db_password"], all_argv)
            self.assertTrue(test_lab.cleanup()["complete"])
            self.assertEqual(fake.resources, {})
            self.assertEqual(fake.volumes, {})
            self.assertEqual(fake.networks, {})

    def test_cleanup_refuses_other_runs(self):
        fake = FakeDocker()
        fake.resources["unowned"] = {"Config": {"Labels": {lab.LABEL: "b" * 32}}}
        with tempfile.TemporaryDirectory() as directory, patch("lab.docker", fake):
            test_lab = lab.CapacityLab(RUN_ID, Path(directory), ["db"], {}, 1, 2, 1024**3)
            test_lab.created["db"] = "unowned"
            self.assertFalse(test_lab.cleanup()["complete"])
            self.assertIn("unowned", fake.resources)
            self.assertFalse(any(a[0] == "rm" for a, _e in fake.calls))

    def test_failed_container_logs_keep_exit_reason_and_redact_secrets(self):
        fake = FakeDocker()
        failed = {"Id": "failed", "Config": {"Labels": {lab.LABEL: RUN_ID}},
                  "State": {"Status": "exited", "ExitCode": 1, "OOMKilled": False, "Error": ""}}
        helper = {"Id": "helper", "Config": {"Labels": {lab.LABEL: RUN_ID}},
                  "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False}}
        unowned = {"Id": "unowned", "Config": {"Labels": {lab.LABEL: "b" * 32}},
                   "State": {"Status": "exited", "ExitCode": 1}}
        fake.resources.update(failed=failed, helper=helper, unowned=unowned)
        with tempfile.TemporaryDirectory() as directory, patch("lab.docker", fake):
            test_lab = lab.CapacityLab(RUN_ID, Path(directory), ["netops"], {}, 1, 2, 1024**3)
            test_lab.created = {"netops": "failed", "volume-init": "helper", "other": "unowned"}
            secret = test_lab.credentials["db_password"]
            log_text = "RuntimeError: database bootstrap failed\npassword='" + secret + "'\n" \
                       "postgresql://capacity:unknown-secret@db/x\nAuthorization: Bearer opaque-token\n"
            with patch("lab.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=log_text)) as log_call:
                result = test_lab.failure_diagnostics()
            self.assertEqual(list(result), ["netops"])
            self.assertEqual(result["netops"]["exit_code"], 1)
            self.assertIn("database bootstrap failed", result["netops"]["log_tail"])
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn("unknown-secret", json.dumps(result))
            self.assertNotIn("opaque-token", json.dumps(result))
            self.assertEqual(log_call.call_args.kwargs["stderr"], lab.subprocess.STDOUT)

    def test_running_startup_timeout_can_capture_logs_without_retaining_container(self):
        fake = FakeDocker()
        fake.resources["running"] = {"Id": "running", "Config": {"Labels": {lab.LABEL: RUN_ID}},
                                     "State": {"Status": "running", "ExitCode": 0, "OOMKilled": False}}
        with tempfile.TemporaryDirectory() as directory, patch("lab.docker", fake):
            test_lab = lab.CapacityLab(RUN_ID, Path(directory), ["netops"], {}, 1, 2, 1024**3)
            test_lab.created = {"netops": "running"}
            test_lab.diagnostic_services.add("netops")
            with patch("lab.subprocess.run", side_effect=OSError("fixture CLI error")):
                result = test_lab.failure_diagnostics()
            self.assertEqual(result["netops"]["log_error"], "CONTAINER_LOGS_UNAVAILABLE")
            self.assertTrue(test_lab.cleanup()["complete"])

    def test_running_netops_and_database_logs_are_captured_for_later_failures(self):
        fake = FakeDocker()
        for service in ("netops", "db"):
            fake.resources[service] = {
                "Id": service,
                "Config": {"Labels": {lab.LABEL: RUN_ID}},
                "State": {"Status": "running", "ExitCode": 0, "OOMKilled": False},
            }
        with tempfile.TemporaryDirectory() as directory, patch("lab.docker", fake):
            test_lab = lab.CapacityLab(RUN_ID, Path(directory), ["netops"], {}, 1, 2, 1024**3)
            test_lab.created = {"netops": "netops", "db": "db"}
            with patch("lab.subprocess.run", return_value=SimpleNamespace(
                    returncode=0, stdout="service diagnostic line\n")) as log_call:
                result = test_lab.failure_diagnostics()

        self.assertEqual(list(result), ["netops", "db"])
        self.assertIn("service diagnostic line", result["netops"]["log_tail"])
        self.assertEqual(log_call.call_count, 2)

    def test_thresholds_require_success_and_achieved_rate(self):
        args = main.parse_args(["--services", "db", "--stage-seconds", "10"])
        success = {"scenarios": {"db": {"completed": 100, "successful": 100, "errors": 0,
                  "success_rps": 10, "dropped": 0, "latency_ms": {"p95": 50}}}}
        self.assertTrue(main.evaluate_stage(success, args, 10)["passed"])
        success["scenarios"]["db"]["success_rps"] = 2
        self.assertIn("db:REQUESTED_RATE_NOT_REACHED", main.evaluate_stage(success, args, 10)["failures"])
        self.assertFalse(main.evaluate_stage({"scenarios": {}}, args, 10)["passed"])

    def test_empty_output_report_and_success_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            main.write_report(Path(directory), {"status": "incomplete", "stages": [], "cleanup": {"complete": True}})
            self.assertTrue((Path(directory) / "report.json").exists())
            self.assertIn("incomplete", (Path(directory) / "report.md").read_text(encoding="utf-8"))

    def _full_flow(self, *, failure=None, missing=False, optional_missing=False, fail_stop=False,
                   warmup_failure=False):
        fake = FakeDocker()
        jobs = []

        def fixture_job(test_lab, job, config, stopped, output, timeout):
            jobs.append(job)
            if failure == "prepare" and job == "prepare":
                raise lab.DockerError("FIXTURE_PREPARE_FAILED")
            if warmup_failure and job.startswith("run-warmup"):
                return {"status": "failed", "error": "api_login_timeout",
                        "scenarios": {"db": {"scheduled": 0, "successful": 0, "errors": 1}}}
            if job.startswith("run-stage"):
                rate = config["rps"]
                actual = rate / 2 if failure == "rate" else rate
                return {"scenarios": {"db": {"completed": rate * 5, "successful": rate * 5,
                        "errors": 0, "dropped": 0, "success_rps": actual, "latency_ms": {"p95": 10}}}}
            return {"status": "passed"}

        with tempfile.TemporaryDirectory() as directory, patch("lab.docker", fake), \
             patch("main.sys.platform", "linux"), patch("main.uuid.uuid4", return_value=uuid.UUID(hex=RUN_ID)), \
             patch.dict("os.environ", {"DOCKER_HOST": ""}), patch("metrics.MetricsCollector", FakeMetrics), \
             patch.object(FakeMetrics, "missing", missing), patch.object(FakeMetrics, "optional_missing", optional_missing), \
             patch.object(FakeMetrics, "fail_stop", fail_stop), \
             patch("main.run_job", fixture_job), patch("main.pause"), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main.main(["--run", "--services", "db", "--stages", "5,10", "--stage-seconds", "5",
                               "--warmup-seconds", "5" if warmup_failure else "0", "--cooldown-seconds", "0",
                               "--output-dir", directory])
            report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["cleanup"]["complete"])
            self.assertEqual(fake.resources, {})
            self.assertEqual(fake.volumes, {})
            self.assertEqual(fake.networks, {})
            self.assertNotIn("not-for-the-report", json.dumps(report))
            return code, report, jobs

    def test_orchestrated_full_flow_passes_and_cleans_up(self):
        code, report, jobs = self._full_flow()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["highest_passing_rps_per_scenario"], 10)
        self.assertEqual(jobs, ["prepare", "check-preflight", "run-stage-0", "run-stage-1", "check-final"])

    def test_orchestrated_low_achieved_rate_stops_ramp(self):
        code, report, jobs = self._full_flow(failure="rate")
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertNotIn("run-stage-1", jobs)

    def test_orchestrated_preparation_failure_still_cleans_up(self):
        code, report, jobs = self._full_flow(failure="prepare")
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(jobs, ["prepare"])

    def test_warmup_failure_is_recorded_and_stops_before_formal_stage(self):
        code, report, jobs = self._full_flow(warmup_failure=True)
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["warmups"][0]["workloads"]["error"], "api_login_timeout")
        self.assertEqual(report["stages"], [])
        self.assertIn("WORKLOAD_FAILED:run-warmup-0:api_login_timeout", report["diagnostics"])
        self.assertEqual(jobs, ["prepare", "check-preflight", "run-warmup-0"])

    def test_orchestrated_missing_metrics_invalidates_capacity_claim(self):
        code, report, _jobs = self._full_flow(missing=True)
        self.assertEqual(code, 2)
        self.assertIsNone(report["highest_passing_rps_per_scenario"])

    def test_orchestrated_optional_metric_gap_keeps_capacity_result(self):
        code, report, _jobs = self._full_flow(optional_missing=True)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["resources"]["optional_missing_metrics"], ["fixture_optional"])

    def test_metric_shutdown_failure_does_not_skip_cleanup(self):
        code, report, _jobs = self._full_flow(fail_stop=True)
        self.assertEqual(code, 2)
        self.assertIn("METRIC_COLLECTION_FINALIZATION_FAILED", report["diagnostics"])

    def test_missing_resource_values_are_not_reported_as_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            main.write_report(Path(directory), {"resources": {"containers": {"fixture": {"role": "lab", "phases": {}}}}})
            self.assertIn("| fixture | 不可用 | 不可用 | 不可用 |", (Path(directory) / "report.md").read_text(encoding="utf-8"))

    def test_parameters_reject_zero_and_non_increasing_rates(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for arguments in (["--concurrency", "0"], ["--stages", "10,5"], ["--sample-interval", "nan"]):
                with self.assertRaises(SystemExit):
                    main.parse_args(arguments)


if __name__ == "__main__":
    unittest.main()
