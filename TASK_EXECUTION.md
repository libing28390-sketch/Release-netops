# Nexora 多 MD 任务执行记录

> 检查点：2026-08-07（Asia/Shanghai）
> 目标：把 `C:\Users\Administrator\Downloads` 下四份整改清单合并为一张可追踪任务表，并持续实施、测试、修复直到验收。

## 当前状态

- 已完整读取全部指定 MD、相关 NetOps 技能规范和仓库规则。
- 已检查 Git 基线：当前分支为 `main`，基线提交为 `18b8a53`；工作区原有未跟踪数据/文档未触碰。
- 已完成第一轮只读代码摸底：AI Platform 已有一批基础实现；告警、PAM、拓扑仍需按清单逐项验证和补齐。
- 本检查点尚未新增业务代码，也尚未运行本次变更的全量测试；下一步从 P0 数据库/后端契约开始。
- 并行审计代理因平台用量限制未返回结果，不作为任务阻塞；由主 Agent 继续完成审计和实施。

## 统一任务清单

状态枚举：`TODO`、`DOING`、`BLOCKED`、`VERIFYING`、`DONE`。

| ID | 优先级 | 状态 | 合并范围（来源） | 依赖 |
|---|---:|---|---|---|
| EXEC-000 | P0 | DONE | 全量读取、去重、Git 基线与技能规范（四份 MD） | — |
| TOPO-001 | P0 | TODO | 资产语义：Role/Function/Site/Zone，取消 Role→固定层级（拓扑 T01-T05） | 资产模型 |
| TOPO-002 | P0 | TODO | Graph Node/Edge、Relation、Evidence、双 Confidence、Unknown、历史字段（拓扑 T06-T11、T37-T40） | TOPO-001，数据库迁移 |
| TOPO-003 | P0 | TODO | LLDP/协议/地址/描述证据归一、Evidence Fusion 与统一 Pipeline（拓扑 T12-T20、T47） | TOPO-002，网络驱动 |
| TOPO-004 | P1 | TODO | Dynamic Rank、Layered Layout、Peer/HA/Stack/Ring/OOB/跨 Site/External/无线/隧道语义（拓扑 T21-T36、T41-T46） | TOPO-003 |
| TOPO-005 | P0/P1 | TODO | 拓扑非标场景回归与多视图验收（拓扑 T48-T63） | TOPO-002~004 |
| ALERT-001 | P0 | TODO | FOR/PENDING、恢复阈值、恢复持续时间、Flapping（告警 T01-T04） | 告警规则/事件模型 |
| ALERT-002 | P0 | TODO | 设备可达性与 ICMP/SNMP/SSH 采集状态解耦、No Data、自监控（告警 T05-T07） | 采集状态/调度 |
| ALERT-003 | P0/P1 | TODO | Dependency Suppression、Correlation、Alert Storm（告警 T08-T10） | TOPO-003，ALERT-001/002 |
| ALERT-004 | P1 | TODO | Incident 模型与自动聚合、Blast Radius、变更关联、规则 RCA（告警 T11-T15） | ALERT-003，TOPO-002 |
| ALERT-005 | P1 | TODO | Maintenance Scope、Silence、Activity、State Machine、Resolve Type、规则版本/审计/Dry Run（告警 T16-T23） | ALERT-001~004 |
| ALERT-006 | P2 | TODO | Incident 工作台、运营 Dashboard、MTTA/MTTR/TopN/压缩率/动态 Severity（告警 T24-T30） | ALERT-004/005 |
| PAM-001 | P0 | TODO | CommandEvent、输入/输出流分离、Assembler、CLI Prompt/Context、Vendor Normalizer、Canonical Action（PAM P0-01~P0-06） | 终端 WebSocket/会话 |
| PAM-002 | P0 | TODO | 多维 Risk Engine、Secret/Input 与 Output DLP、执行状态、实名映射、统一 OperationEvent、Hash Chain（PAM P0-07~P0-15） | PAM-001，RBAC/审计 |
| PAM-003 | P1 | TODO | 执行前 ALLOW/CONFIRM/BLOCK、审批/MFA、Change Transaction、Config Diff、录像时间轴、权限提升、会话干预、二次 SSH、Host Key、Legacy 策略、管理平面保护（PAM P1-01~P1-14） | PAM-002，审批/设备执行 |
| PAM-004 | P2/P3 | TODO | JIT、Break Glass、工单/TACACS 对账、文件传输、批量 Blast Radius、Candidate/Commit/Rollback、延迟动作、行为分析、NETCONF/RESTCONF/SNMP SET、AI 解释/摘要、自动回滚、SIEM（PAM P2/P3） | PAM-003，拓扑/配置 |
| AI-001 | P0 | VERIFYING | AI 基础设施、Provider/Model、密钥加密、Gateway/Router、连接测试、Prompt/Version、日志/Token/Rate Limit、Sanitizer、RBAC、异常与 Fallback、管理 UI（AI-001~020） | 现有 `backend/ai` 与迁移 m0103 |
| AI-002 | P1 | VERIFYING | 命令/配置/Diff/告警分析与 Context Builder/Asset/Alarm/Config/Topology/Monitoring Context（AI-021~030） | AI-001，现有业务服务 |
| AI-003 | P2 | VERIFYING | Assistant、Intent/自然语言查询、IP/MAC 定位、pgvector/知识库/Chunk/Embedding/RAG（AI-031~040） | AI-001/002，IPAM/拓扑 |
| AI-004 | P3 | VERIFYING | Tool Registry/Schema/Risk、READ_ONLY Tools、Agent Runner/Step/故障 Agent/轨迹（AI-041~048） | AI-001~003，PAM-002 |
| AI-005 | P4 | TODO | 配置生成、风险检查、审批、验证/回滚、受控执行（AI-049~054；必须保持 V1 只读红线） | AI-004，PAM-003 |
| CROSS-001 | P0 | DOING | 跨层契约、RBAC、审计、敏感数据、PostgreSQL/SQLite 迁移兼容、异常模型和权限回归 | 全部 P0 |
| CROSS-002 | P0 | TODO | 阶段测试、全量 Backend/Frontend/Integration 回归、构建、迁移验证、文档与最终 Git 检查 | 全部任务 |

## 依赖顺序

```text
数据库迁移/模型
  → 服务与规则引擎
  → API/权限/审计
  → 前端与多视图
  → 聚焦测试
  → 全量回归与发布验收
```

AI 的 V1 只读红线和 PAM 的执行前控制优先于展示层；拓扑 Graph 事实模型优先于布局；告警 RCA 优先使用确定性证据，不以 LLM 替代事实计算。

## 本检查点变更与验证

### 本次写入

- 新增本文件，记录四份 MD 的统一任务、依赖、状态和恢复点。

### 尚未执行

- 业务代码修改：无（本检查点）。
- 数据库迁移：无。
- Backend 测试：待 P0 实施后运行。
- Frontend lint/build：待跨层改动后运行。
- Integration/全量回归：待所有任务完成后运行。

### 已知风险

- 仓库现有 AI Platform 代码已在基线提交中，但需要逐项对照 AI 清单、补充测试并核实安全边界，不能仅凭文件存在标记 DONE。
- 拓扑现有 `topology_links`/`topology_observations` 主要是 LLDP/物理链路模型，前端仍存在按角色分层的布局逻辑；需先扩展 Graph 事实模型再改布局。
- 工作区原有未跟踪文件（数据、压缩包、修复/计划文档）不属于本次检查点，禁止覆盖或纳入提交。

## 下一步

1. 完成告警/PAM/AI/拓扑现有实现的逐文件核对，更新上表状态。
2. 从 TOPO-001/002、ALERT-001、PAM-001/002 的数据库与核心后端 P0 开始实施。
3. 每个任务簇先跑聚焦测试，修复后再进入下一簇，并同步更新本文件。
4. 全部任务完成后运行质量门禁、检查 `git diff/status`，再做最终提交/推送。
