# CMDB/IPAM Phase 0 至 Phase 6 连续整改实施计划

## 执行状态

已完成。完成证据与未执行验证见同编号 walkthrough：

`docs/walkthrough/walkthrough_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`

## 任务目标

按照 `docs/plans/plan_CMDB_IPAM企业级架构整改.md` 的顺序，连续完成 Phase 0 至 Phase 6 尚未闭环的企业级整改任务，使 CMDB、IPAM、Discovery、任务、权限、审计和前端工作流形成可迁移、可审计、可并发验证的统一实现。

本轮覆盖任务：

- `ENT-002`
- `CMDB-002`、`CMDB-003`
- `IPAM-001`、`IPAM-002`、`IPAM-003`、`IPAM-004`
- `REC-001`、`REC-002`、`REC-003`
- `JOB-001`、`JOB-002`
- `SEC-001`、`SEC-002`
- `FE-001`、`FE-002`

## 现状与问题

1. `ENT-001`、`CMDB-001` 已有架构文档和交付记录，但缺少统一整改任务看板。
2. 资产、设备、接口已经形成只读主骨架，仍存在 legacy 字段、接口字符串绑定和历史数据一致性风险。
3. IPAM 已有规范化兼容字段和原子分配接口，但生产字段仍为文本兼容形态，生命周期和冲突域未完整覆盖。
4. Discovery、对账、后台任务、权限和审计已有分散实现，尚未形成统一领域模型和稳定契约。
5. IPAM 前端仍包含页面内直接请求和 CRUD 导向交互，缺少统一 client/hooks 与分配、对账工作流。

## 影响范围

- 数据库：`backend/database/schema.py`、`backend/database/migrations/`
- 后端：`backend/api/`、`backend/services/`、`backend/core/rbac.py`
- 前端：`src/api/`、`src/hooks/`、`src/types/`、`src/pages/IPVlan/` 及 CMDB 相关页面
- 测试：`backend/tests/`
- 文档：`docs/architecture/`、`docs/plans/`、`docs/walkthrough/`

## 拟修改文件

根据调用链核对后，以最小必要集合为准，预计包括：

- `docs/architecture/enterprise_refactor_backlog.md`
- `backend/database/migrations/m0008_cmdb_ipam_phase0_phase6.py`
- `backend/database/schema.py`
- `backend/services/cmdb_service.py`
- `backend/services/ipam_service.py`
- `backend/services/audit_service.py`
- `backend/services/discovery_service.py`
- 新增 reconciliation、job orchestration、authorization 领域服务
- `backend/api/cmdb.py`
- `backend/api/ipam.py`
- `backend/api/discovery.py`
- `backend/api/jobs.py`
- `backend/core/rbac.py`
- `src/api/cmdb.ts`
- `src/api/ipam.ts`
- `src/types/cmdb.ts`
- `src/types/ipam.ts`
- `src/hooks/useCmdbLookups.ts`
- `src/hooks/useIpamPrefixes.ts`
- `src/hooks/useIpamAddresses.ts`
- `src/hooks/useIpamReconciliation.ts`
- `src/pages/IPVlan/` 下相关页面和工作流组件
- `backend/tests/test_enterprise_cmdb_ipam_phase0_phase6.py`

## 实施步骤

1. 建立企业整改 backlog，记录任务状态、优先级、依赖、角色和完成定义。
2. 新增幂等迁移并同步 fresh schema：
   - CMDB 关系审计、唯一索引和兼容回填支撑。
   - PostgreSQL `CIDR/INET` 原生列与索引；SQLite 保留测试兼容。
   - observation、reconciliation、job、audit 标准表。
3. 收敛 CMDB 服务：字段权威审计、关系引用阻断、接口 ID 绑定和历史数据修复入口。
4. 完善 IPAM：prefix 冲突域、生命周期状态机、隔离期、DHCP/VIP 冲突、原子分配和审计。
5. 建立统一审计事件写入/查询契约并接入本轮高风险操作。
6. 建立 Discovery observation -> reconciliation finding -> approval action -> CMDB/IPAM 写入闭环。
7. 建立统一 jobs/job_targets/job_events 模型、并发策略、重试/取消语义和 API。
8. 建立 resource/scope/action 鉴权 helper，并接入本轮写接口。
9. 抽离 CMDB/IPAM 前端 API client、类型和 hooks，补充分配向导与对账处置工作流。
10. 执行聚焦测试、数据库迁移测试、后端全量测试、前端 lint/build，并更新 backlog 和 walkthrough。

## 验证计划

1. 迁移发现、幂等执行和 fresh schema 初始化测试。
2. CMDB 关系约束、删除阻断、孤立引用审计测试。
3. IPv4/IPv6 prefix 冲突、跨 VRF 重用和生命周期状态机测试。
4. PostgreSQL 锁路径与并发分配逻辑测试；无可用 PostgreSQL 实例时记录未执行的实库压测。
5. reconciliation 创建、审批、拒绝、忽略、批量处置和审计测试。
6. job 状态转换、目标计数、取消、重试和并发限制测试。
7. 权限拒绝与 scope 匹配测试。
8. `pytest backend/tests`、`npm run lint`、`npm run build`、`git diff --check`。

## 风险与回滚思路

1. 数据库变更使用新增表、nullable 字段、兼容回填和幂等索引，不在本轮直接删除 legacy 字段。
2. PostgreSQL 原生列先与旧文本列双写；切换查询失败时可回退旧字段。
3. 新 API 保留现有响应字段，前端逐页迁移，避免一次性破坏旧调用方。
4. reconciliation 和 job 新模型先承接新工作流，不强制迁移全部历史执行记录。
5. 权限增强优先复用管理员兼容路径，并为非管理员返回结构化拒绝原因。
6. 若历史脏数据阻止唯一索引创建，迁移记录问题而不删除数据，由数据质量接口给出修复清单。

## 分工边界

本任务由单 Agent 连续执行，不启用并行 Agent。数据库、后端、前端和验证按顺序推进，避免共享文件冲突。
