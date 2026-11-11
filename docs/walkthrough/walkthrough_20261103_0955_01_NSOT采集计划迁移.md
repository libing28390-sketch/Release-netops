# Walkthrough: NSOT 采集迁移

## 完成摘要

- 删除计划作业中的全量 NSOT 新建/编辑入口和定时预览 API；保留 `/assets/nsot` 手动刷新。
- PostgreSQL migration 会软删除精确匹配的系统内置 `NSOT 网络事实库每日采集` 作业，并创建每日 02:00 的独立 ARP 分批系统作业。系统内置 NSOT 行及运行历史仍保留在数据库中。
- BGP 邻居和 OSPF 邻居成为两种独立的只读定时作业。作业使用 SNMP 优先、CLI 回退，不拉取完整 BGP RIB；周期短于 5 分钟会被拒绝，目标范围和执行次数继续受审批授权限制。
- 设备 B-Loop 不再周期采 BGP、OSPF 或 BFD；路由邻居作业使用已采集快照更新事实表和协议告警，避免同一作业重复连接设备。
- 下线 NSOT 模板、设备策略、批量应用和操作目录 API/UI。保留 `/api/collection-plans/bulk-options` 只读接口，因为监控管理页用它填充筛选项；`monitoring_v1` 下的监控计划接口保持独立。
- 旧的用户 NSOT 全量作业记录不由 migration 删除；如果仍启用，它会在下一次调度时先停用并跳过设备采集。

## 实际修改文件

- `backend/database/migrations/m0306_retire_nsot_daily_job.py`
- `backend/services/scheduler_service.py`
- `backend/services/background_monitor_service.py`
- `backend/services/scheduled_job_authorization.py`
- `backend/api/scheduled_jobs.py`
- `backend/api/collection_plans.py`、`backend/api/scheduled_jobs.py`
- `src/pages/ScheduledJobs/`、`src/pages/IPLocatorPage.tsx`、`src/pages/ScriptManagementTab.tsx`
- `src/components/AppMainContent.tsx`、`src/components/AppSidebar/navConfig.ts`、`src/utils/routeContext.ts`

## 验证结果

- `git diff --check`：通过，无空白错误。
- 未运行后端测试、前端测试或构建。
- 当前运行环境未做数据库 migration 或部署。浏览器打开 `http://192.168.56.1:5400/automation/scheduled-jobs` 返回 `net::ERR_CONNECTION_REFUSED`；本机也没有 Docker CLI，无法通过本机容器操作数据库。

## 剩余事项

- migration 需要在应用下一次使用 PostgreSQL 启动时执行。执行前，当前数据库中的系统内置 NSOT 作业仍可能保持启用；源代码变更本身不会即时修改运行数据库。
- BGP/OSPF 作业、ARP 批次大小和任务授权上限尚未在运行环境中验证。
