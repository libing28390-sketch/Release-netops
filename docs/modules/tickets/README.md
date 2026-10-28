# 工单管理模块说明

- 模块 ID：`tickets`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：8
- 生产数据库：PostgreSQL

“故障与服务”入口 `/tickets` 汇总故障工单和服务申请；相关变更单可以关联这些事项。其余入口管理变更单的创建、个人/组内待办、参与记录、关注、全部变更单和草稿。

流程目标见 [Nexora 工单管理流程规范 V1.0](./Nexora工单管理流程规范.md)。该规范区分现行源码能力与待建设项；流程目标本身不代表所有目标控制均已上线。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| 故障与服务 | `/tickets` | — | — |
| 新建工单 | `/change-orders/new` | [功能介绍](./features/new-order/功能介绍.md) | [使用指南](./features/new-order/使用指南.md) |
| 个人待办 | `/change-orders/my-todo` | [功能介绍](./features/my-todo/功能介绍.md) | [使用指南](./features/my-todo/使用指南.md) |
| 组内待办 | `/change-orders/group-todo` | [功能介绍](./features/group-todo/功能介绍.md) | [使用指南](./features/group-todo/使用指南.md) |
| 我参与的 | `/change-orders/participated` | [功能介绍](./features/my-participated/功能介绍.md) | [使用指南](./features/my-participated/使用指南.md) |
| 我的关注 | `/change-orders/focus` | [功能介绍](./features/my-focus/功能介绍.md) | [使用指南](./features/my-focus/使用指南.md) |
| 全部变更单 | `/change-orders/all` | [功能介绍](./features/change-orders/功能介绍.md) | [使用指南](./features/change-orders/使用指南.md) |
| 草稿箱 | `/change-orders/drafts` | [功能介绍](./features/my-drafts/功能介绍.md) | [使用指南](./features/my-drafts/使用指南.md) |

## 相关代码

- 导航与路由：`src/components/AppSidebar/navConfig.ts`、`src/utils/routeContext.ts`
- 故障与服务工单：`src/pages/Tickets`
- 变更单界面：`src/pages/ChangeOrderTab.tsx`、`src/pages/ChangeOrder`
- 后端接口：`backend/api/tickets`、`backend/api/change_orders`
- 服务：`backend/services/service_request_service.py`
