# CAT-008 Cisco OS Boundary Walkthrough

## 关系矩阵

| OS family | C9300 | Canonical platform mapping |
|---|---|---|
| IOS | forbidden | `cisco_ios` |
| IOS XE | supported for 17.9.x/17.18.x | `cisco_ios` (explicit IOS-XE mapping) |
| NX-OS | forbidden | `cisco_nxos` |
| IOS XR | forbidden | `cisco_iosxr` |

缺少 OS、未知版本或不匹配关系都返回候选/UNKNOWN，不自动选择 driver；V1 platform/version 字段不改写。
