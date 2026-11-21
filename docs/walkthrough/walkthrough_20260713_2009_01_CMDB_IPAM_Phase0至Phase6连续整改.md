# CMDB/IPAM Phase 0 至 Phase 6 连续整改完成记录

## 完成摘要

本轮按企业整改主路线图连续完成 Phase 0 至 Phase 6：

1. 建立统一任务 backlog，并回写各阶段完成状态。
2. 收敛资产、设备、接口关系，增加确定性引用回填、复合唯一校验和数据质量指标。
3. 新增 `m0008` 幂等迁移：PostgreSQL `CIDR/INET`、原生索引、地址冲突唯一防线、生命周期列和企业领域表。
4. 完成 Prefix 状态/重叠规则、IP 原子分配、释放隔离期、DHCP/VIP 冲突和地址生命周期状态机。
5. Discovery 改为只写 observation，不直接覆盖 CMDB；finding 必须经过 action 申请和管理员审批后才能写入权威数据。
6. 建立统一 Job/step/target/artifact/event 模型、数据库目标抢占、设备互斥、site/vendor 限流、重试、取消和后台 Worker 抽象。
7. 建立 resource/scope/action 鉴权和用户资源范围管理接口。
8. 统一审计支持 request_id、before/after、递归敏感字段脱敏。
9. 前端新增 CMDB/IPAM API client、领域类型和 hooks；增加站点初始化、IP分配、对账处置、资产投产入口。
10. 原 IP 删除操作收敛为生命周期 release，不再由前端直接硬删除。

## 实际修改文件

### 文档

- `docs/plans/plan_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`
- `docs/plans/plan_CMDB_IPAM企业级架构整改.md`
- `docs/architecture/enterprise_refactor_backlog.md`
- `docs/walkthrough/walkthrough_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`

### 数据库与后端

- `backend/database/schema.py`
- `backend/database/migrations/m0008_enterprise_cmdb_ipam_phase0_phase6.py`
- `backend/core/rbac.py`
- `backend/services/audit_service.py`
- `backend/services/cmdb_service.py`
- `backend/services/ipam_service.py`
- `backend/services/discovery_service.py`
- `backend/services/normalizers/factory.py`
- `backend/services/reconciliation_service.py`
- `backend/services/job_service.py`
- `backend/services/job_worker.py`
- `backend/services/access_scope_service.py`
- `backend/api/cmdb.py`
- `backend/api/ipam.py`
- `backend/api/discovery.py`
- `backend/api/jobs.py`
- `backend/api/reconciliation.py`
- `backend/api/access_scopes.py`
- `backend/main.py`

### 前端

- `src/api/http.ts`
- `src/api/cmdb.ts`
- `src/api/ipam.ts`
- `src/types/cmdb.ts`
- `src/types/ipam.ts`
- `src/hooks/useCmdbLookups.ts`
- `src/hooks/useIpamPrefixes.ts`
- `src/hooks/useIpamAddresses.ts`
- `src/hooks/useIpamReconciliation.ts`
- `src/pages/IPAMManagementTab.tsx`
- `src/pages/IPVlan/components/EnterpriseWorkflowPanel.tsx`
- `src/pages/IPVlan/IPAddressTab.tsx`
- `src/pages/IPVlan/IPReconciliationTab.tsx`
- `src/pages/IPVlan/index.tsx`

### 测试

- `backend/tests/test_enterprise_cmdb_ipam_phase0_phase6.py`

## 关键实现说明

### CMDB

- `devices.asset_id`、`interfaces(device_id, interface_name)`、VRF租户内名称、VLAN站点内ID均建立唯一防线。
- 数据质量接口新增 VRF/VLAN 重复和 Prefix scope 缺失指标。
- 管理员可调用 `POST /api/cmdb/data-quality/backfill-authority`，只回填能够唯一匹配的 site/interface/topology 引用，不猜测、不删除数据。

### IPAM

- PostgreSQL 将 `prefix_cidr` 转为 `CIDR`、`address_inet` 转为 `INET`；无效历史值保留在 legacy 字段并让规范化列为空，避免删除数据。
- 清洁数据上自动补规范化列 `NOT NULL`；存在脏数据时延后约束并由数据质量流程处理。
- 同 tenant/VRF 下的活动地址建立数据库唯一防线。
- release 后进入24小时隔离期，地址记录保留，可审计且不会立即复用。
- DHCP、VIP、静态地址之间在写入时检测冲突。

### Discovery 与 Reconciliation

- Cisco 使用 `show`，Huawei/H3C 使用 `display`，Juniper/Arista/Ruijie使用明确平台命令；未知平台明确拒绝，不回退 Cisco。
- 原始CLI与规范化事实写入 `discovery_observations`。
- 权威字段差异写入 `reconciliation_findings`。
- `register_ip/update_ip_metadata/release_ip/mark_stale/update_device/upsert_interface` 等动作必须申请、审批、审计后执行。

### Job 与权限

- 批量 Discovery 不再同步阻塞 API，而是创建统一 Job。
- `FOR UPDATE SKIP LOCKED` 用于 PostgreSQL Worker 目标抢占；SQLite保留测试兼容路径。
- 数据库层保证单设备不被多个 Job 同时执行，支持全局、site、vendor 并发限制。
- Viewer只读，Operator按资源动作执行，Administrator全权限；tenant和显式资源 scope 可进一步限制。
- 管理接口：`GET/PUT /api/users/{user_id}/resource-scopes`。

### 前端工作流

- 站点初始化：tenant -> site -> VRF -> VLAN -> Prefix。
- IP分配：选择Prefix -> 自动推荐或指定保留 -> 记录用途和审计。
- 对账处置：生成Run -> 查看finding -> 提交action -> 管理员审批。
- 资产投产：引导进入现有 staging -> 验证 -> managed device -> production 流程。

## 验证命令与结果

### Python语法检查

```powershell
.\.venv\Scripts\python.exe -m py_compile <本轮后端文件>
```

结果：通过。

### 聚焦回归

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_enterprise_cmdb_ipam_phase0_phase6.py backend\tests\test_phase1_phase2_cmdb_ipam.py backend\tests\test_schema_migrations.py -q
```

结果：`15 passed`。

### 后端全量测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

结果：`400 passed, 1 warning`，耗时约4分32秒。warning来自FastAPI TestClient依赖弃用提示，与本轮逻辑无关。

### 前端类型检查

```powershell
npm run lint
```

结果：通过。

### 前端生产构建

```powershell
npm run build
```

结果：通过。保留项目原有 chunk size warning，不影响构建产物。

### Diff检查

```powershell
git diff --check
```

结果：通过，仅有Windows换行提示。

## 未执行验证及原因

1. 未在当前 `.env` 指向的 PostgreSQL 数据库上直接执行 `m0008`：该操作会修改用户现有数据库，质量门禁不应把真实数据当测试环境。迁移已通过SQLite fresh schema、幂等迁移和完整后端测试；上线前仍应在生产副本或临时 PostgreSQL 数据库执行一次升级演练。
2. 未执行真实网络设备 Discovery：需要现场设备和有效凭据；自动测试验证了 Cisco、Huawei、H3C 命令族以及未知平台拒绝回退。
3. 未做 Phase 7/8 的多实例和容量压测；这两阶段按主路线图仍为后续任务。

## 剩余风险与后续建议

1. 历史重复 asset/VRF/VLAN/IP 数据会让对应唯一索引延后创建；应先运行数据质量接口和确定性回填，再人工处理歧义数据。
2. PostgreSQL实库升级前必须备份，并在副本验证 `CIDR/INET` 转换结果、索引时长和锁影响。
3. Worker目前提供统一抽象和后台执行入口；Phase 7 多实例部署时应拆为独立进程并增加leader选举。
4. Phase 7继续完成全链路 request_id、指标、健康检查和无状态化；Phase 8完成容量与并发压测。
