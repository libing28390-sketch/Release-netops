# 实时监控模块说明

- 模块 ID：`realtime`
- 英文名称：REAL-TIME
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 子功能数量：6
- 数据库约束：仅使用 PostgreSQL；缓存只作为辅助，不能覆盖数据库事实。
- 状态约束：正常、异常、未知、未配置、无数据必须分别表达。

## 模块目标

实时监控用于承载 运营总览、监控中心、互联网出口、服务器监控、网络监控、网络拓扑 等能力。页面、API、权限和审计必须围绕同一业务对象，任何写操作均需经过角色校验，任何无证据状态均不得默认显示为正常。

## 子功能目录

| # | 子功能 | 路由 | 功能介绍 | 使用指南 |
|---:|---|---|---|---|
| 1 | 运营总览 | `/monitor/overview` | [功能介绍](./features/dashboard/功能介绍.md) | [使用指南](./features/dashboard/使用指南.md) |
| 2 | 监控中心 | `/monitor/telemetry` | [功能介绍](./features/monitoring/功能介绍.md) | [使用指南](./features/monitoring/使用指南.md) |
| 3 | 互联网出口 | `/monitor/outbound` | [功能介绍](./features/outbound-monitoring/功能介绍.md) | [使用指南](./features/outbound-monitoring/使用指南.md) |
| 4 | 服务器监控 | `/monitor/servers` | [功能介绍](./features/server-monitoring/功能介绍.md) | [使用指南](./features/server-monitoring/使用指南.md) |
| 5 | 网络监控 | `/monitor/networks` | [功能介绍](./features/network-monitoring/功能介绍.md) | [使用指南](./features/network-monitoring/使用指南.md) |
| 6 | 网络拓扑 | `/monitor/topology` | [功能介绍](./features/topology/功能介绍.md) | [使用指南](./features/topology/使用指南.md) |

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

