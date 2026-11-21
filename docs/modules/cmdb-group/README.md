# CMDB 基础数据模块说明

- 模块 ID：`cmdb-group`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：10
- 生产数据库：PostgreSQL

当前模块提供凭据中心、机柜管理、资产目录、资源检索、设备与接口骨架、站点、VRF、VLAN 和 VLAN 业务入口。侧栏当前提供“VLAN 业务”，没有“租户管理”入口。资产目录和资源检索允许 Viewer 角色访问，其余 CMDB 菜单在导航配置中要求 Operator。

接口、VLAN、VRF、BGP 等 CMDB 数据通过独立的 CLI 采集快照供页面读取；接口采集可以联动 VLAN 资料。此采集与监控遥测、ARP/MAC 发现使用不同的数据路径。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| 凭据中心 | `/cmdb/credentials` | [功能介绍](./features/cmdb-credentials/功能介绍.md) | [使用指南](./features/cmdb-credentials/使用指南.md) |
| 机柜管理 | `/cmdb/racks` | [功能介绍](./features/cmdb-racks/功能介绍.md) | [使用指南](./features/cmdb-racks/使用指南.md) |
| 资产目录 | `/cmdb/assets` | [功能介绍](./features/cmdb-assets/功能介绍.md) | [使用指南](./features/cmdb-assets/使用指南.md) |
| 资源检索 | `/cmdb/resources` | [功能介绍](./features/cmdb-resources/功能介绍.md) | [使用指南](./features/cmdb-resources/使用指南.md) |
| 设备骨架 | `/cmdb/devices` | [功能介绍](./features/cmdb-devices/功能介绍.md) | [使用指南](./features/cmdb-devices/使用指南.md) |
| 接口骨架 | `/cmdb/interfaces` | [功能介绍](./features/cmdb-interfaces/功能介绍.md) | [使用指南](./features/cmdb-interfaces/使用指南.md) |
| 站点管理 | `/cmdb/sites` | [功能介绍](./features/cmdb-sites/功能介绍.md) | [使用指南](./features/cmdb-sites/使用指南.md) |
| VRF 管理 | `/cmdb/vrfs` | [功能介绍](./features/cmdb-vrfs/功能介绍.md) | [使用指南](./features/cmdb-vrfs/使用指南.md) |
| VLAN 管理 | `/cmdb/vlans` | [功能介绍](./features/cmdb-vlans/功能介绍.md) | [使用指南](./features/cmdb-vlans/使用指南.md) |
| VLAN 业务 | `/cmdb/vlan-business` | — | — |

## 相关代码

- 导航与菜单权限：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- 前端页面：`src/pages/CmdbManagementTab.tsx`
- 后端接口：`backend/api/cmdb.py`
