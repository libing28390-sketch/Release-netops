# IPAM模块说明

- 模块 ID：`ipam-group`
- 英文名称：IPAM
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 子功能数量：7
- 数据库约束：仅使用 PostgreSQL；缓存只作为辅助，不能覆盖数据库事实。
- 状态约束：正常、异常、未知、未配置、无数据必须分别表达。

## 模块目标

IPAM用于承载 Prefix管理、IP地址、地址池、VIP管理、DHCP租约、利用率分析、IP对账中心 等能力。页面、API、权限和审计必须围绕同一业务对象，任何写操作均需经过角色校验，任何无证据状态均不得默认显示为正常。

## 子功能目录

| # | 子功能 | 路由 | 功能介绍 | 使用指南 |
|---:|---|---|---|---|
| 1 | Prefix管理 | `/ipam/prefixes` | [功能介绍](./features/ipam-prefixes/功能介绍.md) | [使用指南](./features/ipam-prefixes/使用指南.md) |
| 2 | IP地址 | `/ipam/ips` | [功能介绍](./features/ipam-ips/功能介绍.md) | [使用指南](./features/ipam-ips/使用指南.md) |
| 3 | 地址池 | `/ipam/pools` | [功能介绍](./features/ipam-pools/功能介绍.md) | [使用指南](./features/ipam-pools/使用指南.md) |
| 4 | VIP管理 | `/ipam/vips` | [功能介绍](./features/ipam-vips/功能介绍.md) | [使用指南](./features/ipam-vips/使用指南.md) |
| 5 | DHCP租约 | `/ipam/dhcp` | [功能介绍](./features/ipam-dhcp/功能介绍.md) | [使用指南](./features/ipam-dhcp/使用指南.md) |
| 6 | 利用率分析 | `/ipam/utilization` | [功能介绍](./features/ipam-util/功能介绍.md) | [使用指南](./features/ipam-util/使用指南.md) |
| 7 | IP对账中心 | `/ipam/reconciliation` | [功能介绍](./features/ipam-reconciliation/功能介绍.md) | [使用指南](./features/ipam-reconciliation/使用指南.md) |

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

