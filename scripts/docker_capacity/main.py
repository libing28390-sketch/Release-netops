#!/usr/bin/env python3
"""Run isolated, staged workloads with the deployment's local Docker images."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from lab import CapacityLab, DockerError, SERVICES, docker, metadata

TOOL_VERSION = "1.1.4"


def parse_csv_ints(value: str) -> list[int]:
    try:
        result = [int(item) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use comma-separated integers") from exc
    if not result or any(n < 1 or n > 1000 for n in result) or result != sorted(set(result)):
        raise argparse.ArgumentTypeError("Stages must strictly increase, each from 1 to 1000 RPS")
    return result


def parse_services(value: str) -> list[str]:
    services = value.split(",")
    if not services or any(s not in SERVICES for s in services) or len(set(services)) != len(services):
        raise argparse.ArgumentTypeError("Select unique services from: " + ",".join(SERVICES))
    return services


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Defaults create no Docker resources (dry run).
--run creates temporary isolated containers and volumes, inheriting source limits.
It generates test-only writes and simulated SNMP traffic. No production data is copied.
Requires Linux, host Python 3.10+, local Docker CLI/socket, and the existing Nexora images.
This tests the stated synthetic dataset, not every possible production workload.

Examples:
  bash scripts/stress-test-docker.sh --dry-run
  bash scripts/stress-test-docker.sh --run
  bash scripts/stress-test-docker.sh --run --stages 5,20,50 --stage-seconds 300
  bash scripts/stress-test-docker.sh --run --services netops,nginx,db,redis
  bash scripts/stress-test-docker.sh --probe --run   # old reachability precheck
""")
    parser.add_argument("--version", action="version", version="Nexora Docker capacity test " + TOOL_VERSION)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Create isolated lab and execute the capacity test")
    mode.add_argument("--dry-run", action="store_true", help="Only show the plan (default, no Docker access)")
    parser.add_argument("--services", type=parse_services, default=list(SERVICES))
    rate = parser.add_mutually_exclusive_group()
    rate.add_argument("--stages", type=parse_csv_ints, default=[5, 20, 50], help="Increasing RPS per scenario, default 5,20,50")
    rate.add_argument("--rps", type=int, help="Single stage RPS per scenario")
    parser.add_argument("--stage-seconds", "--duration", type=int, default=120, help="Measurement time per stage, 5..3600 seconds")
    parser.add_argument("--warmup-seconds", type=int, default=15)
    parser.add_argument("--baseline-seconds", type=int, default=10)
    parser.add_argument("--cooldown-seconds", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=8, help="Clients per scenario, 1..32")
    parser.add_argument("--sample-interval", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--rows", type=int, default=10000, help="Synthetic database rows")
    parser.add_argument("--redis-keys", type=int, default=10000)
    parser.add_argument("--objects", type=int, default=32)
    parser.add_argument("--object-bytes", type=int, default=262144)
    parser.add_argument("--series", type=int, default=10000, help="Synthetic active series")
    parser.add_argument("--history-points", type=int, default=30)
    parser.add_argument("--interfaces", type=int, default=48, help="Interfaces per simulated SNMP device")
    parser.add_argument("--snmp-targets", type=int, default=16)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    parser.add_argument("--max-error-percent", type=float, default=1)
    parser.add_argument("--min-rate-percent", type=float, default=90, help="Minimum achieved successful rate / requested rate")
    parser.add_argument("--min-host-available-percent", type=float, default=10)
    parser.add_argument("--max-container-memory-percent", type=float, default=95)
    parser.add_argument("--generator-cpus", type=float, default=2.0)
    parser.add_argument("--generator-memory-mib", type=int, default=1024)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    limits = {"stage_seconds": (5, 3600), "warmup_seconds": (0, 300), "baseline_seconds": (1, 300),
              "cooldown_seconds": (0, 300), "concurrency": (1, 32), "sample_interval": (0.5, 10),
              "timeout_seconds": (0.5, 60), "rows": (100, 1000000), "redis_keys": (100, 1000000),
              "objects": (1, 10000), "object_bytes": (1024, 16777216), "series": (100, 1000000),
              "history_points": (2, 1000), "interfaces": (1, 1000), "snmp_targets": (1, 128),
              "max_p95_ms": (1, 60000), "max_error_percent": (0, 100), "min_rate_percent": (1, 100),
              "min_host_available_percent": (1, 50), "max_container_memory_percent": (50, 99),
              "generator_cpus": (0.1, 16), "generator_memory_mib": (256, 8192)}
    for key, (low, high) in limits.items():
        if not low <= getattr(args, key) <= high:
            parser.error(f"--{key.replace('_', '-')} must be from {low} to {high}")
    if args.rps is not None:
        if not 1 <= args.rps <= 1000:
            parser.error("--rps must be from 1 to 1000")
        args.stages = [args.rps]
    return args


def evaluate_stage(summary: dict, args: argparse.Namespace, rate: int) -> dict:
    failures = []
    evaluated = {}
    for service in args.services:
        sample = summary.get("scenarios", {}).get(service)
        if not sample:
            failures.append(service + ":MISSING_WORKLOAD_RESULT")
            continue
        completed = sample.get("completed", 0)
        successes = sample.get("successful", 0)
        errors = sample.get("errors", 0)
        dropped = sample.get("dropped", 0)
        actual_rate = sample.get("success_rps", successes / max(args.stage_seconds, 0.001))
        error_percent = errors * 100 / completed if completed else 100
        p95 = sample.get("latency_ms", {}).get("p95")
        conditions = []
        if not successes:
            conditions.append("NO_SUCCESSFUL_REQUESTS")
        if error_percent > args.max_error_percent:
            conditions.append("ERROR_THRESHOLD")
        if p95 is None or p95 > args.max_p95_ms:
            conditions.append("LATENCY_THRESHOLD")
        if actual_rate < rate * args.min_rate_percent / 100:
            conditions.append("REQUESTED_RATE_NOT_REACHED")
        if dropped:
            conditions.append("GENERATOR_DROPPED_REQUESTS")
        evaluated[service] = {"passed": not conditions, "reasons": conditions,
                              "success_rps": actual_rate, "error_percent": round(error_percent, 3), "p95_ms": p95}
        failures.extend(service + ":" + reason for reason in conditions)
    return {"passed": not failures, "failures": failures, "scenarios": evaluated}


def pause(seconds: float, stopped: threading.Event) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stopped.wait(min(0.5, max(0, deadline - time.monotonic()))):
        pass


def run_job(lab: CapacityLab, job: str, config: dict, stopped: threading.Event,
            output: Path, timeout: float) -> dict:
    container_id = lab.create_runner(job)
    # Secrets remain in stdin, never in argv or a report file.
    payload = json.dumps(config)
    process = subprocess.Popen(["docker", "start", "--attach", "--interactive", container_id],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    deadline = time.monotonic() + timeout
    first_input: str | None = payload
    while True:
        try:
            stdout, stderr = process.communicate(input=first_input, timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            first_input = None
            if stopped.is_set() or time.monotonic() >= deadline:
                try:
                    docker("stop", "--time", "2", container_id, timeout=8)
                except DockerError:
                    pass
                process.kill()
                process.communicate(timeout=5)
                raise DockerError("WORKLOAD_STOPPED:" + job)
    if process.returncode != 0:
        # Keep stable structured errors only; third-party stack traces may expose credentials.
        try:
            failed = json.loads(stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            failed = {"status": "failed", "error": "WORKLOAD_PROCESS_FAILED"}
        if isinstance(failed, dict):
            (output / (job + ".json")).write_text(
                json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
        if isinstance(failed, dict) and isinstance(failed.get("error"), str):
            code = failed["error"].split(":", 1)[0]
            if code.replace("_", "").isalnum():
                raise DockerError("WORKLOAD_FAILED:" + job + ":" + code)
        raise DockerError("WORKLOAD_FAILED:" + job)
    try:
        summary = json.loads(stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise DockerError("INVALID_WORKLOAD_SUMMARY:" + job) from exc
    if not isinstance(summary, dict):
        raise DockerError("INVALID_WORKLOAD_SUMMARY:" + job)
    # The workload module's public contract explicitly excludes credentials and response bodies.
    (output / (job + ".json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def write_report(output: Path, report: dict) -> None:
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Nexora Docker 容量测试", "", "状态：" + report.get("status", "unknown"),
             "", "范围：独立测试实例、指定合成数据和混合负载；结论仅适用于本次条件。", "",
             "| 档位（每场景 RPS） | 阈值结果 | 原因 |", "| --- | --- | --- |"]
    for stage in report.get("stages", []):
        evaluation = stage.get("evaluation", {})
        lines.append(f"| {stage['rps_per_scenario']} | {'通过' if evaluation.get('passed') else '失败'} | " +
                     "; ".join(evaluation.get("failures", [])) + " |")
    if report.get("warmups"):
        lines += ["", "## 预热结果", "", "| 档位（每场景 RPS） | 预热秒数 | 状态 |", "| --- | ---: | --- |"]
        for warmup in report["warmups"]:
            workload = warmup.get("workloads", {})
            lines.append(f"| {warmup['rps_per_scenario']} | {warmup['duration_seconds']} | {workload.get('status', 'unknown')} |")
    lines += ["", "最高通过档位（RPS/场景）：" + str(report.get("highest_passing_rps_per_scenario")), "",
              "该档位不是生产最大容量，也不代表长期保留全部业务数据的内存需求。", "",
              "## 运行时限额", "", "| 来源容器 | CPU 核数上限 | 内存硬限制（字节） |", "| --- | --- | --- |"]
    for item in report.get("source_inventory", {}).values():
        lines.append(f"| {item['name']} | {item.get('cpu_limit_cores') or '无显式配额'} | {item.get('memory_limit_bytes') or '无显式硬限制'} |")
    lines += ["", "## 诊断", ""]
    for reason in report.get("diagnostics", []):
        lines += ["- " + reason]
    container_diagnostics = report.get("container_diagnostics", {})
    if container_diagnostics:
        lines += ["", "## 测试容器退出信息", "", "| 服务 | 状态 | 退出码 | OOM |", "| --- | --- | --- | --- |"]
        for service, sample in container_diagnostics.items():
            if isinstance(sample, dict):
                lines.append(f"| {service} | {sample.get('status')} | {sample.get('exit_code')} | {sample.get('oom_killed')} |")
        lines += ["", "清理前捕获的脱敏日志尾部见 report.json 的 container_diagnostics 字段。"]
    resources = report.get("resources", {})
    lines += ["", "## 资源峰值", "", "| 容器 | CPU 峰值（%） | 内存峰值（字节） | CPU 限流（秒） | OOM | 重启 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for name, sample in resources.get("containers", {}).items():
        if sample.get("role") == "source":
            continue
        phases = list(sample.get("phases", {}).values())
        cpu_values = [p["cpu_max_percent"] for p in phases if p.get("cpu_max_percent") is not None]
        memory_values = [p["memory_max_bytes"] for p in phases if p.get("memory_max_bytes") is not None]
        throttle_values = [p["cpu_throttled_seconds"] for p in phases if p.get("cpu_throttled_seconds") is not None]
        cpu = f"{max(cpu_values):.2f}" if cpu_values else "不可用"
        memory = str(max(memory_values)) if memory_values else "不可用"
        throttle = f"{sum(throttle_values):.3f}" if throttle_values else "不可用"
        lines.append(f"| {name} | {cpu} | {memory} | {throttle} | {sample.get('oom_events', '?')} | {sample.get('restart_delta', '?')} |")
    lines += ["", "关键指标缺失：" + json.dumps(resources.get("critical_missing_metrics", []), ensure_ascii=False),
              "", "其他未提供指标：" + json.dumps(resources.get("optional_missing_metrics", []), ensure_ascii=False),
              "", "清理：" + ("完成" if report.get("cleanup", {}).get("complete") else "有残留，请检查 report.json 的 cleanup 字段"), "",
              "## 口径与限制", ""]
    lines += ["- " + item for item in report.get("limitations", [])]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print("Nexora isolated Docker capacity test " + TOOL_VERSION, flush=True)
    print("Scenarios: " + ", ".join(args.services), flush=True)
    print(f"Stages: {args.stages} RPS PER scenario; {args.stage_seconds}s each; warmup {args.warmup_seconds}s", flush=True)
    print(f"Dataset: {args.rows} DB rows, {args.redis_keys} keys, {args.series} series x {args.history_points} points, "
          f"{args.snmp_targets} SNMP devices x {args.interfaces} interfaces, {args.objects} objects x {args.object_bytes} bytes", flush=True)
    if not args.run:
        print("DRY RUN: no Docker access or resources created. Pass --run to execute.")
        return 0
    if sys.platform != "linux":
        print("[ERROR] Execute --run on the Linux Docker deployment host.", file=sys.stderr)
        return 2
    from metrics import MetricsCollector

    run_id = uuid.uuid4().hex
    output = (args.output_dir or Path("/tmp") / ("nexora-capacity-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + run_id[:8])).resolve()
    if output.exists() and any(output.iterdir()):
        print("[ERROR] Output directory must be empty to preserve existing reports.", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    stopped = threading.Event()
    reasons: list[str] = []
    def request_stop(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)
            print("[STOP] " + reason, flush=True)
        stopped.set()
    def signal_handler(number: int, _frame: object) -> None:
        request_stop("SIGNAL_" + str(number))
    prior_handlers = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        prior_handlers[number] = signal.signal(number, signal_handler)
    dataset = {"rows": args.rows, "redis_keys": args.redis_keys, "objects": args.objects,
               "object_bytes": args.object_bytes, "series": args.series,
               "history_points": args.history_points, "interfaces": args.interfaces}
    lab = CapacityLab(run_id, output, args.services, dataset, args.snmp_targets,
                      args.generator_cpus, args.generator_memory_mib * 1024**2, stopped.is_set)
    collector = None
    report = {"tool_version": TOOL_VERSION, "run_id": run_id, "status": "incomplete", "scope": "isolated_synthetic_capacity_test",
              "requested_services": args.services, "dataset": dataset, "snmp_targets": args.snmp_targets,
              "thresholds": {"p95_ms": args.max_p95_ms, "error_percent": args.max_error_percent,
                             "minimum_success_rate_percent": args.min_rate_percent},
              "warmups": [], "stages": [], "diagnostics": [], "limitations": [
                  "使用与源容器相同的镜像及 CPU/内存/PID 限额；独立数据和网络，未复制生产持久化数据。",
                  "API 查询、SQL、缓存、对象、时序及模拟 SNMP 是明确的数据集；未覆盖所有后台作业、AI、PAM 和真实设备延迟。",
                  "测试实例与源实例共享宿主机；原业务、生成器、cAdvisor 和 Docker API 开销可能影响结果。",
                  "Grafana 用测试管理员鉴权调用数据源查询，未覆盖浏览器渲染和生产认证代理链。",
                  "NetOps 保留数据库连接池/worker 参数，测试 API 使用本地存储模式；S3 对象路径单独施压。",
                  "SNMP 模拟设备固定响应规模，未覆盖真实网络丢包、不同厂商或 SNMPv3 加密开销。",
                  "时序历史和对象规模是合成数据；长期保留、压缩、持久化维护和内存增长需增加数据量与持续时间。",
                  "只读 socket proxy 的允许 API 用于 cAdvisor；未开放 Docker 写权限，未将 socket 挂载到负载生成器。",
                  "阶段通过仅说明本次数据/档位/SLO通过；工具不修改限额，也不自动断言生产容量足够。"]}
    try:
        print("[SETUP] Inspecting source images and effective limits...", flush=True)
        host = lab.discover()
        report["host_configuration"] = {key: val for key, val in host.items() if key != "socket_path"}
        report["source_inventory"] = lab.inventory()
        containers = {i["Id"]: metadata(i, s, "source") for s, i in lab.sources.items()}
        collector = MetricsCollector(containers, output, interval=args.sample_interval, socket_path=host["socket_path"],
                                     stop_callback=request_stop, min_host_available_percent=args.min_host_available_percent,
                                     max_container_memory_percent=args.max_container_memory_percent)
        lab.on_container = collector.add_container
        collector.set_phase("setup")
        collector.start()
        print("[SETUP] Creating owned internal network and isolated test volumes...", flush=True)
        lab.build(host)
        config = lab.runner_config()
        config.update(concurrency=args.concurrency, timeout_seconds=args.timeout_seconds)
        collector.set_phase("prepare")
        print("[PREPARE] Seeding synthetic data and test account...", flush=True)
        report["prepare"] = run_job(lab, "prepare", config, stopped, output, 900)
        collector.set_phase("preflight")
        report["preflight"] = run_job(lab, "check-preflight", config, stopped, output, 120)
        collector.set_phase("baseline")
        print("[BASELINE] Sampling all source and lab containers...", flush=True)
        pause(args.baseline_seconds, stopped)
        for index, rate in enumerate(args.stages):
            if stopped.is_set():
                break
            if args.warmup_seconds:
                collector.set_phase(f"warmup-{rate}")
                print(f"[WARMUP] {rate} RPS per scenario", flush=True)
                warm = dict(config, duration_seconds=args.warmup_seconds, rps=rate)
                warmup = run_job(lab, "run-warmup-" + str(index), warm, stopped, output,
                                 args.warmup_seconds + args.timeout_seconds * 2 + 30)
                report["warmups"].append({"rps_per_scenario": rate,
                                          "duration_seconds": args.warmup_seconds,
                                          "workloads": warmup})
                if warmup.get("status") != "passed":
                    error = warmup.get("error")
                    if not isinstance(error, str) or not error.replace("_", "").isalnum() or len(error) > 80:
                        error = "WARMUP_NOT_PASSED"
                    raise DockerError(f"WORKLOAD_FAILED:run-warmup-{index}:{error}")
            collector.set_phase(f"stage-{rate}")
            print(f"[STAGE] {rate} RPS per scenario for {args.stage_seconds}s", flush=True)
            measured = dict(config, duration_seconds=args.stage_seconds, rps=rate)
            summary = run_job(lab, "run-stage-" + str(index), measured, stopped, output,
                              args.stage_seconds + args.timeout_seconds * 2 + 30)
            evaluation = evaluate_stage(summary, args, rate)
            report["stages"].append({"rps_per_scenario": rate, "duration_seconds": args.stage_seconds,
                                     "workloads": summary, "evaluation": evaluation})
            print("[STAGE RESULT] " + ("PASS" if evaluation["passed"] else "FAIL"), flush=True)
            collector.set_phase(f"cooldown-{rate}")
            pause(args.cooldown_seconds, stopped)
            if not evaluation["passed"]:
                report["diagnostics"] += evaluation["failures"]
                print("[STOP RAMP] A threshold failed; higher stages will not run.", flush=True)
                break
        if not stopped.is_set():
            collector.set_phase("verification")
            report["verification"] = run_job(lab, "check-final", config, stopped, output, 120)
        report["status"] = "aborted" if stopped.is_set() else (
            "passed" if report["stages"] and all(s["evaluation"]["passed"] for s in report["stages"]) else "failed")
    except (DockerError, OSError, RuntimeError, ValueError) as exc:
        report["status"] = "aborted" if stopped.is_set() else "incomplete"
        # DockerError deliberately contains stable codes, never daemon/SQL log text.
        report["diagnostics"].append(str(exc) if isinstance(exc, DockerError) else type(exc).__name__)
        print("[ERROR] " + report["diagnostics"][-1], file=sys.stderr, flush=True)
    finally:
        if collector:
            try:
                collector.set_phase("cleanup")
                collector.stop()
                report["resources"] = collector.summary()
            except Exception:
                report["status"] = "incomplete"
                report["diagnostics"].append("METRIC_COLLECTION_FINALIZATION_FAILED")
        report["diagnostics"] += reasons
        if report["status"] != "passed":
            try:
                report["container_diagnostics"] = lab.failure_diagnostics()
            except Exception:
                report["diagnostics"].append("CONTAINER_DIAGNOSTIC_COLLECTION_FAILED")
        print("[CLEANUP] Removing only resources labelled with this run ID...", flush=True)
        try:
            report["cleanup"] = lab.cleanup()
        except Exception:
            report["cleanup"] = {"complete": False, "errors": ["CLEANUP_FINALIZATION_FAILED"],
                                 "resource_prefix": lab.prefix}
        if not report["cleanup"]["complete"]:
            report["status"] = "incomplete"
        passing = [s["rps_per_scenario"] for s in report["stages"] if s["evaluation"]["passed"]]
        report["highest_passing_rps_per_scenario"] = max(passing) if passing else None
        for sample in report.get("resources", {}).get("containers", {}).values():
            if sample.get("role") == "lab" and (sample.get("oom_events", 0) or sample.get("restart_delta", 0)):
                report["status"] = "failed"
                report["diagnostics"].append("TEST_CONTAINER_OOM_OR_RESTART:" + sample.get("service", "unknown"))
            if sample.get("role") == "generator":
                for phase, data in sample.get("phases", {}).items():
                    if phase.startswith("stage-") and (data.get("cpu_max_percent") or 0) >= args.generator_cpus * 85:
                        report["diagnostics"].append("GENERATOR_CPU_MAY_LIMIT_RATE:" + phase)
        if report.get("resources", {}).get("critical_missing_metrics") and report["status"] == "passed":
            report["status"] = "incomplete"
            report["diagnostics"].append("MISSING_CRITICAL_RESOURCE_METRICS")
        if report["status"] != "passed":
            report["highest_passing_rps_per_scenario"] = None if report["status"] in ("aborted", "incomplete") else report["highest_passing_rps_per_scenario"]
        write_report(output, report)
        for number, handler in prior_handlers.items():
            signal.signal(number, handler)
        print(f"[RESULT] {report['status'].upper()}\nReport: {output / 'report.md'}\nJSON: {output / 'report.json'}", flush=True)
    return 0 if report["status"] == "passed" else 1 if report["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
