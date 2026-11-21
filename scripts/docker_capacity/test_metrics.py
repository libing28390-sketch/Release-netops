"""Focused stdlib tests for :mod:`metrics`.

These tests keep Docker and ``/proc`` out of the test process.  The parent
capacity tool owns the runtime/container integration tests; this file checks
the counter semantics and safety boundaries that are easy to regress.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from scripts.docker_capacity import metrics


CONTAINER_ID = "a" * 12


def stats_fixture(
    *,
    cpu_total: int = 200,
    cpu_previous: int = 100,
    system_total: int = 1200,
    system_previous: int = 1100,
    usage: int = 900,
    cache: int = 100,
    rx: int = 100,
    tx: int = 200,
    block_read: int = 1000,
    block_write: int = 2000,
    throttled_periods: int | None = 2,
    periods: int | None = 10,
    throttled_time: int | None = 1_000_000_000,
) -> dict:
    throttling = {}
    if throttled_periods is not None:
        throttling["throttled_periods"] = throttled_periods
    if periods is not None:
        throttling["periods"] = periods
    if throttled_time is not None:
        throttling["throttled_time"] = throttled_time
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total, "percpu_usage": [1, 1]},
            "system_cpu_usage": system_total,
            "online_cpus": 2,
            "throttling_data": throttling,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": cpu_previous},
            "system_cpu_usage": system_previous,
        },
        "memory_stats": {"usage": usage, "limit": 99_999_999, "stats": {"cache": cache}},
        "networks": {"eth0": {"rx_bytes": rx, "tx_bytes": tx}},
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "Read", "value": block_read},
                {"op": "Write", "value": block_write},
            ]
        },
        "pids_stats": {"current": 3},
    }


class MetricsCollectorTests(unittest.TestCase):
    def make_collector(self, **metadata) -> tuple[metrics.MetricsCollector, tempfile.TemporaryDirectory[str], list[str]]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        callbacks: list[str] = []
        container_metadata = {
            "name": "lab-actual",
            "service": "lab-service",
            "role": "lab",
            "memory_limit_bytes": 1000,
            "cpu_limit_cores": 2,
            "initial_restart_count": 0,
            "initial_oom_killed": False,
        }
        container_metadata.update(metadata)
        collector = metrics.MetricsCollector(
            {CONTAINER_ID: container_metadata},
            Path(temp_dir.name),
            interval=0.05,
            stop_callback=callbacks.append,
        )
        self.addCleanup(collector.stop)
        return collector, temp_dir, callbacks

    def test_cpu_memory_limit_cache_and_rates(self) -> None:
        collector, temp_dir, callbacks = self.make_collector()
        collector.set_phase("load")

        first = collector.record_stats(CONTAINER_ID, stats_fixture(), sample_mono=1.0)
        second = collector.record_stats(
            CONTAINER_ID,
            stats_fixture(
                cpu_total=300,
                cpu_previous=200,
                system_total=1300,
                system_previous=1200,
                usage=940,
                cache=140,
                rx=200,
                tx=400,
                block_read=1500,
                block_write=2400,
                throttled_periods=5,
                periods=20,
                throttled_time=3_000_000_000,
            ),
            sample_mono=3.0,
        )

        self.assertIsNone(first["net_rx_bytes_per_second"])
        self.assertAlmostEqual(second["cpu_percent"], 200.0)
        self.assertAlmostEqual(second["cpu_limit_percent"], 100.0)
        self.assertEqual(first["memory_working_set_bytes"], 800.0)
        self.assertEqual(second["memory_working_set_bytes"], 800.0)
        self.assertAlmostEqual(second["memory_percent"], 94.0)
        self.assertEqual(second["net_rx_bytes_per_second"], 50.0)
        self.assertEqual(second["net_tx_bytes_per_second"], 100.0)
        self.assertEqual(second["block_read_bytes_per_second"], 250.0)
        self.assertEqual(second["cpu_throttled_periods_delta"], 3.0)
        self.assertEqual(second["cpu_periods_delta"], 10.0)
        self.assertAlmostEqual(second["cpu_throttled_ratio_percent"], 30.0)
        self.assertAlmostEqual(second["cpu_throttled_seconds_delta"], 2.0)
        self.assertEqual(callbacks, [])

        summary = collector.summary()
        phase = summary["containers"]["lab-actual"]["phases"]["load"]
        self.assertEqual(phase["samples"], 2)
        self.assertEqual(phase["memory_max_bytes"], 940.0)
        self.assertEqual(phase["memory_working_set_max_bytes"], 800.0)
        self.assertEqual(phase["net_rx_total_bytes"], 100.0)
        self.assertEqual(phase["net_tx_total_bytes"], 200.0)
        self.assertEqual(phase["block_read_total_bytes"], 500.0)
        self.assertEqual(phase["block_write_total_bytes"], 400.0)
        self.assertNotIn("Config", (Path(temp_dir.name) / "rawstats.jsonl").read_text())

    def test_created_or_first_running_null_stats_do_not_become_missing(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector()
        null_stats = {}
        collector.record_stats(CONTAINER_ID, null_stats, sample_mono=1.0)
        self.assertEqual(collector.summary()["missing_metrics"], [])

        collector._states[CONTAINER_ID]["status"] = "running"
        collector.record_stats(CONTAINER_ID, null_stats, sample_mono=2.0)
        self.assertEqual(collector.summary()["missing_metrics"], [])
        collector.record_stats(CONTAINER_ID, null_stats, sample_mono=3.0)
        self.assertIn(f"container:{CONTAINER_ID}:memory", collector.summary()["missing_metrics"])
        self.assertIn(f"container:{CONTAINER_ID}:network", collector.summary()["missing_metrics"])

    def test_first_cpu_without_precpu_baseline_is_not_missing(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector(status="running")
        first = stats_fixture()
        first.pop("precpu_stats")
        first_row = collector.record_stats(CONTAINER_ID, first, sample_mono=1.0)
        second = stats_fixture()
        second.pop("precpu_stats")
        second["cpu_stats"]["cpu_usage"]["total_usage"] = 300
        second["cpu_stats"]["system_cpu_usage"] = 1300
        second_row = collector.record_stats(CONTAINER_ID, second, sample_mono=2.0)
        self.assertIsNone(first_row["cpu_percent"])
        self.assertAlmostEqual(second_row["cpu_percent"], 200.0)
        self.assertNotIn(f"container:{CONTAINER_ID}:cpu", collector.summary()["missing_metrics"])

    def test_cpu_counter_reset_without_restart_restarts_adjacent_baseline(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector(status="running")
        first = collector.record_stats(CONTAINER_ID, stats_fixture(cpu_total=200, system_total=1200), sample_mono=1.0)
        self.assertIsNone(first["cpu_percent"])

        reset = stats_fixture(cpu_total=50, system_total=1100)
        reset_row = collector.record_stats(CONTAINER_ID, reset, sample_mono=2.0)
        self.assertIsNone(reset_row["cpu_percent"])

        resumed = stats_fixture(cpu_total=100, system_total=1200)
        resumed_row = collector.record_stats(CONTAINER_ID, resumed, sample_mono=3.0)
        self.assertAlmostEqual(resumed_row["cpu_percent"], 100.0)

    def test_cpu_counters_missing_during_stable_runtime_are_missing(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector(status="running")
        first = collector.record_stats(CONTAINER_ID, {"memory_stats": {}}, sample_mono=1.0)
        self.assertIsNone(first["cpu_percent"])
        collector.record_stats(CONTAINER_ID, {"memory_stats": {}}, sample_mono=2.0)
        self.assertIn(f"container:{CONTAINER_ID}:cpu", collector.summary()["missing_metrics"])

    def test_cpu_counters_without_positive_delta_are_eventually_missing(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector(status="running")
        same = stats_fixture(cpu_total=200, system_total=1200)
        collector.record_stats(CONTAINER_ID, same, sample_mono=1.0)
        collector.record_stats(CONTAINER_ID, same, sample_mono=2.0)
        self.assertNotIn(f"container:{CONTAINER_ID}:cpu", collector.summary()["missing_metrics"])
        collector.record_stats(CONTAINER_ID, same, sample_mono=3.0)
        self.assertIn(f"container:{CONTAINER_ID}:cpu", collector.summary()["missing_metrics"])

    def test_running_stats_fetch_failure_is_real_missing_metric(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector(status="running")
        with patch.object(collector, "_fetch_stats", side_effect=RuntimeError("daemon unavailable")):
            collector._sample_container(CONTAINER_ID)
        self.assertIn(f"docker_stats:{CONTAINER_ID}", collector.summary()["missing_metrics"])

    def test_unlimited_memory_does_not_use_engine_memory_limit(self) -> None:
        collector, temp_dir, _callbacks = self.make_collector(memory_limit_bytes=0)
        row = collector.record_stats(CONTAINER_ID, stats_fixture(), sample_mono=1.0)
        self.assertEqual(row["memory_limit_bytes"], 0)
        self.assertIsNone(row["memory_percent"])
        self.assertIsNone(collector.summary()["containers"]["lab-actual"]["phases"]["init"]["memory_max_percent"])

    def test_counter_reset_and_restart_boundary_suppress_negative_deltas(self) -> None:
        collector, temp_dir, _callbacks = self.make_collector()
        collector.record_stats(CONTAINER_ID, stats_fixture(rx=1000, tx=1000, throttled_periods=8, periods=20), sample_mono=1.0)
        collector._states[CONTAINER_ID]["current_restart_count"] = 1
        row = collector.record_stats(
            CONTAINER_ID,
            stats_fixture(cpu_total=50, cpu_previous=0, system_total=50, system_previous=0, rx=10, tx=20, throttled_periods=1, periods=2),
            sample_mono=2.0,
        )
        self.assertIsNone(row["cpu_percent"])
        self.assertIsNone(row["net_rx_bytes_per_second"])
        self.assertIsNone(row["cpu_throttled_periods_delta"])

        # The new baseline is usable after the restart boundary.
        row = collector.record_stats(
            CONTAINER_ID,
            stats_fixture(cpu_total=100, cpu_previous=50, system_total=100, system_previous=50, rx=20, tx=40, throttled_periods=3, periods=5),
            sample_mono=3.0,
        )
        self.assertAlmostEqual(row["cpu_percent"], 200.0)
        self.assertEqual(row["net_rx_bytes_per_second"], 10.0)
        self.assertEqual(row["cpu_throttled_periods_delta"], 2.0)

    def test_event_oom_is_targeted_and_invokes_lab_stop_callback(self) -> None:
        collector, temp_dir, callbacks = self.make_collector()
        line = json.dumps({"Action": "oom", "Actor": {"ID": CONTAINER_ID}, "time": 123})
        self.assertTrue(collector.process_event_line(line))
        self.assertFalse(collector.process_event_line(json.dumps({"Action": "oom", "Actor": {"ID": "b" * 12}})))
        summary = collector.summary()["containers"]["lab-actual"]
        self.assertEqual(summary["oom_events"], 1)
        self.assertEqual(callbacks, [f"container_oom:{CONTAINER_ID}"])
        self.assertTrue(any(reason.startswith("container_oom:") for reason in collector.summary()["stop_reasons"]))

    def test_inspect_restart_and_oom_transition(self) -> None:
        collector, temp_dir, callbacks = self.make_collector()
        completed = MagicMock(returncode=0, stdout=json.dumps([{"Id": CONTAINER_ID, "RestartCount": 2, "State": {"Status": "running", "OOMKilled": True}}]))
        with patch("scripts.docker_capacity.metrics.subprocess.run", return_value=completed):
            collector._inspect_once()
        item = collector.summary()["containers"]["lab-actual"]
        self.assertEqual(item["restart_delta"], 2)
        self.assertEqual(item["oom_events"], 1)
        self.assertEqual(callbacks, [f"container_oom:{CONTAINER_ID}"])

    def test_generator_exit_stats_are_not_global_missing_and_lab_exit_stops(self) -> None:
        collector, temp_dir, callbacks = self.make_collector()
        generator_id = "g" * 12
        collector.add_container(generator_id, {"name": "runner", "service": "runner", "role": "generator"})
        with patch.object(collector, "_fetch_stats", side_effect=RuntimeError("exited")):
            collector._sample_container(generator_id)
        self.assertNotIn(f"docker_stats:{generator_id}", collector.summary()["missing_metrics"])
        self.assertEqual(collector.summary()["containers"]["runner"]["errors"], [])

        completed = MagicMock(returncode=0, stdout=json.dumps([{"Id": CONTAINER_ID, "RestartCount": 0, "State": {"Status": "exited", "OOMKilled": False}}]))
        with patch("scripts.docker_capacity.metrics.subprocess.run", return_value=completed):
            collector._inspect_once()
        self.assertIn(f"container_unexpected_exit:{CONTAINER_ID}", callbacks)

    def test_endpoint_falls_back_when_one_shot_is_not_supported(self) -> None:
        collector, temp_dir, _callbacks = self.make_collector()
        response = stats_fixture()
        with patch.object(collector, "_docker_get_json", side_effect=[RuntimeError("unsupported query"), response]) as get_json:
            result = collector._fetch_stats(CONTAINER_ID)
        self.assertEqual(result, response)
        self.assertEqual(get_json.call_args_list[0].args[0], f"/containers/{CONTAINER_ID}/stats?stream=false&one-shot=true")
        self.assertEqual(get_json.call_args_list[1].args[0], f"/containers/{CONTAINER_ID}/stats?stream=false")

    def test_missing_proc_is_unavailable_and_not_zero(self) -> None:
        collector, temp_dir, _callbacks = self.make_collector()
        with tempfile.TemporaryDirectory() as missing_proc:
            with patch.object(metrics, "PROC_ROOT", Path(missing_proc)):
                collector.sample_host_once()
        summary = collector.summary()
        self.assertEqual(summary["host"]["samples"], 1)
        self.assertIsNone(summary["host"]["minimum_available_bytes"])
        self.assertIn("host_meminfo", summary["missing_metrics"])
        self.assertIn("host_proc_stat", summary["missing_metrics"])
        self.assertIn("host_loadavg", summary["missing_metrics"])
        self.assertIn("host_proc_stat", summary["critical_missing_metrics"])
        self.assertNotIn("host_loadavg", summary["critical_missing_metrics"])

    def test_sustained_host_cpu_above_threshold_requests_stop(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        callbacks: list[str] = []
        collector = metrics.MetricsCollector(
            {}, Path(temp_dir.name), interval=2.0, stop_callback=callbacks.append,
            max_host_cpu_percent=80.0, host_cpu_stop_samples=2,
        )
        self.addCleanup(collector.stop)
        cpu_samples = [
            {"busy_seconds": 0.0, "iowait_seconds": 0.0, "total_seconds": 0.0},
            {"busy_seconds": 90.0, "iowait_seconds": 0.0, "total_seconds": 100.0},
            {"busy_seconds": 180.0, "iowait_seconds": 0.0, "total_seconds": 200.0},
        ]
        meminfo = {"MemAvailable": 4 * 1024**3, "MemTotal": 8 * 1024**3,
                   "SwapTotal": 0, "SwapFree": 0}
        with patch.object(collector, "_read_meminfo", return_value=meminfo), \
             patch.object(collector, "_read_proc_cpu", side_effect=cpu_samples), \
             patch.object(collector, "_read_proc_load", return_value=(0.1, 0.1, 0.1)), \
             patch("scripts.docker_capacity.metrics.shutil.disk_usage",
                   return_value=type("Usage", (), {"free": 1000, "total": 2000})()):
            collector.sample_host_once()
            collector.sample_host_once()
            self.assertEqual(callbacks, [])
            collector.sample_host_once()

        self.assertEqual(callbacks, ["host_cpu_above_threshold"])
        self.assertIn("host_cpu_above_threshold", collector.summary()["stop_reasons"])

    def test_optional_block_io_gap_does_not_hide_critical_cpu_memory_gaps(self) -> None:
        collector, _temp_dir, _callbacks = self.make_collector(status="running")
        collector.record_stats(CONTAINER_ID, stats_fixture(), sample_mono=1.0)
        collector.record_stats(CONTAINER_ID, stats_fixture(cpu_total=300, system_total=1300), sample_mono=2.0)
        collector._record_container_missing_locked(CONTAINER_ID, f"container:{CONTAINER_ID}:block_io")
        summary = collector.summary()
        self.assertIn(f"container:{CONTAINER_ID}:block_io", summary["optional_missing_metrics"])
        self.assertNotIn(f"container:{CONTAINER_ID}:block_io", summary["critical_missing_metrics"])

        collector._record_container_missing_locked(CONTAINER_ID, f"container:{CONTAINER_ID}:memory")
        summary = collector.summary()
        self.assertIn(f"container:{CONTAINER_ID}:memory", summary["critical_missing_metrics"])

    def test_start_stop_terminates_event_process_without_docker_or_network(self) -> None:
        collector, temp_dir, _callbacks = self.make_collector()
        fake_process = MagicMock()
        fake_process.stdout = iter(())
        fake_process.wait.return_value = 0
        with patch("scripts.docker_capacity.metrics.subprocess.Popen", return_value=fake_process), patch.object(collector, "_fetch_stats", side_effect=RuntimeError("test stats")), patch("scripts.docker_capacity.metrics.subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            started = time.monotonic()
            collector.start()
            time.sleep(0.08)
            collector.stop()
        self.assertLess(time.monotonic() - started, 10.0)
        fake_process.terminate.assert_called_once()
        self.assertTrue((Path(temp_dir.name) / "container-stats.csv").exists())
        self.assertTrue((Path(temp_dir.name) / "host-stats.csv").exists())


if __name__ == "__main__":
    unittest.main()
