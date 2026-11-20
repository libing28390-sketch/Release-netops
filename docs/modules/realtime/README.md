# 实时监控模块说明

- 模块 ID：`realtime`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：9
- 生产数据库：PostgreSQL

当前模块包括运营总览、监控大盘、专线中心、SNMP 诊断、监控报表、采集器管理和网络拓扑。监控报表下分为接口流量与利用率、网络设备运行与资源、互联网出口与 WAN 链路三个入口。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| 运营总览 | `/monitor/overview` | [功能介绍](./features/dashboard/功能介绍.md) | [使用指南](./features/dashboard/使用指南.md) |
| 监控大盘 | `/monitor/dashboards` | — | — |
| 专线中心 | `/monitor/circuits` | — | — |
| SNMP 诊断 | `/monitor/snmp-walk` | — | — |
| 全网接口流量与利用率 | `/monitor/reports/interfaces` | — | — |
| 网络设备运行与资源 | `/monitor/reports/devices` | — | — |
| 互联网出口与 WAN 链路 | `/monitor/reports/outbound` | — | — |
| 采集器管理 | `/monitor/collectors` | — | — |
| 网络拓扑 | `/monitor/topology` | [功能介绍](./features/topology/功能介绍.md) | [使用指南](./features/topology/使用指南.md) |

## 相关代码

- 导航与菜单权限：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- 页面组合：`src/App.tsx`
