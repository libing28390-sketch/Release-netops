# Monitoring Center remediation status

## Scope

This walkthrough covers only the monitoring center / NOC remediation checklist in
`docs/monitoring-center-remediation-task-list.md`. Configuration search,
configuration templates, configuration diff, topology filtering, and other
unrelated modules are outside this change set.

## Completed in this pass

### Health model and metric drill-down

- Availability, collection integrity, health evaluation, alert counts, and data
  confidence remain separate dimensions.
- Missing telemetry is represented as unknown/unavailable rather than a false
  health score of zero.
- Online/offline, healthy/warning/critical/unknown, and collection anomaly
  metrics open the exact filtered device set in the monitoring center.
- The collection anomaly panel is independently filterable and shows the
  collector/device status that caused the anomaly.
- The monitoring center does not silently navigate to `/health` when a metric is
  selected.

### Events and response loop

- Connectivity alerts are deduplicated into monitoring incidents while the
  original alerts remain available in the incident timeline.
- Incident acknowledgement, investigation, assignment, and resolution append
  audit timeline events.
- Incident detail shows topology links and affected/neighbor devices.
- Root-cause inference is explicitly marked as evidence-based, with confidence,
  evidence, and a disclaimer rather than being presented as a confirmed cause.
- Business impact shows known site scope and explicitly reports missing CMDB
  service/business-owner mappings instead of inventing business facts.
- Quick collection diagnostics show each DNS, SSH/TCP, and SNMP check status.
- Health drill-down accepts site, role, alert-severity, and problem-keyword
  filters while preserving the canonical user-entered site name.
- Incident detail loads only platform-compatible read-only Playbook
  recommendations.  Configuration Playbooks are intentionally excluded and
  remain subject to the change-order approval workflow.
- Diagnostics, recommendation views, and incident-linked work-order creation
  append durable timeline events.

### Trends and platform self-monitoring

- Health trend supports 1 hour, 24 hour, and 7 day ranges.
- Trend data includes online rate, collection success rate, active/critical alert
  counts, new alerts, recovered alerts, and average recovery time.
- The platform health section exposes database/collector state, per-collector
  queue backlog, worker slots, active Playbook WebSocket sessions, Redis
  configuration state, collection delay, and host CPU/memory when the metrics
  are available. Unknown or unconfigured dependencies are not reported as
  healthy.
- Risk ranking gives core, aggregation, firewall, router, and load-balancer
  roles higher impact weight within the same health state.

### Incident to work-order handoff

- `change_orders.incident_id` is added through migration `m0063` and indexed.
- Creating a work order from an incident preserves the incident association,
  pre-fills the incident title/summary and affected devices, and allows the
  incident detail to list linked work orders.
- Migration and service behavior use the project database adapter and remain
  compatible with PostgreSQL deployments.

## Validation

```text
.venv\\Scripts\\python.exe -m pytest -q backend/tests/monitoring backend/tests/vendor_audit
# 285 passed

npm run lint
# passed (tsc --noEmit)

npm run build
# passed; Vite only reports the existing large-bundle warning

.venv\\Scripts\\python.exe -m compileall -q <monitoring backend files>
git diff --check
# passed; only line-ending normalization warnings were reported
```

The complete `backend/tests` suite was also attempted with a five-minute
timeout. It did not emit a test failure before the timeout; the monitoring and
vendor-audit suites above are the completed acceptance scope for this pass.

## Explicitly deferred P2 work

The following items require additional product/data contracts and are not
claimed as complete:

- automated topology root-cause inference beyond evidence presentation;
- authoritative service, business-unit, owner, and SLA relationships in CMDB;
- asynchronous Playbook execution directly from the incident drawer with
  approval/risk gates.  The current release is recommendation-only and routes
  configuration changes through the existing automation/change-order flow;
- full Redis latency/auth probes, worker heartbeat age, and host disk/network
  metrics; the current UI reports the runtime facts that are available and
  labels unconfigured/unverified dependencies explicitly.

These items should be implemented only after the corresponding CMDB ownership
model and Playbook execution contract are confirmed, so the NOC does not expose
unsafe or fabricated remediation actions.
