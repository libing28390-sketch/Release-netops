# DOC-001：Current State、Gap、Target Architecture、Data Model

**Task ID：** DOC-001  
**Milestone：** M2（文档与运营）  
**文档版本：** v1.0  
**盘点日期：** 2026-08-18  
**权威数据库：** PostgreSQL 18；SQLite 不属于验收或生产路径

## 1. 文档边界与结论

本文是 Nexora Knowledge Engine V2 的架构基线文档，回答四个问题：

1. 当前仓库和已验证运行链路是什么（Current State）；
2. 从当前状态到可生产 V2 还缺什么（Gap）；
3. V1 保留、V2 增量演进时的目标运行边界是什么（Target Architecture）；
4. 领域实体、关系、租户、权限、版本和派生索引如何落在 PostgreSQL（Data Model）。

本文不会把 DB-001 的冻结模型、尚未执行的 migration、未完成的 source verification 或未完成的浏览器冒烟写成“已上线”。生产切换当前仍是 **NO-GO**；可继续在开发/测试/预生产执行受控实现和验证。

## 2. Current State（当前状态）

### 2.1 发布与运行基线

| 维度 | 当前可验证状态 | 证据/边界 |
| --- | --- | --- |
| 应用 | 0.1.1；V1 默认服务路径保留 | REL-012 release communication；V2 默认关闭 |
| 数据库 | PostgreSQL 为唯一生产权威；当前迁移启动矩阵 152/152、重复执行无新增 | REL-002/REL-008；SQLite fixture 不作为验收证据 |
| 扩展 | `vector` 0.8.6、`pg_trgm` 1.6 | REL-002、DB-004/DB-016 |
| V1 | Provider、模型路由、知识文档/Chunk、Copilot、诊断和引用回归保持可用 | EVAL-011/013/017/020、V1 PostgreSQL baseline 10/10 |
| V2 | 增量表、契约、feature flag、shadow、reindex、source registry 等实现已在仓库；默认不接管用户答案 | DB/CAT/ING/CHK/RET/MIG/REL evidence |
| V2 生成 | 当前 active V2 generation=0；没有可比的 Shadow 样本 | MIG-015：0/30，不能 cutover |
| 运行时 | 代码使用 Python 3.11 `enum.StrEnum`；Docker 与 CI 已统一到 3.11，Python 3.10 仅由兼容 helper 支持本地工具 | REL-012：目标环境仍需完成镜像启动/健康检查 |
| 外部 AI | 只能经 AI Security Gateway；Provider/model allowlist、密钥引用、Kill Switch 和审计已实现 | LLM/SEC/OBS/REL-009/010 |
| 网络设备 | Copilot/诊断默认为只读；禁止隐式设备写命令 | DIA/COP/SEC contracts |
| 可观测性 | Provider 健康、延迟、错误率、队列、成本和安全事件聚合已接入 Usage dashboard | REL-011；只返回脱敏聚合 |

### 2.2 当前端到端数据流

1. 用户请求进入 FastAPI/API boundary，生成 bounded `request_id`，先执行认证、租户和权限检查。
2. AI Security Gateway 执行 prompt/secret/DLP、模型 allowlist、外发策略和安全审计；拒绝默认 fail-closed。
3. Model/route service 按 scene、租户、角色和 Provider 健康选择 primary/fallback；请求模型不能绕过路由策略。
4. 知识检索仍以 V1 可用路径为用户答案基线；V2 可通过 shadow/feature flag 生成受控比较结果，不能在未过 Gate 时替换 V1。
5. 检索结果必须带 bounded retrieval trace、版本化 citation 和 ACL/来源校验；原文、密钥、完整 prompt 和 SQL 不进入观测聚合。
6. Copilot 只输出结构化建议、证据、风险、验证与回滚步骤；任何设备执行必须独立授权，当前任务不开放隐式写操作。
7. 运行指标写入 PostgreSQL 观测表/既有 AI 控制面，Usage dashboard 只读取脱敏聚合。

### 2.3 已验证能力与未验证能力

**已验证：** PostgreSQL migration fresh/upgrade/rollback 矩阵、Provider/model/ACL/fallback、检索与引用契约、Security Gateway、V1 baseline、V2 kill switch、reindex pause、备份清单、前端 lint/build、自动化发布冒烟。

**尚未验证或不能宣称完成：**

- `MIG-007`：156 条 legacy row 尚无已审核的官方 source registry/version 与 catalog entity，因此 Parse→Chunk→Embed→Index 生产重建保持阻断；
- `MIG-015`：没有 active V2 generation 和 30 条可比 Shadow 样本，不能做差异分析或 cutover；
- `ING-020`、`ING-021`、`REL-013`：自动化 PostgreSQL/静态门禁通过，但可见浏览器登录/页面冒烟需要用户提供已认证浏览器会话；
- 发布镜像运行时已对齐 Python 3.11，目标环境启动/健康检查仍需在发布前复核；
- `EVAL-018` 大样本 trigram P95 超过当前初始目标，发布性能门槛仍关闭；
- 当前文档/培训/运营任务（DOC-002 以后）尚未完成。

## 3. Gap（差距与处理顺序）

| Gap | 影响 | 解除条件 | 当前动作 |
| --- | --- | --- | --- |
| 未验证 source/entity | 禁止自动复制 legacy document/chunk/embedding | 建立 allowlisted source registry、source version、审核 catalog snapshot，并通过 MIG-006/007 | 保持 migration apply guard 关闭 |
| 无 Shadow 样本 | 无法证明 V1/V2 差异和安全回退 | V2 generation ready，累计至少 30 条同 Query 可比样本，MIG-015 通过 | 继续只读 shadow/离线评测 |
| 浏览器未认证 | 无法完成登录、Provider、模型切换、知识、Copilot 可见验证 | 由操作员在本地浏览器完成登录后复跑 REL-013/ING-020/021 | 不读取或猜测密码/API Key |
| Python runtime 漂移 | 目标环境若使用旧镜像可能在 import 阶段失败（`StrEnum`） | 使用已对齐 Python >=3.11 的镜像并完成启动/健康检查 | 旧镜像不得发布 |
| 大规模 trigram 延迟 | 高负载下错误/超时风险 | 按 EVAL-018 优化索引、分区/候选裁剪或调整经批准的 SLO，并重新测量 | 不降低安全和质量阈值 |
| 目标实体未全量物理化 | 目标模型与 V1 adapter 之间仍有映射成本 | 逐项 additive migration、fresh/upgrade/rollback 和 V1 parallel gate | 仅执行已批准、可回滚 migration |
| 文档与培训缺口 | 运维无法按统一流程操作 | DOC-002～010、发布手册、结构化培训反馈完成 | 每项文档独立 Gate/Evidence |

Gap 的优先顺序是：**运行时启动安全 → source/entity 可追溯 → V2 generation/shadow → 性能 → 可见冒烟 → cutover 评审**。任何 Gap 未满足时，保持 V1 默认和 V2 kill switch。

## 4. Target Architecture（目标架构）

### 4.1 分层与信任边界

```text
Browser / CLI
    │ HTTPS + request_id
    ▼
API Boundary ── Auth/RBAC/Tenant Scope ── Audit
    │
    ▼
AI Security Gateway ── DLP/secret/prompt-injection/outbound/model policy
    │                         │
    │                         └── fail-closed security event / incident
    ▼
Route & Provider Control Plane ── primary/fallback/health/kill switch
    │
    ├── V1 answer adapter (default, preserved until cutover Gate)
    └── V2 retrieval pipeline (flagged or shadow only)
             │
             ▼
PostgreSQL authority
  Source Registry → Source Version → Document Version → Chunk Generation
       → Embedding/Index Generation → Retrieval Trace → Citation Validation
             │
             ▼
      Redacted Observability / Evaluation / Rollback controls
```

### 4.2 关键架构原则

- PostgreSQL 是生产唯一权威；所有租户作用域实体显式带 `tenant_id`。
- Source Registry 是来源身份、allowlist、信任和采集策略的权威；`metadata_json` 只能扩展，不能承载身份、ACL 或认证事实。
- 原始文档版本、source manifest、content hash、来源定位是不可变事实；Chunk、Embedding、Index、Shadow 结果都是可重建派生物。
- Product、OS、software version、CLI platform 是正交维度；未知/歧义值显式保留并 fail-closed，不从正文猜测 canonical entity。
- V1/V2 并行：V1 数据和路由不可删除，V2 只能通过 flag、shadow、灰度和可观测回退提升。
- 所有外部 AI 请求必须经过 Gateway；Provider 密钥只保存加密引用，日志/Trace/页面不回显明文。
- 检索与引用在输出前经过 tenant/ACL/source/version/lifecycle 校验；无法验证时拒答或降级为明确的不确定性。
- 设备诊断默认只读；写操作必须有独立审批、命令 allowlist、变更审计和回滚，不由 Copilot 隐式执行。

### 4.3 发布和回退路径

`V2 off → shadow → 内部用户 → Site → 10% → 50% → 100%`。每一步都要求 PostgreSQL 观测、质量/安全阈值、备份和回滚证据。出现错误、泄漏、wrong-vendor、引用失效、成本/延迟超阈值时，先暂停/kill switch，再恢复最近 READY generation；不删除 V1 行、原始事实或审计记录。

## 5. Data Model（PostgreSQL 数据模型）

### 5.1 通用约束

DB-001 冻结的所有租户作用域表至少包含 `id`、`tenant_id`、`created_at`、`updated_at`、`created_by`、`updated_by`、`status`；时间为 UTC `timestamptz`，主键为 UUID，状态使用实体 allowlist 且未知值 fail-closed。`metadata_json` 使用 JSONB 作为扩展，不作为身份、租户、ACL、密钥或权限来源。

### 5.2 领域实体与关系

| 领域 | PostgreSQL 实体 | 关系/责任 | 当前状态 |
| --- | --- | --- | --- |
| Catalog | `kb_vendor`, `kb_product_family`, `kb_product_series`, `kb_product_model`, `kb_product_alias` | Vendor→Family→Series→Model；Alias 仅用于受控解析/冲突裁决 | 目录契约和样本已实现；全量迁移仍受 source/entity Gate 约束 |
| OS/Software | `kb_os_family`, `kb_os_generation`, `kb_release_train`, `kb_software_version` | OS、release train、software version 与产品正交 | 结构已冻结；未知值不推断 |
| Source | `kb_source_registry`, `kb_source_version` | Registry 保存 allowlist/policy；Version 保存 immutable fetch manifest、hash、parser pin | Source Registry/refresh 已实现；MIG-007 仍缺 verified source entities |
| Knowledge | `kb_collection`, `kb_document`, `kb_document_version`, `kb_document_product`, `kb_document_software` | Collection/ACL 定义边界；Document 是稳定身份；Document Version 是原文/规范化内容事实；Applicability 显式关联产品/软件 | DB-009 目标模型；现有 V1 adapter 仍保留 |
| Retrieval | `kb_chunk_version`, `kb_chunk`, `kb_chunk_edge`, `kb_embedding_model`, `kb_chunk_embedding`, `kb_index_version` | Chunk/Edge/Embedding/Index 按 generation 派生，可重建、可切换、可回退 | CHK/RET/DB-010/016 契约已验证；V2 generation=0 |
| Jobs | `kb_import_job`（及现有 import/reindex job projection） | 导入、解析、重建、租约、重试、取消、失败原因和幂等键 | Job controls/observability 已实现；生产 apply 仍受 Gate |
| AI Control Plane | `ai_provider`, `ai_model`, `ai_model_route` | Provider→Model；Route 按 scene/role 指定 primary/fallback，不能绕过 Gateway | 多 Provider/模型切换、密钥引用、ACL/fallback 已验证 |
| Trace/Citation | `ai_request_trace`, `kb_retrieval_log`, `kb_rag_trace`, `kb_citation_validation` | Request→Retrieval→RAG→Citation；每条引用绑定 document version/chunk/hash/ACL 校验 | 目标规范已冻结；部分现有 V1 projection 作为 adapter，不宣称全量物理化 |
| Security/Audit | `ai_security_events`, `ai_security_incidents`, `ai_outbound_audits` | Gateway 决策、阻断、泄漏信号和外发审计；仅存 bounded metadata | 安全审计和脱敏聚合已验证 |
| Rollout/Observability | `ai_retrieval_rollout_flag`, `ai_knowledge_reindex_job`, provider/job/DB metrics projections | Flag 控制 V2 范围；generation/job/health/latency/cost 可观测 | REL/MIG/OBS 已实现，切换仍需 shadow 样本和发布 Gate |

### 5.3 V1 到 V2 兼容映射

| V1 表/概念 | V2 目标映射 | 兼容规则 |
| --- | --- | --- |
| `ai_knowledge_base` | `kb_collection` | 通过 adapter 映射；不直接删除或改写 V1 语义 |
| `ai_document` | `kb_document` + `kb_document_version` | stable identity 与 immutable fact 分离；原文/hash 保留 |
| `ai_document_chunk` | `kb_chunk` + `kb_chunk_embedding` | Chunk/向量属于派生 generation；可重建并保留 V1 回退 |
| `ai_provider` / `ai_model` / `ai_model_route` | 同名控制面增量约束 | 增加租户、secret reference、capability、fallback 和审计，不绕过原路由 |
| `ai_request_log` | `ai_request_trace` 与检索/引用投影 | 只增加 bounded provenance；不写 raw prompt/secret |

### 5.4 数据生命周期和权限

1. Source registry/version、document version 和原始 hash 属于受保护事实，禁止无审计修改/删除；替代、移除和 freshness 变化走 append-only observation/action。
2. 派生 Chunk、Embedding、Index 以 `generation_no` 和状态指针管理；只有已验证 READY generation 可进入主动检索。
3. 所有读写查询带 tenant predicate；collection/document ACL 在检索、引用和详情展示前再次校验。
4. `created_by`/`updated_by` 使用 opaque principal；系统任务明确标记 system actor。Metadata JSON 不得覆盖租户、ACL、身份或 Provider secret。
5. 备份包含 PostgreSQL schema/data、source manifest 和配置版本；回退通过 flag/READY pointer/应用版本恢复，不删除 V1 数据。

## 6. Gate、证据与恢复点

DOC-001 的完成定义是本文、契约 YAML、静态门禁、测试、报告和 Evidence 同时存在，并且内容能区分 Current/Gap/Target/Data Model。本文不替代 MIG-007、MIG-015 或 REL-013 的实证 Gate。

当前恢复点：`DOC-002`。独立阻断仍记录在 `EXECUTION_STATUS.md` 和 `.codex/knowledge-engine-v2-state.json`：MIG-007、MIG-015、ING-020、ING-021、REL-013。下一阶段文档必须引用本文的 PostgreSQL 权威、V1 保留、source-first、tenant/ACL、可回退和无 SQLite 验收原则。

## 7. 参考资料

- `docs/knowledge-engine/architecture/DB-001-core-er-model.yaml`
- `docs/knowledge-engine/architecture/DB-008-SOURCE-REGISTRY-CONTRACT.yaml`
- `docs/knowledge-engine/architecture/DB-009-DOCUMENT-SCOPE-CONTRACT.yaml`
- `docs/knowledge-engine/architecture/DB-010-CHUNK-INDEX-RELATIONSHIPS.yaml`
- `docs/knowledge-engine/architecture/DB-012-TRACE-CITATION-SECURITY-CONTRACT.yaml`
- `docs/knowledge-engine/architecture/AUD-024-gate-decision.yaml`
- `docs/knowledge-engine/architecture/REL-012-RELEASE-COMMUNICATION-CONTRACT.yaml`
- `docs/knowledge-engine/governance/ENVIRONMENT_MATRIX.md`
- `docs/knowledge-engine/EXECUTION_STATUS.md`
