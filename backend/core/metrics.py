import time
from collections import deque
from threading import Lock

class MetricsRegistry:
    def __init__(self):
        self._lock = Lock()
        self.api_latencies = deque(maxlen=1000)
        
        # Background monitor telemetry
        self.device_polling_durations = deque(maxlen=100)
        self.snmp_successes = 0
        self.snmp_failures = 0
        
        # SSH/Telnet orchestrator execution
        self.ssh_successes = 0
        self.ssh_failures = 0
        self.ssh_durations = deque(maxlen=100)

        # IPAM allocation conflicts
        self.ipam_allocation_conflicts = 0

    def record_api_latency(self, latency_ms: float):
        with self._lock:
            self.api_latencies.append(latency_ms)

    def record_polling(self, duration_s: float, success: bool):
        with self._lock:
            self.device_polling_durations.append(duration_s)
            if success:
                self.snmp_successes += 1
            else:
                self.snmp_failures += 1

    def record_ssh(self, duration_s: float, success: bool):
        with self._lock:
            self.ssh_durations.append(duration_s)
            if success:
                self.ssh_successes += 1
            else:
                self.ssh_failures += 1

    def record_ipam_conflict(self):
        with self._lock:
            self.ipam_allocation_conflicts += 1

    def get_metrics(self) -> dict:
        with self._lock:
            api_list = list(self.api_latencies)
            avg_api = sum(api_list) / len(api_list) if api_list else 0.0
            
            poll_list = list(self.device_polling_durations)
            avg_poll = sum(poll_list) / len(poll_list) if poll_list else 0.0
            
            ssh_list = list(self.ssh_durations)
            avg_ssh = sum(ssh_list) / len(ssh_list) if ssh_list else 0.0
            
            total_snmp = self.snmp_successes + self.snmp_failures
            snmp_failure_rate = (self.snmp_failures / total_snmp * 100) if total_snmp > 0 else 0.0
            
            total_ssh = self.ssh_successes + self.ssh_failures
            ssh_failure_rate = (self.ssh_failures / total_ssh * 100) if total_ssh > 0 else 0.0

            return {
                "api_latency_avg_ms": round(avg_api, 2),
                "api_latency_count": len(api_list),
                "device_polling_duration_avg_s": round(avg_poll, 2),
                "snmp_success_count": self.snmp_successes,
                "snmp_failure_count": self.snmp_failures,
                "snmp_failure_rate_pct": round(snmp_failure_rate, 2),
                "ssh_success_count": self.ssh_successes,
                "ssh_failure_count": self.ssh_failures,
                "ssh_failure_rate_pct": round(ssh_failure_rate, 2),
                "ssh_duration_avg_s": round(avg_ssh, 2),
                "ipam_allocation_conflict_count": self.ipam_allocation_conflicts,
            }

metrics_registry = MetricsRegistry()
