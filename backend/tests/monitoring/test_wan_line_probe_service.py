from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from services import outbound_probe_service
from services import wan_line_probe_service as line_probe


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _seed_line_probe_rows(*, links: tuple[str, ...] = ("link-a", "link-b")) -> None:
    from database import get_db_connection

    now = (datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=3)).isoformat()
    conn = get_db_connection()
    try:
        for index, link_id in enumerate(links, start=1):
            conn.execute(
                """
                INSERT INTO wan_links (
                    id, link_name, site_id, site_name, device_id, interface_id,
                    interface_name, if_index, contracted_download_bps,
                    contracted_upload_bps, created_at, updated_at, tenant_id,
                    configuration_version, enabled
                ) VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, TRUE)
                """,
                (link_id, f"Line {index}", f"device-{index}", f"interface-{index}", f"Gi0/{index}", index, 100_000_000, 100_000_000, now, now, "tenant-probe"),
            )
        conn.execute(
            """
            INSERT INTO outbound_probe_targets (
                id, target_name, host, port, probe_type, is_active, enabled,
                created_at, updated_at, group_name, tenant_id
            ) VALUES (?, ?, ?, ?, ?, TRUE, TRUE, ?, ?, ?, ?)
            """,
            ("shared-target", "Shared target", "203.0.113.10", 443, "ICMP_PING", now, now, "business", "tenant-probe"),
        )
        for index, link_id in enumerate(links, start=1):
            conn.execute(
                """
                INSERT INTO wan_probe_bindings (
                    id, link_id, target_id, route_mode, source_ip, priority,
                    enabled, created_by, created_at, updated_at,
                    route_evidence_json, updated_by
                ) VALUES (?, ?, ?, 'default', '', ?, TRUE, 'test', ?, ?, ?::jsonb, 'test')
                """,
                (f"binding-{index}", link_id, "shared-target", index, now, now, json.dumps({"evidence_status": "insufficient_default_route"})),
            )
            conn.execute(
                """
                INSERT INTO wan_link_sla_policies (
                    link_id, tenant_id, policy_version, policy_json,
                    updated_by, updated_at
                ) VALUES (?, ?, 1, ?::jsonb, 'test', ?)
                """,
                (link_id, "tenant-probe", json.dumps({"availability_target_pct": 99.9, "minimum_coverage_pct": 0, "availability_rule": "any_success"}), now),
            )
        conn.commit()
    finally:
        conn.close()


def test_icmp_quality_keeps_measured_packet_counts(monkeypatch):
    output = "5 packets transmitted, 3 received, 40% packet loss\nrtt min/avg/max/mdev = 1/2/3/0.5 ms"
    assert outbound_probe_service._parse_icmp_counts(output) == (5, 3)
    average, loss, jitter = outbound_probe_service._parse_icmp_quality(output)
    assert average == 2
    assert loss == 40
    assert jitter is None


def test_path_evidence_never_promotes_source_ip_configuration():
    result = line_probe._path_evidence(
        {
            "link_id": "link-a",
            "target_id": "target-a",
            "configuration_version": 1,
            "route_evidence_json": json.dumps({"evidence_status": "source_ip_configured_unverified"}),
        },
        context_version="ctxv-a",
        executor_id="executor-a",
    )
    assert result["status"] == "unverified"
    assert result["reason_code"] == "source_ip_only"


def test_verified_path_requires_every_active_identity_field():
    now = datetime.now(timezone.utc)
    identity = {
        "link_id": "link-a",
        "target_id": "target-a",
        "executor_id": "executor-a",
        "configuration_version": 1,
        "context_version": "ctxv-a",
    }
    for missing in identity:
        evidence = {
            "status": "verified",
            "verified_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "evidence_ref": "route-proof-1",
            **identity,
        }
        evidence.pop(missing)
        result = line_probe._path_evidence(
            {
                "link_id": "link-a",
                "target_id": "target-a",
                "configuration_version": 1,
                "route_evidence_json": json.dumps(evidence),
            },
            context_version="ctxv-a",
            executor_id="executor-a",
            now=now,
        )
        assert result["status"] == "invalid"
        assert result["reason_code"] == f"path_evidence_{missing}_missing"


def test_source_ip_evidence_and_probe_result_must_match_for_sla():
    now = datetime.now(timezone.utc)
    identity = {
        "link_id": "link-a",
        "target_id": "target-a",
        "executor_id": "executor-a",
        "configuration_version": 1,
        "context_version": "ctxv-a",
    }
    evidence = {
        "status": "verified",
        "verified_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "evidence_ref": "route-proof-1",
        "source_ip": "192.0.2.20",
        **identity,
    }
    binding = {
        "route_evidence_json": json.dumps(evidence),
        "link_id": "link-a",
        "target_id": "target-a",
        "configuration_version": 1,
        "route_mode": "source_ip",
        "source_ip": "192.0.2.20",
    }
    result = line_probe._path_evidence(
        binding,
        context_version="ctxv-a",
        executor_id="executor-a",
        route_mode="source_ip",
        source_ip="192.0.2.20",
        now=now,
    )
    assert result["status"] == "verified"

    mismatched = dict(evidence, source_ip="192.0.2.21")
    binding["route_evidence_json"] = json.dumps(mismatched)
    result = line_probe._path_evidence(
        binding,
        context_version="ctxv-a",
        executor_id="executor-a",
        route_mode="source_ip",
        source_ip="192.0.2.20",
        now=now,
    )
    assert result["status"] == "invalid"
    assert result["reason_code"] == "path_evidence_source_ip_mismatch"

    missing_source = dict(evidence)
    missing_source.pop("source_ip")
    binding["route_evidence_json"] = json.dumps(missing_source)
    result = line_probe._path_evidence(
        binding,
        context_version="ctxv-a",
        executor_id="executor-a",
        route_mode="source_ip",
        source_ip="192.0.2.20",
        now=now,
    )
    assert result["status"] == "invalid"
    assert result["reason_code"] == "path_evidence_source_ip_missing"

    context = {
        "tenant_mismatch": False,
        "path_status": "verified",
        "path_reason": "path_verified",
        "context_id": "ctx-a",
        "context_version": "ctxv-a",
        "tenant_id": "tenant-a",
        "link_id": "link-a",
        "target_id": "target-a",
        "configuration_version": 1,
        "policy_version": 1,
        "executor_id": "executor-a",
        "target": {"id": "target-a", "probe_type": "ICMP_PING"},
        "target_name": "target-a",
        "target_host": "198.51.100.10",
        "protocol": "ICMP_PING",
        "route_mode": "source_ip",
        "source_ip": "192.0.2.20",
        "evidence_version": "ev-a",
        "path_evidence": evidence,
    }
    bad_execution = line_probe._execute_context(
        context,
        probe_runner=lambda target, source_ip=None: {
            "success": True,
            "source_ip_used": "192.0.2.21",
            "sent_count": 1,
            "received_count": 1,
        },
    )
    assert bad_execution["execution_status"] == "unsupported"
    bad_sample = line_probe._sample_record(context, bad_execution, now)
    assert bad_sample["path_status"] == "invalid"
    assert bad_sample["sla_eligible"] is False

    good_execution = line_probe._execute_context(
        context,
        probe_runner=lambda target, source_ip=None: {
            "success": True,
            "source_ip_used": "192.0.2.20",
            "sent_count": 1,
            "received_count": 1,
        },
    )
    good_sample = line_probe._sample_record(context, good_execution, now)
    assert good_execution["execution_status"] == "completed"
    assert good_sample["path_status"] == "verified"
    assert good_sample["sla_eligible"] is True


def test_default_route_mode_ignores_conflicting_source_ip():
    calls: list[dict] = []

    def fake_probe(target):
        calls.append(target)
        return {"success": True, "sent_count": 1, "received_count": 1}

    context = {
        "tenant_mismatch": False,
        "path_status": "unverified",
        "path_reason": "source_ip_only",
        "target": {"id": "target-a", "host": "192.0.2.10", "probe_type": "ICMP_PING"},
        "route_mode": "default",
        "source_ip": "192.0.2.20",
    }
    execution = line_probe._execute_context(context, probe_runner=fake_probe)
    assert execution["execution_status"] == "completed"
    assert calls == [context["target"]]


def test_unsupported_probe_path_cannot_be_sla_eligible():
    context = {
        "tenant_mismatch": False,
        "path_status": "verified",
        "path_reason": "path_verified",
        "target": {"id": "target-a", "host": "example.test", "probe_type": "DNS_RESOLVE"},
        "route_mode": "source_ip",
        "source_ip": "192.0.2.20",
    }
    execution = line_probe._execute_context(
        context,
        probe_runner=lambda target, source_ip=None: {
            "unsupported": True,
            "error_type": "SOURCE_BIND_UNSUPPORTED",
            "error_message": "cannot bind DNS resolver",
        },
    )
    assert execution["execution_status"] == "unsupported"
    assert execution["success"] is None


def test_non_availability_samples_are_retained_but_cannot_enter_availability_sla():
    now = datetime.now(timezone.utc)
    context = {
        "purpose": "application",
        "tenant_mismatch": False,
        "path_status": "verified",
        "path_reason": "path_verified",
        "context_id": "ctx-application",
        "context_version": "ctxv-application",
        "tenant_id": "tenant-a",
        "link_id": "link-a",
        "target_id": "target-a",
        "configuration_version": 1,
        "policy_version": 1,
        "executor_id": "executor-a",
        "target": {"id": "target-a", "probe_type": "HTTP_GET"},
        "target_name": "target-a",
        "target_host": "example.test",
        "route_mode": "default",
        "source_ip": "",
        "evidence_version": "ev-a",
        "path_evidence": {"evidence_ref": "route-proof"},
    }
    execution = line_probe._execute_context(
        context,
        probe_runner=lambda target: {"success": True, "sent_count": 1, "received_count": 1},
    )
    sample = line_probe._sample_record(context, execution, now)
    assert sample["purpose"] == "application"
    assert sample["sla_eligible"] is False

    availability_context = {**context, "purpose": "availability", "context_id": "ctx-availability"}
    availability_sample = {**sample, "purpose": "availability", "context_id": "ctx-availability"}
    slot = line_probe._slot_for_contexts(
        [availability_context, context],
        [availability_sample, sample],
        slot_start=now,
    )
    assert slot["sample_count"] == 1
    assert slot["status"] == "up"


def test_expired_verified_path_is_invalid():
    now = datetime.now(timezone.utc)
    result = line_probe._path_evidence(
        {
            "link_id": "link-a",
            "target_id": "target-a",
            "configuration_version": 1,
            "route_evidence_json": json.dumps(
                {
                    "status": "verified",
                    "verified_at": (now - timedelta(hours=25)).isoformat(),
                    "expires_at": (now - timedelta(hours=1)).isoformat(),
                    "evidence_ref": "route-proof-1",
                }
            ),
        },
        context_version="ctxv-a",
        executor_id="executor-a",
        now=now,
    )
    assert result["status"] == "invalid"
    assert result["reason_code"] == "path_evidence_expired"


def test_unknown_slot_can_still_prove_availability_breach():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    activation = now - timedelta(minutes=3)

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT id, tenant_id, configuration_version, created_at, site_id, device_id FROM wan_links"):
                return Result([{
                    "id": "link-a",
                    "tenant_id": "tenant-a",
                    "configuration_version": 1,
                    "created_at": activation.isoformat(),
                    "site_id": "site-a",
                    "device_id": "device-a",
                }])
            if normalized.startswith("SELECT policy_version, policy_json, updated_at FROM wan_link_sla_policies"):
                return Result([{
                    "policy_version": 1,
                    "policy_json": {"availability_target_pct": 99.9, "minimum_coverage_pct": 0},
                    "updated_at": activation.isoformat(),
                }])
            if "FROM wan_link_sla_policy_history" in normalized:
                return Result([])
            if "FROM wan_line_quality_slots" in normalized:
                return Result([
                    {
                        "slot_start": activation.isoformat(),
                        "slot_end": (activation + timedelta(minutes=1)).isoformat(),
                        "status": "down",
                        "updated_at": activation.isoformat(),
                        "configuration_version": 1,
                        "policy_version": 1,
                        "evidence_refs": [],
                    },
                    {
                        "slot_start": (activation + timedelta(minutes=1)).isoformat(),
                        "slot_end": (activation + timedelta(minutes=2)).isoformat(),
                        "status": "unknown",
                        "updated_at": (activation + timedelta(minutes=1)).isoformat(),
                        "configuration_version": 1,
                        "policy_version": 1,
                        "evidence_refs": [],
                    },
                ])
            if normalized.startswith("SELECT scheduled_at FROM wan_line_probe_samples"):
                return Result([])
            raise AssertionError(normalized)

    result = line_probe._calculate_sla(
        FakeConnection(),
        "link-a",
        tenant_id="tenant-a",
        window="24h",
        now=now,
    )
    assert result["upper"] == round(2 / 3 * 100, 6)
    assert result["slot_stats"]["unknown"] == 2
    assert result["status"] == "breached"
    assert result["reason_code"] == "availability_upper_below_target"


def test_maintenance_exclusion_removes_only_matching_eligible_seconds():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    activation = now - timedelta(minutes=3)

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT id, tenant_id, configuration_version, created_at, site_id, device_id FROM wan_links"):
                return Result([{"id": "link-a", "tenant_id": "tenant-a", "configuration_version": 1, "created_at": activation, "site_id": "site-a", "device_id": "device-a"}])
            if normalized.startswith("SELECT policy_version, policy_json, updated_at FROM wan_link_sla_policies"):
                return Result([{"policy_version": 1, "policy_json": {"availability_target_pct": 99.9, "minimum_coverage_pct": 99, "maintenance_excluded": True}, "updated_at": activation}])
            if "FROM wan_link_sla_policy_history" in normalized:
                return Result([(activation,)])
            if normalized.startswith("SELECT group_id FROM wan_link_group_members"):
                return Result([])
            if normalized.startswith("SELECT * FROM wan_maintenance_windows"):
                return Result([{
                    "link_id": "link-a", "site_id": "", "device_id": "", "link_group_id": "",
                    "starts_at": activation + timedelta(minutes=1),
                    "ends_at": activation + timedelta(minutes=2), "recurrence": "once", "timezone": "UTC",
                }])
            if "FROM wan_line_quality_slots" in normalized:
                return Result([
                    {"slot_start": activation, "slot_end": activation + timedelta(minutes=1), "status": "up", "updated_at": activation, "configuration_version": 1, "policy_version": 1, "evidence_refs": []},
                    {"slot_start": activation + timedelta(minutes=2), "slot_end": activation + timedelta(minutes=3), "status": "up", "updated_at": activation + timedelta(minutes=2), "configuration_version": 1, "policy_version": 1, "evidence_refs": []},
                ])
            if normalized.startswith("SELECT scheduled_at FROM wan_line_probe_samples"):
                return Result([])
            raise AssertionError(normalized)

    result = line_probe._calculate_sla(FakeConnection(), "link-a", tenant_id="tenant-a", window="24h", now=now)
    assert result["status"] == "met"
    assert result["observed"] == 100.0
    assert result["coverage"] == 100.0
    assert result["slots"] == 2
    assert result["slot_stats"]["unknown"] == 0
    assert result["slot_stats"]["maintenance_excluded_seconds"] == 60
    assert result["slot_stats"]["fully_excluded_slots"] == 1


def test_recurring_maintenance_expands_in_its_configured_timezone():
    start = datetime(2026, 10, 24, 20, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=27)

    class Result:
        def __init__(self, rows=None):
            self.rows = rows or []

        def fetchall(self):
            return self.rows

    window = {
        "link_id": "", "site_id": "site-a", "device_id": "", "link_group_id": "",
        "starts_at": "2026-10-24T23:00:00+02:00", "ends_at": "2026-10-25T00:00:00+02:00",
        "recurrence": "daily", "timezone": "Europe/Paris",
    }

    class FakeConnection:
        def execute(self, sql, params=()):
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT group_id FROM wan_link_group_members"):
                return Result()
            return Rows([window])

    class Rows(Result):
        def fetchall(self):
            return [window]

    intervals = line_probe._maintenance_intervals(
        FakeConnection(), {"id": "link-a", "site_id": "site-a", "device_id": "device-a"}, start=start, end=end,
    )
    assert len(intervals) == 2
    assert all((right - left) == timedelta(hours=1) for left, right in intervals)
    assert intervals[0][0] == datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)
    assert intervals[1][0] == datetime(2026, 10, 25, 22, 0, tzinfo=timezone.utc)


def test_same_target_bound_to_two_links_has_isolated_contexts_and_unknown_sla(isolated_db, monkeypatch):
    _seed_line_probe_rows()
    calls: list[str] = []

    def fake_probe(target):
        calls.append(str(target["id"]))
        return {"success": True, "latency_ms": 4.0, "sent_count": 5, "received_count": 5}

    scheduled_at = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1)
    result = line_probe.run_wan_line_probe_once(scheduled_at=scheduled_at, probe_runner=fake_probe)
    assert result["status"] == "completed"
    assert calls == ["shared-target", "shared-target"]

    from database import get_db_connection

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT link_id, target_id, context_id, success, sent_count, received_count FROM wan_line_probe_samples ORDER BY link_id"
        ).fetchall()
        assert len(rows) == 2
        assert {row[0] for row in rows} == {"link-a", "link-b"}
        assert len({row[2] for row in rows}) == 2
        assert all(row[3] is True and row[4] == 5 and row[5] == 5 for row in rows)
        slots = conn.execute("SELECT link_id, status, reason_code FROM wan_line_quality_slots ORDER BY link_id").fetchall()
        assert [(row[0], row[1]) for row in slots] == [("link-a", "unknown"), ("link-b", "unknown")]
        assert all(row[2] == "path_evidence_unavailable" for row in slots)
    finally:
        conn.close()

    for link_id in ("link-a", "link-b"):
        sla = line_probe.get_wan_line_sla(link_id, tenant_id="tenant-probe", window="24h")
        assert sla is not None
        assert sla["status"] == "insufficient_data"
        assert sla["observed"] is None
        assert sla["coverage"] == 0.0
        assert sla["slot_stats"]["unknown"] == sla["slots"]
        assert sla["slot_stats"]["missing_slots"] >= 1


def test_slot_bounds_are_reported_from_up_down_unknown_slots(isolated_db):
    from database import get_db_connection

    _seed_line_probe_rows(links=("link-a",))
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=3)
    conn = get_db_connection()
    try:
        for index, status in enumerate(("up", "down", "unknown")):
            start = now + timedelta(minutes=index)
            conn.execute(
                """
                INSERT INTO wan_line_quality_slots (
                    id, tenant_id, link_id, slot_start, slot_end,
                    configuration_version, policy_version, context_ids,
                    context_versions, status, reason_code, reason,
                    evidence_refs, sample_count, eligible_sample_count,
                    sent_count, received_count, coverage_percent,
                    algorithm_version
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?::jsonb, ?::jsonb, ?, '', '',
                          ?::jsonb, 1, 1, 5, 5, ?, ?)
                """,
                (f"slot-{index}", "tenant-probe", "link-a", start.isoformat(), (start + timedelta(minutes=1)).isoformat(),
                 json.dumps([f"ctx-{index}"]), json.dumps([f"version-{index}"]), status, json.dumps([]), 100.0, line_probe.SLA_ALGORITHM_VERSION),
            )
        conn.commit()
    finally:
        conn.close()

    sla = line_probe.get_wan_line_sla("link-a", tenant_id="tenant-probe", window="24h", persist_snapshot=False)
    assert sla is not None
    assert sla["observed"] == 50.0
    assert sla["lower"] == round(1 / 3 * 100, 6)
    assert sla["upper"] == round(2 / 3 * 100, 6)
    assert sla["coverage"] == round(2 / 3 * 100, 6)
    assert sla["status"] == "breached"
