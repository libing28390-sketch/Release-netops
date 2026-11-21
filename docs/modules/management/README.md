# 平台管理模块说明

- 模块 ID：`management`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：6
- 生产数据库：PostgreSQL

当前平台管理菜单包括审计日志、用户管理、凭据轮换、邮件通知，以及对象存储下的存储配置和文件浏览。六个入口均在导航配置中要求 Administrator。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| 审计日志 | `/management/audit` | [功能介绍](./features/audit/功能介绍.md) | [使用指南](./features/audit/使用指南.md) |
| 用户管理 | `/management/users` | [功能介绍](./features/users/功能介绍.md) | [使用指南](./features/users/使用指南.md) |
| 凭据轮换 | `/management/credentials` | [功能介绍](./features/credentials/功能介绍.md) | [使用指南](./features/credentials/使用指南.md) |
| 邮件通知 | `/management/notifications` | — | — |
| 存储配置 | `/management/storage` | — | — |
| 文件浏览 | `/management/storage/files` | — | — |

## 相关代码

- 导航与菜单权限：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- 页面组合：`src/App.tsx`；对象存储页面：`src/pages/StorageManagementPage.tsx`、`src/pages/StorageFilesPage.tsx`
