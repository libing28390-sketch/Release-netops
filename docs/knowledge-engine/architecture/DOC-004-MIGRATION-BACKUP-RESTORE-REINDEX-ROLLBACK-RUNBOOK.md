# DOC-004：Migration、Backup、Restore、Reindex、Rollback Runbook

**Task ID：** DOC-004  
**Owner：** DBA + OPS  
**版本：** v1.0（2026-08-18）  
**生产数据库：** PostgreSQL 18；SQLite 不作为生产或验收证据

本 Runbook 是 V2 变更的操作顺序和停机/回退边界。它不能授权生产执行；每次真实生产操作仍需变更单、审批、维护窗口、备份成功证据和回滚负责人。任何步骤出现未预期错误，默认停止 V2 写入/切换，保留 V1 和旧 READY generation，记录稳定错误码后再处理。

## 1. 总体安全边界

- PostgreSQL 是唯一生产权威；`DATABASE_URL` 只从受保护运行环境读取，不写入命令历史、日志、Evidence、manifest 或聊天。
- Migration 只允许 additive、事务化、幂等和可审计变更；禁止删除 V1 表、原始 source/document facts、旧 generation 或 migration history。
- 备份必须同时有 `pg_dump` custom/compressed dump、脱敏 Source Manifest 和配置 bundle；缺任一项视为备份不完整。
- Restore rehearsal 只能到明确的隔离 PostgreSQL 数据库/路径；禁止把演练目标解析为生产数据库。
- Reindex 使用稳定主键 keyset、租约 fencing、bounded batch、私有 checkpoint 和幂等 document replace；不使用 OFFSET、不把全量 corpus 载入内存、不暴露 cursor/lease token。
- V2 通过 flag、READY generation、Provider/Kill Switch 回退；不通过删除数据或 destructive downgrade 回退。

## 2. 角色和准备

| 角色 | 责任 | 必须签署 |
| --- | --- | --- |
| Change owner | 变更单、范围、窗口、停止条件 | migration/rollback plan |
| DBA | PostgreSQL 连接、迁移、备份、restore probe、锁/容量观察 | schema/backup/restore |
| OPS | 服务编排、worker/lease、flags、日志和回滚计时 | runtime/rollback |
| QA | V1 baseline、回归、验证 SQL/报告、证据完整性 | test gate |
| Security | secret/egress/权限/审计和事件响应 | security gate |

### 2.1 Preflight（所有操作前）

1. 确认 branch/release manifest、应用版本、migration head、PostgreSQL 版本/扩展（`vector 0.8.6`、`pg_trgm 1.6`）和 feature flags；V2 默认 `off/0%/write=false`。
2. 确认工作目录、备份目录和日志目录权限为 owner-only（Windows 等价 ACL），磁盘空间足够，临时 restore DB 名称唯一且不在生产 allowlist。
3. 确认当前 V1 PostgreSQL baseline、health/readiness、Provider health、active READY generation、reindex backlog、security incidents 和最近备份均可读。
4. 确认变更不涉及真实网络设备写命令；诊断/采集 outbound 仍 default-deny/GET-HEAD only。
5. 在变更单记录 `request_id/deployment_id/change_id` 和 rollback owner；不记录 DSN、密码、API key、原始文档或设备输出。

## 3. Migration Runbook

### 3.1 Fresh / upgrade 预检查

```text
read migration manifest and expected head
connect using protected DATABASE_URL
check current schema_migrations and PostgreSQL extensions (read only)
check V1 row counts/hashes and active READY generation (read only)
```

预检查失败（数据库不可达、扩展版本不符、history drift、未知 migration、V1 baseline 变化或 blocker 未清除）时不得继续。MIG-007 未有 verified source/entity、MIG-015 无 Shadow samples、REL runtime 未对齐时只能做契约/临时库演练，不能 apply production V2。

### 3.2 执行顺序

1. 先生成并验证备份 + manifest（第 4 节），再锁定 maintenance/worker scope。
2. 按 manifest 顺序执行 migration；每个 migration 在 PostgreSQL transaction 中完成，成功后记录 version、duration、row/index/constraint 摘要。
3. 检查重复执行为 no-op；检查 `schema_migrations` 无 gap、unknown、name drift；所有租户 FK/unique/check/index 完整。
4. 新列/索引先 additive；旧 V1 reader 能继续读，V2 writer 受 flag 控制。不要在同一变更里删除旧列/重写原始事实。
5. 运行 migration-specific PostgreSQL probe、V1 baseline、AI/security/retrieval 回归和 readiness；所有报告只写聚合计数和稳定错误。
6. 只有 Gate 通过才可把 migration 状态标为 verified；否则状态 failed/blocked，保留数据库和日志供诊断，不伪造成功。

### 3.3 Migration 失败处理

- 事务内失败：等待 rollback 完成，确认 `schema_migrations`、目标表、索引、约束恢复到 preflight；不能人工删除半成品。
- 事务外/锁等待/worker 丢失：停止 V2 worker，保留旧 generation，使用 lock/lease owner fencing；必要时通过运维审批终止阻塞 session。
- 数据完整性失败：不做自动 repair；标记 job failed/quarantined，使用 manifest/hash 对比，修复后重新 dry-run/retry。
- 连续三次同方案失败后更换排查路径（锁/容量/版本/权限/代码），不重复盲执行。

## 4. Backup Runbook

### 4.1 PostgreSQL dump

1. 创建权限私有的备份目录和唯一 backup id；不覆盖已有 dump。
2. 使用环境提供的 `DATABASE_URL` 执行 `pg_dump --format=custom --no-owner --file=<explicit-private-path>`；密码不进入参数、输出或日志。
3. 记录 dump 文件大小、sha256、PostgreSQL/server version、schema head、backup id、created_at；不记录 URL/tenant/name/raw source。
4. 使用项目 manifest generator 读取允许的 `ai_document`、`ai_document_chunk`、`schema_migrations` 摘要，生成 `nexora-knowledge-source-manifest/v2` companion。

### 4.2 Manifest 必须包含/排除

**包含：** schema version、document/chunk count、deterministic sorted digest、content/metadata/source/vendor/platform/tenant hashes、status、trust、updated_at 和 redaction markers。  
**排除：** raw document id/name/source/path/url/content/metadata/tenant id、Provider secret、password、DSN、prompt、设备输出。

### 4.3 配置 bundle

只备份受保护的配置文件权限/版本 marker（例如 owner-only 0600 等价 ACL）；报告只验证 key presence、schema 和 secret reference，不复制配置值。备份完成后做独立 hash/权限检查并保存 Evidence。

### 4.4 备份失败

Dump、manifest 或 config 任一失败，backup 状态为 incomplete；删除/隔离本次显式 partial artifacts（不触碰旧备份），修复后重新生成。禁止用“只有 dump 没 manifest”进入 migration 或 release。

## 5. Restore Rehearsal Runbook

1. 由 DBA 创建一次性、显式命名的隔离 PostgreSQL rehearsal database/role；通过 allowlist 证明目标不属于 production。
2. 使用 `pg_restore` 导入 custom dump；不执行生产 endpoint、不覆盖现有 rehearsal 之外的数据库。
3. 执行 integrity check、schema/migration head、extension version、document/chunk count、tenant scope、V1 facts hash 和 manifest digest 对比。
4. 运行 V1 PostgreSQL baseline、V2 read-only retrieval/citation、security redaction、migration startup 和 rollback probe；禁止外部 Provider/设备写入。
5. 把 restore 报告与原 manifest/dump hash 关联。任何 count/hash/schema mismatch 都是失败，不允许人工改报告。
6. 复盘完成后按保留策略清理 rehearsal database 和临时文件；清理对象必须是本次明确创建的隔离资源，旧备份不可删除。

## 6. Reindex Runbook

### 6.1 任务启动

1. 校验 `ai.knowledge.manage`、tenant scope、job kind、scope fingerprint、idempotency key、V2 flag 和 source/document/index 状态。
2. 任务初始 `queued`，服务端维护 counters；客户端不能写 counters、cursor、lease owner 或 tenant。
3. worker 以 `knowledge_reindex:<job_id>` 在 `scheduler_locks` 取得 opaque owner token 和过期时间（默认 900 秒）；第二 worker 只读返回当前快照，不修改任务。

### 6.2 批处理与租约

- 通过 `WHERE d.id > :last_id ORDER BY d.id LIMIT :batch_size` keyset 读取，batch 1～5000（默认 250），不使用 OFFSET/全量 materialization。
- 每个 document/batch 前 heartbeat；只有匹配 owner token 才可 renew/release。失去 lease → `retry_wait`，从最近已提交 checkpoint 恢复。
- 单文档在事务内幂等 replace derived generation；source/document facts 不删除、不改写；batch 只有 terminal outcomes 后才能提交 checkpoint。
- cancel 请求在安全点确认；重复 cancel 幂等；当前文档完成或重试，不启动新 batch。
- 错误使用 stable code/phase/item/attempt/retryable/correlation_id；禁止 raw body、DSN、credential、设备输出和依赖异常。

### 6.3 成功/失败/暂停

- 成功：`succeeded`，processed=total，generation/index validation 通过，记录 READY pointer 和聚合 metrics。
- 可重试：`retry_wait`，保留 checkpoint/retry count；超过预算 → `failed`，不伪造 completed。
- 暂停/kill switch：停止新 batch，保留旧 READY generation 和 V1 read path；恢复时先验证 lease/checkpoint，再继续。
- partial persistence、第二 worker 并发写、跨租户 scope 或未验证 embedding dimension 均为失败。

## 7. Rollback Runbook

### 7.1 决策条件

出现 migration/schema drift、wrong vendor/version conflict、citation/ACL 失败、secret/DLP event、Provider 级故障、trigram 延迟超阈值、reindex corruption、租户泄漏或 V1 baseline regression，立即暂停 rollout，按事件等级决定回退。

### 7.2 快速 runtime rollback（首选）

1. `AI_RETRIEVAL_V2_KILL_SWITCH=true` / `AI_RETRIEVAL_FORCE_V1=true`；V2 mode off、rollout 0、writes false。
2. `KNOWLEDGE_REINDEX_PAUSE=true`，暂停/取消新 job；Provider 逐级 disable 或 global AI kill switch，恢复 local deterministic/V1 fallback。
3. active index pointer 指向最近已验证 READY generation；不删除新 generation，保留其 audit/incident 供调查。
4. 运行 readiness、V1 PostgreSQL baseline、security/Citation/tenant checks；确认用户答案不再使用异常 V2。

### 7.3 应用/Schema rollback

- 应用版本回退必须能读取当前 additive schema；禁止先 downgrade schema 再回退应用。
- 只有经过批准、非破坏性 forward-fix/downgrade 才可执行；不能删除 source facts、V1 rows、migration history、audit tombstones 或被引用 generation。
- 如果无法证明 schema 回退安全，保持 schema、关闭 V2 flags，修复新版本后再部署；这是可接受的安全回退。

### 7.4 恢复后验证

检查 migration head/history、V1 facts/hash、active READY generation、tenant/ACL、security events、Provider health、reindex counters、backup/manifest digest、front-end/API smoke。记录 rollback start/end、决策人、影响范围、原因、测试、剩余风险和下一次 Gate；不以“服务已启动”代替恢复成功。

## 8. Gate 与证据

每次执行必须保存：preflight、backup/dump/manifest hash、migration output、restore rehearsal、reindex job snapshot、rollback decision、V1 baseline、PostgreSQL probe、security check、权限/审计和 cleanup 结果。Evidence 不含 secret、DSN、raw body、raw SQL 或设备输出。

DOC-004 本身是文档任务，无 DDL、无数据库写入、无外部调用、无设备写入；真实生产操作必须通过 REL/MIG/DB 对应 Gate。SQLite 兼容 fixture 即使存在，也不计入本 Runbook 的验收。

## 9. 参考合同

- `DB-017-MIGRATION-ORDER-CONTRACT.yaml`、`DB-018-IDEMPOTENT-FRESH-SYNC-CONTRACT.yaml`、`DB-019-UPGRADE-TEST-CONTRACT.yaml`、`DB-020-FRESH-FAILURE-ROLLBACK-CONTRACT.yaml`
- `DB-022-REINDEX-BATCH-LEASE-CONTRACT.yaml`、`DB-023-BACKUP-MANIFEST-RESTORE-CONTRACT.yaml`
- `MIG-013-FAST-V1-ROLLBACK-CONTRACT.yaml`、`MIG-014-ROLLBACK-COMPATIBILITY-CONTRACT.yaml`
- `REL-002-POSTGRES-MIGRATION-STARTUP.yaml`、`REL-006-BACKUP-MANIFEST-CONTRACT.yaml`、`REL-010-EMERGENCY-CONTROL-RUNBOOK-CONTRACT.yaml`
