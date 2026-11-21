from types import SimpleNamespace

from services import outbound_probe_service


def test_parse_icmp_quality_extracts_linux_echo_rtt_loss_and_variation():
    output = """
64 bytes from 203.0.113.8: icmp_seq=1 ttl=54 time=10.100 ms
64 bytes from 203.0.113.8: icmp_seq=2 ttl=54 time=12.100 ms
64 bytes from 203.0.113.8: icmp_seq=3 ttl=54 time=13.100 ms
5 packets transmitted, 3 received, 40% packet loss, time 401ms
rtt min/avg/max/mdev = 10.100/11.767/13.100/1.238 ms
"""

    average, packet_loss, jitter = outbound_probe_service._parse_icmp_quality(output)

    assert round(average, 3) == 11.767
    assert packet_loss == 40
    assert jitter == 1.5


def test_icmp_probe_sends_bounded_multi_echo_and_persists_quality_values(monkeypatch):
    captured = {}

    monkeypatch.setattr(outbound_probe_service, "_resolve_and_validate", lambda host, port: ["203.0.113.8"])
    monkeypatch.setattr("platform.system", lambda: "Linux")

    def run_command(command, timeout):
        captured["command"] = command
        captured["timeout"] = timeout
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "64 bytes from 203.0.113.8: time=5.000 ms\n"
                "64 bytes from 203.0.113.8: time=7.000 ms\n"
                "5 packets transmitted, 2 received, 60% packet loss\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("core.subprocess_utils.run_console_command", run_command)

    result = outbound_probe_service._probe_icmp({
        "id": "probe-target",
        "target_name": "example probe",
        "host": "example.com",
        "timeout_ms": 2000,
        "probe_type": "ICMP_PING",
    })

    assert result["success"] is True
    assert result["latency_ms"] == 6.0
    assert result["packet_loss_percent"] == 60
    assert result["rtt_jitter_ms"] == 2.0
    assert captured["command"][captured["command"].index("-c") + 1] == "5"
    assert captured["timeout"] == 3.0
