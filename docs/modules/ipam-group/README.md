# IPAM 模块说明

- 模块 ID：`ipam-group`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：7
- 生产数据库：PostgreSQL

侧栏把 IPAM 分成“IPAM 工作台”和“地址空间”两组。工作台包含正式 IP 地址台账、发现终端、IP 定位、利用率和 IP 对账；地址空间包含网段与 VIP。

IP 地址页展示登记台账，发现终端页展示从 ARP/MAC 数据形成的观察历史。发现记录不会自动登记为地址分配，也不会因为长期未发现而自动释放 IP；对账结论依赖覆盖范围和采集证据，采集失败或范围不明不能显示为核对通过。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| IP 地址 | `/ipam/ips` | [功能介绍](./features/ipam-ips/功能介绍.md) | [使用指南](./features/ipam-ips/使用指南.md) |
| 发现终端 | `/ipam/endpoints` | — | — |
| IP 定位 | `/ipam/locate` | — | — |
| 利用率 | `/ipam/utilization` | [功能介绍](./features/ipam-util/功能介绍.md) | [使用指南](./features/ipam-util/使用指南.md) |
| IP 对账 | `/ipam/reconciliation` | [功能介绍](./features/ipam-reconciliation/功能介绍.md) | [使用指南](./features/ipam-reconciliation/使用指南.md) |
| 网段 | `/ipam/prefixes` | [功能介绍](./features/ipam-prefixes/功能介绍.md) | [使用指南](./features/ipam-prefixes/使用指南.md) |
| VIP | `/ipam/vips` | [功能介绍](./features/ipam-vips/功能介绍.md) | [使用指南](./features/ipam-vips/使用指南.md) |

“IPAM 工作台”和“地址空间”是分组菜单，数量不计入末级入口。代码仍保留 `/ipam/pools` 与 `/ipam/dhcp` 页面路由和对应页面，但当前侧栏未列出地址池、DHCP 租约入口；本表只统计侧栏中的末级菜单。

## 相关代码

- 导航与分组路由：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- IPAM 页面：`src/pages/IPAMManagementTab.tsx`、`src/pages/IPVlan`
- 后端接口与服务：`backend/api/ipam.py`、`backend/services/ipam_service.py`、`backend/services/ipam_discovery_service.py`
