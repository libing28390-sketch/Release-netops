---
name: netops-topology-engine
description: Use when changing topology discovery, neighbor normalization, link and LAG deduction, or graph visualization.
---

# NetOps Topology

## Workflow

1. Trace the affected path from device output or SNMP data through parsing, graph calculation, API, and UI.
2. Keep vendor interface identity canonical across discovery and graph operations; preserve the original name for display.
3. Read [interface and LAG contracts](references/interface-and-lag-contracts.md) for neighbor matching, aggregation, or observation lifecycle changes.
4. Read [graph visualization guidance](references/graph-visualization.md) only when changing graph layout or rendering behavior.
5. Use representative fixtures across the vendors affected by the change.

## Boundaries

- Device and protocol collection belongs in drivers and SNMP services.
- Link derivation, graph generation, and caching belong in `backend/services/topology_*.py`.
- Topology APIs belong in `backend/api/topology.py` and `backend/api/graph.py`.
- Graph rendering belongs in `src/components/TopologyGraph.tsx` and `src/pages/TopologyPage.tsx`.

## Verification

Run focused topology, LLDP, and neighbor tests. Cover the affected vendor fixtures and include asymmetric observations, missing devices, or aggregation cases when relevant.
