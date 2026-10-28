# 资产与配置模块说明

- 模块 ID：`assets-config`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：6
- 生产数据库：PostgreSQL

本模块的侧栏入口为资产管理、网络设备、服务器、NPA 智能路径诊断、网络事实库和标签管理。IP 定位当前位于 IPAM 菜单，不再列作本模块入口。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| 资产管理 | `/assets/dashboard` | [功能介绍](./features/assets/功能介绍.md) | [使用指南](./features/assets/使用指南.md) |
| 网络设备 | `/assets/network-devices` | [功能介绍](./features/devices/功能介绍.md) | [使用指南](./features/devices/使用指南.md) |
| 服务器 | `/assets/servers` | [功能介绍](./features/servers/功能介绍.md) | [使用指南](./features/servers/使用指南.md) |
| NPA 智能路径诊断 | `/assets/diagnose` | [功能介绍](./features/path-diagnose/功能介绍.md) | [使用指南](./features/path-diagnose/使用指南.md) |
| 网络事实库 | `/assets/nsot` | [功能介绍](./features/nsot/功能介绍.md) | [使用指南](./features/nsot/使用指南.md) |
| 标签管理 | `/assets/tags` | [功能介绍](./features/tags/功能介绍.md) | [使用指南](./features/tags/使用指南.md) |

## 相关代码

- 导航与菜单权限：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- 页面组合：`src/App.tsx`
