# 资产平台与 H3C TextFSM 模板分层

## Asset platform values

The asset-management platform selector now exposes and persists these platform keys:

| Vendor | Platform key | Display label |
| --- | --- | --- |
| Huawei | `huawei_vrp` | Huawei VRPv5 |
| Huawei | `huawei_vrpv8` | Huawei VRPv8 |
| H3C | `hp_comware` | H3C Comware V5 |
| H3C | `h3c_comware` | H3C Comware V7 |
| H3C | `h3c_comware9` | H3C Comware V9 |
| Cisco | `cisco_ios` | Cisco IOS |
| Cisco | `cisco_xe` | Cisco IOS-XE |
| Cisco | `cisco_nxos` | Cisco NX-OS |

The backend asset allowlist preserves these values and synchronizes the selected platform to the linked `devices.platform` field. IOS-XE uses the Cisco IOS transport/parser family when no dedicated IOS-XE template exists, while retaining `cisco_xe` as the asset/platform identity.

## H3C template layout

The custom template directory is not a single H3C template:

- `h3c_comware_*`: 14 Comware7-focused custom templates.
- `hp_comware_*`: 9 Comware5-focused custom templates.
- `h3c_comware9_*`: 1 Comware9-specific custom template currently, for `display link-aggregation verbose`.

Some common H3C commands use the read-only NTC built-in `hp_comware_*` templates through the compatibility chain. This avoids copying identical grammars into every platform namespace. The built-in directory remains unmodified.

When a Comware version has a materially different official output, the fixture and template must be added under that platform key instead of broadening a shared H3C template.
