# NSOT 操作目录与作业预览

## 完成摘要

- Automation 操作管理增加只读 NSOT 采集目录，展示模板、平台 Profile、操作发布号、采集项、Action、CLI 命令与 TextFSM 来源。
- NSOT 作业详情按当前在线目标和有效设备策略生成分组预览，叠加 tenant/site 查看范围。
- 已发布 Action 优先；Quick Ops 操作类别缺少 Action 时，通过精确平台/版本的 TextFSM 模板解析只读回退命令。
- 按单条命令区分 Registry、TextFSM 和兼容目录来源；数据库派生项不再误报为不支持。设备软件版本与 Registry 发布号分别展示。
- 提交同时包含先前实现的 NSOT 单 IP 策略查询、模板批量应用、在线范围调度及其数据库 IP 索引依赖。

## 修改文件

- `backend/api/collection_plans.py`、`backend/api/scheduled_jobs.py`：策略与预览 API。
- `backend/services/nsot_collection_preview_service.py`、`operational_data_service.py`：命令目录、预览及 TextFSM 解析来源。
- `backend/services/collection_plan_service.py`、`interface_collection_service.py`、`ip_locator_service.py`、`scheduler_service.py`：设备模板和调度范围依赖。
- `backend/database/schema.py`、`backend/database/migrations/m0230_devices_ip_lookup_index.py`：IP 查询索引。
- `src/pages/NSOTCollectionOperations.tsx`、`ScriptManagementTab.tsx`、`ScheduledJobs/`：操作目录、批量模板、作业详情与类型契约。
- `src/pages/IPLocatorPage.tsx`：仅提交 NSOT 策略查询和模板相关改动。
- 相关测试位于 `backend/tests/vendor_audit/`、`backend/tests/scheduled_jobs/`、`backend/tests/topology/`、`backend/tests/database/`。

## 关键实现与验证

- 目录和作业预览不连接设备；运行时设备能力、凭据、VRF 和协议发现仍可能改变实际执行结果。
- 已完成聚焦回归：61 passed；最终包含依赖的隔离 PostgreSQL 回归结果在提交修复记录中补充。
- `npm run lint`、隔离目录 `npm run build`、Python 编译和 PostgreSQL-only 检查通过。
- 浏览器已确认 NSOT 目录成功加载平台列表，并返回 Arista Profile 的命令、Action 和 TextFSM 数据；没有执行设备命令或启动作业。
- 启动日志以 `KeyboardInterrupt` 结束；文件热重载发生于编辑期间。独立 `import schemas.schemas` 与 `import main` 均成功，未发现该日志所指的模型导入错误。

## 未验证项与风险

- 未验证真实设备采集成功率；目录是预计命令，不是实际执行审计。
- 作业详情完整浏览器走查尚未完成，API 与范围行为由隔离回归覆盖。
- 本次未部署容器；push 后的 CI/release 结果需以工作流实际结果为准。
- 回滚本次提交可撤销目录和调度策略变更；IP 索引迁移提供自身回滚。
