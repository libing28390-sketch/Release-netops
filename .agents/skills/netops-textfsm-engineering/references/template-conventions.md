# TextFSM template conventions

Read when adding or changing template filenames, parser fields, regular expressions, or state transitions.

## Platform keys and filenames

- Cisco IOS: `cisco_ios_<command>.textfsm`.
- Huawei VRP: `huawei_vrp_<command>.textfsm`.
- H3C Comware: `h3c_comware_<command>.textfsm`, or `h3c_comware_v3_`, `h3c_comware_v5_`, `h3c_comware_v7_`, and `h3c_comware_v9_` variants when the device profile selects that grammar.
- Keep `h3c_comware` as the public parser family. The transport adapter maps it to Netmiko's `hp_comware` device type; do not use `hp_comware_` or `h3c_comware9_` as template filename prefixes.

## Fields and parsing

Use stable field names across vendors for the same concept:

- Interface brief: `INTERFACE`, `IP_ADDRESS`, `STATUS`, `PROTOCOL`, `DESCRIPTION`.
- LLDP neighbors: `LOCAL_INTERFACE`, `NEIGHBOR_NAME`, `NEIGHBOR_INTERFACE`, `CHASSIS_ID`, `MANAGEMENT_IP`.
- MAC table: `VLAN`, `MAC_ADDRESS`, `TYPE`, `PORT`.
- ARP table: `IP_ADDRESS`, `MAC_ADDRESS`, `INTERFACE`, `VLAN`.

Use `Filldown` for header values shared by records and `Required` for primary keys. Prefer constrained expressions over greedy `.*`; account for wrapped lines, whitespace variation, and firmware output differences. Confirm normalized fields still match downstream consumers such as topology, IP location, inspection, and inventory.
