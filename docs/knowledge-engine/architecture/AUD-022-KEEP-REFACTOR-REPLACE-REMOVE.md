# AUD-022 KEEP / REFACTOR / REPLACE / REMOVE 决策表

## 结论

AUD-022 将 ADR-001～012、GOV-001～012、AUD-001～021 和 V1 baseline 汇总为 24 个可执行决策。架构不做静默改写：V1/V2 并行、PostgreSQL 权威存储、产品/OS/版本正交建模、只读咨询、确定性 metadata hard-filter 和基线评测被列为不可变 KEEP；Gateway、文档版本、知识域、Provider/Model、Trace、Prompt/附件导入、引用和 API 合同必须 REFACTOR；AI 专用 crypto 与浏览器附件导入需要 REPLACE；潜在 Gateway 旁路的 direct Provider `test_connection` 只允许 REMOVE。

本表不是“已修复”清单，而是后续 DB/CAT/ING/CHK/RET/CIT/LLM/SEC/COP/DIA/KUI/API/OBS/EVAL/MIG/REL 任务的架构决策输入。OPEN/P0 发现项保持 OPEN，不能通过选择 KEEP 伪装为完成。

## 决策词义

| 决策 | 含义 |
|---|---|
| KEEP | 保留职责与架构不变量，只补测试、审计和观测。 |
| REFACTOR | 保留职责/合同，在兼容层或双读写后替换实现。 |
| REPLACE | 引入新实现并迁移；旧实现只有在回滚/兼容证据后下线。 |
| REMOVE | 删除明确的旁路或重复能力；必须有依赖、迁移、回滚和 V1 Gate。 |

## 主决策矩阵

| ID | 组件 | 决策 | 依据 | 后续任务 | V1/回滚边界 |
|---|---|---|---|---|---|
| DEC-001 | V1/V2 并行兼容 | KEEP | ADR-001、AUD-001、AUD-021 | DB-001/API-001/EVAL-001/MIG-001/REL-001 | 保留 V1 路由，关闭 V2 flag 即回滚 |
| DEC-002 | PostgreSQL 权威存储 | KEEP | ADR-002、AUD-003/004 | DB-001/002/MIG-001/REL-001 | SQLite 仅本地/测试 |
| DEC-003 | Product/OS/Software 正交模型 | KEEP | ADR-003、AUD-005/009/021 | CAT-001/002/RET-001/EVAL-001 | alias 只能走显式 resolver |
| DEC-004 | Document Version 与衍生索引分离 | REFACTOR | ADR-004、AUD-005/006/010/023 | DB-001/003/ING-001/CHK-001/MIG-001 | 双读写，V2 失败回退旧索引 |
| DEC-005 | 官方/企业知识域 | REFACTOR | ADR-005、AUD-005/010/014/020 | CAT-001/ING-001/004/RET-001/SEC-001 | 旧文档先标 legacy，不直接删除 |
| DEC-006 | 外部 AI 双网关与 DLP | REFACTOR | ADR-006、AUD-015～020 | LLM-001/SEC-001/002/API-001/OBS-001 | 默认禁用外发，kill switch 可回滚 |
| DEC-007 | 默认只读咨询 | KEEP | ADR-007、AUD-001/012/017 | COP-001/DIA-001/SEC-005 | 新工具能力可单独禁用 |
| DEC-008 | 写配置变更治理 | REFACTOR | ADR-008、AUD-001/012/017 | DIA-001/005/API-004/SEC-010/REL-008 | 先 proposal-only |
| DEC-009 | 确定性 metadata 匹配优先 | KEEP | ADR-009、AUD-009/021 | RET-001/002/003/EVAL-001 | V1 lexical 只作 shadow |
| DEC-010 | 歧义澄清/跨平台标记 | REFACTOR | ADR-010、AUD-009/012/013/021 | RET-010/CIT-001/COP-004/API-003/EVAL-004 | 失败回退安全 no-match |
| DEC-011 | 多供应商/模型路由 | REFACTOR | ADR-011、AUD-012/015/017 | LLM-001/003/007/API-001/KUI-001 | 保留 V1 默认 route |
| DEC-012 | 答案 provenance/citation DTO | REFACTOR | ADR-012、AUD-013/019/021 | CIT-001/003/API-006/COP-010/EVAL-006 | legacy citation 作为投影 |
| DEC-013 | AI 专用 crypto helper | REPLACE | AUD-018、ADR-006 | DB-009/SEC-003/004/MIG-004/REL-005 | legacy 双解密，验收后重加密 |
| DEC-014 | Agent Trace/AI audit 存储 | REFACTOR | AUD-019 | DB-010/API-007/SEC-008/OBS-003/MIG-006 | 先收紧 reader，保留旧数据 |
| DEC-015 | Prompt/HTML/附件/知识导入 | REFACTOR | AUD-020、ADR-005/006 | ING-001/006/012/SEC-011/KUI-012/EVAL-010 | 新导入可全量 quarantine |
| DEC-016 | RAG metadata hard-filter | KEEP | ADR-009、AUD-009/021 | RET-001/002/005 | V2 结果可 shadow 比较 |
| DEC-017 | Vector/Embedding/Rerank | REFACTOR | AUD-007/008/009/015 | DB-014/RET-012/014/LLM-020/MIG-010 | 本地 embedding/lexical 作为回退 |
| DEC-018 | Copilot 模型/速度/推理控件 | REFACTOR | AUD-012、ADR-011/012 | KUI-001/004/API-001/LLM-009/OBS-005 | 无参数时沿用服务端默认 |
| DEC-019 | 浏览器附件/二进制 placeholder | REPLACE | AUD-020、AUD-002 | ING-012/013/API-008/SEC-011/REL-009 | 新服务端 gate 前可禁用附件 |
| DEC-020 | 直连 Provider `test_connection` | REMOVE | AUD-017 | LLM-006/SEC-002/API-002 | 只保留 Gateway-backed endpoint |
| DEC-021 | 未约束 dict API payload | REFACTOR | AUD-002/012/018/020 | API-001/003/008/SEC-014/EVAL-012 | legacy fields 由 versioned adapter 接收 |
| DEC-022 | localStorage 原始 Copilot session | REFACTOR | ADR-001、AUD-011/019 | COP-015/KUI-015/API-006/MIG-012 | 只允许一次性导入，不新增 raw |
| DEC-023 | 观测与 route provenance | REFACTOR | ADR-012、AUD-002/019/021 | OBS-001/003/005/API-009/EVAL-015 | 旧 metric 名称保持兼容 |
| DEC-024 | 基线与回归评测 | KEEP | AUD-021 | EVAL-001/010/015/REL-010 | 旧 baseline 永久可重跑 |

## 不可变架构决策

以下决策在后续实现中不得自行改成另一种架构：

1. 生产 PostgreSQL 是唯一权威数据源；SQLite 不能成为发布环境的第二事实源。
2. 原文档/Document Version 是事实源，Metadata/Chunk/Embedding/Index 是可重建衍生数据。
3. 任何外部 LLM/Embedding 都必须经过 Security Gateway、DLP、tokenization、provider allowlist 和 audit；Provider SDK 不能直接持有业务原文。
4. 普通咨询默认 read-only；写配置必须走提案、审批、执行、验证、回滚链路。
5. 硬 metadata 过滤和平台/版本歧义澄清优先于模糊/向量排名；不允许静默选错平台。
6. V1/V2 必须可逆并行，V2 不能以删除旧入口作为“完成”。

## P0 发布阻断

在以下决策关闭前，不得宣称生产 GO：

- DEC-006：外发策略、密钥来源、Provider allowlist、审计和 prompt injection 的 fail-closed 完整性。
- DEC-013：AI API Key 使用版本化、可轮换、fail-closed 的统一 crypto。
- DEC-014：Agent Trace 的 tenant/owner 隔离、opaque user、统一最小化和 retention。
- DEC-015：知识污染/恶意附件的服务端扫描、quarantine 和不可执行检索上下文。
- DEC-019：附件不可绕过的服务端解析/大小/魔数/压缩/恶意内容边界。
- DEC-020：删除潜在 Gateway bypass 的直连 Provider 测试方法，并用架构测试锁定。

## 后续执行规则

每个决策的后续任务必须先满足依赖，再进入实现；REFACTOR/REPLACE/REMOVE 必须分别提供 migration、dual-run 或 adapter、异常/权限/安全测试、回滚和 V1 回归证据。若实施发现与 ADR 不可兼容，必须新增 ADR/Blocker，不得在代码中静默改变本表。

## 数据库、回滚与 V1 影响

本任务只新增决策矩阵、YAML 和 Evidence，没有生产数据库写入、migration 或外部网络调用。回滚为删除三份 AUD-022 文件并恢复状态/清单；所有决策均明确保留 V1 或禁用 V2 的回退方式。

## 最终结论

**PASS（KEEP/REFACTOR/REPLACE/REMOVE 决策已形成并与 ADR/AUD/基线逐项追溯；P0 阻断项仍待后续实现任务关闭）。**
