# 工单管理模块说明

- 模块 ID：`tickets`
- 英文名称：TICKETS
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 子功能数量：7
- 数据库约束：仅使用 PostgreSQL；缓存只作为辅助，不能覆盖数据库事实。
- 状态约束：正常、异常、未知、未配置、无数据必须分别表达。

## 模块目标

工单管理用于承载 新建工单、个人待办、组内待办、我参与的、我的关注、全部工单、草稿箱 等能力。页面、API、权限和审计必须围绕同一业务对象，任何写操作均需经过角色校验，任何无证据状态均不得默认显示为正常。

## 子功能目录

| # | 子功能 | 路由 | 功能介绍 | 使用指南 |
|---:|---|---|---|---|
| 1 | 新建工单 | `/change-orders/new` | [功能介绍](./features/new-order/功能介绍.md) | [使用指南](./features/new-order/使用指南.md) |
| 2 | 个人待办 | `/change-orders/my-todo` | [功能介绍](./features/my-todo/功能介绍.md) | [使用指南](./features/my-todo/使用指南.md) |
| 3 | 组内待办 | `/change-orders/group-todo` | [功能介绍](./features/group-todo/功能介绍.md) | [使用指南](./features/group-todo/使用指南.md) |
| 4 | 我参与的 | `/change-orders/participated` | [功能介绍](./features/my-participated/功能介绍.md) | [使用指南](./features/my-participated/使用指南.md) |
| 5 | 我的关注 | `/change-orders/focus` | [功能介绍](./features/my-focus/功能介绍.md) | [使用指南](./features/my-focus/使用指南.md) |
| 6 | 全部工单 | `/change-orders/all` | [功能介绍](./features/change-orders/功能介绍.md) | [使用指南](./features/change-orders/使用指南.md) |
| 7 | 草稿箱 | `/change-orders/drafts` | [功能介绍](./features/my-drafts/功能介绍.md) | [使用指南](./features/my-drafts/使用指南.md) |

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

