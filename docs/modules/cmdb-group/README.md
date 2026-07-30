# CMDB基础数据模块说明

- 模块 ID：`cmdb-group`
- 英文名称：CMDB Core
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 子功能数量：10
- 数据库约束：仅使用 PostgreSQL；缓存只作为辅助，不能覆盖数据库事实。
- 状态约束：正常、异常、未知、未配置、无数据必须分别表达。

## 模块目标

CMDB基础数据用于承载 凭据中心、机柜管理、资产目录、资源检索、设备骨架、接口骨架、站点管理、VRF管理、VLAN管理、租户管理 等能力。页面、API、权限和审计必须围绕同一业务对象，任何写操作均需经过角色校验，任何无证据状态均不得默认显示为正常。

## 子功能目录

| # | 子功能 | 路由 | 功能介绍 | 使用指南 |
|---:|---|---|---|---|
| 1 | 凭据中心 | `/cmdb/credentials` | [功能介绍](./features/cmdb-credentials/功能介绍.md) | [使用指南](./features/cmdb-credentials/使用指南.md) |
| 2 | 机柜管理 | `/cmdb/racks` | [功能介绍](./features/cmdb-racks/功能介绍.md) | [使用指南](./features/cmdb-racks/使用指南.md) |
| 3 | 资产目录 | `/cmdb/assets` | [功能介绍](./features/cmdb-assets/功能介绍.md) | [使用指南](./features/cmdb-assets/使用指南.md) |
| 4 | 资源检索 | `/cmdb/resources` | [功能介绍](./features/cmdb-resources/功能介绍.md) | [使用指南](./features/cmdb-resources/使用指南.md) |
| 5 | 设备骨架 | `/cmdb/devices` | [功能介绍](./features/cmdb-devices/功能介绍.md) | [使用指南](./features/cmdb-devices/使用指南.md) |
| 6 | 接口骨架 | `/cmdb/interfaces` | [功能介绍](./features/cmdb-interfaces/功能介绍.md) | [使用指南](./features/cmdb-interfaces/使用指南.md) |
| 7 | 站点管理 | `/cmdb/sites` | [功能介绍](./features/cmdb-sites/功能介绍.md) | [使用指南](./features/cmdb-sites/使用指南.md) |
| 8 | VRF管理 | `/cmdb/vrfs` | [功能介绍](./features/cmdb-vrfs/功能介绍.md) | [使用指南](./features/cmdb-vrfs/使用指南.md) |
| 9 | VLAN管理 | `/cmdb/vlans` | [功能介绍](./features/cmdb-vlans/功能介绍.md) | [使用指南](./features/cmdb-vlans/使用指南.md) |
| 10 | 租户管理 | `/cmdb/tenants` | [功能介绍](./features/cmdb-tenants/功能介绍.md) | [使用指南](./features/cmdb-tenants/使用指南.md) |

## 通用验收口径

1. 路由可从侧栏进入，刷新后仍保持正确页面。
2. 加载、空数据、未知、失败、成功均有明确反馈。
3. 列表支持与业务规模匹配的筛选、分页或搜索。
4. 写操作有权限校验、确认反馈和可追踪审计。
5. 数据源、采集时间或更新时间在需要判断新鲜度时可见。
6. 后端持久化与查询兼容 PostgreSQL，不新增 SQLite/MySQL 专用实现。

## 相关代码

- 导航：`src/components/AppSidebar/navConfig.ts`
- 路由：`src/App.tsx`
- 前端页面：`src/pages`
- 后端 API：`backend/api`
- 服务与数据库：`backend/services`、`backend/database`

