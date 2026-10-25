# Nexora 工单规范改造实施走查

## 当前状态

- M0 基线已完成。
- M1 变更单体验代码、专项测试和本地 mock 浏览器检查已完成；目标运行实例目前拒绝连接，现场验收待部署后补做。
- M2 责任分工、审批快照、执行授权和结果验证闭环已完成，focused PostgreSQL 与前端验证通过。
- M3 故障工单代码与自动化验证已完成；目标实例待部署验收。
- M4 服务申请、目录与 SLA 代码及验证已完成。
- M5 有界周期作业授权、逐次运行账本和紧急变更事后复核代码及自动化验证已完成；目标实例部署、迁移和浏览器验收待补。

## 已交付行为

- 变更表单按“基本信息与范围、实施验证与回退、审核提交”组织；控制表重复字段对齐主表，明确区分人工实施步骤和机器命令。
- 变更列表默认每页 10 条，保留条数选择器；筛选归第一页，记录数缩小时自动修正越界页码。详情显示负责人和下一步动作。
- 责任分工支持指派、接手、转派和事件记录。实施人变更或批准范围变化会使旧授权失效，重新进入审核。
- 技术验证由非实施人记录；配置业务验证时必须由申请人或指定业务确认人通过。完成与回退完成前验证当前审批快照。
- 批准快照覆盖实施人、目标、命令、窗口、模板、控制表及附件 SHA-256。直接执行和关联 Playbook 复核当前身份、MFA、权限、范围、窗口与单次授权。
- 设备操作开始后，控制表附件和普通附件上传都会被拒绝，避免执行范围被后台修改。
- M3 根据源码核查新增真实责任组/成员模型，不复用 `change_groups` 审核角色标签；事件恢复不自动关闭故障工单，并收紧 incident 与变更摘要的访问范围。
- 统一只读列表和 SLA 按来源类型关联；M3 没有跨类型通用主表/事件表，M4 不双写事件账本。服务目录、申请与变更执行继续分离。
- 周期作业的审批快照、范围、工单关联、有效期、次数和目标上限形成不可变授权版本；每次调度按 UTC 计划时间唯一认领，运行结果支持分页查看，未知结果暂停作业并要求人工核实。
- 旧用户作业缺少新授权时停用并标记待重新授权，保留配置与历史；作业软删除不会删除授权和运行账本。
- 授权拒绝和运行异常同时进入新账本及兼容的旧执行历史；失败、部分失败、未知和拒绝结果写入幂等通知 outbox。
- 紧急变更增加结构化原因、独立复核人、复核期限和结果；只有工单完成或已回退并记录结束时间后，指定复核人才能登记结论。

## 修改文件范围

- M1/M2 前端：`src/pages/ChangeOrder/` 下的表单、列表、详情、工作流面板、执行交互、辅助逻辑和测试。
- M2 后端：`backend/api/change_orders/`、`backend/services/change_order_service.py`、`backend/api/automation.py`、`backend/api/playbooks/` 与 focused 授权测试。
- 实施计划及本 walkthrough；《Nexora 工单管理流程规范》保持不变。
- M3 后端：`backend/api/tickets/`、`backend/services/incident_ticket_service.py`、`backend/database/migrations/m0292_incident_tickets.py`、相关 monitoring/change-order/RBAC 入口与测试。
- M3 前端：`src/pages/Tickets/`、`src/App.tsx`、`src/components/AppSidebar/navConfig.ts`、`src/components/MonitoringCenter.tsx`、`src/hooks/usePageTitle.ts` 及测试。
- M4/M5 后端：`backend/database/migrations/m0293_service_requests_sla.py` 至 `m0295_scheduled_job_grants_and_emergency_reviews.py`、工单 ticket API/service、scheduled-job 授权/账本/调度器与 change-order emergency 字段及接口。
- M4/M5 前端：`src/pages/Tickets/`、`src/pages/ScheduledJobs/`、`src/pages/ChangeOrder/` 及相关组件测试。

## 已验证结果

- `npm run test:frontend -- run src/pages/ChangeOrder`：6 个文件、45 项通过。
- `npm run lint`：通过。
- `node node_modules/vite/bin/vite.js build --outDir .codex-build-validation-change-orders-m2-final-20261024`：通过；输出位于任务临时目录。
- 使用隔离 PostgreSQL 数据库 `nexora_pytest_m2root_332c8fdf145d` 运行 `backend/tests/change_orders/test_m2_authorization.py`：15 项通过，包含并发初审只有一次状态转换成功、附件状态保护、责任与验证约束。
- `.venv\\Scripts\\python.exe scripts\\validate_postgresql_only.py`：0 项违规。
- M3 后端：隔离 PG `nexora_pytest_m2root_332c8fdf145d` 上 4 个 focused suites 共 43 项通过；`py_compile` 与 `git diff --check` 通过。
- M3 前端：`npm run test:frontend -- run src/pages/Tickets src/hooks/usePageTitle.test.tsx`，3 个文件、15 项通过；`npm run lint` 通过；Vite 隔离构建通过。
- M4：隔离 PostgreSQL 51 项、前端 29 项通过；`npm run lint`、隔离 Vite 构建及本地 mock 列表检查通过。展开统计区域后仍显示列表和分页，默认每页 10 条。
- M5 后端定时作业专属用例：隔离 PostgreSQL 10 项通过，覆盖有界授权、幂等运行、未知结果核实、授权拒绝历史和软删除拦截。
- M5 合并回归：定时作业及 M2/M5 变更单套件其余 46 项通过；唯一失败为紧急复核测试仍预期“实施中”，代码收紧后实际保留“已完成”。更正该测试断言后重跑紧急复核文件，2 项通过。
- M5 前端：`npm run test:frontend -- run src/pages/ScheduledJobs src/pages/ChangeOrder`，7 个文件、51 项通过；`npm run lint` 通过；事后复核时序、指定复核人和编辑弹窗入口均有测试覆盖。
- 全局增量验证：隔离 Vite 生产构建通过；`.venv\\Scripts\\python.exe scripts\\validate_postgresql_only.py` 报告 0 项违规；受影响 Python 文件 `py_compile` 和 `git diff --check` 通过。
- CUA 检查 `http://127.0.0.1:15400/tickets` 的本地 mock 页面：列表显示 3 条样例，默认 10 条/页，显示负责人和下一步；未连接 `netops` 数据库，也未提交设备或工单操作。
- CUA 本地 mock 浏览器检查了变更列表、详情和新建表单；页面使用 mock 账号和 3 条临时样例，无 `netops` 数据库连接。现场部署与真实设备行为未验证。

## M3 关键实现约束

- 监控 incident 只是来源与恢复证据；工单状态独立保存。
- 创建故障工单按 incident 生命周期幂等；重复或并发创建返回同一工单。
- PG 唯一约束、行锁和事务负责并发状态转换与变更关联。
- 待确认时 incident 复发，会把工单退回处理中并保留事件历史；监控恢复本身不关闭工单。
- 变更摘要按 change-order 权限过滤；incident 可见不自动代表关联变更单可见。
- 新增责任组数据和成员校验；不把设备组或审核角色分类当作支持组。

## 未执行验证与限制

- `http://192.168.56.1:5400` 当前拒绝连接，因此未在用户目标实例验证 UI、迁移、M3–M5 页面、现有数据或服务配置；本次也未部署。
- M1/M2 未向真实设备下发命令；Playbook 和执行行为使用 mock/隔离测试。
- M2/M3 未运行整个后端测试库；按影响范围执行了 focused PostgreSQL 用例。未进行部署验证或真实设备操作。
- M2–M5 persistence tests 使用隔离 PostgreSQL fixture，未连接业务 `netops` 库或真实设备；M5 迁移的现场升级路径仍待部署窗口验证。
- 临时构建目录将在本次交付前清理；既有用户构建目录、日志和其他工作树改动保留。

## 下一步

M0–M5 的工作区实现与自动化验证已完成。下一步是目标环境恢复后执行数据库迁移、浏览器验收和部署验证；当前未对目标环境或真实设备作任何操作。

## 工单全量回归与开发环境关机（2026-10-25）

- 后端完整工单域回归：91 passed、0 failed、0 skipped，覆盖变更单、故障工单、服务申请/SLA、定时授权/运行账本、监控事件及 incident-变更关联。测试使用隔离 PostgreSQL；运行结束确认没有 `nexora_pytest_*` 测试库和活动测试连接。
- 前端工单域回归：19 个测试文件、103 项通过，覆盖 Tickets、ChangeOrder、ScheduledJobs、监控关联、执行历史、审批编辑和 Escape 关闭。
- `npm run lint`、隔离 Vite build（4344 模块）、PostgreSQL-only 扫描（0 violations）、Python 编译和 `git diff --check` 通过。
- 用户目标页面无法现场打开：CUA 返回 `ERR_CONNECTION_REFUSED`，宿主 5400 端口未监听。未创建现场工单、未部署代码、未运行设备命令。
- 所有测试完成后，仅对已确认的 `I:\\NetDevOps\\Ubuntu 64 位.vmx` 执行关机。VMware Tools RPC 超时，soft stop 未完成；随后 hard stop 成功。复核 `vmrun list` 只剩 `I:\\ubuntu_vm2\\Ubuntu 64 位.vmx`，Windows 宿主及另一 VM 保持运行。
