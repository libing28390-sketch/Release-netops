---
name: netops-grafana-dashboards
description: Use when designing, editing, validating, or troubleshooting Nexora Grafana dashboards, panel visualizations and settings, PromQL, variables, or provisioning.
---

# NetOps Grafana Dashboards

Build dashboards that answer a clear operations question with accurate metric semantics, useful filters, and honest empty-data behavior.

## Project conventions

- Check the target Grafana version before using a feature or dashboard schema. This repository currently pins Grafana `12.1.0` in `docker-compose.yml`; the Grafana `/latest/` documentation may describe a newer release. Treat `/latest/` links below as entry points, then switch the docs to the deployed version before relying on behavior or schema details.
- The provisioned default data source is VictoriaMetrics, using the Prometheus query model and UID `victoriametrics`. Preserve the configured UID and verify the data source before changing dashboard queries.
- Dashboards are provisioned from `monitoring/grafana/dashboards/` by `monitoring/grafana/provisioning/dashboards/nexora.yml`. The repository's `monitoring/grafana/generate_dashboards.py` writes the dashboard JSON files. Treat the generator as the source of truth for dashboards it builds: change it, regenerate its outputs, and review every affected diff. Do not fix generated JSON alone. Provisioned file changes can replace database/UI edits when Grafana reloads them.
- Before running the generator, inspect `git status` and the generator's full output list. It rewrites all dashboards it builds, so preserve and review any existing user edits.
- Treat metric names, labels, units, and meanings as an explicit contract. Check the collector/exporter configuration, metric catalog, generator queries, and relevant tests before writing PromQL. Do not infer that a metric or label exists from a dashboard title.
- For network interface metadata, keep the local meaning consistent: `ifName` is the interface name, `ifAlias` carries the configured interface description, and `ifIndex` is an internal join key. Match series on the correct device/interface identity and avoid requiring a label that the selected source metric does not expose.

## Dashboard responsibilities and traffic semantics

- Keep fleet discovery on the network overview: device/interface health, major exceptions, and monitored traffic hotspots. Use the interface traffic and health dashboard to explain the selected ports with utilization, rates, errors/discards, and state. Device/interface detail should answer why one selected asset is unhealthy. Prefer drill-down links over repeating the same Top-N panels on every dashboard.
- Do not call the sum of all monitored interface rates “total network traffic.” The same flow can be counted at access, aggregation, and core interfaces, and `ifHCIn`/`ifHCOut` are relative to each device. Use “observed interface traffic” or “monitored interface aggregate” and show the selected scope. Use WAN/edge ingress or egress only when interface roles identify the boundary and the query filters exactly those interfaces.
- Separate traffic hotspots from congestion risk. Rank raw throughput to find busy links; rank utilization against known per-direction capacity to find constrained links. Do not interpret unknown or invalid speed as spare capacity. On full-duplex links, evaluate ingress and egress against capacity independently.

## Choose a visualization for the network task

The existing Nexora dashboards mainly use Stat, Time series, and Table panels. Keep those as the default; choose another panel when its data shape makes a network operation easier to understand.

| Operator question | Preferred view | Network-specific fit and limits |
|---|---|---|
| How many devices, interfaces, APs, or failed scrapes are there right now? | Stat | Show a small set of fleet totals or current values. Pair it with an exception list; a total alone does not locate the fault. |
| Is traffic, utilization, CPU, temperature, or scrape duration changing over time? | Time series | Best for timestamped measurements. Keep fleet series bounded (for example, selected devices or Top N) and use separate units/queries for bps, pps, percent, and temperature. |
| Which device or interface is down, busy, or accumulating errors? | Table | Best when the operator needs identity and several facts together: site, device, interface name/description, admin state, oper state, current rate, and errors. Sort by the operational concern and use readable state mappings. |
| Which interfaces or devices have the highest current rate or utilization? | Bar chart or Table | Use a ranked bar chart for quick comparison; use a table when device/interface identity, alias, multiple metrics, or drill-down links matter. Limit the result to a useful Top N. |
| Is one selected interface close to its capacity? | Gauge; Bar gauge or table gauge for several interfaces | Use a Gauge for one selected interface and a known capacity range. For many ports, prefer a Bar gauge or a table with gauge cells so labels and values remain readable. Do not imply 0–100% capacity when the speed is absent or invalid. |
| Which links flapped or remained down during a time window? | State timeline or Status history | Use for a small, filtered set of sampled device/interface states. State timeline can merge consecutive equal states; Status history preserves each periodic sample. Scrape interval, gaps, and retention limit the accuracy of the history. |
| Where are devices or sites, and how are they physically connected? | Geomap or Node graph, only with matching data | Geomap needs usable location fields such as coordinates or geohash. Node graph needs real node/edge data. Current VictoriaMetrics dashboard labels provide site/device/interface identity but no site coordinates or topology edges; get that data from the asset/topology model before choosing these views. |
| Is a measurement distribution changing? | Heatmap or Histogram, only with distribution data | Use when the source supplies histogram buckets or a suitable distribution. Ordinary interface byte counters and their rates are not histograms. |

Pie charts are appropriate only for a small categorical composition where proportions answer the question. They are a poor fit for time trends and long device/interface rankings.

## Configure Grafana for network semantics

- **Units and field options:** Use the source metric's actual unit. IF-MIB octet counters become bytes/s after `rate()` and bits/s after multiplying by 8; error/discard counter rates are packets/s; utilization is percent only after dividing traffic rate by a known interface capacity. Match the Grafana percent unit and thresholds to the query scale (0–1 ratio versus 0–100 percentage). Set unit, decimals, min/max, and no-value text explicitly. Do not threshold a raw counter as though it were a utilization percentage.
- **Capacity and health measures:** Show current utilization and rate for the selected interval. Add peak/P95 utilization only with an explicit time window and per-interface meaning; calculate PPS from collected packet counters rather than estimating it from bit rate. Show headroom only when capacity is known, keeping ingress and egress separate. Treat `ifLastChange` as an uptime-relative state-change value, not a wall-clock timestamp; derive flap counts from adequately sampled state transitions. Check the current collector and metric contract before using any of these measures.
- **Value mappings:** Use exact Value mappings for enumerated states, Range mappings for meaningful continuous bands, Special mappings for `null`/`NaN`, and Regex mappings only for controlled string formats. For IF-MIB, distinguish `ifAdminStatus` (desired/admin state) from `ifOperStatus` (observed operational state). `ifOperStatus` values 1–7 mean up, down, testing, unknown, dormant, notPresent, and lowerLayerDown; confirm what the exporter actually emits before mapping any extra value such as 0. An interface with admin-down and oper-down is not automatically faulty; admin-up plus oper-down is a fault candidate. Keep unavailable data separate from a valid unknown state. In tables, choose colored-text/background cell mode for mapped colors. Value mappings are presentation rules, not data conversion; mapped values can bypass unit/decimal formatting, and on Time series they change display text but do not apply mapped colors to the series.
- **Thresholds and overrides:** Apply thresholds to continuous values with a known unit and range, such as utilization against interface capacity or a documented temperature policy. Panel thresholds only affect display; they do not create alert rules or notifications. For alert-policy changes, use `netops-monitoring-telemetry` and follow the project's alert architecture. Use targeted field overrides for direction-specific colors, units, and labels; avoid a global override when one panel contains mixed units or different device metrics.
- **Queries and expressions:** Use PromQL in the current VictoriaMetrics data source for metric filtering, counter rates, label joins, and aggregation. Calculate `rate()` before aggregating counters and keep grouping labels aligned with device/interface identity. Grafana expressions can help with small post-query calculations or combining query results. Share a query result across panels only when the query and result shape really are shared; avoid unnecessary dependencies between panels. SQL Expressions became public preview after this repository's Grafana `12.1.0` pin; do not make the current dashboards depend on them unless the target instance has been upgraded and the feature has been confirmed.
- **Transformations:** Use transformations for presentation tasks such as organizing, renaming, hiding, or sorting fields after the query. Keep counter math and identity-sensitive joins in PromQL or the metric contract where possible. Transformations run in order, so inspect intermediate/final table data when a panel looks wrong; do not use a lossy reduction that hides the per-device or per-interface fault.
- **Legends, tooltips, and drill-down:** Name series with stable site/device/interface labels and bound high-cardinality views with variables or Top N. Use tooltips that support the comparison without listing an unreadable fleet. Add data links from fleet/top-N tables to the relevant device or interface dashboard while carrying the selected variables. Grafana panel Actions can issue unauthenticated API calls; do not use them for device configuration changes or other privileged operations.
- **Empty panels:** Inspect the raw query and expanded variables first, then the returned fields/labels, transformation output, panel mappings, time range, scrape interval, and datasource health. Distinguish a truly zero counter rate from a missing scrape or absent metric.

## Visual conventions for operations

- Follow the existing semantic palette consistently: inbound blue, outbound green, errors orange, and discards red. Keep ordinary Stat panels neutral; reserve warning colors for states or values that need attention.
- Use a short time-series legend such as Last, Max, and Avg when it helps compare links. Keep comparison charts to roughly 5–10 readable series; use a ranked table for larger Top-N sets. For utilization tables, pair a gauge cell with the numeric percentage and capacity context.
- Put identity and fault context first in diagnostic tables (site, device, interface/alias, admin/oper state), followed by utilization, rate, and error/discard measures. Avoid decorative panels that do not help locate, prioritize, or explain a network issue.

## Dashboard workflow

1. Identify the operator question, audience, time horizon, and source metrics. Check the current dashboard, data source, collection path, and target Grafana version before changing panel definitions.
2. Design the page around investigation order: fleet status and important exceptions first, then device/interface detail. Use concise titles, explicit units, consistent inbound/outbound/error/discard colors, and bounded variable filters such as site, vendor, role, and device where supported.
3. Write queries against observed metric contracts. For counters, calculate rates before aggregating; retain only labels needed for filtering or interpretation; avoid accidental duplicate series from joins. Prefer high-capacity interface counters where collected, and use a fallback only when the fallback metric is part of the contract.
4. Keep missing, unknown, and healthy-zero states distinct. Do not turn absent telemetry into zero or a healthy status unless another availability signal proves that the zero is meaningful. Configure useful no-value text and explicit status mappings where panels show device or interface state.
5. Use dashboard variables and transformations only when they improve reuse or legibility. Confirm variable queries return values for the configured data source, and confirm chained filters do not create unexpectedly broad or expensive queries.
6. Keep dashboard files version-controlled. Do not write to a live Grafana instance, alter provisioning, or deploy generated dashboards unless the user requested that operation.

## Validation

- For generator changes, run the generator only after reviewing its output scope, then compile the Python module and parse every generated dashboard JSON file.
- Review query expressions, data source UIDs, variable queries, unique panel IDs, units, thresholds/value mappings, and expected No data behavior. Check key queries against the actual metric labels and collection interval.
- Review the complete diff, including regenerated files, and run `git diff --check`. Use `netops-monitoring-telemetry` when the work changes metric collection or alert semantics, and `netops-quality-gate` when focused repository checks are needed.
- Source JSON validation does not prove that the dashboard renders or returns data in the target Grafana. State clearly when visual or live-instance verification was not performed.

## Grafana documentation

Use the official documentation for the target Grafana release when checking UI behavior or schema details. The links below use `/latest/`; switch to the deployed release in Grafana's documentation version selector before relying on specifics:

- [Dashboards](https://grafana.com/docs/grafana/latest/visualizations/dashboards/) — panels, queries, transformations, and dashboard structure.
- [Dashboard variables](https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/) — variable types and behavior.
- [Panel visualizations](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/) — choose a panel by the shape and question of the data.
- [Configure value mappings](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-value-mappings/) — exact values, ranges, regexes, and special values.
- [Configure standard options](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-standard-options/) — units, bounds, decimals, display names, colors, and no-value display.
- [Configure thresholds](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-thresholds/) — numeric thresholds and threshold modes.
- [Configure field overrides](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-overrides/) — targeted per-field or per-series display settings.
- [Transform data](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/query-transform-data/transform-data/) — field shaping and transformation order.
- [Configure tooltips](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-tooltips/) — interaction when inspecting time-series panels.
- [Configure data links and actions](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-data-links/) — contextual drill-down and action behavior.
- [Provision Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/) — file-based dashboard and data-source provisioning.
- [Dashboard overview](https://grafana.com/docs/grafana/latest/fundamentals/dashboards-overview/) — data source, query, transformation, and panel concepts.
- [RFC 2863: IF-MIB](https://www.rfc-editor.org/rfc/rfc2863) — interface admin/oper state and counter semantics.
