"""Read Docker-local capacity facts; no device traffic or configuration changes.

Run on the deployment host: python3 telemetry_runtime_readonly_20261117.py
Requires Docker access and the existing nexora-* containers. Prints no metric
labels, environment values, credentials or complete container inspection.
One /hardware-metrics request reads existing DB inventory; it does not poll devices.
"""
import json
import subprocess


def run(args, timeout=45):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode:
            return {"ok": False, "exit_code": proc.returncode}
        try:
            return {"ok": True, "data": json.loads(proc.stdout)}
        except ValueError:
            return {"ok": False, "reason": "unexpected_output"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": type(exc).__name__}


hardware_code = r'''
import json, time, urllib.request
started = time.monotonic()
size = samples = 0
carry = b""
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open("http://127.0.0.1:8003/hardware-metrics", timeout=30) as response:
        encoding = response.headers.get("Content-Encoding", "identity")
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > 256*1024*1024:
                raise RuntimeError("response_exceeds_measurement_cap_256MiB")
            parts = (carry+chunk).split(b"\n")
            carry = parts.pop()
            samples += sum(bool(line.strip()) and not line.lstrip().startswith(b"#") for line in parts)
        if carry.strip() and not carry.lstrip().startswith(b"#"):
            samples += 1
    print(json.dumps({"ok": True, "body_bytes": size, "mib": round(size/1048576, 3),
        "sample_lines": samples, "content_encoding": encoding,
        "elapsed_seconds": round(time.monotonic()-started, 3),
        "at_or_above_64MiB": size >= 67108864, "above_32MiB_budget": size > 33554432}))
except Exception as exc:
    print(json.dumps({"ok": False, "reason": type(exc).__name__, "bytes_read": size}))
'''


def main():
    containers = ("nexora-netops", "nexora-vmagent", "nexora-victoriametrics")
    report = {"scope": "docker-local read-only; no device access", "containers": {}}
    template = ('{"memory_bytes":{{.HostConfig.Memory}},"nano_cpus":{{.HostConfig.NanoCpus}},'
                '"oom_killed":{{.State.OOMKilled}},"restart_count":{{.RestartCount}}}')
    for container in containers:
        report["containers"][container] = run(["docker", "inspect", "--format", template, container])
    report["hardware_response"] = run(["docker", "exec", "nexora-netops", "python", "-c", hardware_code])
    # Only allowlisted non-secret process flags are returned.
    inspected = run(["docker", "inspect", "--format", "{{json .Config.Cmd}}", "nexora-vmagent"])
    if inspected.get("ok"):
        prefixes = ("-promscrape.maxScrapeSize=", "-remoteWrite.maxDiskUsagePerURL=",
                    "-remoteWrite.maxBlockSize=", "-maxInsertRequestSize=", "-maxLabelsPerTimeseries=")
        report["vmagent_size_flags"] = [value for value in inspected["data"] or []
                                         if isinstance(value, str) and value.startswith(prefixes)]
    else:
        report["vmagent_size_flags"] = inspected
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
