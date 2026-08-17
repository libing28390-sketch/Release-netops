# Nexora Knowledge Engine V2 终极开发任务清单

> 版本：1.0  
> 日期：2026-08-09  
> 状态：待架构确认后执行  
> 适用范围：Nexora Knowledge Engine V2、AI Copilot、多供应商与多模型、安全网关、网络诊断、迁移、发布与运维  
> 核心策略：V1 保持可运行，V2 并行建设，影子检索验证，功能开关切换，可随时回滚。

---

## 1. 使用说明

### 1.1 优先级

- `P0`：架构或上线阻断项，未完成不得进入下一里程碑。
- `P1`：首个生产可用版本必须完成。
- `P2`：规模化、自动化和体验增强项。
- `P3`：长期演进项，不阻断首版上线。

### 1.2 角色

- `ARCH`：架构负责人。
- `BE`：后端工程师。
- `FE`：前端工程师。
- `AI`：RAG/LLM 工程师。
- `DBA`：数据库工程师。
- `NET`：资深网络工程师/领域专家。
- `SEC`：安全工程师。
- `QA`：测试工程师。
- `OPS`：发布与运维工程师。
- `PM`：产品负责人。

### 1.3 规模

- `XS`：不超过 0.5 人日。
- `S`：约 1 人日。
- `M`：约 2～3 人日。
- `L`：约 4～5 人日。
- `XL`：必须继续拆分后再进入迭代。

### 1.4 单项任务完成定义

每个任务只有同时满足以下条件才能勾选：

- 有明确实现或文档交付物；
- 有成功、非法输入、权限拒绝、空数据和依赖失败测试；
- 数据库变更包含新装、升级、回填、索引和恢复验证；
- 前端覆盖加载、空状态、错误、权限拒绝和窄屏状态；
- 不记录或返回密码、API Key、SNMP Community、私钥及原始敏感数据；
- API 契约同步到前端类型；
- 通过相关后端测试、`npm run lint` 和 `npm run build`；
- 有监控、审计和回滚办法；
- 未降低现有 V1 可用性。

### 1.5 单项任务即时验证硬门槛（强制）

为避免多个任务叠加后才发现问题，所有任务必须采用“完成一项、验证一项、再进入下一项”的闭环。该规则是执行要求，不是建议：

1. 开始任务前，重新读取本文件中该任务的原始定义、优先级、依赖、验收条件和退出标准，并将状态记录为 `ANALYZING`。
2. 进入 `IMPLEMENTING` 后，只修改该任务及其必要的关联文件；不得用未验证的后续任务修改掩盖当前任务缺陷。
3. 实现完成后，立即进入 `TESTING`，执行该任务的最小成功路径、非法输入、权限拒绝、空数据和依赖失败测试；适用的异常路径不得延期到 Milestone Gate。
4. 按任务影响范围立即完成真实边界验证：
   - 后端/API：API 契约、响应结构、认证授权、租户隔离和错误码；
   - 数据库：新装、升级、幂等、约束、索引、事务回滚和恢复；
   - 前端：路由、真实交互、加载/空/错误/权限状态及窄屏布局；
   - 安全/外部访问：allowlist、SSRF、重定向、脱敏、审计和无密钥泄漏。
5. 进入 `VERIFYING` 后，检查 V1 兼容性、文档、监控、审计和回滚方式，并保存该任务唯一对应的 Evidence。Evidence 至少包含执行命令、关键输出、修改文件、测试结果、数据库影响、安全影响、回滚方式和已知限制。
6. 只有实现、测试、边界验证、Evidence 和质量检查全部通过，才允许将状态改为 `DONE`、把原任务 `[ ]` 改为 `[x]`，并选择下一个依赖满足的任务。
7. 任一检查失败时，任务必须保持 `[ ]`，状态改为 `FAILED` 或 `BLOCKED`，记录根因、已尝试方法和解除条件；修复后必须重新执行本任务的完整验证闭环。不得以“主要功能完成”“代码已经写完”或“后续统一测试”代替验收。
8. `npm run lint`、`npm run build`、全量回归或 Milestone Gate 只能作为补充，不能替代本任务完成后的即时验证；不得把多个未验证任务批量标记为完成。
9. 自动化验证通过后，必须向用户提交该 Task 的验证入口、操作步骤、预期结果、实测结果和 Evidence 摘要。涉及前端、API、Provider、模型切换、运行时行为或数据展示的任务，必须等待用户完成一次可见验证并明确确认；确认前状态保持 `VERIFYING`（或 `USER_VERIFY_PENDING`），原任务保持 `[ ]`，不得开始下一个任务。

---

## 2. 不可变架构决策

- [x] `ADR-001` `P0/ARCH/S`：确认采用 V1/V2 并行方案，禁止在未验证前替换生产检索。
- [x] `ADR-002` `P0/ARCH/S`：确认 PostgreSQL 为权威数据库，首版采用关系字段 + JSONB + FTS + pg_trgm + pgvector。
- [x] `ADR-003` `P0/ARCH/S`：确认 Product、OS、Software Version 正交建模。
- [x] `ADR-004` `P0/ARCH/S`：确认 Document/Document Version 是事实源，Chunk/Embedding/Index 是可重建衍生数据。
- [x] `ADR-005` `P0/ARCH/S`：确认官方知识与企业知识使用独立检索域、权限和数据分类。
- [x] `ADR-006` `P0/ARCH/S`：确认所有外部 LLM 与 Embedding 调用必须经过 AI Security Gateway 和 LLM Gateway。
- [x] `ADR-007` `P0/ARCH/S`：确认普通 AI 咨询默认只读，不允许隐式执行设备命令。
- [x] `ADR-008` `P0/ARCH/S`：确认所有写配置动作必须进入变更审批、差异预览、回滚和验证流程。
- [x] `ADR-009` `P0/ARCH/S`：确认 Exact/Alias/Prefix 优先于 Fuzzy/FTS/Vector。
- [x] `ADR-010` `P0/ARCH/S`：确认型号、厂商、OS 或版本存在高风险歧义时必须追问，不得静默选择。
- [x] `ADR-011` `P0/ARCH/S`：确认多供应商、多模型为正式能力；管理员配置可用范围，工程师在授权范围内自由切换。
- [x] `ADR-012` `P0/ARCH/S`：确认每条 AI 回答必须记录实际供应商、模型、模型版本、路由原因和故障转移过程。

**退出标准**：上述 ADR 全部评审通过并存档，后续任务不得通过临时 Prompt 绕过这些原则。

---

## 3. 项目治理与研发准备

- [x] `GOV-001` `P0/PM+ARCH/S`：指定产品、架构、AI、网络、安全、测试和发布负责人。
- [x] `GOV-002` `P0/PM/S`：建立 RACI，明确模型、知识、网络命令和生产切换的最终审批人。
- [x] `GOV-003` `P0/PM/S`：建立 Epic、Story、Bug、Risk、ADR、Release 六类工作项模板。
- [x] `GOV-004` `P0/ARCH/S`：定义 V2 分支、功能开关、数据库迁移和版本号策略。
- [x] `GOV-005` `P0/OPS/S`：准备独立开发、测试、影子和预生产环境。
- [x] `GOV-006` `P0/SEC/S`：确认测试环境不得使用生产 API Key、真实密码和未脱敏配置。
- [x] `GOV-007` `P0/QA/M`：建立固定回归清单和发布证据模板。
- [x] `GOV-008` `P0/NET/M`：确定首批 Huawei CE6800 与 Cisco Catalyst 9300 范围及版本样本。
- [x] `GOV-009` `P0/PM+NET/M`：定义咨询、故障诊断、配置生成、知识检索四类核心用户旅程。
- [x] `GOV-010` `P0/PM/S`：冻结 PoC 范围；H3C、Ruijie 全量接入不进入首批关键路径。
- [x] `GOV-011` `P1/PM/S`：建立每周风险评审与指标评审机制。
- [x] `GOV-012` `P1/ARCH/S`：规定任何跨层变更必须同时评审 API、数据库、前端、权限、日志和回滚。

**退出标准**：人员、环境、首批范围、迭代节奏和升级流程明确。

---

## 4. P0 当前状态审计

### 4.1 数据与代码审计

- [x] `AUD-001` `P0/BE+ARCH/M`：绘制现有 AI 请求从前端、API、Assistant Service、RAG、Gateway 到 Provider 的调用图。
- [x] `AUD-002` `P0/BE/M`：列出所有 `/api/ai` 与 `/api/v1/ai` 端点、调用方、权限码和响应契约。
- [x] `AUD-003` `P0/DBA+BE/M`：审计 `ai_provider`、`ai_model`、`ai_model_route`、`ai_document`、`ai_document_chunk`、`ai_conversations` 等现有表。
- [x] `AUD-004` `P0/DBA/M`：核对 fresh schema 与 m0103～m0114 迁移的一致性和执行顺序。
- [x] `AUD-005` `P0/DBA/M`：统计现有文档、Chunk、Embedding、孤儿记录、重复记录和空 Metadata。
- [x] `AUD-006` `P0/AI+NET/L`：随机抽样现有 Chunk，评估标题、CLI、表格、警告、版本信息是否丢失。
- [x] `AUD-007` `P0/AI/M`：确认当前 Embedding Provider、维度、模型版本、归一化与相似度算法。
- [x] `AUD-008` `P0/AI+DBA/M`：确认当前 Vector 查询是否实际使用 pgvector，记录 SQLite/本地兼容分支。
- [x] `AUD-009` `P0/AI/M`：确认当前 FTS、pg_trgm、Alias、Metadata Filter、Reranker 的实际完成度。
- [x] `AUD-010` `P0/BE/M`：审计文档 Create/Update/Delete/Reindex 是否产生孤儿 Chunk 或 Vector。
- [x] `AUD-011` `P0/BE/M`：审计会话持久化、上下文截断、租户隔离和消息引用保存。
- [x] `AUD-012` `P0/FE/M`：核对 Copilot 模型、推理强度、速度控件是否真正进入请求。
- [x] `AUD-013` `P0/FE+BE/M`：核对引用条目的文档打开、URL、版本和章节定位是否可用。
- [x] `AUD-014` `P0/FE/M`：审计 Provider、Model、Prompt、Agent、Knowledge、Security 的角色可见性。

### 4.2 外发与安全审计

- [x] `AUD-015` `P0/SEC+BE/L`：扫描 `openai`、`deepseek`、`httpx`、`requests`、Provider SDK、Embedding URL 和代理调用。
- [x] `AUD-016` `P0/SEC/M`：输出所有外部 AI 数据出口及调用数据类型。
- [x] `AUD-017` `P0/SEC/M`：验证 Provider 连接测试是否也经过 Security Gateway。
- [x] `AUD-018` `P0/SEC/M`：审计 API Key 加密、主密钥来源、轮换、掩码和错误日志。
- [x] `AUD-019` `P0/SEC+DBA/M`：审计检索 Trace、会话和审计日志是否可能保存密钥、配置或用户标识。
- [x] `AUD-020` `P0/SEC/M`：审计 Prompt Injection、隐藏 HTML、恶意附件与知识污染防护。

### 4.3 基线与结论

- [x] `AUD-021` `P0/QA+AI+NET/L`：建立 V1 基线评测，记录准确率、错误厂商率、版本冲突率、引用准确率与延迟。
- [x] `AUD-022` `P0/ARCH/M`：形成 KEEP/REFACTOR/REPLACE/REMOVE 决策表。
- [x] `AUD-023` `P0/DBA+AI/M`：形成原文档、Metadata、Chunk、Embedding 的迁移可信度分级。
- [x] `AUD-024` `P0/ARCH+PM/M`：形成正式 GO/CONDITIONAL GO/NO-GO 审计结论。

**退出标准**：现有实现不可再标记为“未知”；所有后续任务都有实际差距依据。

---

## 5. 数据库与迁移基础

- [x] `DB-001` `P0/DBA+ARCH/M`：冻结 V2 核心 ER 模型和字段命名规范。
- [x] `DB-002` `P0/DBA/M`：统一 UUID、tenant_id、created_at、updated_at、created_by、status 字段语义。
- [x] `DB-003` `P0/DBA/M`：定义软删除、禁用、归档、净化删除四种生命周期行为。
- [x] `DB-004` `P0/DBA/S`：验证 PostgreSQL `vector`、`pg_trgm` 和必要扩展的安装检查与错误提示。
- [x] `DB-005` `P0/DBA/M`：建立 `kb_vendors` 或确认复用现有厂商注册表的映射边界。
- [x] `DB-006` `P0/DBA/L`：建立/改造 Product Family、Series、Model、Alias 数据结构。
- [x] `DB-007` `P0/DBA/L`：建立/改造 OS Family、Generation、Release Train、Software Version 数据结构。
- [x] `DB-008` `P0/DBA/L`：建立 Source Registry、来源版本、采集策略和允许域名结构。
- [x] `DB-009` `P0/DBA/L`：建立 Document、Document Version、Document Scope、适用产品/版本关联。
- [x] `DB-010` `P0/DBA/M`：建立 Chunk Version、Parent/Child、Neighbor、Chunk Role 和 Index Version 关系。
- [x] `DB-011` `P0/DBA/M`：建立 Import Job、阶段状态、重试、取消、错误和进度字段。
- [x] `DB-012` `P0/DBA/M`：建立 Retrieval Log、RAG Trace、Citation Validation 和 Security Audit 结构。
- [x] `DB-013` `P0/DBA/M`：建立 Collection 与 Collection Document 引用关系，不修改 canonical Metadata。
- [x] `DB-014` `P0/DBA/M`：定义关系字段与 JSONB 边界；高频过滤、唯一性和权限字段禁止只放 JSONB。
- [x] `DB-015` `P0/DBA/M`：为 Exact、Alias、Prefix、tenant、status、vendor、product、version 查询设计索引。
- [x] `DB-016` `P0/DBA/M`：为 FTS、pg_trgm、JSONB 和 pgvector 建立经 EXPLAIN 验证的索引。
- [x] `DB-017` `P0/DBA/S`：规定所有新增字段先可空、回填、验证、再加约束的迁移顺序。
- [x] `DB-018` `P0/DBA+BE/M`：编写幂等迁移与 fresh schema 同步任务。
- [x] `DB-019` `P0/DBA+QA/M`：测试从当前最高迁移版本升级到 V2。
- [x] `DB-020` `P0/DBA+QA/M`：测试 fresh install、重复执行、部分失败恢复和事务回滚。
- [x] `DB-021` `P1/DBA/M`：建立数据一致性巡检查询和定期孤儿检测。
- [x] `DB-022` `P1/DBA/M`：为大规模 Reindex 设计批次、锁、租约和并发保护。
- [x] `DB-023` `P1/DBA+OPS/M`：建立数据库备份、Source Manifest 导出与恢复演练。
- [x] `DB-024` `P2/DBA/M`：评估 10k 文档、100k Chunk、1m Chunk 的表膨胀和索引上限。

**退出标准**：V2 表可独立部署且不影响 V1；升级、新装和回滚均经过测试。

---

## 6. 官方来源与产品目录治理

- [x] `CAT-001` `P0/NET+AI/M`：定义 Huawei、Cisco 首批官方来源 allowlist。
- [x] `CAT-002` `P0/NET+AI/M`：定义官方 URL、产品页、配置指南、命令参考、版本说明的来源类型。
- [x] `CAT-003` `P0/BE/M`：实现 Source Registry CRUD、启用、禁用、验证和版本记录。
- [x] `CAT-004` `P0/BE+SEC/M`：限制采集只能访问允许域名、协议和安全重定向目标。
- [x] `CAT-005` `P0/NET+AI/L`：建立 Huawei CloudEngine/CE6800 产品层级样本。
- [x] `CAT-006` `P0/NET+AI/L`：建立 Cisco Catalyst/C9300 产品层级样本。
- [x] `CAT-007` `P0/NET+AI/M`：建立 Huawei VRP Family/Generation/Version 样本及 UNKNOWN 规则。
- [x] `CAT-008` `P0/NET+AI/M`：建立 Cisco IOS/IOS XE/NX-OS/IOS XR 分界与 C9300 适用关系。
- [x] `CAT-009` `P0/AI+BE/M`：实现 Alias Exact、Canonical、Prefix、Trigram 和冲突字段。
- [x] `CAT-010` `P0/AI+NET/M`：建立 `CE68`、`CE688`、`CE6885`、`C9300`、`Catalyst93` 等样本。
- [x] `CAT-011` `P0/BE/M`：实现 Alias 冲突检测、候选列表和人工裁决状态。
- [x] `CAT-012` `P0/NET/M`：定义型号歧义时可安全使用系列知识与必须追问的边界。
- [x] `CAT-013` `P1/FE+BE/M`：实现 Product Catalog 与 Alias 管理界面。
- [x] `CAT-014` `P1/FE/M`：实现产品按 Vendor/Family/Series/Model 浏览和版本筛选。
- [x] `CAT-015` `P1/BE+QA/M`：支持 Product Catalog 版本导入、差异预览和回滚。
- [x] `CAT-016` `P2/NET+AI/L`：补充 H3C Comware 产品与版本模型。
- [x] `CAT-017` `P2/NET+AI/L`：补充 Ruijie 产品与 OS 模型。
- [x] `CAT-018` `P2/BE/M`：建立官方目录只读保护与自定义 Collection 分离。

**退出标准**：首批型号能够唯一识别或明确返回歧义，不依赖模型猜测厂商。

---

## 7. 统一采集与导入流水线

- [x] `ING-001` `P0/ARCH+BE/M`：定义单一 Ingestion Pipeline 状态机和错误分类。
- [x] `ING-002` `P0/BE/M`：实现单官方 URL 导入任务。
- [x] `ING-003` `P0/BE+SEC/M`：实现 URL 安全校验、SSRF 防护、重定向检查和大小限制。
- [x] `ING-004` `P0/BE/M`：实现本地官方文件导入，并强制保存来源证明。
- [x] `ING-005` `P0/BE/M`：实现企业 SOP 本地文件导入，默认分类为 INTERNAL。
- [x] `ING-006` `P0/BE+AI/L`：统一 HTML、Markdown、TXT、PDF 解析适配器接口。
- [x] `ING-007` `P0/BE+AI/M`：清除脚本、隐藏文本、导航、页脚、广告和非正文区域。
- [x] `ING-008` `P0/AI+SEC/M`：检测 Prompt Injection 和知识污染特征并隔离文档。
- [x] `ING-009` `P0/BE/M`：保存原始 Source、内容哈希、HTTP 元数据、采集时间和解析器版本。
- [x] `ING-010` `P0/BE+AI/M`：实现 Metadata 提取、规范化、验证和 UNKNOWN 处理。
- [x] `ING-011` `P0/BE+AI/M`：实现 Product/OS/Version Entity Resolution。
- [x] `ING-012` `P0/BE/M`：实现 URL 相同内容相同的幂等处理。
- [x] `ING-013` `P0/BE/M`：实现 URL 相同内容变化的新 Document Version。
- [x] `ING-014` `P0/BE/M`：实现不同 URL 相同内容的去重与来源合并策略。
- [x] `ING-015` `P0/BE/M`：实现 Published、Draft、Quarantined、Superseded、Disabled 生命周期。
- [x] `ING-016` `P0/BE/M`：实现任务进度、取消、重试、失败阶段和错误详情。
- [x] `ING-017` `P0/BE+DBA/M`：实现 Import Job 租约与重复 Worker 防护。
- [x] `ING-018` `P1/BE+OPS/M`：实现 ETag、Last-Modified、Content Hash 定期刷新。
- [x] `ING-019` `P1/BE/M`：实现官方文档移除、替代和版本更新检测。
- [ ] `ING-020` `P1/FE/M`：实现导入任务列表、过滤、分页、阶段进度和错误重试。
- [ ] `ING-021` `P1/FE+BE/M`：实现导入前 Metadata 预览与人工确认。
- [x] `ING-022` `P2/BE+SEC/L`：实现官方 Seed URL 小规模批量采集与速率限制。
- [x] `ING-023` `P2/BE+OPS/M`：实现采集并发、退避、robots/服务条款记录和站点异常告警。
- [x] `ING-024` `P2/QA/L`：建立恶意 HTML、超大文件、损坏 PDF、重定向循环和重复内容测试。

**退出标准**：Source 到 Published Document 可重复、可追踪、可重试、可隔离。

---

## 8. Chunking V2 与 Embedding

- [x] `CHK-001` `P0/AI+NET/M`：定义网络知识结构块：标题、段落、CLI、输出、表格、警告、前提、示例。
- [x] `CHK-002` `P0/AI/M`：审计并补齐现有 ChunkingEngine 的配置与边界。
- [x] `CHK-003` `P0/AI/M`：保证单条命令、参数、输出和解释不被错误拆分。
- [x] `CHK-004` `P0/AI/M`：实现 Parent/Child Chunk 与 Neighbor 关系。
- [x] `CHK-005` `P0/AI/M`：实现 Chunk Role、Section Path、Page、Token Count、Content Hash。
- [x] `CHK-006` `P0/AI+NET/M`：验证 Huawei/Cisco CLI、表格和警告样本的结构完整性。
- [x] `CHK-007` `P0/AI/M`：实现超大 Chunk、过小 Chunk、空 Chunk 和重复 Chunk 校验。
- [x] `CHK-008` `P0/AI+BE/M`：记录 chunker_version、parser_version、document_version 和 index_version。
- [x] `CHK-009` `P0/AI+BE/M`：实现 Embedding Provider 抽象，区分本地与外部 Provider。
- [x] `CHK-010` `P0/AI+SEC/M`：外部 Embedding 前执行分类、最小化、DLP 和审计。
- [x] `CHK-011` `P0/AI+DBA/M`：验证 Embedding 维度与 pgvector 列兼容性，拒绝静默混用。
- [x] `CHK-012` `P0/AI+BE/M`：实现批量 Embedding、失败重试、幂等和限速。
- [x] `CHK-013` `P1/AI+BE/M`：实现 Document 修改后的精确 Rechunk/Reembed/Reindex。
- [x] `CHK-014` `P1/AI+BE/M`：实现双 Index、Shadow Index、切换和回滚。
- [x] `CHK-015` `P1/FE/M`：实现 Chunk 查看器，支持 Parent、Neighbor、Metadata 和来源定位。
- [x] `CHK-016` `P2/AI+QA/L`：建立不同 Chunk 配置的离线对比实验。

**退出标准**：任何 Chunk 都能追溯并重建；CLI 与版本前提没有被切断。

---

## 9. Query Understanding 与混合检索

- [x] `RET-001` `P0/AI+NET/M`：定义 Query Normalizer 输入输出契约。
- [x] `RET-002` `P0/AI/M`：解析 vendor、product、model、os_family、generation、version、topic、command、error、intent。
- [x] `RET-003` `P0/AI/M`：未出现的实体保持 null，不允许模型补造。
- [x] `RET-004` `P0/AI+BE/M`：将 Product Resolver 接入所有知识检索入口。
- [x] `RET-005` `P0/AI/M`：实现 Exact Product/Model Match。
- [x] `RET-006` `P0/AI/M`：实现 Canonical Alias Match。
- [x] `RET-007` `P0/AI/M`：实现 Prefix 与 Product Hierarchy Match。
- [x] `RET-008` `P0/AI+DBA/M`：实现 pg_trgm Fuzzy Match 与阈值配置。
- [x] `RET-009` `P0/AI+DBA/M`：实现 PostgreSQL FTS，优化命令、错误字符串和关键词。
- [x] `RET-010` `P0/AI+DBA/M`：实现 pgvector Semantic Retrieval。
- [x] `RET-011` `P0/AI/M`：实现 Metadata Filter，至少覆盖租户、知识域、厂商、产品、OS、版本、状态和权限。
- [x] `RET-012` `P0/AI/M`：实现 Lexical、Vector、Metadata、Trust、Version 的融合评分。
- [x] `RET-013` `P0/AI/M`：实现 Reranker 接口、超时、降级和成本限制。
- [x] `RET-014` `P0/AI+NET/M`：实现版本兼容性校验和冲突证据说明。
- [x] `RET-015` `P0/AI/M`：实现 Ambiguous Match 返回候选，不进入高风险回答。
- [x] `RET-016` `P0/AI/M`：实现 No Match，禁止使用模型记忆伪装成本地资料。
- [x] `RET-017` `P0/AI+BE/M`：实现 Parent/Neighbor Context Builder 与最小上下文限制。
- [x] `RET-018` `P0/AI+DBA/M`：实现按 document_version、metadata_version、index_version、access_scope 的缓存键。
- [x] `RET-019` `P0/AI+BE/M`：实现文档禁用、更新和权限变化后的精确缓存失效。
- [x] `RET-020` `P1/AI+BE/M`：实现检索解释对象，供工程师证据面板使用。
- [x] `RET-021` `P1/FE+BE/M`：实现管理员检索测试页，可显示解析实体、过滤条件、候选和最终 Chunk。
- [x] `RET-022` `P1/AI+QA/L`：为 10k/100k/1m 规模完成检索与索引 Benchmark。

**退出标准**：CE68/CE688/Catalyst93 等真实写法可正确识别；错误厂商和版本不被静默混用。

**RET 验收环境强制规则**：RET-008 至 RET-022 的数据库、索引、检索、租户/权限和性能证据必须以真实 PostgreSQL 为准；必须验证 `vector` 与 `pg_trgm` 扩展、事务回滚和必要的 EXPLAIN 计划。本项目不使用 SQLite；历史 SQLite 兼容夹具不属于本测试方案，不能替代 PostgreSQL 通过，也不能作为 RET 任务完成证据。详见 `docs/knowledge-engine-v2/architecture/RET-008-022-POSTGRES-TEST-PLAN.yaml`。

---

## 10. Grounding、引用与回答合同

- [x] `CIT-001` `P0/AI+BE/M`：定义 Citation 数据合同：vendor、product、OS、software version、document、version、URL、section、chunk。
- [x] `CIT-002` `P0/AI+BE/M`：实现关键结论与引用的映射，不只返回来源数量。
- [x] `CIT-003` `P0/AI/M`：实现 Citation Validator，校验 allowlist、版本、Published 状态和 URL。
- [x] `CIT-004` `P0/AI/M`：实现无足够证据时的标准拒答和补充信息提示。
- [x] `CIT-005` `P0/AI+NET/M`：定义事实、推断、建议、命令四种回答标记。
- [x] `CIT-006` `P0/AI+NET/M`：定义网络故障回答结构：判断、事实、缺口、假设、下一步、风险、修复、验证。
- [x] `CIT-007` `P1/FE/M`：实现可点击来源卡片和文档章节定位。
- [x] `CIT-008` `P1/FE/M`：展示来源类型、适用型号、OS、版本和更新时间。
- [x] `CIT-009` `P1/FE/M`：在引用不完整、版本冲突和知识过期时显示明确警告。
- [x] `CIT-010` `P1/QA+NET/L`：建立逐结论引用准确率人工评测。

**退出标准**：工程师能从每个关键结论回到正确官方文档和适用版本。

---

## 11. 多 AI 供应商、多模型与自由切换

### 11.1 数据与供应商管理

- [x] `LLM-001` `P0/ARCH+BE/S`：确认一个 Provider Type 可创建多个 Provider Instance，例如两个 OpenAI-compatible Endpoint。
- [x] `LLM-002` `P0/DBA+BE/M`：补齐 Provider 唯一名称、类型、Base URL、代理、超时、重试、启用状态、健康状态和标签字段。
- [x] `LLM-003` `P0/BE+SEC/M`：实现 API Key 加密保存、掩码返回、更新不回显和主密钥缺失拒绝启动。
- [x] `LLM-004` `P0/SEC+OPS/M`：实现 API Key 轮换、失效、审计和恢复流程。
- [x] `LLM-005` `P0/BE/M`：移除当前仅允许 DeepSeek Provider 的硬限制，改为可扩展 Provider Adapter 注册表。
- [x] `LLM-006` `P0/BE/M`：支持 DeepSeek Adapter。
- [x] `LLM-007` `P0/BE/M`：支持通用 OpenAI-compatible Adapter。
- [x] `LLM-008` `P1/BE/M`：评估并支持 OpenAI、Azure OpenAI、Ollama/本地兼容端点的差异配置。
- [x] `LLM-009` `P0/BE+SEC/M`：所有 Provider 连接测试必须经过 Security Gateway，且只发送公开测试文本。
- [x] `LLM-010` `P0/BE/M`：实现 Provider 健康检查、延迟、最近成功、最近错误和稳定错误码。
- [x] `LLM-011` `P1/BE+OPS/M`：实现健康探测退避，避免不可用 Provider 被高频测试。
- [x] `LLM-012` `P1/FE/M`：实现多个供应商实例的新增、编辑、禁用、测试和删除影响预览。

### 11.2 模型目录与能力

- [x] `LLM-013` `P0/DBA+BE/M`：保证模型唯一性以 Provider ID + Model Code 为边界，禁止仅按 model_code 全局匹配。
- [x] `LLM-014` `P0/BE/M`：实现 Chat、Reasoning、Embedding、Rerank 模型类型。
- [x] `LLM-015` `P0/BE/M`：记录 context length、max output、tool call、JSON、stream、thinking、temperature 支持能力。
- [x] `LLM-016` `P0/BE/M`：实现手动添加模型和可选的 Provider 模型发现。
- [x] `LLM-017` `P0/BE+QA/M`：验证模型能力与请求参数，拒绝向不支持的模型发送 thinking/tool 参数。
- [x] `LLM-018` `P0/BE/M`：实现模型启用、禁用、默认、优先级和展示名称。
- [x] `LLM-019` `P0/BE/M`：模型删除前检查会话默认值、场景路由、Fallback 和正在执行的任务。
- [x] `LLM-020` `P1/FE/M`：实现按供应商分组的模型管理和能力徽标。
- [x] `LLM-021` `P1/FE/M`：展示模型健康、最近延迟、错误率、Token 与成本摘要。

### 11.3 路由、切换与故障转移

- [x] `LLM-022` `P0/ARCH+BE/M`：定义优先级：消息显式选择 > 会话选择 > 用户默认 > 场景路由 > 系统默认。
- [x] `LLM-023` `P0/BE+SEC/M`：实现模型可见范围和 RBAC，用户只能选择被授权模型。
- [x] `LLM-024` `P0/BE+FE/M`：Chat 请求增加稳定的 model_id；不得只传可能冲突的 model_code。
- [x] `LLM-025` `P0/FE+BE/M`：真正接通 Copilot 模型选择到 SSE 与非流式请求。
- [x] `LLM-026` `P0/FE+BE/M`：实现会话级模型锁定与持久化，刷新页面后保持选择。
- [x] `LLM-027` `P0/FE+BE/M`：允许下一条消息切换模型，但不修改历史消息的模型归属。
- [x] `LLM-028` `P0/BE+DBA/M`：每条消息保存 requested_model_id、actual_model_id、provider_id 和路由原因。
- [x] `LLM-029` `P0/BE/M`：场景路由支持 Primary、Fallback、启停和优先级。
- [x] `LLM-030` `P0/BE+SEC/M`：仅在策略允许、数据分类兼容时执行跨 Provider Fallback。
- [x] `LLM-031` `P0/BE+FE/M`：发生 Fallback 时在回答元数据中明确显示，不得静默替换。
- [x] `LLM-032` `P0/BE/M`：区分超时、认证失败、限流、模型不存在、内容安全、网络失败和无效响应。
- [x] `LLM-033` `P1/BE/M`：实现并发上限、每用户/租户额度、Provider 配额和熔断。
- [x] `LLM-034` `P1/BE+OPS/M`：实现预算阈值、成本告警和超额策略。
- [x] `LLM-035` `P1/FE/M`：普通工程师界面只显示授权模型；高级参数进入专家模式。
- [x] `LLM-036` `P1/FE/M`：模型切换器显示供应商、模型名称、用途、速度、上下文和可用状态。
- [x] `LLM-037` `P1/QA/L`：覆盖多供应商同名模型、Provider 禁用、模型禁用、Fallback、无权限和切换并发测试。

**退出标准**：用户选择的模型真实生效；每条消息能证明实际使用了哪个供应商和模型；故障转移透明、受控、可审计。

---

## 12. AI Security Gateway

- [x] `SEC-001` `P0/SEC+ARCH/M`：定义 PUBLIC、INTERNAL、CONFIDENTIAL、SECRET 分类规则。
- [x] `SEC-002` `P0/SEC+BE/M`：统一所有 LLM 和 Embedding 出口到 Security Gateway。
- [x] `SEC-003` `P0/SEC+BE/M`：实现默认拒绝；未知 Provider、未知分类、未知权限一律拒绝。
- [x] `SEC-004` `P0/SEC+BE/M`：实现密码、Community、API Key、私钥、RADIUS/TACACS Key、JWT、Cookie 检测。
- [x] `SEC-005` `P0/SEC+BE/M`：实现内部 IP、主机名、序列号、MAC、Site 和业务名称的策略化处理。
- [x] `SEC-006` `P0/SEC+BE/M`：实现脱敏、令牌化、最小上下文和 Scope-bound Token Vault。
- [x] `SEC-007` `P0/SEC+BE/M`：禁止默认外发整台配置、全量 CMDB、完整日志、整张拓扑和全量会话。
- [x] `SEC-008` `P0/SEC+BE/M`：实现 Prompt Injection Pattern Detection 与 Data/Instruction 分离。
- [x] `SEC-009` `P0/SEC+BE/M`：实现文档 Hidden Text、Script 和非正文指令过滤。
- [x] `SEC-010` `P0/SEC+BE/M`：实现 tenant、workspace、site、department、document_scope、user_role 访问控制。
- [x] `SEC-011` `P0/SEC+AI/M`：确保无权限文档不进入候选、Context、Citation 或 Trace。
- [x] `SEC-012` `P0/SEC+BE/M`：实现 Provider/Model 数据驻留和允许分类策略。
- [x] `SEC-013` `P0/SEC+BE/M`：实现全局、租户和 Provider Kill Switch。
- [x] `SEC-014` `P0/SEC+BE/M`：审计记录策略版本、分类、发现项、处置、Provider、模型和请求 ID。
- [x] `SEC-015` `P0/SEC+BE/M`：审计日志本身执行脱敏和访问控制。
- [x] `SEC-016` `P0/SEC+FE/M`：安全拦截向用户返回可理解原因，不泄露检测规则和敏感原文。
- [x] `SEC-017` `P1/FE+SEC/M`：实现安全策略、审计、事件和 Kill Switch 管理页。
- [x] `SEC-018` `P1/SEC+QA/L`：建立恶意附件、Prompt Injection、跨租户、秘密外发和日志侧信道测试集。
- [x] `SEC-019` `P1/SEC+OPS/M`：建立安全事件响应、API Key 吊销和审计导出流程。
- [x] `SEC-020` `P2/SEC/M`：定期审计新 Provider Adapter 是否存在旁路调用。

**退出标准**：测试集 SECRET 外发为 0；任何外部调用都有安全决策和审计记录。

---

## 13. Copilot 工程师体验

- [x] `COP-001` `P0/PM+NET+FE/M`：拆分普通工程师 AI 助手与管理员 AI 管理中心。
- [x] `COP-002` `P0/FE/M`：普通工程师导航只保留 Copilot、我的会话、故障案例和知识检索。
- [x] `COP-003` `P0/FE+BE/M`：Provider、Model、Prompt、Agent、Security 菜单按角色隐藏且后端强制鉴权。
- [x] `COP-004` `P0/PM+NET/M`：定义咨询、故障诊断、配置生成、知识检索四种意图和风险边界。
- [x] `COP-005` `P0/FE+BE/M`：Composer 支持选择设备、接口、Site、时间范围和关联告警。
- [x] `COP-006` `P0/FE+BE/M`：支持关联最近变更、拓扑邻居、性能指标和历史事件。
- [x] `COP-007` `P0/FE+SEC/M`：附件上传前显示分类、脱敏和外发提示。
- [x] `COP-008` `P0/FE+AI/M`：AI 缺少厂商、型号、版本或影响范围时使用结构化追问。
- [x] `COP-009` `P0/FE+AI/M`：展示 AI 识别到的厂商、型号、OS、版本和歧义候选。
- [x] `COP-010` `P0/FE+AI/M`：实现诊断回答模板，不以无结构长文作为唯一结果。
- [x] `COP-011` `P0/FE/M`：展示已确认事实、假设、置信度、所需证据和下一步三项检查。
- [x] `COP-012` `P0/FE/M`：清楚标记官方知识、企业知识、实时设备数据和模型推断。
- [x] `COP-013` `P0/FE/M`：将开发者 Trace 与工程师证据面板拆分。
- [x] `COP-014` `P0/FE+BE/M`：明确显示本次是否连接设备、是否执行 CLI、是否外发和使用哪个模型。
- [x] `COP-015` `P0/FE/M`：实现停止生成、重试、修改问题、继续排查和复制。
- [x] `COP-016` `P0/FE+BE/M`：实现流式中断后消息一致性和可恢复错误状态。
- [x] `COP-017` `P0/FE+BE/M`：实现真实反馈记录，不使用只弹窗不落库的点赞/点踩。
- [x] `COP-018` `P1/FE+BE/M`：差评支持型号错、版本错、命令错、证据不足、过时、无关等原因。
- [x] `COP-019` `P1/FE+BE/M`：支持会话重命名、归档、删除、搜索、分页和恢复。
- [x] `COP-020` `P1/FE+BE/M`：将会话上下文预算、摘要和截断结果可解释化。
- [x] `COP-021` `P1/FE/M`：完成窄屏、长命令、长引用、中文/英文和暗色模式适配。
- [x] `COP-022` `P1/FE+QA/M`：完成键盘操作、ARIA、焦点和对比度检查。
- [x] `COP-023` `P1/PM+FE/M`：设计首次使用引导和高质量示例问题。
- [x] `COP-024` `P2/FE+BE/M`：支持将会话生成故障案例、交接记录或工单草稿。

**退出标准**：网络工程师不需要了解 RAG 或模型内部概念，也能完成一次可追溯诊断。

---

## 14. 网络故障诊断编排与只读工具

- [x] `DIA-001` `P0/NET+ARCH/M`：定义诊断状态机：症状、范围、假设、证据、检查、结论、修复、验证。
- [x] `DIA-002` `P0/NET+BE/M`：定义设备不可达、接口 Down/Flap、OSPF/BGP、丢包、CPU/内存的首批 Playbook。
- [x] `DIA-003` `P0/BE+NET/M`：复用 CMDB 设备、平台、凭据和 Site 上下文。
- [x] `DIA-004` `P0/BE+NET/M`：复用告警、拓扑、变更、健康和监控数据源。
- [x] `DIA-005` `P0/BE+NET/M`：所有网络工具从统一 vendor/platform/command contract 选择命令。
- [x] `DIA-006` `P0/BE+NET/M`：禁止根据型号单独推断厂商，禁止缺少平台时回退 Cisco 命令。
- [x] `DIA-007` `P0/BE+NET/M`：实现 Ping、TCP、SSH、认证的分层只读诊断。
- [x] `DIA-008` `P0/BE+NET/L`：实现 Cisco/Huawei/H3C 首批只读命令映射与 Fixture。
- [x] `DIA-009` `P0/BE+NET/M`：复用接口 canonicalizer，处理 10GE/Te/XGE 等等价名称。
- [x] `DIA-010` `P0/BE+SEC/M`：只读工具调用仍需权限、审计、超时、并发和输出脱敏。
- [x] `DIA-011` `P0/BE+AI/M`：工具结果先结构化和最小化，再进入模型上下文。
- [x] `DIA-012` `P0/BE+AI/M`：每个工具步骤记录目的、命令、目标、状态、证据和耗时。
- [x] `DIA-013` `P0/BE+AI/M`：依据最新证据更新假设，禁止重复执行无信息增益检查。
- [x] `DIA-014` `P0/FE+BE/M`：在 Copilot 显示检查计划并允许逐步授权只读命令。
- [x] `DIA-015` `P1/BE+NET/M`：支持用户粘贴 CLI 输出而不连接设备。
- [x] `DIA-016` `P1/BE+NET/M`：识别认证失败、超时、不可达、命令不支持和解析失败的稳定错误码。
- [x] `DIA-017` `P1/QA+NET/L`：使用 Fixture 和 Mock Driver 覆盖多厂商成功与失败路径。
- [x] `DIA-018` `P2/ARCH+SEC/L`：设计写配置审批、差异、快照、回滚和修复后验证；首版不默认启用。
- [x] `DIA-019` `P2/BE+NET+SEC/L`：将写操作接入现有 PAM/Change Governance，而不是从 Copilot 直接执行。

**退出标准**：首批故障可形成“假设—证据—检查—结论”闭环；默认无设备写操作。

---

## 15. 知识库管理界面

- [x] `KUI-001` `P0/PM+FE/M`：确定知识管理员信息架构：目录、来源、文档、导入、产品、Alias、Chunk、检索测试、评测、安全审计。
- [x] `KUI-002` `P0/FE/M`：保留树形浏览，但不向用户暴露 `kb_import` 物理路径作为 Metadata。
- [x] `KUI-003` `P0/FE+BE/M`：默认按 Vendor/Product Family/Series 浏览。
- [x] `KUI-004` `P0/FE+BE/M`：支持 OS、版本、型号、主题、内容类型、文档类型、状态服务端筛选。
- [x] `KUI-005` `P0/FE+BE/M`：500 条以上使用服务端搜索、筛选和分页，列表不返回正文。
- [x] `KUI-006` `P0/FE+BE/M`：文档正文、Chunk、原始来源、版本历史使用详情接口按需加载。
- [x] `KUI-007` `P0/FE+BE/M`：实现请求取消，防止旧筛选响应覆盖新结果。
- [x] `KUI-008` `P0/FE/M`：区分首次加载、筛选加载、空库、无结果、权限拒绝、失败与重试。
- [x] `KUI-009` `P0/FE+BE/M`：实现官方知识与企业知识明显分区。
- [x] `KUI-010` `P0/FE+BE/M`：官方来源导入与企业文件上传使用不同表单和校验。
- [x] `KUI-011` `P0/FE+BE/M`：批量上传前预览每个文件的 Metadata，不允许用一组错误 Metadata 覆盖不同文档。
- [x] `KUI-012` `P0/FE+BE/M`：删除、禁用、Reparse、Rechunk、Reindex 使用独立动作和确认。
- [x] `KUI-013` `P0/FE+BE/M`：危险操作显示影响文档、Chunk、Index、引用和恢复方式。
- [x] `KUI-014` `P1/FE+BE/M`：实现文档版本比较、发布、替代和回滚。
- [x] `KUI-015` `P1/FE+BE/M`：实现 Source Registry 与刷新状态管理。
- [x] `KUI-016` `P1/FE+BE/M`：实现 RAG Evaluation 与回归结果页面。
- [x] `KUI-017` `P1/FE+BE/M`：实现 Retrieval Trace 管理员查看器，默认脱敏。
- [x] `KUI-018` `P1/FE+QA/M`：完成中英文、暗色、窄屏、表格粘性表头和分页验证。

**退出标准**：管理员管理的是业务实体和生命周期，不是文件夹与向量细节。

---

## 16. API、会话、任务与可观测性

- [x] `API-001` `P0/ARCH+BE/M`：统一 `/api/v2/kb` 与 `/api/v1/ai` 边界和版本策略。
- [x] `API-002` `P0/BE/M`：为 Provider、Model、Source、Document、Product、Alias、Import、Search 定义 Pydantic 契约。
- [x] `API-003` `P0/BE/M`：禁止稳定合同继续使用无类型 Dict 请求。
- [x] `API-004` `P0/BE+FE/M`：统一分页、排序、筛选、错误码和权限拒绝响应。
- [x] `API-005` `P0/BE/M`：列表仅返回摘要，详情独立加载正文、Chunk、日志和 Trace。
- [x] `API-006` `P0/BE/M`：SSE 定义 meta、progress、token、citation、done、error 事件版本。
- [x] `API-007` `P0/BE+FE/M`：SSE 中断、取消和重连保持幂等，不产生重复消息。
- [x] `API-008` `P0/BE+DBA/M`：会话、消息、任务、工具调用和证据保持租户与用户隔离。
- [x] `API-009` `P0/BE/M`：实现任务取消、超时、最大步骤、最大工具次数和状态转换并发保护。
- [x] `OBS-001` `P0/BE+AI/M`：记录 raw query、normalized query、entities、filters、candidates、scores、final chunks。
- [x] `OBS-002` `P0/BE+AI/M`：记录 reranker、citation、latency、tokens、provider、model 和 security result。
- [x] `OBS-003` `P0/SEC+BE/M`：Trace 和日志写入前脱敏，限制原始查询保留。
- [x] `OBS-004` `P0/BE+OPS/M`：建立请求 ID 贯穿前端、API、RAG、Gateway 和 Provider。
- [x] `OBS-005` `P1/OPS+BE/M`：建立 Provider 错误率、延迟、限流、Fallback 和成本监控。
- [x] `OBS-006` `P1/OPS+AI/M`：建立检索 No Match、错误厂商、版本冲突和低置信度监控。
- [x] `OBS-007` `P1/OPS+BE/M`：建立 Import/Reindex 队列积压、失败和租约异常告警。
- [x] `OBS-008` `P1/DBA+OPS/M`：建立索引膨胀、慢查询、缓存命中和数据库容量监控。

**退出标准**：每个回答和失败都能通过 request_id 追踪到检索、安全和模型调用。

---

## 17. Evaluation 与质量门禁

- [x] `EVAL-001` `P0/NET+AI+QA/L`：建立首批 100～200 条固定 Query 数据集。
- [x] `EVAL-002` `P0/NET+AI/M`：覆盖 Huawei/Cisco 的 VLAN、Interface、OSPF、SSH、NTP、Route。
- [x] `EVAL-003` `P0/NET+AI/M`：覆盖 Exact、Alias、Prefix、Ambiguous、Typo、Wrong Vendor、Product Conflict。
- [x] `EVAL-004` `P0/NET+AI/M`：覆盖指定版本、未指定版本、冲突版本和未知版本。
- [x] `EVAL-005` `P0/AI+QA/M`：定义 Recall@K、Precision@K、MRR、NDCG 和 Entity Resolution Accuracy。
- [ ] `EVAL-006` `P0/AI+QA/M`：定义 Product、OS、Version Match、Wrong Vendor、Official Source 和 Citation Accuracy。
- [ ] `EVAL-007` `P0/SEC+QA/M`：定义秘密泄漏、Prompt Injection、越权和外发策略指标。
- [ ] `EVAL-008` `P0/QA+NET/M`：建立人工 Golden Answer、适用版本和引用标注流程。
- [ ] `EVAL-009` `P0/AI+QA/M`：实现可重复离线评测命令和机器可读报告。
- [ ] `EVAL-010` `P0/QA+AI/M`：在 CI 中执行小型固定集，完整集进入发布门禁。
- [ ] `EVAL-011` `P0/QA/L`：覆盖 Provider CRUD、模型切换、Fallback、权限和密钥安全测试。
- [ ] `EVAL-012` `P0/QA/L`：覆盖 Source/Document/Version/Chunk/Reindex 生命周期测试。
- [ ] `EVAL-013` `P0/QA/L`：覆盖检索、引用、No Match、Ambiguous 和版本冲突测试。
- [ ] `EVAL-014` `P0/QA+DBA/L`：覆盖迁移、新装、重复迁移、回填、约束、回滚和恢复。
- [ ] `EVAL-015` `P0/QA+BE/L`：覆盖成功、非法输入、权限拒绝、空数据和依赖失败。
- [ ] `EVAL-016` `P0/QA+NET/L`：使用 Mock/Fixture 验证 Cisco、Huawei、H3C 平台映射和只读命令。
- [ ] `EVAL-017` `P1/QA+FE/M`：完成 Copilot、Provider、Model、Knowledge、Security 浏览器关键路径测试。
- [ ] `EVAL-018` `P1/QA+AI/M`：执行 10k/100k/1m 性能样本并记录 P50/P95/P99。
- [ ] `EVAL-019` `P1/QA+OPS/M`：长时间运行导入、Reindex、SSE、Provider 故障和恢复稳定性测试。
- [ ] `EVAL-020` `P1/QA+SEC/M`：执行依赖、Secret、权限、日志和错误响应安全检查。

### 发布硬门槛

- Official Source Rate（官方知识域）= 100%。
- Wrong Vendor（固定测试集）= 0。
- 重大版本冲突（固定测试集）= 0。
- Ambiguous 明确提示率 = 100%。
- 关键结论 Citation Accuracy ≥ 95%。
- 禁用文档继续召回 = 0。
- SECRET Outbound Leak（安全测试集）= 0。
- 检索 P95 初始目标 < 3 秒；端到端首个有效反馈初始目标 < 5 秒。
- V2 可从 Source + Metadata 完整重建。
- V2 可通过功能开关切回 V1。

---

## 18. 数据迁移、影子运行与切换

- [ ] `MIG-001` `P0/ARCH+DBA+AI/M`：按 Document、Metadata、Chunk、Embedding 分别确定迁移策略。
- [ ] `MIG-002` `P0/DBA+AI/M`：可信原始文档优先迁移；不可证明质量的 Chunk/Embedding 不直接迁移。
- [ ] `MIG-003` `P0/DBA+AI/M`：建立旧 ID 到 V2 ID 映射和迁移 Manifest。
- [ ] `MIG-004` `P0/DBA+BE/M`：迁移脚本支持 dry-run、断点续跑、幂等和批次回滚。
- [ ] `MIG-005` `P0/DBA+AI/M`：为旧 Metadata 建立可信、需验证、不可用三个等级。
- [ ] `MIG-006` `P0/NET+AI/L`：从官方来源重新验证厂商、产品、OS 和版本字段。
- [ ] `MIG-007` `P0/AI+BE/L`：对迁移文档重新 Parse、Chunk、Embed、Index。
- [ ] `MIG-008` `P0/QA+DBA/M`：核对文档数量、哈希、版本、Chunk 和权限一致性。
- [ ] `MIG-009` `P0/BE+AI/M`：实现 V1/V2 双检索 Shadow Mode，不向用户展示双答案。
- [ ] `MIG-010` `P0/BE+AI/M`：记录同 Query 的实体、候选、最终 Chunk、引用、延迟和差异。
- [ ] `MIG-011` `P0/FE+BE/M`：实现仅管理员/内测用户可切换 V2 的 Feature Flag。
- [ ] `MIG-012` `P0/ARCH+QA/M`：定义管理员、内测用户、指定 Site、10%、50%、100% 灰度顺序。
- [ ] `MIG-013` `P0/OPS+BE/M`：实现不依赖数据库回退的快速 V1/V2 流量切换。
- [ ] `MIG-014` `P0/OPS+DBA/M`：演练 V2 Index 回滚、Schema 向前兼容和应用版本回退。
- [ ] `MIG-015` `P1/AI+QA/L`：Shadow 运行达到样本量后输出差异分析和阻断问题。
- [ ] `MIG-016` `P1/ARCH+PM+SEC/M`：召开 Cutover 评审，确认质量、安全、性能、备份和回滚证据。
- [ ] `MIG-017` `P1/OPS/M`：完成灰度切换与指标观察。
- [ ] `MIG-018` `P2/ARCH+OPS/M`：稳定期结束后制定 V1 下线计划，先停止写入再归档。

**退出标准**：切换是可观测、可暂停、可逆的，不需要删除 V1 数据。

---

## 19. 发布、部署与运行保障

- [ ] `REL-001` `P0/OPS+ARCH/S`：确认 Windows、Ubuntu、Docker Compose、CI 四类目标影响。
- [ ] `REL-002` `P0/OPS+BE/M`：定义 PostgreSQL 扩展检查、数据库迁移顺序和启动失败策略。
- [ ] `REL-003` `P0/OPS+SEC/M`：补齐 `.env.example` 的 Provider、Security Gateway、Embedding、Feature Flag 配置，真实密钥不得提交。
- [ ] `REL-004` `P0/OPS+BE/M`：确认 FastAPI 静态资源、SSE、反向代理超时和请求大小限制。
- [ ] `REL-005` `P0/OPS/M`：确认 Nginx/Docker/桌面环境的流式响应不被缓冲。
- [ ] `REL-006` `P0/OPS+DBA/M`：发布前自动备份数据库、Source Manifest 和配置。
- [ ] `REL-007` `P0/OPS+QA/M`：运行后端测试、lint、生产构建和配置语法检查。
- [ ] `REL-008` `P0/OPS+QA/M`：验证 fresh install、旧版本升级和回退版本启动。
- [ ] `REL-009` `P0/OPS+SEC/M`：验证生产密钥、权限、文件路径和日志目录。
- [ ] `REL-010` `P0/OPS+BE/M`：准备 Kill Switch、Provider Disable、V2 Disable 和 Reindex Pause Runbook。
- [ ] `REL-011` `P1/OPS/M`：建立容量、延迟、错误率、队列、成本、泄漏事件和 Provider 健康看板。
- [ ] `REL-012` `P1/OPS+PM/S`：准备发布公告、兼容性说明、已知风险和回退窗口。
- [ ] `REL-013` `P1/OPS+QA/M`：发布后执行冒烟：登录、Provider、模型切换、知识检索、引用、Copilot、安全阻断。
- [ ] `REL-014` `P1/OPS+ARCH/M`：稳定观察结束后关闭临时兼容路径并归档发布证据。

---

## 20. 文档、培训与运营

- [ ] `DOC-001` `P0/ARCH/M`：完成 Current State、Gap、Target Architecture、Data Model 文档。
- [ ] `DOC-002` `P0/AI+NET/M`：完成 Product/OS/Version、Source Governance、Chunking、Retrieval 设计文档。
- [ ] `DOC-003` `P0/SEC/M`：完成 Security Architecture、Outbound Map 和事件响应文档。
- [ ] `DOC-004` `P0/DBA+OPS/M`：完成 Migration、Backup、Restore、Reindex 和 Rollback Runbook。
- [ ] `DOC-005` `P0/QA/M`：完成 Evaluation Plan、固定测试集版本和质量报告模板。
- [ ] `DOC-006` `P1/PM+FE/M`：完成网络工程师 Copilot 使用手册。
- [ ] `DOC-007` `P1/PM+FE/M`：完成知识管理员 Source、Document、Alias、Import、Evaluation 使用手册。
- [ ] `DOC-008` `P1/OPS+SEC/M`：完成 Provider/Model 管理、密钥轮换、Kill Switch 和审计手册。
- [ ] `DOC-009` `P1/NET+PM/M`：培训首批内测网络工程师，并收集结构化反馈。
- [ ] `DOC-010` `P2/PM+AI/M`：建立错误答案复盘、知识修订、评测集补充和月度质量运营流程。

---

## 21. 里程碑与关键路径

### M0：审计与架构冻结（第 1～2 周）

必须完成：`ADR-*`、`GOV-*`、`AUD-*`。  
产出：现状报告、决策表、基线指标、数据与外发流图。  
阻断条件：现有数据流、Provider 出口或迁移状态仍为未知。

### M1：可信数据底座（第 3～5 周）

必须完成：`DB-* P0`、`CAT-* P0`、`ING-* P0`、`CHK-* P0`。  
产出：Huawei/Cisco 少量官方样本从 Source 到 Published Index 跑通。  
阻断条件：CLI 被错误切分、版本不可追溯、导入不幂等或无法重建。

### M2：可信检索与引用（第 6～8 周）

必须完成：`RET-* P0`、`CIT-* P0`、`EVAL-001～010`。  
产出：Alias/Prefix/Fuzzy/FTS/Vector/Version/Citation 完整链路。  
阻断条件：Wrong Vendor、重大版本混用、无来源确定性回答。

### M3：多供应商、多模型与安全出口（第 7～9 周，可与 M2 部分并行）

必须完成：`LLM-* P0`、`SEC-* P0`。  
产出：多个供应商实例、多个模型、用户自由切换、透明 Fallback、统一安全审计。  
阻断条件：模型选择未真实生效、存在旁路调用、SECRET 测试泄漏。

### M4：工程师 Copilot 与诊断闭环（第 9～11 周）

必须完成：`COP-* P0`、`DIA-* P0`、`KUI-* P0`、`API-* P0`、`OBS-* P0`。  
产出：工程师可完成一次结构化、只读、可追溯的故障诊断。  
阻断条件：必须阅读开发者 Trace 才能判断证据、权限边界不清或隐式执行命令。

### M5：影子运行与发布（第 12～16 周）

必须完成：`EVAL-*`、`MIG-* P0/P1`、`REL-*`。  
产出：Shadow 对比、灰度、监控、备份、回滚与 Cutover 评审。  
阻断条件：任一发布硬门槛不达标。

---

## 22. 建议团队与工作量

建议最小团队：

- 1 名架构/技术负责人；
- 2 名后端工程师；
- 1 名 AI/RAG 工程师；
- 1 名前端工程师；
- 1 名测试工程师；
- 1 名兼职资深网络工程师；
- 安全与运维按里程碑参与。

在现有 V2 雏形可复用且审计结果良好的前提下：

- 可演示 PoC：约 8～10 周；
- 可控内测试运行：约 12～16 周；
- Huawei/Cisco 首版生产稳定：约 16～20 周；
- H3C/Ruijie、自动化诊断和受控写操作应另开后续里程碑。

如果只有 1～2 名主力开发，必须把首批范围缩小到 Huawei CE6800，并将总周期至少扩大一倍。

---

## 23. 最终上线签字表

- [ ] 架构负责人确认 V2 没有破坏 V1 回滚能力。
- [ ] 数据库负责人确认新装、升级、备份、恢复、索引和回填通过。
- [ ] AI 负责人确认检索、版本、引用和评测指标达标。
- [ ] 网络负责人确认首批命令、型号、OS 和版本适用性。
- [ ] 安全负责人确认所有外发经过 Gateway，安全测试集泄漏为 0。
- [ ] 前端负责人确认模型切换真实生效，工程师/管理员界面分离。
- [ ] 测试负责人确认后端、前端、迁移、浏览器和性能门禁通过。
- [ ] 运维负责人确认监控、Kill Switch、备份和回滚演练通过。
- [ ] 产品负责人确认核心用户旅程完成并由内测工程师验收。
- [ ] 最终 Cutover 评审给出书面 GO 决议。

只有全部签字完成，V2 才允许成为默认检索与 Copilot 后端。
