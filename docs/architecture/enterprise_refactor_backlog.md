# CMDB/IPAM 企业级整改任务看板

> 状态口径：`done` 表示通过任务验收；`in_progress` 表示本轮正在补齐；`pending` 表示尚未开始。每项完成后必须链接对应 walkthrough 和验证证据。

| 编号 | 阶段 | 优先级 | 状态 | 依赖 | 负责人角色 | 数据迁移 | 后端 | 前端 | 测试 | 完成定义 |
|---|---|---:|---|---|---|---:|---:|---:|---:|---|
| ENT-001 | Phase 0 | P0 | done | - | coordinator/data | 否 | 否 | 否 | 文档审查 | 数据关系图和字段权威矩阵可回答核心字段归属 |
| ENT-002 | Phase 0 | P0 | done | ENT-001 | coordinator | 否 | 否 | 否 | 文档审查 | 所有任务包含状态、依赖、角色和完成定义 |
| CMDB-001 | Phase 1 | P0 | done | ENT-001 | backend/data | 否 | 是 | 否 | 架构审查 | CMDB/IPAM/Discovery 三层事实源边界明确 |
| CMDB-002 | Phase 1 | P0 | done | CMDB-001 | backend/data | 是 | 是 | 是 | pytest/lint | 资产设备一对一、接口设备内唯一、IP/拓扑以接口 ID 关联且无孤儿数据 |
| CMDB-003 | Phase 1 | P0 | done | CMDB-001 | backend/data | 是 | 是 | 是 | pytest/lint | tenant/site/VRF/VLAN 复合唯一和引用阻断完整 |
| IPAM-001 | Phase 2 | P0 | done | CMDB-003 | data/backend | 是 | 是 | 是 | migration/pytest | PostgreSQL CIDR/INET、回填、索引和兼容双写完成 |
| IPAM-002 | Phase 2 | P0 | done | IPAM-001 | backend/data | 是 | 是 | 是 | pytest | 重复、父子、兄弟重叠、IPv4/IPv6 与容器状态规则完整 |
| IPAM-003 | Phase 2 | P0 | done | IPAM-001/002 | backend/data/quality | 是 | 是 | 是 | 并发测试 | 原子分配/保留/释放无重复、失败回滚并写审计 |
| IPAM-004 | Phase 2 | P0 | done | IPAM-003 | backend/frontend | 是 | 是 | 是 | pytest/lint | 地址生命周期、隔离期、DHCP/VIP 冲突和 UI 操作完整 |
| REC-001 | Phase 3 | P1 | done | CMDB-001 | network/backend/data | 是 | 是 | 否 | pytest | 统一 observation 可追溯 run、来源、置信度和时间 |
| REC-002 | Phase 3 | P1 | done | REC-001 | backend/data/frontend | 是 | 是 | 是 | pytest/lint | finding/action 状态机和批量处置完成 |
| REC-003 | Phase 3 | P1 | done | REC-002 | backend/security | 是 | 是 | 是 | 权限/审计测试 | Discovery 不静默覆盖权威表，审批写入可追溯 |
| JOB-001 | Phase 4 | P1 | done | SEC-002 | backend/data | 是 | 是 | 是 | pytest | 统一 job/step/target/artifact/event 生命周期、进度和取消 |
| JOB-002 | Phase 4 | P1 | done | JOB-001 | backend/network | 否 | 是 | 是 | 限流测试 | 全局/site/vendor/device 限流、重试、超时和取消有效 |
| SEC-001 | Phase 5 | P1 | done | CMDB-003 | backend/security/frontend | 是 | 是 | 是 | 权限拒绝测试 | resource/scope/action 权限和 tenant/site 范围隔离完成 |
| SEC-002 | Phase 5 | P0 | done | ENT-002 | backend/security/data | 是 | 是 | 是 | 脱敏/审计测试 | 核心动作统一 before/after/request_id 审计且无敏感信息 |
| FE-001 | Phase 6 | P2 | done | CMDB/IPAM API | frontend | 否 | 否 | 是 | lint/build | CMDB/IPAM API client、类型和领域 hooks 统一 |
| FE-002 | Phase 6 | P2 | done | FE-001/REC-002 | frontend/backend | 否 | 是 | 是 | lint/build/smoke | 初始化、分配、对账和资产投产工作流有明确入口 |
| OPS-001 | Phase 7 | P2 | pending | JOB/SEC | backend/release | 否 | 是 | 是 | 集成测试 | request_id 和结构化日志全链路完成 |
| OPS-002 | Phase 7 | P2 | pending | JOB-002 | backend/release | 否 | 是 | 是 | 健康检查 | 平台指标和依赖健康状态可监控 |
| OPS-003 | Phase 7 | P2 | pending | JOB-002 | backend/release | 是 | 是 | 否 | 多实例测试 | API 无状态、调度单 leader、共享 artifact 完成 |
| QA-001 | Phase 8 | P2 | pending | Phase 0-7 | quality | 否 | 否 | 否 | 全量门禁 | 标准测试矩阵和发布门禁固化 |
| QA-002 | Phase 8 | P2 | pending | QA-001 | quality/release | 否 | 否 | 否 | 容量压测 | 达到主计划容量与 p95 指标 |

## 本轮执行边界

本轮连续执行到 Phase 6；Phase 7、Phase 8 保持 `pending`，但会运行与本轮风险相称的现有质量门禁。

## Phase 0–6 完成证据

- 实施计划：`docs/plans/plan_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`
- 完成记录：`docs/walkthrough/walkthrough_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`
- 数据库迁移：`backend/database/migrations/m0008_enterprise_cmdb_ipam_phase0_phase6.py`
- 企业整改回归：`backend/tests/test_enterprise_cmdb_ipam_phase0_phase6.py`
- 全量后端验证：400 passed。
- 前端验证：TypeScript lint 与 Vite production build 通过。
