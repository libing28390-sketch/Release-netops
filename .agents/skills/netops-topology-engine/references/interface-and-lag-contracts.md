# Topology interface, neighbor, and LAG contracts

Read this reference when changing interface matching, neighbor normalization, link confirmation, aggregation, or discovery refresh behavior.

## Interface identity

Use the shared canonicalizer in `backend/core/interface_utils.py`; do not compare vendor display names literally. At minimum, equivalent families include H3C XGE/FGE/HGE, Huawei 10GE/40GE/100GE, and Cisco Te/Fo/Hu plus expanded names such as Ten-GigabitEthernet, FortyGigE, and HundredGigE. Preserve raw names for display and CLI drill-downs; use canonical keys for LLDP matching, aggregation membership, upserts, and topology deduplication.

## Neighbors and aggregation

- Normalize LLDP, CDP, and NDP into the shared neighbor collection contract.
- Distinguish physical member ports from logical bundles such as Port-Channel, Eth-Trunk, and Bridge-Aggregation. Present members under their aggregate when that is the existing graph behavior.
- Confirm physical links from bidirectional observations; represent single-sided observations as unconfirmed or asymmetric.
- On a successful discovery cycle, mark missing neighbor observations stale instead of silently deleting their history.

## Manual topology refresh

A manual topology refresh updates the read-only interface summary, aggregation inventory, and LLDP neighbors in one topology run. It is separate from the full CMDB interface/IP status job. The aggregation command is authoritative for LAG membership; after a successful device snapshot, detach members absent from the latest inventory and mark missing neighbor observations stale.
