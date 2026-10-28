# 自动化模块说明

- 模块 ID：`automation`
- 导航来源：`src/components/AppSidebar/navConfig.ts`
- 末级菜单入口：10
- 生产数据库：PostgreSQL

当前侧栏包含快捷操作、巡检、执行计划与历史、定时作业、巡检指标、解析模板，以及操作管理下的脚本/系统操作和 NSOT 采集目录。快捷操作入口使用 `/automation/quick-ops`；相关执行、任务等页面由该入口的活动路由匹配覆盖。

## 当前菜单与路由

| 末级菜单 | 路由 | 功能介绍 | 使用指南 |
|---|---|---|---|
| 快捷操作 | `/automation/quick-ops` | [功能介绍](./features/auto-exec/功能介绍.md) | [使用指南](./features/auto-exec/使用指南.md) |
| 巡检概览 | `/automation/inspections` | [功能介绍](./features/inspection/功能介绍.md) | [使用指南](./features/inspection/使用指南.md) |
| 巡检记录 | `/automation/records` | [功能介绍](./features/inspection-records/功能介绍.md) | [使用指南](./features/inspection-records/使用指南.md) |
| 执行计划 | `/automation/schedules` | [功能介绍](./features/exec-schedule/功能介绍.md) | [使用指南](./features/exec-schedule/使用指南.md) |
| 执行历史 | `/automation/history` | [功能介绍](./features/exec-history/功能介绍.md) | [使用指南](./features/exec-history/使用指南.md) |
| 定时作业 | `/automation/scheduled-jobs` | [功能介绍](./features/scheduled-jobs/功能介绍.md) | [使用指南](./features/scheduled-jobs/使用指南.md) |
| 巡检指标 | `/automation/metrics` | [功能介绍](./features/inspection-metrics/功能介绍.md) | [使用指南](./features/inspection-metrics/使用指南.md) |
| 解析模板 | `/automation/textfsm` | [功能介绍](./features/textfsm-templates/功能介绍.md) | [使用指南](./features/textfsm-templates/使用指南.md) |
| 脚本 / 系统操作 | `/automation/scripts` | [功能介绍](./features/scripts/功能介绍.md) | [使用指南](./features/scripts/使用指南.md) |
| NSOT 采集目录 | `/automation/nsot` | — | — |

“操作管理”是包含两个入口的分组菜单，不计入末级入口数。

## 相关代码

- 导航与路由匹配：`src/components/AppSidebar/navConfig.ts`
- 路由解析：`src/utils/routeContext.ts`
- 页面与执行入口：`src/pages/AutomationExecute`
