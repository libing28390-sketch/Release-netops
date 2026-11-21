# DOC-002：Product/OS/Version、Source Governance、Chunking、Retrieval 设计

**Task ID：** DOC-002  
**Milestone：** M2（文档与运营）  
**文档版本：** v1.0  
**盘点日期：** 2026-08-18  
**生产权威：** PostgreSQL；SQLite 不作为验收或生产数据库

本文把网络知识的四个关键设计面连成一条可审计链路：**产品/OS/版本身份 → 官方来源治理 → 结构化 Chunk/Embedding → 租户安全的融合检索**。目标设计与当前已验证实现分开描述；未通过 source、Shadow、发布 Gate 的部分不能直接替换 V1。

## 1. Product / OS / Version 设计

### 1.1 正交实体模型

```text
kb_vendor
  └─ kb_product_family ─ kb_product_series ─ kb_product_model
       └─ kb_product_alias（exact/canonical/prefix/trigram，冲突需裁决）

kb_vendor ─ kb_os_family ─ kb_os_generation
kb_vendor ─ kb_release_train ─ kb_software_version

document_version ── explicit applicability ── product_model
document_version ── explicit applicability ── os_generation + software_version + cli_platform
```

- 产品维度回答“这是哪个厂商/产品族/系列/型号”；OS 维度回答“运行在哪个操作系统代际”；Software 维度回答“属于哪个 release train 和版本”；`cli_platform` 是执行身份，必须来自显式输入或已审核 platform registry。
- Product、OS、release train、version、CLI platform 互相正交。软件版本不能选择驱动，OS 名称不能自动转换为 CLI platform，设备资产的 `devices.version` 不能直接成为知识版本事实。
- `kb_software_version.version_string` 保留原始来源事实；`normalized_version` 是审计过的确定性派生值。版本比较使用 vendor/OS scheme 和 sort key，不做普通字符串排序；范围只能标记为范围，不能假装 exact version。

### 1.2 解析边界

解析结果只有 `unique`、`ambiguous`、`candidates`、`unknown` 四类：

| 结果 | 安全知识范围 | 可做的事 | 禁止的事 |
| --- | --- | --- | --- |
| unique model | vendor/family/series/model | 进行型号级检索、平台与版本过滤 | 无额外澄清 |
| same series 多型号 | series | 返回系列能力并要求 `product_model` 澄清 | 生成型号/平台专属结论 |
| same family 多系列 | family | 返回家族级资料并要求系列/型号 | 推断具体型号 |
| cross-vendor 或 unknown | generic | 请求澄清、返回通用边界 | 目录专属知识、驱动选择、写命令 |

Alias 只能帮助解析候选，不是授权，不从任意正文或型号字符串推导身份。Prefix、trigram、层级命中均为 candidate，必须经过 bounded candidate list（上限 20）和人工/明确上下文裁决。

### 1.3 当前状态与目标状态

**已验证/已落地：** Huawei CloudEngine/VRP、Cisco Catalyst/IOS-XE、H3C Comware、Ruijie RGOS 的目录契约、Alias 冲突边界、unknown/ambiguous fail-closed、V1 metadata compatibility fields 和 PostgreSQL retrieval probes。

**目标/仍需 Gate：** 将全部产品、OS、版本事实迁移到显式 `kb_*` 表；为每个事实保存 source evidence、reviewer、时间和状态；只有 `active` catalog rows 进入 document applicability 和检索；MIG-007 的 156 条 legacy row 在获得 verified source/entity 前不得自动回填。

## 2. Source Governance 设计

### 2.1 Authority chain

```text
CAT allowlist → kb_source_registry → kb_source_version (immutable hash/manifest)
       → document_version → applicability/evidence → published generation
```

- 第一批官方范围是 Huawei Enterprise Support 与 Cisco Documentation 的明确 host/path；每个 source row 绑定 vendor、product scope、version scope、source kind、trust、reviewer 和 evidence。
- 允许的 source kind：`product_support`、`configuration_guide`、`command_reference`、`release_note`；企业 SOP/用户上传资料必须进入独立 collection/trust boundary，不能伪装 official。
- 网络策略 default-deny：仅 HTTPS/443、精确 host、已登记 path prefix；禁止 wildcard、userinfo、fragment、默认 query；每一跳 redirect 都按同一 vendor entry、host 和 path 重新校验，禁止 HTTPS 降级。
- Registry 的 trust 不授权网络设备、Provider 或写命令；Source Registry 只定义来源身份与采集策略，设备写权限仍由诊断/变更控制面管理。

### 2.2 Source lifecycle

| 状态/事实 | 规则 |
| --- | --- |
| draft | 可编辑、不可进入主动检索 |
| validated/active | allowlist、host/path、terms、content hash、parser pin 和人工审核齐全后才可采集/发布 |
| disabled/quarantined | freshness/removal/replacement/安全事件触发；立即排除主动检索，保留事实与观察记录 |
| archived | 保留审计和引用历史，不再作为新答案候选 |

`kb_source_version` 保存 fetched_at、content_hash、byte_size、parser name/version、ETag/Last-Modified 等 immutable manifest；官方 404/410、替代链接、hash 变化走 append-only refresh observation/action，不能直接删除或改写来源事实。源文档发布前必须通过 parser、cleaning、prompt-injection、metadata、entity 和 ACL 检查。

### 2.3 Source/tenant/security 约束

- 所有 registry/version/document 查询由服务端绑定 `tenant_id`；跨租户 source、version、document 或 ACL 不可读写。
- metadata JSON 只能放非权威扩展；不存密码、API key、Bearer token、Cookie、设备凭据、完整请求体或原始异常。
- 未知厂商、未 allowlist host/path、未审核 product/version、无法验证 hash 或 ACL 的来源均 fail-closed 并进入 review/quarantine，不调用 LLM“补全”事实。
- Source collection 只读；不允许从知识导入链路触达网络设备写命令。

## 3. Chunking / Embedding 设计

### 3.1 Parser 到 Chunk 的阶段边界

```text
bytes → parse (HTML/Markdown/TXT/PDF)
      → clean/security scan → metadata/entity resolve
      → structure blocks → parent/child chunks → embedding → index
      → validation → published generation
```

Parser 只负责字节有界、格式识别、结构块和 locator；不做清洗、发布或身份推断。输入上限 20 MB，格式/magic/编码不匹配、控制字节、损坏 Front Matter 均以稳定安全错误结束；错误不携带正文、路径、依赖异常或 secret。

### 3.2 结构化 Chunk 规则

| 结构 | 规则 | 检索角色 |
| --- | --- | --- |
| heading | 保留 heading path、层级和 locator | heading/context |
| paragraph/table/warning/prerequisite/example | 作为语义单元，保留来源定位 | standalone 或 child |
| cli | 命令与 continuation 必须同块，不能跨段拆开 | standalone/child |
| output | 无已知记录边界时整体保留，避免把输出拆坏 | standalone/child |
| parent/child | child 必须挂到已有 parent；parent 默认不是 retrieval candidate | child 作为候选，parent 仅补上下文 |
| neighbor | 明确 next/previous edge；禁止 self edge；ordinal 仅展示顺序 | 召回后补相邻上下文 |

Chunk 内容必须有 `content_hash`、structure type、heading path、source locator、token count、size class 和 parser/chunker/document/index version。空 chunk、重复 hash、无效 role/structure 拒绝；oversize 只能在 atomic CLI/output 或有记录的 reason 下保留。每个 generation 可重建、可校验、可回滚。

### 3.3 Embedding 与索引

- Embedding contract 绑定 provider/model、dimension、contract version、mode 和 content hash；向量维度与 pgvector typmod、查询维度必须一致，静默 mismatch 拒绝或 score=0 并计数。
- External embedding 仅可经 `AISecurityGateway.protect_embedding`，执行分类、最小化、tokenization、DLP 和脱敏审计；provider 失败、超时、限流使用 bounded retry，不做部分持久化。
- Lexical/FTS、pg_trgm、vector index 均有显式 `index_version`/`generation_no`；只有 validated READY generation 可进入主动检索。重建失败时保留旧 generation，切换 pointer 是原子且可回退。
- V1 `ai_document`/`ai_document_chunk` 的新增 projection columns 是 additive compatibility，不等价于 DB-001 全部 canonical graph tables 已物理化。

## 4. Retrieval 设计

### 4.1 请求与硬过滤顺序

```text
authenticate → tenant/ACL scope → normalize query
  → resolve product/OS/version (unique/candidate/unknown)
  → hard filters → lexical/vector candidates
  → metadata/trust/version fusion → bounded reranker
  → context expansion → citation validation → answer/fallback
```

硬过滤先于打分，至少包括：tenant、collection/ACL、lifecycle/status、vendor/product family/series/model、OS/generation/CLI platform、software train/release、official/trust 和 document category。硬过滤失败不能靠 reranker 或 LLM 补救。

### 4.2 排序、候选和上下文

- 默认融合权重：lexical 0.45、vector 0.25、metadata 0.15、trust 0.10、version 0.05；权重和实现必须确定性、可解释、可观测。
- 候选最多 20；reranker 超时上限 5 秒，失败返回原始顺序并记录 degradation，不阻塞 V1 fallback。
- context 由 primary、parent、immediate neighbor 组成，按类别有硬字符预算；不把超预算原文全量发送 Provider。
- cache 默认关闭；开启时 key 必须包含 query/filter/document version/metadata/index/access scope/tenant，document disable/update、权限变化、租户变化立即失效。

### 4.3 Ambiguous、No Match 与 Citation

- `ambiguous`：返回 bounded candidates 和澄清字段；高风险回答阻断；不选一个“看起来最像”的厂商/型号。
- `unknown/no_match`：显式本地知识缺口，不能调用 LLM 编造本地事实；可以返回需要的 source/version/设备信息。
- Citation 必须绑定 document version、chunk、content hash、locator、trust/official、lifecycle 和 ACL 校验。任何一步失败都标记 non-verified，答案不得声称 verified fact。
- Retrieval explanation 只含 filters、candidate count、stage、score components、version evidence、no_match；排除 raw query、raw SQL、Provider secret 和未脱敏正文。

### 4.4 多租户与回退

服务端始终重建 tenant/ACL scope，前端传入的 tenant/filter 只能作为请求意图，不能扩大权限。V2 retrieval 失败、索引 generation 不 READY、Provider/Gateway 不可用或引用未验证时，走 V1/本地 deterministic fallback 或安全拒答；不删除 V1 数据、不绕过 Gateway、不执行设备写命令。

## 5. 端到端验收与可观测性

DOC-002 的设计验收必须覆盖：

1. Product/OS/version unique、ambiguous、unknown、version conflict 和 vendor conflict；
2. allowlist host/path、redirect、source kind、refresh/removal、tenant/ACL 和 secret redaction；
3. HTML/Markdown/TXT/PDF parser boundary、CLI/output atomicity、parent/child、neighbor、duplicate/oversize、dimension mismatch；
4. FTS/trigram/vector 融合、hard filter、candidate cap、reranker timeout、no match、citation validation、cache invalidation；
5. PostgreSQL transaction/tenant isolation/EXPLAIN、V1 baseline、lint/build/YAML/secret/diff gates。

所有数据库验收使用 PostgreSQL；文档/静态测试可以不连接数据库，但必须明确 `database_probe=not_applicable`，不得用 SQLite 结果替代 PostgreSQL 证据。观测只写 bounded metadata 和聚合指标，禁止 raw query/body/SQL/credential。

## 6. 当前差距与恢复顺序

- `MIG-007` 解除前，不能将 156 条 legacy rows 自动映射为 active product/source/version 或生成 V2 index；
- `MIG-015` 需要 active generation 和至少 30 条 comparable Shadow samples；
- `ING-020/021` 和 `REL-013` 的浏览器页面验证需要认证会话；
- 大样本 trigram P95 capacity warning 需按 EVAL-018 重新优化和评测；
- DOC-003～DOC-010 继续补充 Security、DBA/OPS、QA、Copilot、知识管理员和运营手册。

恢复点：完成 DOC-002 后进入 `DOC-003`；source/entity、Shadow、runtime 和 browser blockers 继续保留在执行状态文件中。

## 7. 参考合同

- `CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml`、`CAT-012-MODEL-AMBIGUITY-BOUNDARY.yaml`
- `DB-006-PRODUCT-CATALOG-STRUCTURE.yaml`、`DB-007-OS-SOFTWARE-STRUCTURE.yaml`、`DB-008-SOURCE-REGISTRY-CONTRACT.yaml`
- `ING-001-INGESTION-PIPELINE-CONTRACT.yaml`、`ING-006-DOCUMENT-PARSER-CONTRACT.yaml`
- `CHK-P0-12-CHUNK-EMBEDDING-CONTRACT.yaml`
- `RET-004-007-PRODUCT-RESOLUTION-CONTRACT.yaml`、`RET-011-020-RETRIEVAL-CONTRACT.yaml`
- `CIT-001-010-GROUNDING-CONTRACT.yaml`、`DB-012-TRACE-CITATION-SECURITY-CONTRACT.yaml`
