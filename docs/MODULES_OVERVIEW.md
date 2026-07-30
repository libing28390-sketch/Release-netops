# Nexora 模块、子功能与截图总览

> 数据来源：`src/components/AppSidebar/navConfig.ts`
>
> 统计：11 个一级模块、62 个二级页面、11 份模块 README、62 份功能介绍、62 份使用指南、62 张真实页面截图。
>
> 数据库：PostgreSQL。

## 1. 实时监控

[模块 README](./modules/realtime/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 运营总览 | `/monitor/overview` | [介绍](./modules/realtime/features/dashboard/功能介绍.md) | [指南](./modules/realtime/features/dashboard/使用指南.md) | [截图](./images/realtime/dashboard.png) |
| 监控中心 | `/monitor/telemetry` | [介绍](./modules/realtime/features/monitoring/功能介绍.md) | [指南](./modules/realtime/features/monitoring/使用指南.md) | [截图](./images/realtime/monitoring.png) |
| 互联网出口 | `/monitor/outbound` | [介绍](./modules/realtime/features/outbound-monitoring/功能介绍.md) | [指南](./modules/realtime/features/outbound-monitoring/使用指南.md) | [截图](./images/realtime/outbound-monitoring.png) |
| 服务器监控 | `/monitor/servers` | [介绍](./modules/realtime/features/server-monitoring/功能介绍.md) | [指南](./modules/realtime/features/server-monitoring/使用指南.md) | [截图](./images/realtime/server-monitoring.png) |
| 网络监控 | `/monitor/networks` | [介绍](./modules/realtime/features/network-monitoring/功能介绍.md) | [指南](./modules/realtime/features/network-monitoring/使用指南.md) | [截图](./images/realtime/network-monitoring.png) |
| 网络拓扑 | `/monitor/topology` | [介绍](./modules/realtime/features/topology/功能介绍.md) | [指南](./modules/realtime/features/topology/使用指南.md) | [截图](./images/realtime/topology.png) |

## 2. 终端接入

[模块 README](./modules/terminal-access/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 操作工作台 | `/access/workspace` | [介绍](./modules/terminal-access/features/access-center/功能介绍.md) | [指南](./modules/terminal-access/features/access-center/使用指南.md) | [截图](./images/terminal-access/access-center.png) |
| PAM 受控审计 | `/access/pam-audit` | [介绍](./modules/terminal-access/features/pam-audit/功能介绍.md) | [指南](./modules/terminal-access/features/pam-audit/使用指南.md) | [截图](./images/terminal-access/pam-audit.png) |

## 3. 告警处置

[模块 README](./modules/alerts/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 告警中心 | `/alerts/desk` | [介绍](./modules/alerts/features/alert-desk/功能介绍.md) | [指南](./modules/alerts/features/alert-desk/使用指南.md) | [截图](./images/alerts/alert-desk.png) |
| 历史告警 | `/alerts/history` | [介绍](./modules/alerts/features/alert-history/功能介绍.md) | [指南](./modules/alerts/features/alert-history/使用指南.md) | [截图](./images/alerts/alert-history.png) |
| 告警规则 | `/alerts/rules` | [介绍](./modules/alerts/features/alert-rules/功能介绍.md) | [指南](./modules/alerts/features/alert-rules/使用指南.md) | [截图](./images/alerts/alert-rules.png) |
| 维护期 | `/alerts/maintenance` | [介绍](./modules/alerts/features/maintenance/功能介绍.md) | [指南](./modules/alerts/features/maintenance/使用指南.md) | [截图](./images/alerts/maintenance.png) |

## 4. 资产与配置

[模块 README](./modules/assets-config/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 资产管理 | `/assets/dashboard` | [介绍](./modules/assets-config/features/assets/功能介绍.md) | [指南](./modules/assets-config/features/assets/使用指南.md) | [截图](./images/assets-config/assets.png) |
| 网络设备 | `/assets/devices` | [介绍](./modules/assets-config/features/devices/功能介绍.md) | [指南](./modules/assets-config/features/devices/使用指南.md) | [截图](./images/assets-config/devices.png) |
| 服务器 | `/assets/servers` | [介绍](./modules/assets-config/features/servers/功能介绍.md) | [指南](./modules/assets-config/features/servers/使用指南.md) | [截图](./images/assets-config/servers.png) |
| NPA 智能路径诊断 | `/assets/diagnose` | [介绍](./modules/assets-config/features/path-diagnose/功能介绍.md) | [指南](./modules/assets-config/features/path-diagnose/使用指南.md) | [截图](./images/assets-config/path-diagnose.png) |
| 网络事实库 | `/assets/nsot` | [介绍](./modules/assets-config/features/nsot/功能介绍.md) | [指南](./modules/assets-config/features/nsot/使用指南.md) | [截图](./images/assets-config/nsot.png) |
| IP 工具箱 | `/assets/toolbox` | [介绍](./modules/assets-config/features/ip-locator/功能介绍.md) | [指南](./modules/assets-config/features/ip-locator/使用指南.md) | [截图](./images/assets-config/ip-locator.png) |
| 标签管理 | `/assets/tags` | [介绍](./modules/assets-config/features/tags/功能介绍.md) | [指南](./modules/assets-config/features/tags/使用指南.md) | [截图](./images/assets-config/tags.png) |

## 5. CMDB 基础数据

[模块 README](./modules/cmdb-group/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 凭据中心 | `/cmdb/credentials` | [介绍](./modules/cmdb-group/features/cmdb-credentials/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-credentials/使用指南.md) | [截图](./images/cmdb-group/cmdb-credentials.png) |
| 机柜管理 | `/cmdb/racks` | [介绍](./modules/cmdb-group/features/cmdb-racks/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-racks/使用指南.md) | [截图](./images/cmdb-group/cmdb-racks.png) |
| 资产目录 | `/cmdb/assets` | [介绍](./modules/cmdb-group/features/cmdb-assets/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-assets/使用指南.md) | [截图](./images/cmdb-group/cmdb-assets.png) |
| 资源检索 | `/cmdb/resources` | [介绍](./modules/cmdb-group/features/cmdb-resources/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-resources/使用指南.md) | [截图](./images/cmdb-group/cmdb-resources.png) |
| 设备骨架 | `/cmdb/devices` | [介绍](./modules/cmdb-group/features/cmdb-devices/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-devices/使用指南.md) | [截图](./images/cmdb-group/cmdb-devices.png) |
| 接口骨架 | `/cmdb/interfaces` | [介绍](./modules/cmdb-group/features/cmdb-interfaces/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-interfaces/使用指南.md) | [截图](./images/cmdb-group/cmdb-interfaces.png) |
| 站点管理 | `/cmdb/sites` | [介绍](./modules/cmdb-group/features/cmdb-sites/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-sites/使用指南.md) | [截图](./images/cmdb-group/cmdb-sites.png) |
| VRF 管理 | `/cmdb/vrfs` | [介绍](./modules/cmdb-group/features/cmdb-vrfs/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-vrfs/使用指南.md) | [截图](./images/cmdb-group/cmdb-vrfs.png) |
| VLAN 管理 | `/cmdb/vlans` | [介绍](./modules/cmdb-group/features/cmdb-vlans/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-vlans/使用指南.md) | [截图](./images/cmdb-group/cmdb-vlans.png) |
| 租户管理 | `/cmdb/tenants` | [介绍](./modules/cmdb-group/features/cmdb-tenants/功能介绍.md) | [指南](./modules/cmdb-group/features/cmdb-tenants/使用指南.md) | [截图](./images/cmdb-group/cmdb-tenants.png) |

## 6. IPAM

[模块 README](./modules/ipam-group/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| Prefix 管理 | `/ipam/prefixes` | [介绍](./modules/ipam-group/features/ipam-prefixes/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-prefixes/使用指南.md) | [截图](./images/ipam-group/ipam-prefixes.png) |
| IP 地址 | `/ipam/ips` | [介绍](./modules/ipam-group/features/ipam-ips/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-ips/使用指南.md) | [截图](./images/ipam-group/ipam-ips.png) |
| 地址池 | `/ipam/pools` | [介绍](./modules/ipam-group/features/ipam-pools/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-pools/使用指南.md) | [截图](./images/ipam-group/ipam-pools.png) |
| VIP 管理 | `/ipam/vips` | [介绍](./modules/ipam-group/features/ipam-vips/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-vips/使用指南.md) | [截图](./images/ipam-group/ipam-vips.png) |
| DHCP 租约 | `/ipam/dhcp` | [介绍](./modules/ipam-group/features/ipam-dhcp/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-dhcp/使用指南.md) | [截图](./images/ipam-group/ipam-dhcp.png) |
| 利用率分析 | `/ipam/utilization` | [介绍](./modules/ipam-group/features/ipam-util/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-util/使用指南.md) | [截图](./images/ipam-group/ipam-util.png) |
| IP 对账中心 | `/ipam/reconciliation` | [介绍](./modules/ipam-group/features/ipam-reconciliation/功能介绍.md) | [指南](./modules/ipam-group/features/ipam-reconciliation/使用指南.md) | [截图](./images/ipam-group/ipam-reconciliation.png) |

## 7. 配置管理

[模块 README](./modules/config-mgmt/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 备份中心 | `/config/backup` | [介绍](./modules/config-mgmt/features/config-backup/功能介绍.md) | [指南](./modules/config-mgmt/features/config-backup/使用指南.md) | [截图](./images/config-mgmt/config-backup.png) |
| 备份计划 | `/config/schedule` | [介绍](./modules/config-mgmt/features/config-schedule/功能介绍.md) | [指南](./modules/config-mgmt/features/config-schedule/使用指南.md) | [截图](./images/config-mgmt/config-schedule.png) |
| 配置对比 | `/config/diff` | [介绍](./modules/config-mgmt/features/config-diff/功能介绍.md) | [指南](./modules/config-mgmt/features/config-diff/使用指南.md) | [截图](./images/config-mgmt/config-diff.png) |
| 配置搜索 | `/config/search` | [介绍](./modules/config-mgmt/features/config-search/功能介绍.md) | [指南](./modules/config-mgmt/features/config-search/使用指南.md) | [截图](./images/config-mgmt/config-search.png) |
| 配置模板 | `/config/templates` | [介绍](./modules/config-mgmt/features/configuration/功能介绍.md) | [指南](./modules/config-mgmt/features/configuration/使用指南.md) | [截图](./images/config-mgmt/configuration.png) |

## 8. 自动化

[模块 README](./modules/automation/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 自动化任务 | `/automation/tasks` | [介绍](./modules/automation/features/auto-exec/功能介绍.md) | [指南](./modules/automation/features/auto-exec/使用指南.md) | [截图](./images/automation/auto-exec.png) |
| 巡检概览 | `/automation/inspections` | [介绍](./modules/automation/features/inspection/功能介绍.md) | [指南](./modules/automation/features/inspection/使用指南.md) | [截图](./images/automation/inspection.png) |
| 巡检记录 | `/automation/records` | [介绍](./modules/automation/features/inspection-records/功能介绍.md) | [指南](./modules/automation/features/inspection-records/使用指南.md) | [截图](./images/automation/inspection-records.png) |
| 执行计划 | `/automation/schedules` | [介绍](./modules/automation/features/exec-schedule/功能介绍.md) | [指南](./modules/automation/features/exec-schedule/使用指南.md) | [截图](./images/automation/exec-schedule.png) |
| 执行历史 | `/automation/history` | [介绍](./modules/automation/features/exec-history/功能介绍.md) | [指南](./modules/automation/features/exec-history/使用指南.md) | [截图](./images/automation/exec-history.png) |
| 定时作业 | `/automation/scheduled-jobs` | [介绍](./modules/automation/features/scheduled-jobs/功能介绍.md) | [指南](./modules/automation/features/scheduled-jobs/使用指南.md) | [截图](./images/automation/scheduled-jobs.png) |
| 巡检指标 | `/automation/metrics` | [介绍](./modules/automation/features/inspection-metrics/功能介绍.md) | [指南](./modules/automation/features/inspection-metrics/使用指南.md) | [截图](./images/automation/inspection-metrics.png) |
| 解析模板 | `/automation/textfsm` | [介绍](./modules/automation/features/textfsm-templates/功能介绍.md) | [指南](./modules/automation/features/textfsm-templates/使用指南.md) | [截图](./images/automation/textfsm-templates.png) |
| 操作管理 | `/automation/scripts` | [介绍](./modules/automation/features/scripts/功能介绍.md) | [指南](./modules/automation/features/scripts/使用指南.md) | [截图](./images/automation/scripts.png) |

## 9. 工单管理

[模块 README](./modules/tickets/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 新建工单 | `/change-orders/new` | [介绍](./modules/tickets/features/new-order/功能介绍.md) | [指南](./modules/tickets/features/new-order/使用指南.md) | [截图](./images/tickets/new-order.png) |
| 个人待办 | `/change-orders/my-todo` | [介绍](./modules/tickets/features/my-todo/功能介绍.md) | [指南](./modules/tickets/features/my-todo/使用指南.md) | [截图](./images/tickets/my-todo.png) |
| 组内待办 | `/change-orders/group-todo` | [介绍](./modules/tickets/features/group-todo/功能介绍.md) | [指南](./modules/tickets/features/group-todo/使用指南.md) | [截图](./images/tickets/group-todo.png) |
| 我参与的 | `/change-orders/participated` | [介绍](./modules/tickets/features/my-participated/功能介绍.md) | [指南](./modules/tickets/features/my-participated/使用指南.md) | [截图](./images/tickets/my-participated.png) |
| 我的关注 | `/change-orders/focus` | [介绍](./modules/tickets/features/my-focus/功能介绍.md) | [指南](./modules/tickets/features/my-focus/使用指南.md) | [截图](./images/tickets/my-focus.png) |
| 全部工单 | `/change-orders/all` | [介绍](./modules/tickets/features/change-orders/功能介绍.md) | [指南](./modules/tickets/features/change-orders/使用指南.md) | [截图](./images/tickets/change-orders.png) |
| 草稿箱 | `/change-orders/drafts` | [介绍](./modules/tickets/features/my-drafts/功能介绍.md) | [指南](./modules/tickets/features/my-drafts/使用指南.md) | [截图](./images/tickets/my-drafts.png) |

## 10. 容量与报表

[模块 README](./modules/capacity/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 容量分析 | `/capacity/analysis` | [介绍](./modules/capacity/features/capacity/功能介绍.md) | [指南](./modules/capacity/features/capacity/使用指南.md) | [截图](./images/capacity/capacity.png) |
| 报表中心 | `/capacity/reports` | [介绍](./modules/capacity/features/reports/功能介绍.md) | [指南](./modules/capacity/features/reports/使用指南.md) | [截图](./images/capacity/reports.png) |

## 11. 平台管理

[模块 README](./modules/management/README.md)

| 子功能 | 路由 | 功能介绍 | 使用指南 | 真实截图 |
| --- | --- | --- | --- | --- |
| 审计日志 | `/management/audit` | [介绍](./modules/management/features/audit/功能介绍.md) | [指南](./modules/management/features/audit/使用指南.md) | [截图](./images/management/audit.png) |
| 用户管理 | `/management/users` | [介绍](./modules/management/features/users/功能介绍.md) | [指南](./modules/management/features/users/使用指南.md) | [截图](./images/management/users.png) |
| 凭据轮换 | `/management/credentials` | [介绍](./modules/management/features/credentials/功能介绍.md) | [指南](./modules/management/features/credentials/使用指南.md) | [截图](./images/management/credentials.png) |

## 维护要求

导航新增、删除、改名或改路由时，必须同步更新模块 README、功能介绍、使用指南、页面截图和浏览器验收记录。截图只能来自真实运行页面，禁止使用静态设计稿或伪造数据代替。
