# Vendor, platform, and command contract

Read this reference when changing device creation, editing, imports, asset synchronization, driver selection, or command dispatch.

The business `vendor`, technical `platform`, driver type, and command family form one contract:

| Vendor | Canonical platform | Driver family | Query commands |
| --- | --- | --- | --- |
| Cisco | `cisco_ios` or an explicit Cisco family | `cisco_ios` | IOS `show ...` |
| Huawei | `huawei_vrp` / `huawei_vrpv8` | `huawei` | VRP `display ...` |
| H3C | `h3c_comware` (device profile may identify a version) | `hp_comware` transport type | Comware `display ...` |
| Juniper | `juniper_junos` | `juniper_junos` | Junos `show ...` |
| Arista | `arista_eos` | `arista_eos` | EOS `show ...` |
| Ruijie | `ruijie_rgos` | `ruijie_os` | RGOS command catalog |

Check `physical_assets`, the linked `devices` row, UI forms, Excel imports, API create/update, synchronization, and the command catalog along the affected path. When a vendor changes, replace an incompatible platform and clear or revalidate vendor-specific model data.

Never infer the vendor from a model number alone; names such as `S6800` are ambiguous. Never send a recognized vendor through Cisco commands when its platform is missing or incompatible. Normalize the mapping or return a clear validation error.

H3C device profiles use `h3c_comware`; the transport adapter maps that platform to Netmiko's `hp_comware` device type. TextFSM uses the separate `h3c_comware` parser family and `h3c_comware_vN` template variants. Do not use the transport-only `hp_comware` prefix for TextFSM templates; see the TextFSM conventions reference.

For interface identity, use `backend/core/interface_utils.py`. Preserve raw display names while using canonical keys for matching, LAG membership, upserts, and topology deduplication. Cover H3C XGE/FGE/HGE, Huawei 10GE/40GE/100GE, and Cisco Te/Fo/Hu families, including expanded names.

For changes to this mapping contract, test Cisco, Huawei, and H3C end to end from vendor selection through platform, driver, and query command; include a vendor-switch regression that proves the old platform is cleared.
