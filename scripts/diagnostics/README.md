# Nexora PostgreSQL / live latency diagnostics

`collect_nexora_pg_latency.sh` measures the lightweight backend endpoint, Nginx proxy and component health while sampling PostgreSQL activity every second. It also records table and transaction counter snapshots, enabled Monitoring V1 assignment intervals, aggregate device-loop counts, backend cgroup data and Docker CPU/memory/PID statistics. Its optional plans use fixed, sanitized `EXPLAIN (FORMAT JSON)` SELECTs; they never use `ANALYZE`.

The collector connects through the running `nexora-netops` container, so database credentials stay there. The PostgreSQL session is read-only, statement timeout is two seconds, lock timeout is 500 ms, each HTTP request has a six-second timeout and collection duration is limited to ten minutes. It writes two mode-600, no-overwrite JSONL files under `/tmp`; no application SQL text, query parameters, device identifiers, addresses, credentials or response bodies are exported. Query families and PostgreSQL query IDs are used to group sampled active work. A sampled activity window can miss short queries, so table counters and the optional plans are context, not a query duration measurement.

Alongside direct-backend and Nginx health checks, the collector repeats the read-only GETs used by the asset form (`/api/racks`, rack U-position validation with a synthetic missing-rack name, `/api/cmdb/sites`, `/api/credentials`), the asset list (`/api/assets/summary`, page 1), the Grafana auth gate, and all dashboard iframe URLs listed in the frontend. Health routes run every five seconds, asset/auth routes every fifteen seconds, dashboard URLs every thirty seconds, and PostgreSQL activity at the selected `SAMPLE_SECONDS`. The HTTP probes are staggered and leave a quiet gap after each response so a slow endpoint cannot trigger a tight retry loop.

The collector deliberately sends no Authorization header and does not call the UI's `POST /api/grafana/session` endpoint. Protected asset and dashboard routes can therefore return 401/403; such results measure the unauthenticated routing/auth gate only, not the authenticated asset query or Grafana PromQL panels. The body is never read. To correlate the real UI path, keep a signed-in browser open and reproduce the operation during the same collection window; this collector does not capture browser cookies or credentials, and dashboard HTML probes do not execute the Grafana iframe's JavaScript or PromQL requests.

Copy the shell script and Python helper beside each other on the Linux Docker host. Run from that host:

```bash
DURATION_SECONDS=300 SAMPLE_SECONDS=1 COLLECT_PLANS=1 \
  bash ./collect_nexora_pg_latency.sh
```

`DURATION_SECONDS` defaults to 90 and accepts 1–600. `SAMPLE_SECONDS` defaults to 1 and accepts 1–10. `COLLECT_PLANS=1` estimates the fixed raw telemetry rollup, retention selector, credential-device association, MIB contains search, and exact case-insensitive MIB symbol lookup used by hardware discovery. These are fixed, parameterized `EXPLAIN (FORMAT JSON)` statements without `ANALYZE`; they do not execute the SELECTs. The output pathname may be supplied as the first argument; the resource file uses the same prefix with `.resources.jsonl`.

Use the same page operation during each collection when comparing latency across runs. Keep the returned JSONL files with that operation and its approximate time; they provide correlation evidence, not proof that one table or workload caused a slow request. No extension, database setting, statistics reset, container or device change is required.
