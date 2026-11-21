from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.alert_control_service import (
    AlertState,
    calculate_impact,
    check_no_data,
    compute_health,
    detect_flapping,
    detect_storm,
    suppress_dependency_alerts,
    transition_state,
)


def test_for_duration_and_recovery_hysteresis():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state = AlertState()
    assert transition_state(state, breached=True, now=start, for_seconds=60).state == "PENDING"
    assert transition_state(state, breached=True, now=start + timedelta(seconds=61), for_seconds=60).emit
    assert transition_state(state, breached=False, now=start + timedelta(seconds=62), recovery_threshold=2).state == "RECOVERING"
    assert transition_state(state, breached=False, now=start + timedelta(seconds=63), recovery_threshold=2).emit


def test_health_no_data_and_flapping():
    assert compute_health(icmp=True, snmp=False, ssh=True)["state"] == "DEGRADED"
    assert compute_health(icmp=None, snmp=None, ssh=None)["state"] == "UNKNOWN"
    now = datetime.now(timezone.utc)
    assert check_no_data(now - timedelta(seconds=301), now=now, threshold_seconds=300)
    assert detect_flapping([now - timedelta(seconds=i) for i in (10, 20, 30, 40)], now=now, threshold=4)


def test_dependency_suppression_preserves_underlying_alerts_and_impact_is_graph_based():
    alerts = [
        {"id": "root", "device_id": "core", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "child", "device_id": "access", "created_at": "2026-01-01T00:01:00Z"},
    ]
    result = suppress_dependency_alerts(alerts, [{"source_node_id": "core", "target_node_id": "access", "relation_type": "PHYSICAL"}])
    assert len(result) == 2
    assert result[1]["is_suppressed"] is True
    impact = calculate_impact(alerts[0], graph_nodes=[{"id": "access", "function": "service"}], graph_edges=[{"source_node_id": "core", "target_node_id": "access"}])
    assert "access" in impact["impacted_node_ids"]
    assert detect_storm(alerts, count_threshold=2)["is_storm"] is True

