"""Owned Docker resources for an isolated capacity run (stdlib only)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from typing import Callable

SERVICES = (
    "db", "netops", "redis", "victoriametrics", "snmp-exporter", "vmagent",
    "docker-socket-proxy", "cadvisor", "grafana", "nginx", "seaweedfs",
)
LABEL = "nexora.capacity.run"
DEPENDENCIES = {
    "netops": {"db", "redis", "victoriametrics"},
    "nginx": {"netops", "grafana"},
    "grafana": {"victoriametrics"},
    "vmagent": {"victoriametrics", "snmp-exporter", "cadvisor"},
    "cadvisor": {"docker-socket-proxy"},
}


class DockerError(RuntimeError):
    pass


def docker(*args: str, stdin: str | None = None, env: dict | None = None,
           timeout: float = 60) -> str:
    """Never echo a command's stdin or environment, which can contain secrets."""
    try:
        result = subprocess.run(["docker", *args], input=stdin, text=True,
                                capture_output=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise DockerError("DOCKER_CLI_NOT_FOUND") from exc
    except subprocess.TimeoutExpired as exc:
        raise DockerError("DOCKER_OPERATION_TIMED_OUT:" + args[0]) from exc
    if result.returncode:
        # Startup logs and daemon error text can contain environment values.
        raise DockerError("DOCKER_OPERATION_FAILED:" + args[0])
    return result.stdout.strip()


def cpu_limit(info: dict) -> float | None:
    host = info.get("HostConfig", {})
    if host.get("NanoCpus", 0) > 0:
        return host["NanoCpus"] / 1_000_000_000
    if host.get("CpuQuota", 0) > 0:
        return host["CpuQuota"] / (host.get("CpuPeriod", 0) or 100_000)
    return None


def inherited_limits(info: dict) -> list[str]:
    host = info.get("HostConfig", {})
    flags = []
    for field, flag in (("Memory", "--memory"), ("MemoryReservation", "--memory-reservation")):
        if host.get(field, 0) > 0:
            flags += [flag, str(host[field])]
    if host.get("Memory", 0) and host.get("MemorySwap", 0):
        flags += ["--memory-swap", str(host["MemorySwap"])]
    if host.get("NanoCpus", 0) > 0:
        flags += ["--cpus", str(host["NanoCpus"] / 1_000_000_000)]
    elif host.get("CpuQuota", 0) > 0:
        flags += ["--cpu-quota", str(host["CpuQuota"]), "--cpu-period", str(host.get("CpuPeriod", 0) or 100_000)]
    if host.get("CpuShares", 0) > 0:
        flags += ["--cpu-shares", str(host["CpuShares"])]
    if host.get("CpusetCpus"):
        flags += ["--cpuset-cpus", host["CpusetCpus"]]
    if host.get("PidsLimit", 0) and host["PidsLimit"] > 0:
        flags += ["--pids-limit", str(host["PidsLimit"])]
    return flags


def metadata(info: dict, service: str, role: str) -> dict:
    return {
        "name": info.get("Name", "").lstrip("/"), "service": service, "role": role,
        "memory_limit_bytes": info.get("HostConfig", {}).get("Memory", 0),
        "cpu_limit_cores": cpu_limit(info),
        "initial_restart_count": info.get("RestartCount", 0),
        "initial_oom_killed": info.get("State", {}).get("OOMKilled", False),
    }


def required_services(selected: list[str]) -> list[str]:
    result = set(selected)
    while True:
        expanded = result | set().union(*(DEPENDENCIES.get(s, set()) for s in result))
        if expanded == result:
            return [s for s in SERVICES if s in result]
        result = expanded


class CapacityLab:
    def __init__(self, run_id: str, output: Path, services: list[str], dataset: dict,
                 snmp_targets: int, generator_cpus: float, generator_memory: int,
                 should_stop: Callable[[], bool] | None = None):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("INVALID_RUN_ID")
        self.run_id = run_id
        self.prefix = "nexora-capacity-" + run_id[:12]
        self.output = output.resolve()
        self.files = self.output / "lab-config"
        self.files.mkdir(parents=True, exist_ok=True)
        self.scripts = Path(__file__).resolve().parent
        self.selected = services
        self.required = required_services(services)
        self.dataset = dataset
        self.ports = list(range(1161, 1161 + snmp_targets))
        self.generator_cpus = generator_cpus
        self.generator_memory = generator_memory
        self.should_stop = should_stop or (lambda: False)
        self.sources: dict[str, dict] = {}
        self.created: dict[str, str] = {}
        self.volumes: list[str] = []
        self.diagnostic_services: set[str] = set()
        self.network = ""
        self.credentials = {
            "db_user": "capacity", "db_password": secrets.token_hex(24),
            "db_name": "nexora_capacity_" + run_id,
            "app_username": "capacity", "app_password": secrets.token_hex(24),
            "redis_password": secrets.token_hex(24), "grafana_user": "admin",
            "grafana_password": secrets.token_hex(24), "s3_access_key": secrets.token_hex(16),
            "s3_secret_key": secrets.token_hex(24), "s3_bucket": "nexora-capacity-" + run_id,
        }
        self._redaction_values = {value for key, value in self.credentials.items()
                                  if any(word in key for word in ("password", "secret", "key"))}
        self.on_container: Callable[[str, dict], None] | None = None

    def inspect(self, name: str) -> dict:
        return json.loads(docker("inspect", "--type", "container", name))[0]

    def discover(self) -> dict:
        info = json.loads(docker("info", "--format", "{{json .}}"))
        if info.get("OSType") != "linux":
            raise DockerError("LINUX_DOCKER_HOST_REQUIRED")
        # A bind mount and /proc measurements must refer to the same host.
        endpoint = os.environ.get("DOCKER_HOST", "")
        if not endpoint:
            context = json.loads(docker("context", "inspect"))[0]
            endpoint = context.get("Endpoints", {}).get("docker", {}).get("Host", "")
        if not endpoint.startswith("unix://"):
            raise DockerError("LOCAL_UNIX_DOCKER_CONTEXT_REQUIRED")
        for service in set(self.required) | {"netops"}:
            try:
                source = self.inspect("nexora-" + service)
            except DockerError as exc:
                raise DockerError("SOURCE_CONTAINER_REQUIRED:nexora-" + service) from exc
            if source.get("State", {}).get("Status") != "running":
                raise DockerError("SOURCE_CONTAINER_NOT_RUNNING:nexora-" + service)
            docker("image", "inspect", source["Image"])
            self.sources[service] = source
        return {"socket_path": endpoint[len("unix://"):],
                "engine_version": info.get("ServerVersion"), "host_cpus": info.get("NCPU"),
                "host_memory_bytes": info.get("MemTotal"),
                "docker_root": info.get("DockerRootDir", "/var/lib/docker")}

    def inventory(self) -> dict:
        return {s: {**metadata(i, s, "source"), "image_id": i["Image"],
                    "pids_limit": i.get("HostConfig", {}).get("PidsLimit"),
                    "cpu_cpuset": i.get("HostConfig", {}).get("CpusetCpus", "")}
                for s, i in self.sources.items()}

    def _volume(self, suffix: str) -> str:
        name = self.prefix + "-" + suffix
        docker("volume", "create", "--label", LABEL + "=" + self.run_id, name)
        if not self.owns("volume", name):
            raise DockerError("TEST_VOLUME_OWNERSHIP_NOT_CONFIRMED")
        self.volumes.append(name)
        return name

    def _create(self, service: str, source: str, env: dict | None = None,
                extra: list[str] | None = None, command: list[str] | None = None,
                entrypoint: str | None = None, aliases: list[str] | None = None,
                generator: bool = False) -> str:
        if self.should_stop():
            raise DockerError("RUN_STOP_REQUESTED")
        name = self.prefix + "-" + service
        flags = ["create", "--name", name, "--pull=never", "--label", LABEL + "=" + self.run_id,
                 "--label", "nexora.capacity.service=" + service,
                 "--network", self.network, "--network-alias", service,
                 "--restart", "no"]
        for alias in aliases or []:
            flags += ["--network-alias", alias]
        flags += ["--log-driver", "local", "--log-opt", "max-size=5m", "--log-opt", "max-file=2"]
        if generator:
            flags += ["--cpus", str(self.generator_cpus), "--memory", str(self.generator_memory),
                      "--pids-limit", "1024"]
        else:
            flags += inherited_limits(self.sources[source])
        clean_env = {"HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
                     "http_proxy": "", "https_proxy": "", "all_proxy": "",
                     "NO_PROXY": "*", "no_proxy": "*", "NEXORA_CAPACITY_RUN_ID": self.run_id}
        clean_env.update(env or {})
        for key, value in clean_env.items():
            if value and any(word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "CREDENTIAL", "ACCESS_KEY", "COMMUNITY")):
                self._redaction_values.add(str(value))
        process_env = dict(os.environ)
        for key, value in clean_env.items():
            process_env[key] = str(value)
            flags += ["--env", key]
        if entrypoint:
            flags += ["--entrypoint", entrypoint]
        flags += extra or []
        flags += [self.sources[source]["Image"], *(command or [])]
        container_id = docker(*flags, env=process_env)
        self.created[service] = container_id
        if self.on_container:
            self.on_container(container_id, metadata(self.inspect(container_id), service,
                                                     "generator" if generator else "lab"))
        return container_id

    def _start(self, container_id: str) -> None:
        docker("start", container_id)

    def _file_mount(self, path: Path, target: str) -> list[str]:
        return ["--mount", f"type=bind,src={path.resolve()},dst={target},readonly"]

    def _scripts_mount(self) -> list[str]:
        return self._file_mount(self.scripts, "/capacity")

    def _write_configs(self) -> None:
        # Explicit configuration for simulated devices; never copy real SNMP auths.
        self.snmp_config = self.files / "snmp.yml"
        self.snmp_config.write_text("""auths:
  capacity_v2:
    version: 2
    community: capacity_lab_only
modules:
  capacity_ifmib:
    walk: [1.3.6.1.2.1.2.2.1.1, 1.3.6.1.2.1.2.2.1.10, 1.3.6.1.2.1.2.2.1.16]
    metrics:
      - name: ifIndex
        oid: 1.3.6.1.2.1.2.2.1.1
        type: gauge
        help: Synthetic interface index.
        indexes: [{labelname: ifIndex, type: gauge}]
      - name: ifInOctets
        oid: 1.3.6.1.2.1.2.2.1.10
        type: counter
        help: Synthetic inbound octets.
        indexes: [{labelname: ifIndex, type: gauge}]
      - name: ifOutOctets
        oid: 1.3.6.1.2.1.2.2.1.16
        type: counter
        help: Synthetic outbound octets.
        indexes: [{labelname: ifIndex, type: gauge}]
    max_repetitions: 25
    retries: 1
    timeout: 2s
""", encoding="utf-8")
        targets = []
        for port in self.ports:
            targets.append(f"      - targets: ['snmp-simulator:{port}']\n        labels: {{capacity_device: '{port}'}}")
        self.scrape_config = self.files / "scrape.yml"
        self.scrape_config.write_text("""global:
  scrape_interval: 15s
  scrape_timeout: 10s
scrape_configs:
  - job_name: capacity_snmp
    metrics_path: /snmp
    params: {auth: [capacity_v2], module: [capacity_ifmib]}
    static_configs:
""" + "\n".join(targets) + """
    relabel_configs:
      - {source_labels: [__address__], target_label: __param_target}
      - {source_labels: [__param_target], target_label: instance}
      - {target_label: __address__, replacement: 'snmp-exporter:9116'}
  - job_name: capacity_cadvisor
    static_configs: [{targets: ['cadvisor:8080']}]
""", encoding="utf-8")
        self.datasource = self.files / "datasource.yml"
        self.datasource.write_text("""apiVersion: 1
datasources:
  - name: CapacityVictoriaMetrics
    uid: victoriametrics
    type: prometheus
    access: proxy
    url: http://victoriametrics:8428
    isDefault: true
    editable: false
    jsonData: {httpMethod: POST, timeInterval: 15s}
""", encoding="utf-8")

    def build(self, host: dict) -> None:
        self._write_configs()
        self.network = self.prefix + "-internal"
        docker("network", "create", "--internal", "--label", LABEL + "=" + self.run_id, self.network)
        creds = self.credentials
        if "db" in self.required:
            volume = self._volume("postgres")
            source_mount = next((m.get("Destination") for m in self.sources["db"].get("Mounts", [])
                                 if m.get("Destination", "").startswith("/var/lib/postgresql")), "/var/lib/postgresql")
            container = self._create("db", "db", {"POSTGRES_USER": creds["db_user"],
                "POSTGRES_PASSWORD": creds["db_password"], "POSTGRES_DB": creds["db_name"]},
                ["--mount", f"type=volume,src={volume},dst={source_mount}", "--shm-size", "256m"])
            self.diagnostic_services.add("db")
            self._start(container)
            self._wait_db()
        if "redis" in self.required:
            volume = self._volume("redis")
            container = self._create("redis", "redis", {"CAPACITY_REDIS_PASSWORD": creds["redis_password"]},
                ["--mount", f"type=volume,src={volume},dst=/data"], entrypoint="/bin/sh",
                command=["-ec", 'umask 077; printf "user default off\\nuser nexora on >%s ~nexora:* +ping +get +set +incr +del +eval +scan\\n" "$CAPACITY_REDIS_PASSWORD" > /data/users.acl; exec redis-server --aclfile /data/users.acl --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru'])
            self._start(container)
        if "victoriametrics" in self.required:
            volume = self._volume("vmdata")
            container = self._create("victoriametrics", "victoriametrics", extra=["--mount", f"type=volume,src={volume},dst=/storage"],
                command=["-storageDataPath=/storage", "-retentionPeriod=90d", "-httpListenAddr=:8428"])
            self._start(container)
        if "snmp-exporter" in self.required:
            simulator = self._create("snmp-simulator", "netops", generator=True,
                extra=self._scripts_mount(), entrypoint="python",
                command=["/capacity/snmp_simulator.py", "--interfaces", str(self.dataset["interfaces"]),
                         "--ports", ",".join(map(str, self.ports)), "--community", "capacity_lab_only"])
            self._start(simulator)
            container = self._create("snmp-exporter", "snmp-exporter", entrypoint="/bin/snmp_exporter",
                extra=self._file_mount(self.snmp_config, "/capacity-snmp.yml"),
                command=["--config.file=/capacity-snmp.yml", "--web.listen-address=:9116"])
            self._start(container)
        if "docker-socket-proxy" in self.required:
            container = self._create("docker-socket-proxy", "docker-socket-proxy",
                {"CONTAINERS": "1", "INFO": "1", "PING": "1", "VERSION": "1", "EVENTS": "1", "POST": "0"},
                ["--mount", f"type=bind,src={host['socket_path']},dst=/var/run/docker.sock,readonly"])
            self._start(container)
        if "cadvisor" in self.required:
            mounts = ["--mount", "type=bind,src=/sys,dst=/sys,readonly"]
            source_root = next((m["Source"] for m in self.sources["cadvisor"].get("Mounts", [])
                                if m.get("Destination") == "/var/lib/docker"), host["docker_root"])
            mounts += ["--mount", f"type=bind,src={source_root},dst=/var/lib/docker,readonly",
                       "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--read-only"]
            container = self._create("cadvisor", "cadvisor", extra=mounts,
                command=["--docker=tcp://docker-socket-proxy:2375", "--docker_only=true",
                         "--housekeeping_interval=30s", "--store_container_labels=false",
                         "--disable_metrics=percpu,sched,process,hugetlb,resctrl,tcp,udp,network"])
            self._start(container)
        if "vmagent" in self.required:
            queue = self._volume("vmagent-queue")
            container = self._create("vmagent", "vmagent", extra=self._file_mount(self.scrape_config, "/capacity-scrape.yml") +
                ["--mount", f"type=volume,src={queue},dst=/var/lib/vmagent"],
                command=["-promscrape.config=/capacity-scrape.yml", "-remoteWrite.url=http://victoriametrics:8428/api/v1/write",
                         "-remoteWrite.tmpDataPath=/var/lib/vmagent", "-remoteWrite.maxDiskUsagePerURL=1GB", "-httpListenAddr=:8429"])
            self._start(container)
        if "seaweedfs" in self.required:
            volume = self._volume("seaweedfs")
            container = self._create("seaweedfs", "seaweedfs", {"AWS_ACCESS_KEY_ID": creds["s3_access_key"],
                "AWS_SECRET_ACCESS_KEY": creds["s3_secret_key"], "S3_BUCKET": creds["s3_bucket"]},
                ["--mount", f"type=volume,src={volume},dst=/data"], command=["mini", "-dir=/data"])
            self._start(container)
        if "grafana" in self.required:
            volume = self._volume("grafana")
            container = self._create("grafana", "grafana", {"GF_SECURITY_ADMIN_USER": creds["grafana_user"],
                "GF_SECURITY_ADMIN_PASSWORD": creds["grafana_password"], "GF_AUTH_PROXY_ENABLED": "false",
                "GF_SERVER_ROOT_URL": "http://grafana:3000/", "GF_SERVER_SERVE_FROM_SUB_PATH": "false",
                "GF_ANALYTICS_REPORTING_ENABLED": "false", "GF_ANALYTICS_CHECK_FOR_UPDATES": "false"},
                self._file_mount(self.datasource, "/etc/grafana/provisioning/datasources/capacity.yml") +
                ["--mount", f"type=volume,src={volume},dst=/var/lib/grafana"], aliases=["grafana-auth"])
            self._start(container)
        if "netops" in self.required:
            self._build_netops()
        if "nginx" in self.required:
            self.nginx_config = self.files / "nginx.conf"
            docker("cp", "nexora-nginx:/etc/nginx/conf.d/default.conf", str(self.nginx_config))
            container = self._create("nginx", "nginx", {"TLS_COMMON_NAME": "nginx"},
                self._file_mount(self.nginx_config, "/etc/nginx/conf.d/default.conf") +
                ["--mount", f"type=volume,src={self.dist_volume},dst=/usr/share/nginx/html,readonly"])
            self._start(container)

    def _wait_db(self) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not self.should_stop():
            try:
                docker("exec", self.created["db"], "pg_isready", "-U", self.credentials["db_user"],
                       "-d", self.credentials["db_name"], timeout=5)
                return
            except DockerError:
                time.sleep(2)
        self.diagnostic_services.add("db")
        raise DockerError("TEST_POSTGRES_STARTUP_FAILED")

    def _build_netops(self) -> None:
        data, backup = self._volume("app-data"), self._volume("backup")
        self.dist_volume = self._volume("frontend")
        # Named volumes begin root-owned; initialize only these owned test volumes.
        init_script = "import os,shutil; shutil.copytree('/app/frontend-dist','/seed/dist',dirs_exist_ok=True); [os.chown(p,1000,1000) for p in ['/seed/data','/seed/backup']]; print('test volumes initialized')"
        helper = self._create("volume-init", "netops", entrypoint="python", generator=True,
            extra=["--user", "0", "--mount", f"type=volume,src={data},dst=/seed/data",
                   "--mount", f"type=volume,src={backup},dst=/seed/backup",
                   "--mount", f"type=volume,src={self.dist_volume},dst=/seed/dist"], command=["-c", init_script])
        self.diagnostic_services.add("volume-init")
        docker("start", "--attach", helper, timeout=90)
        exit_code = self.inspect(helper).get("State", {}).get("ExitCode")
        if exit_code != 0:
            raise DockerError("TEST_VOLUME_INIT_FAILED")
        self.diagnostic_services.discard("volume-init")
        creds = self.credentials
        # The application's database module uses POSTGRES_USER to recognize
        # its container profile; without it, @db is rewritten to @localhost.
        env = {"ENVIRONMENT": "production", "POSTGRES_USER": creds["db_user"],
               "DATABASE_URL": f"postgresql://{creds['db_user']}:{creds['db_password']}@db:5432/{creds['db_name']}",
               "SECRET_KEY": secrets.token_hex(32), "CREDENTIAL_ENCRYPTION_KEY": secrets.token_hex(32),
               "EXTERNAL_AI_ENABLED": "0", "AI_ENABLED": "0", "CONFIG_MANAGEMENT_URL": "",
               "REDIS_URL": f"redis://nexora:{creds['redis_password']}@redis:6379/0",
               "MONITORING_METRIC_BACKEND": "victoriametrics", "VICTORIAMETRICS_URL": "http://victoriametrics:8428",
               "VICTORIAMETRICS_ALLOWED_HOSTS": "victoriametrics", "WORKERS": "1", "STORAGE_BACKEND": "local"}
        original_env = dict(v.split("=", 1) for v in self.sources["netops"].get("Config", {}).get("Env", []) if "=" in v)
        for key in ("DB_POOL_SIZE", "DB_POOL_OVERFLOW_MAX", "DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "WORKERS", "TEMPLATES_CACHE_TTL_SECONDS"):
            if key in original_env:
                env[key] = original_env[key]
        container = self._create("netops", "netops", env,
            ["--init", "--mount", f"type=volume,src={data},dst=/app/data",
             "--mount", f"type=volume,src={backup},dst=/app/backup",
             "--mount", f"type=volume,src={self.dist_volume},dst=/app/dist"], entrypoint="python",
            command=["-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8003",
                     "--workers", env["WORKERS"], "--timeout-graceful-shutdown", "20"])
        self.diagnostic_services.add("netops")
        self._start(container)
        deadline = time.monotonic() + 300
        check = "import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8003/api/health/live',timeout=3).read()"
        while time.monotonic() < deadline and not self.should_stop():
            try:
                docker("exec", container, "python", "-c", check, timeout=6)
                return
            except DockerError:
                if self.inspect(container).get("State", {}).get("Status") == "exited":
                    break
                time.sleep(3)
        raise DockerError("TEST_NETOPS_STARTUP_FAILED")

    def _redact_diagnostic(self, text: str) -> str:
        for value in sorted(self._redaction_values, key=len, reverse=True):
            text = text.replace(value, "<redacted>")
        text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9_+/=.-]+", r"\1 <redacted>", text)
        text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@", r"\1<redacted>@", text)
        text = re.sub(
            r'''(?i)([\w.-]*(?:password|passwd|secret|token|authorization|community)[\w.-]*["']?\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;}\]]+)''',
            r"\1<redacted>", text)
        return text[-16000:]

    def failure_diagnostics(self) -> dict:
        """Capture failed services and runtime dependencies before deletion; never retain Config.Env."""
        if not self.created:
            return {}
        try:
            items = json.loads(docker("inspect", "--type", "container", *self.created.values(), timeout=10))
        except (DockerError, ValueError):
            return {"collection_error": "CONTAINER_DIAGNOSTIC_INSPECT_UNAVAILABLE"}
        by_id = {item.get("Id"): item for item in items if isinstance(item, dict)}
        result = {}
        for service, container_id in self.created.items():
            item = by_id.get(container_id, {})
            if (item.get("Config", {}).get("Labels") or {}).get(LABEL) != self.run_id:
                continue
            state = item.get("State") or {}
            ended = state.get("Status") in ("exited", "dead")
            runtime_dependency = service in {"netops", "db", "redis"}
            if (service not in self.diagnostic_services and not runtime_dependency
                    and not (ended and (state.get("ExitCode") or state.get("OOMKilled")))):
                continue
            sample = {"container_id": container_id, "status": state.get("Status"),
                      "exit_code": state.get("ExitCode"), "oom_killed": state.get("OOMKilled"),
                      "started_at": state.get("StartedAt"), "finished_at": state.get("FinishedAt"),
                      "engine_error": self._redact_diagnostic(str(state.get("Error") or ""))}
            try:
                logs = subprocess.run(["docker", "logs", "--tail", "100", container_id],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", timeout=10)
                if logs.returncode == 0:
                    sample["log_tail"] = self._redact_diagnostic(logs.stdout)
                else:
                    sample["log_error"] = "CONTAINER_LOGS_UNAVAILABLE"
            except (OSError, subprocess.TimeoutExpired):
                sample["log_error"] = "CONTAINER_LOGS_UNAVAILABLE"
            result[service] = sample
        return result

    def runner_config(self) -> dict:
        return {"run_id": self.run_id, "services": self.selected, "available_services": self.required, "dataset": self.dataset,
                "credentials": self.credentials,
                "targets": {"db": "db", "redis": "redis", "netops": "http://netops:8003",
                            "nginx": "https://nginx:443", "victoriametrics": "http://victoriametrics:8428",
                            "vmagent": "http://vmagent:8429", "snmp-exporter": "http://snmp-exporter:9116",
                            "grafana": "http://grafana:3000", "cadvisor": "http://cadvisor:8080",
                            "docker-socket-proxy": "http://docker-socket-proxy:2375", "seaweedfs": "http://seaweedfs:8333"},
                "insecure_tls": True, "timeout_seconds": 5, "query_window_seconds": 1800,
                "snmp_ports": self.ports, "snmp_auth": "capacity_v2", "snmp_module": "capacity_ifmib"}

    def create_runner(self, job: str) -> str:
        return self._create("runner-" + job, "netops", generator=True,
            extra=["--interactive", "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=64m"] + self._scripts_mount(),
            env={"PYTHONDONTWRITEBYTECODE": "1"}, entrypoint="python",
            command=["/capacity/runner.py", job.split("-", 1)[0]])

    def owns(self, kind: str, name: str) -> bool:
        try:
            args = ("inspect", "--type", "container", name) if kind == "container" else (kind, "inspect", name)
            info = json.loads(docker(*args))[0]
            labels = info.get("Config", {}).get("Labels", {}) if kind == "container" else info.get("Labels", {})
            return (labels or {}).get(LABEL) == self.run_id
        except (DockerError, ValueError, IndexError):
            return False

    def cleanup(self) -> dict:
        failures = []
        for service, container_id in reversed(list(self.created.items())):
            if not self.owns("container", container_id):
                failures.append("OWNERSHIP_NOT_CONFIRMED:" + service)
                continue
            try:
                docker("rm", "--force", "--volumes", container_id)
            except DockerError:
                failures.append("CONTAINER_CLEANUP_FAILED:" + service)
        for volume in reversed(self.volumes):
            if not self.owns("volume", volume):
                failures.append("VOLUME_OWNERSHIP_NOT_CONFIRMED:" + volume)
                continue
            try:
                docker("volume", "rm", volume)
            except DockerError:
                failures.append("VOLUME_CLEANUP_FAILED:" + volume)
        if self.network:
            if self.owns("network", self.network):
                try:
                    docker("network", "rm", self.network)
                except DockerError:
                    failures.append("NETWORK_CLEANUP_FAILED:" + self.network)
            else:
                failures.append("NETWORK_OWNERSHIP_NOT_CONFIRMED:" + self.network)
        return {"complete": not failures, "errors": failures, "resource_prefix": self.prefix}
