---
name: netops-monitoring-telemetry
description: Implement and review network telemetry, SNMP metric collection, background monitors, outbound health probes, alert evaluation rules, maintenance windows, and multi-channel notification dispatchers. Use for changes under backend/services/*monitor*, backend/services/snmp*, backend/services/alert*, backend/services/outbound_probe*, backend/api/monitoring.py, or backend/api/alerts.py.
---

# NetOps Monitoring, Telemetry & Alerting

## Workflow

1. Trace metric lifecycle: Collector / Probe execution -> Counter delta calculation -> Threshold evaluation (`alert_rule_service.py`) -> Incident state machine (`monitoring_incident_service.py`) -> Maintenance/Flapping suppression -> Notification dispatch (`notification_service.py`).
2. Keep collector loops (`background_monitor_service.py`) decoupled from HTTP request handling. Run background collection through designated async tasks or scheduler workers.
3. Handle 32-bit and 64-bit SNMP counter overflows safely during bandwidth rate calculations.
4. Enforce strict SSRF protection on all outbound probes and webhook dispatchers using `safe_outbound_http.py`.
5. Ensure alert lifecycle transitions (Triggered -> Acknowledged -> Suppressed -> Resolved) are audited and idempotent.

## Mandatory Conventions & Telemetry Rules

- **SNMP Metric Calculation & Counter Wrap**:
  - Prefer 64-bit high-capacity counters (`ifHCInOctets`, `ifHCOutOctets`, `ifHCInUcastPkts`) over 32-bit counters whenever supported by the device.
  - When calculating rate (`bps` / `pps`), compute `(current_counter - previous_counter) / delta_seconds`. Detect counter resets or rollovers: if `current < previous`, handle max-value wrap-around or discard the anomalous sample.
  - Resolve SNMP credentials strictly via `resolve_collector_credentials` using Community-based SNMPv2c or SNMPv3 user profiles. Never hardcode communities or credentials in metric templates.
- **Outbound Probes & Network Security**:
  - Outbound HTTP/TCP/ICMP probes must strictly route through `safe_outbound_http.py` or restricted socket wrappers to prevent SSRF vulnerabilities (e.g., prohibiting requests to cloud metadata `169.254.169.254` or internal forbidden ports unless authorized).
  - Outbound probe concurrency must be bounded to avoid exhausting socket descriptors or flooding target networks.
- **Alert Evaluation & Suppression**:
  - Implement flapping protection (debounce threshold): require N consecutive anomalous samples before triggering a critical incident.
  - Check active maintenance windows (`alert_maintenance_service.py`) before firing notifications. Suppressed alerts must still be logged for auditability but silenced on notification channels.
  - Dispatch notifications asynchronously across supported channels (DingTalk, Feishu, WeChat Work, Email, Webhooks) with exponential backoff on delivery failures.

## Boundaries

- SNMP protocol communication belongs in `backend/services/snmp_service.py` and MIB repositories.
- Background worker execution and probe loops belong in `backend/services/background_monitor_service.py` and `outbound_probe_service.py`.
- Alert rule definition, evaluation, and incident state tracking belong in `backend/services/alert_*.py`.
- REST endpoints for metrics, probe targets, and alert management belong in `backend/api/monitoring.py` and `backend/api/alerts.py`.
- Frontend alert desks and rule configuration belong in `src/pages/AlertDeskTab.tsx` and `src/pages/AlertRulesTab.tsx`.

## Safety and Verification

- Run focused tests: `pytest backend/tests/ -k "monitor or snmp or alert or probe"`.
- Verify counter wrap-around logic with unit test fixtures simulating 32-bit and 64-bit integer overflows.
- Test notification payload formatting and error handling when webhook endpoints return 5xx errors or timeouts.
