# DOC-003：Security Architecture、Outbound Map 与事件响应

**Task ID：** DOC-003  
**Milestone：** M2（文档与运营）  
**文档版本：** v1.0  
**盘点日期：** 2026-08-18  
**权威数据库：** PostgreSQL 18；SQLite 不属于生产或验收路径

本文把 Nexora Knowledge Engine V2 的安全边界、全部 AI/采集外发出口和安全事件处置流程落成一份操作基线。文中“当前已验证”只引用已有 Gate/Evidence；“目标/待关闭”明确列出，不把架构合同等同于生产切换授权。

## 1. Security Architecture（安全架构）

### 1.1 信任边界

```text
Browser / CLI / Upload
        │ HTTPS, request_id, auth
        ▼
API Boundary → Auth/RBAC/Tenant/Workspace/Site scope
        │
        ▼
AI Security Gateway
  ├─ classification + minimization + tokenization + DLP
  ├─ prompt-injection / unsafe-context detection
  ├─ provider/model/data-region/permission allowlist
  ├─ payload/timeout/egress limits + kill switches
  └─ metadata-only security event / outbound audit
        │
        ├─ local deterministic/V1 fallback
        └─ approved Provider/Embedding endpoint (HTTPS only)
```

Gateway 是唯一 AI 外发边界。未知 Provider、分类、权限、数据区域、目的地或安全策略默认 BLOCK；任何外发都必须先有 Gateway decision，再生成 metadata-only audit。Provider adapter、stream/non-stream、embedding、诊断工具和 Provider connection test 都不能旁路 Gateway。

### 1.2 数据分类与动作

| 类别 | 典型内容 | 外发默认动作 | 控制 |
| --- | --- | --- | --- |
| `PUBLIC/L0` | 官方文档、厂商 release note | ALLOW（仍需 provider/model allowlist） | source/trust policy |
| `INTERNAL/L1` | 脱敏 SOP、聚合指标 | ALLOW | tenant scope、最小化 |
| `CONFIDENTIAL/L2` | tenant、内网 IP、hostname、MAC、serial、site | TOKENIZE | tenant/task-scoped token vault，TTL ≤ 86400 秒 |
| `SECRET/L3-L4` | password、community、API key、private key、JWT、Cookie、设备密钥 | MINIMIZE 或 BLOCK；原文禁止外发 | DLP、secret scanner、final egress check |
| unsafe context | full config/topology/CMDB/log/session、隐藏指令、script、prompt injection | BLOCK 或隔离为不可执行知识 | stable finding code、quarantine、人工复核 |

Token vault 可逆但不持久化 raw value；只允许同一 tenant/task 使用，过期或 kill switch 立即失效。Trace、日志、API response、页面和 Evidence 不包含明文秘密、完整 prompt、原始 Provider response、原始工具 payload 或 DSN。

### 1.3 权限、租户和诊断边界

- 服务端重建 tenant/workspace/site/department/document/user-role scope；客户端提交的 tenant、Provider、model、filter 不能扩大授权。
- Gateway decision、security incident、outbound audit 只保存 request_id、tenant_id、policy version、classification、decision、disposition、provider/model、finding categories、data region、时间等 bounded metadata。
- Copilot 将 engineer evidence 与 developer trace 分离；用户看不到内部 prompt、SQL、完整工具 payload 或 Provider secret。
- 诊断工具默认只读；每一步必须记录 purpose、command、target、status、evidence、duration_ms。写操作默认 false，任何变更必须走独立授权/审批/审计/回滚。
- Knowledge ingestion/collection 只允许安全 GET/HEAD、allowlist host/path 和响应大小/超时约束；Source Registry 信任不授权设备或 Provider 写操作。

## 2. Outbound Map（外发出口地图）

### 2.1 出口总表

| 出口类别 | 代码/主要入口 | 可发送数据类别 | 目标/边界 | 失败/回退 |
| --- | --- | --- | --- | --- |
| 非流式聊天 | `backend/ai/providers/openai_compatible.py::chat`，经 `assistant.py`、分析服务 | D0 system、D1 user、最小化 D2/D3/D4、D5 controls；D6 credentials 禁止 | Provider allowlist + Gateway + HTTPS | stable error、local/V1 fallback、audit |
| 流式聊天 | `openai_compatible.py::chat_stream`、chat/SSE API | 同上；token/citation bounded | Gateway stream mode；request_id 贯穿 SSE | abort/timeout/fallback；不缓冲 raw response |
| Embedding | `ExternalEmbeddingProvider` → `AISecurityGateway.protect_embedding` | 最小化文本/结构化 chunk，D6 禁止 | embedding provider/model/dimension allowlist | bounded retry；partial persistence forbidden；local stable embedding fallback |
| Provider 连通性测试 | `backend/ai/api/providers.py` | 固定 PUBLIC 探测 prompt + model control metadata | Gateway fixed probe；不得发送业务/设备数据 | stable provider error；熔断/health update |
| 官方来源采集 | `safe_outbound_http.safe_fetch`、ING-002/018/019/023 | URL facts、bounded bytes in memory；不向 AI 外发原文 | CAT/Source Registry exact host/path、HTTPS GET/HEAD、redirect revalidation | source observation/quarantine；body 不进 API/audit |
| 诊断读取 | diagnostics orchestrator / read-only agent tools | 明确授权的最小 D2/D3/D4 | device allowlist、read-only command allowlist、bounded timeout/concurrency | no write path；stable error；保留最小证据 |
| 本地路径 | local V1/RAG、deterministic resolver、local embedding | 不离开本地；仍执行 tenant/ACL | no network | 优先回退路径 |

### 2.2 目前登记的 AI data exits

AUD-016 登记的 15 个 transport sites 必须全部落在同一个 Gateway boundary：

- `intent_parser.py`：自然语言 intent/structured metadata；
- `natural_query.py`：最小化 CMDB summary；
- `assistant.py`：聊天和聊天流，带 retrieval/citation trace；
- `chat_v1.py`：V1 chat/chat stream，保持 V1 response/SSE contract；
- `command_analysis.py`、`config_analysis.py`、`diff_analysis.py`、`alarm_analysis.py`：命令/配置/差异/告警分析；
- `ip_troubleshooting.py`、`mac_troubleshooting.py`：只读定位摘要；
- `agents/runner.py`：只读 Agent step loop；
- `config_generation.py`：只生成 draft、verification、rollback，不能直接执行；
- `api/providers.py`：固定 PUBLIC Provider probe。

新出口必须先加入本表、完成分类/最小化/DLP/allowlist/审计测试，再允许合并。任何未登记的 `requests/httpx/provider SDK/device transport` 直接调用均属于 P0 bypass finding。

### 2.3 外发硬门槛

1. `external_ai_enabled`、global/tenant/provider kill switch 和 V2 flag 均必须允许；任一关闭即不外发。
2. Provider、model、data region、scene、role 和 endpoint 通过服务端 allowlist；用户请求不能强制选择未批准模型或旁路 URL。
3. 分类→最小化→tokenize/DLP→payload size→final DLP 顺序不可跳过；发现 SECRET、unsafe context、prompt injection 或不明分类时 BLOCK。
4. 发送前产生 request_id/decision；发送后只保留 bounded result、latency、status、token/cost aggregate 和安全 finding categories。
5. Provider 返回内容同样进行 output safety/redaction；原始响应不能进入日志、数据库 Evidence、前端详情或异常文本。

## 3. Incident Response（事件响应）

### 3.1 事件等级

| 等级 | 触发样例 | 立即动作 | 通知/时限 |
| --- | --- | --- | --- |
| P0 | SECRET 外发、Gateway bypass、跨租户读取、设备写命令、Provider key 泄漏 | 立即 global kill switch、禁用 Provider/V2、暂停相关 job、隔离 incident | on-call + Security + DBA；15 分钟内确认和回滚决定 |
| P1 | DLP/Prompt injection 误放行、错误 source egress、citation/ACL 失效、连续高风险拒绝 | tenant/provider kill switch、quarantine source/generation、保留审计、降低流量 | owner/security 当日处置；24 小时内修复计划 |
| P2 | 单 Provider 不健康、超时/限流、聚合指标异常、可恢复的 parser/queue failure | Provider disable/fallback、retry budget、观察指标 | 当班运维记录并纳入周复盘 |

### 3.2 标准处置流程

**Detect（发现）**

- 从 `ai_security_events`、`ai_security_incidents`、`ai_outbound_audits`、Provider health、job/retrieval/citation 指标和用户报告识别事件。
- 记录 bounded request_id、tenant_id、policy_version、decision、disposition、finding category、provider/model、data_region、时间；不得复制 raw payload、密钥或设备输出。
- 先确认是否为误报、重复事件或单租户影响；禁止在排查中重新发送敏感样本。

**Contain（遏制）**

1. P0 直接启用 global AI Kill Switch；P1/P2 按 tenant/provider/source/job 细粒度停用。
2. `Provider.enabled=false`、V2 mode=off、`AI_RETRIEVAL_FORCE_V1=true`、`KNOWLEDGE_REINDEX_PAUSE=true`，必要时切换 local deterministic/V1。
3. 对 source/document/index generation 标记 quarantined/disabled，保留事实和 observation；停止新外发、embedding、reindex 或设备工具调用。
4. 确认审计写入仍 fail-closed；不能因为审计故障而放行 Gateway。

**Eradicate / Recover（清除与恢复）**

- 轮换/撤销受影响 Provider key、token vault token 或 session；只允许通过受审计的密钥轮换流程，不在聊天/日志中粘贴新密钥。
- 修复根因（allowlist、DLP、权限、parser、source、版本或依赖），增加最小复现和负向测试；同一问题不以扩大异常捕获掩盖。
- 从最近 backup/manifest 和 READY generation 恢复；先在 preprod/影子验证，再按 `0% → internal → canary → gray` 提升。不得删除 V1 数据或篡改 immutable source/document facts。
- 恢复后核对 secret leakage=0、cross-tenant=0、Gateway decision/audit 完整、citation/ACL 通过、Provider health 和延迟稳定。

**Review（复盘）**

- 形成 timeline、影响租户/Provider/scope、检测与响应延迟、根因、证据引用、修复 commit、测试和回滚结果。
- 只导出脱敏 metadata；保留事件 tombstone、audit retention 和权限记录。将新增出口、finding 或控制缺口回写 AUD/SEC/EVAL/REL 合同。

### 3.3 操作授权矩阵

| 操作 | 最低权限 | 是否需二次确认 | 审计 |
| --- | --- | --- | --- |
| 查看聚合安全指标 | `ai.audit.read` | 否 | request_id/actor/tenant |
| 查看有限事件 metadata | `ai.audit.read_sensitive_metadata` | 是 | reason + actor |
| Provider disable/kill switch | `ai.provider.manage` / security on-call | 是 | immutable action ledger |
| V2/reindex pause | `ai.knowledge.manage` + operations | 是 | flag/job state + rollback point |
| 导出事件 | `ai.audit.export` + Security approval | 是 | export scope/expiry/actor |
| 设备写命令 | 独立变更权限 | 必须 | change ticket/command/evidence/rollback；Copilot 默认无此权限 |

## 4. 当前验证、Gap 与发布门槛

**已验证：** PostgreSQL security/coproilot/diagnostics probes、Provider/model ACL/fallback、secret redaction、Gateway block codes、metadata-only events/incidents、kill switch/Provider disable/V2 off/reindex pause、V1 fallback、frontend lint/build 和自动化 security smoke。

**仍需关闭：**

- AUD-016 中新增出口必须持续登记并验证，旧审计仍保留“新增出口需纳入 inventory”的开放项；
- Docker 镜像已对齐 Python 3.11；目标环境仍需完成启动/健康检查；
- REL-013/ING-020/021 可见浏览器安全路径需认证会话；
- MIG-007/015 和 EVAL-018 性能容量阻断在安全发布评审中仍有效；
- 任一 P0 secret egress、bypass、跨租户或设备 write finding 都禁止生产 GO。

## 5. 测试与证据规范

- 数据库安全/租户/审计验收统一使用 PostgreSQL 18；SQLite 明确排除，不可作为证据。
- 每个出口至少有 allow、block、unknown、timeout、redaction、permission 和 fallback 负向测试；Provider test 只能使用固定 PUBLIC 探测。
- CI 运行 secret scan、adapter bypass scan、YAML/compile/lint/build、PostgreSQL transaction/rollback、V1 baseline 和 no-device-write check。
- Evidence 只记录命令、计数、稳定错误码、聚合指标和回滚方式；不得记录密钥、DSN、raw request/response、设备输出。

## 6. 参考合同

- `SEC-001-020-SECURITY-GATEWAY-CONTRACT.yaml`
- `SEC-COP-DIA-POSTGRES-TEST-PLAN.yaml`
- `AUD-016` `audits/external-ai-data-exits.yaml`
- `CAT-004-SECURE-OUTBOUND.yaml`、`ING-003-URL-SECURITY-CONTRACT.yaml`
- `EVAL-007-SECURITY-METRICS-CONTRACT.yaml`、`EVAL-020-SECURITY-GATE-CONTRACT.yaml`
- `REL-009-SECURITY-PATH-GATE-CONTRACT.yaml`、`REL-010-EMERGENCY-CONTROL-RUNBOOK-CONTRACT.yaml`
- `DB-012-TRACE-CITATION-SECURITY-CONTRACT.yaml`
