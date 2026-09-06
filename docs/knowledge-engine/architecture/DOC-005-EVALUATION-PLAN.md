# DOC-005：Evaluation Plan、固定测试集版本与质量报告模板

**Task ID：** DOC-005  
**Owner：** QA  
**版本：** v1.0（2026-08-18）  
**数据库权威：** PostgreSQL 18；SQLite 不作为验收证据

本文定义 Nexora Knowledge Engine V2 的固定评测集、执行顺序、指标、硬门槛、质量报告字段和失败处理。离线 fixture 可不连接数据库；任何 database-backed evaluation、retrieval、tenant、migration 或性能验证均必须使用 PostgreSQL 临时/批准环境，禁止用 SQLite 结果替代。

## 1. 评测目标与执行层级

| 层级 | 目的 | 数据/环境 | 触发 | 发布含义 |
| --- | --- | --- | --- | --- |
| Contract/static | 验证 schema、标签、指标公式、脱敏和可重复性 | checked-in offline fixtures；无数据库/网络 | 每次修改合同 | 失败即不能进入下一层 |
| Small CI | 低延迟发现 query/type/metric/security 回归 | EVAL-001/003/005/007，offline；PostgreSQL service 仅供相关 CI wrapper | PR/main push | strict non-zero 阻断合并 |
| Full release | 统一跑 EVAL-001～008 和 fixed annotations | offline fixed set；无外网 | release candidate | 任一组件非 PASS 禁止 release |
| PostgreSQL integration | 检索、租户、ACL、Provider、migration、citation、rollback | 临时/预生产 PostgreSQL；无生产写入 | milestone/release Gate | 需要 transaction/cleanup/V1 regression |
| Performance/stability | 10k/100k/1m、reindex、SSE、Provider cycles | PostgreSQL 临时会话/批准 staging | release review | warning 必须透明记录；硬门槛按合同决定 |
| Browser/manual | 登录、Provider、模型切换、检索、引用、Copilot、安全阻断 | 已认证浏览器 + 本地/preprod | post-release smoke | 未认证只能标 BLOCKED，不得伪造 PASS |

### 1.1 统一执行顺序

`dataset/schema → intent/version → metrics → security → golden annotations → offline strict → PostgreSQL integration → performance/stability → browser smoke`。失败时保留原始固定集和报告，修复后从失败组件重跑并执行相关回归；不删除测试或降低阈值。

## 2. 固定测试集版本（不可静默修改）

| Fixture | ID/版本 | 当前内容 | 规则 |
| --- | --- | --- | --- |
| Query dataset | `nexora-kb-eval-v1-20260817` / schema 1 | 120 cases，EVAL-Q001～Q120；Huawei/Cisco × VLAN/Interface/OSPF/SSH/NTP/Route；exact/alias/prefix/ambiguous/typo/wrong_vendor/product_conflict/version/no_match | case id、gold ids、标签冻结；变更创建 v2，不覆盖 v1 |
| Security cases | `nexora-kb-eval-security-cases-v1-20260817` / schema 1 | 9 synthetic cases：secret、prompt injection、authorization、outbound | synthetic parts only；不是真实密钥；不输出匹配值 |
| Golden annotations | `nexora-kb-eval-golden-v1-20260817` | 12 条 Huawei/Cisco × 6 intents；答案、applicability、official locator、version relation | 双人复核/争议 adjudication 后 frozen；变更新 annotation_set_id |
| V1 baseline | `nexora-kb-v1-20260809` | 10 条当前 V1 PostgreSQL baseline；retrieval/citation/wrong-vendor/version/latency | 作为回归比较，不因 V2 变更覆盖；重新采样需新 baseline id |
| Offline report | `eval-offline-report-v1.json` | EVAL-001～008 八组件 strict report | canonical report hash；generated_at/random_seed 置空以保证可重复 |
| Performance sample | EVAL-018 10k/100k/1m | FTS/trigram/vector，Top-K=10，p50/p95/p99 | PostgreSQL temporary session；记录 warning，不隐藏 1m trigram 超目标 |

固定集文件和 manifest：

- `docs/knowledge-engine/eval/eval-query-dataset-v1.yaml` / `.manifest.json`；
- `docs/knowledge-engine/eval/eval-security-cases-v1.yaml`；
- `docs/knowledge-engine/eval/eval-golden-annotations-v1.yaml` / `.manifest.json`；
- `docs/knowledge-engine/eval/v1-baseline-cases.yaml` / `v1-baseline-results.json`；
- `docs/knowledge-engine/eval/eval-offline-report-v1.json`。

## 3. 指标、标签与硬门槛

### 3.1 检索与实体指标

- `Recall@K = unique(topK) ∩ Gold / Gold`；`Precision@K` 分母固定为 K；`MRR` 为首个 unique relevant 的倒数；`NDCG@K` 使用 binary unique relevance。
- `Entity Resolution Accuracy` 要求 query 的所有期望/预测实体字段一致；unknown 期望时预测具体值视为错误。
- Product/OS/Version Match 使用 EVAL-006；version exact 必须 relation 和 release 同时匹配；conflict/unknown 不得伪造 exact。
- Wrong Vendor rate = 错误/意外厂商预测数 ÷ 全部 cases；ambiguous case 任意猜厂商都算错误。

### 3.2 引用与安全指标

- Official Source rate：answer case 至少一条 citation 且全部 official；非 answer 应无 citation。
- Citation Accuracy：answer citation 非空、属于 Gold 且至少命中一条；clarify/no_match 必须空 citation。
- Secret leakage、prompt-injection block、authorization violation、outbound policy compliance 按 EVAL-007 公式计算；报告只写 counts/rates，不写匹配值。

### 3.3 发布硬门槛

| 门槛 | 目标/判定 | 失败动作 |
| --- | --- | --- |
| Wrong vendor | 0；ambiguous 不得猜 | 立即阻断，保留 V1 |
| Version conflict | 0 个未经澄清的冲突答案 | 阻断相关 scope，检查 hard filter |
| Citation | answer 必须 official/Gold/locator 可验证 | 阻断答案发布，降级 no_match/clarify |
| Secret egress | 0 | global kill switch、Provider disable、P0 incident |
| Unauthorized execution | 0 executed unauthorized action | 立即停 Agent/diagnostic route，审计和回退 |
| Outbound compliance | 100% sent requests allowed + sanitized；deny 不得发送 | Gateway fail-closed、bypass scan |
| Tenant leakage | 0 | P0，隔离租户和数据库 scope |
| V1 preservation | V1 baseline 不回归；V1 route/data intact | V2 off/Force V1，禁止 cutover |
| Performance | EVAL-018 各规模/路径都有 p50/p95/p99；超 3000ms 记录 warning | release gate 保持关闭，不能平均/隐藏 |

阈值若需变更，必须新建合同/版本、说明理由和回归影响，不能修改历史报告期待值。

## 4. 质量报告模板

标准模板：`docs/knowledge-engine/eval/quality-report-template-v1.md`。每份报告必须包含：

1. **Identity**：report id、task/release、fixture ids + sha256、code commit、environment/deployment id、PostgreSQL version/extension（适用时）；
2. **Scope**：small/full/integration/performance/browser、tenant scope、case count、excluded cases 和原因；
3. **Results**：组件 PASS/FAIL/BLOCKED、指标 counts/rates/p50/p95/p99、Gold/citation/tenant/security 结果；
4. **Hard gates**：每项 PASS/FAIL、threshold、observed、evidence link、阻断码；
5. **Regression**：V1 baseline 对比、API/UI/build/lint、migration/rollback、previous READY generation；
6. **Incidents and deviations**：稳定 error code、request/correlation id 的 hash/opaque projection、是否触发 kill switch；不写 raw payload；
7. **Decision**：GO / CONDITIONAL / NO-GO / BLOCKED，owner、reviewer、时间、恢复点；
8. **Reproducibility**：命令、Python/Node/DB versions、random_seed、generated_at policy、report hash；
9. **Safety**：database authority、SQLite policy、external network、production write、device write、secret scan；
10. **Rollback**：flag、Provider disable、V1 fallback、READY generation、DB restore/cleanup 和 SLA。

报告状态语义：`PASS` 仅表示所有 required checks 通过；`PASS_WITH_WARNING` 必须列出不影响当前 Gate 的 warning；`BLOCKED` 表示外部条件/认证/样本缺失，不得勾选任务；`FAIL` 表示有可修复失败，必须修复后重跑。

## 5. PostgreSQL 与安全执行要求

- Offline fixture/metric runner 不连接数据库、不调用网络、不写生产；其报告必须写 `database=none`、`sqlite=not_used`。
- Database-backed evaluation 只允许 PostgreSQL 临时/批准 staging，transaction rollback 或显式 cleanup；SQLite 结果不得计入 acceptance。
- 所有报告、日志、Trace、citation projection 和 error response 禁止 secret、DSN、raw SQL、raw prompt、raw provider response、raw source/document body 和设备输出。
- 浏览器未认证、Provider credential 缺失、source verified entity 缺失或 Shadow sample 不足时，状态为 BLOCKED 并写解除条件；不得用静态或离线 PASS 覆盖可见路径。

## 6. 失败恢复与版本策略

1. 先重现单组件，再执行最小修复、单测、相关回归、全 profile；同方案连续失败 3 次后更换根因假设。
2. 固定 v1 fixture 只读；错误标签、Gold citation、阈值变更使用新版本和新 manifest。
3. 质量下降、泄漏、wrong vendor、citation/ACL 失败时，切换 V2 off/Force V1，保留旧 generation 和审计，不删除数据。
4. 报告和 Evidence 与 checklist/state 同步更新；没有报告、命令、关键输出和安全/回滚结论不能标 DONE。

## 7. 参考合同

- `EVAL-001-FIXED-QUERY-DATASET-CONTRACT.yaml` ～ `EVAL-010-CI-RELEASE-GATE-CONTRACT.yaml`
- `EVAL-011-PROVIDER-MODEL-SECURITY-CONTRACT.yaml`、`EVAL-013-RETRIEVAL-CITATION-CONTRACT.yaml`
- `EVAL-017-BROWSER-KEYPATH-CONTRACT.yaml`、`EVAL-018-PERFORMANCE-CONTRACT.yaml`、`EVAL-020-SECURITY-GATE-CONTRACT.yaml`
- `REL-007-RELEASE-QUALITY-GATE.yaml`、`REL-013-POST-RELEASE-SMOKE-CONTRACT.yaml`
