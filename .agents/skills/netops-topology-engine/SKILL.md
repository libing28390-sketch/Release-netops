---
name: netops-topology-engine
description: Build, troubleshoot, and optimize network topology discovery, LLDP/CDP neighbor calculation, LAG/VLAN link deduction, graph algorithms, and frontend topology visualization. Use for changes under backend/services/topology*, backend/api/topology.py, or src/components/TopologyGraph.tsx.
---

# NetOps Topology Engine & Graph Visualization

## Workflow

1. Trace topology discovery from raw driver output / SNMP neighbor tables -> protocol parser (`topology_protocol_service.py`) -> graph model calculation (`topology_service.py` / `topology_graph_service.py`) -> REST API -> frontend graph renderer ([TopologyGraph.tsx](file:///d:/nexora/nexora-private/src/components/TopologyGraph.tsx)).
2. Canonicalize all interface names immediately across multi-vendor boundaries using `backend/core/interface_utils.py`.
3. Separate logical topology layers (L2 physical/switching, L3 routing/subnets, WAN tunnels, aggregation groups) to prevent link clutter and inaccurate graph deductions.
4. Calculate link bidirectional symmetry: verify both A->B and B->A observations before marking a physical link confirmed, or flag single-sided observations accurately.
5. Benchmark frontend graph render performance when node or edge counts scale beyond hundreds.

## Mandatory Conventions & Graph Rules

- **Multi-Vendor Interface Canonicalization**:
  - Never match interface strings literally. H3C `XGE/FGE/HGE`, Huawei `10GE/40GE/100GE`, Cisco `Te/Fo/Hu` and expanded names (`Ten-GigabitEthernet`, `FortyGigE`) must resolve to equivalent canonical keys.
  - Preserve raw interface names in metadata for display and CLI drill-downs, but use canonical keys for deduplication, link hashing, and database upserts.
- **Neighbor Protocol & LAG Deduplication**:
  - LLDP (IEEE 802.1AB), CDP, and NDP entries must be normalized into a unified neighbor schema (`neighbor_collection_contract.py`).
  - Distinguish physical member ports from logical aggregation bundles (Cisco `Port-Channel`, Huawei `Eth-Trunk`, H3C `Bridge-Aggregation`). Physical member links must be nested under the aggregated link in graph views to avoid visual spiderwebs.
  - Mark missing neighbor observations as stale on successful full-device discovery cycles rather than silently dropping historical connections.
- **Graph Layout & Visualization ([TopologyGraph.tsx](file:///d:/nexora/nexora-private/src/components/TopologyGraph.tsx))**:
  - Support hierarchical layouts (Core -> Aggregation -> Access) and force-directed dynamic layouts.
  - Optimize Canvas/SVG rendering: implement viewport culling, level-of-detail (LOD) node labels, and throttled zoom/pan handlers to maintain 60 FPS.
  - Status indicators (Link Up/Down, high utilization, alarm badges) must reflect real-time monitoring state without triggering full graph re-layouts.

## Boundaries

- Raw neighbor data extraction belongs in `backend/drivers/` or SNMP services.
- Link derivation, graph generation, and graph caching belong in `backend/services/topology_*.py`.
- Topology REST APIs and filters belong in `backend/api/topology.py` and `backend/api/graph.py`.
- Interactive graph rendering, layout state, node dragging, and canvas styling belong in `src/components/TopologyGraph.tsx` and `src/pages/TopologyPage.tsx`.

## Safety and Verification

- Run topology tests: `pytest backend/tests/ -k "topology or lldp or neighbor"`.
- Validate interface matching with test fixtures across Cisco, Huawei, and H3C sample outputs.
- Test edge cases: circular loops, unidirectional LLDP neighbors, orphan devices, and dual-homed server links.
