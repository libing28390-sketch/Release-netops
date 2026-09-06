# AI/RAG 整改预发布说明与迁移/回滚须知

日期：2026-09-03（最后复核：2026-09-05）
状态：`HOLD — NOT A RELEASE CANDIDATE`

本说明与 [AI/RAG 配置、Kill Switch 与回滚清单](../knowledge-engine/runbooks/AI-RAG-RELEASE-CONFIG-AND-ROLLBACK-20260903.md) 配套。当前工作区完成了主要代码和自动化门禁；400 条评测集已按用户确认切换为 `official_url_backed_local_summary` 官方来源自动校验策略，不要求人工 Gold 审核；50-anchor 已由用户明确授权完成批次签字并切换到新的冻结 v3，但仍受来源反查、脱敏、PostgreSQL-only 和检索质量门禁约束。m0204～m0208 已合入本地 `main`，本地严格迁移与开发启动已通过。真实 sidecar、CI 实跑、Provider live sample、浏览器 UAT、生产迁移/回滚和 Release Candidate 尚未完成，禁止将数据来源门禁或本说明解释为生产放行。

## 已交付的代码范围

- 50 条锚点评测已经从“业务状态通过”改为安全门禁与质量门禁分离，并纳入 Gold 命中、Recall、MRR、NDCG、引用身份代理、延迟和错误率。
- Reranker、Docling、Langfuse 的边界适配、超时、白名单、降级和 metadata-only 契约已接入；默认仍为 legacy/off，Shadow 不覆盖生产 baseline。
- 迁移 0202 增加实验运行、案例结果、灰度指针和 Shadow 观察的 PostgreSQL-only 持久化；m0204～m0208 已补齐官方模板并与配套投影链路一起进入本地 `main`；OBS-002 API/UI 只展示脱敏摘要。
- Promptfoo 已固定 Node 22.22.2 / Promptfoo 0.118.0 的独立 CI 工作流，并复用仓库内带 pgvector/pg_trgm 的 PostgreSQL CI 镜像；本机验证不替代 GitHub Actions 实跑证据。

## 当前验证证据

| 门禁 | 结果 |
| --- | --- |
| `pytest backend/tests/ai -q` | `553 passed`（当前代码最新回归证据） |
| `pytest backend/tests -q` | `1764 passed, 26 subtests passed，退出码 0；隔离 PostgreSQL 本次复核` |
| 前端全量 Vitest | `53 files / 195 passed` |
| 前端 KUI/OBS-002 定向测试 | `5 passed` |
| `npm run lint` | `PASS` |
| `npm run build` | `PASS`，`4265 modules transformed` |
| PostgreSQL-only 扫描 | `0 violation(s) PASS` |
| CI 配置静态检查 | `PASS` |
| 50 条真实锚点评测 | 当前签字冻结 v3：标准/隔离均 `safety=PASS, quality=PASS, overall=PASS`；50/50，Recall@5/10=`1.0`，Citation Precision=`0.9643`、Citation Recall=`1.0`。旧 v1 的 39/50 与候选 v2 均保留作对比 |
| 50 条 Gold 审核 | 签字 v3：`review=PASS`、`gold=PASS`、50/50 `annotation_status=approved`、`missing_review=0`、`unresolved_gold=0`；审核人为 `libing28390-sketch` |
| 400 条官方来源自动检查 | 普通合同检查和 `--require-production` 均 `PASS`，`case_count=400`，answer 来源证据 `300/300`；`human_review_required=false` |
| 400 条隔离 PostgreSQL 直连检索 | `300` 条 answer：Recall@5/10=`1.0`、MRR=`1.0`、厂商/Feature 污染 `0`；100 条 clarify/no-match 未调用低层检索 |

## 迁移说明

1. 生产迁移前确认 `DATABASE_URL` 为 PostgreSQL，并完成备份、恢复点和当前 `schema_migrations` 版本记录。
2. 使用标准迁移入口执行升级；迁移 `m0202_ai_experiment_observability.py` 创建四张表和租户/状态/过期索引，使用 `JSONB`，不修改现有 `ai_document`、`ai_document_chunk` 的权威语义。
3. 在隔离 PostgreSQL 先验证新库初始化、旧库升级、重复执行幂等、约束和租户隔离；当前仓库只具备隔离测试证据，尚无生产旧库演练证据。
4. 迁移失败必须由事务回滚处理；不得手工删除表、实验记录、审计记录、原始文档或旧 Chunk 来“恢复”。
5. 升级后确认四张表存在、`schema_migrations` 已到最新版本、旧文档/Chunk 计数不下降，再启用只读 OBS-002 查询。

迁移的 `downgrade` 保持实验和审计证据，不执行删除式回退。发布回滚通过恢复上一版本代码/配置、关闭新组件和恢复 baseline 指针完成；不能把 downgrade 当作删除新表的清理脚本。

## 回滚与 Kill Switch

- Provider 异常：先禁用单个 Provider；必要时执行租户 Kill Switch，再扩大到全局 Kill Switch。
- Reranker/Parser：设置为 `legacy`；灰度表将 `kill_switch` 设为 `true`，生产结果继续使用 baseline。
- Langfuse：设置 `AI_OBSERVABILITY_MODE=off`；导出故障不得阻断主请求。
- 重建任务：停止 worker/scheduler，等待 PostgreSQL lease 过期，从最后一个已提交批次恢复；不修改私有 cursor。
- 恢复前必须有 health/ready、安全审计、数据完整性和事件号；未经质量门禁批准，不得直接恢复 `active`。

## 已知限制与发布阻断

- 当前严格 50-anchor 输入为签字冻结 v3：[eval-golden-anchors-50-v3-signed-20260905.yaml](../knowledge-engine/eval/eval-golden-anchors-50-v3-signed-20260905.yaml)。只读审核报告为 `review=PASS/gold=PASS`，50 条审核字段齐全，所有 acceptable Gold ID 均在 PostgreSQL 官方投影中解析；标准/隔离 runner 均为 `50/50 PASS`。旧 v1 的 39/50、候选 v2 和签字 v3 均保留，签字动作由用户明确授权执行，不表示独立第二审核人复核。
- 400 条数据不以人工审核作为门槛；当前 `eval-golden-400.yaml` 是官方 URL 支撑的自动生成 Dataset，answer 用例的来源证据必须反查到 `data/kb_import/manifest.json`，普通模式和 `--require-production` 均通过。隔离 runner 已对 300 条 answer 完成真实 PostgreSQL + RAGRetriever 直连测量并通过；100 条 guard、完整 Assistant/Citation 链路、真实版本冲突和生产语料仍未由该 runner 覆盖。
- BGE、Docling、Langfuse 真实服务、模型加载和资源验收尚未完成；Docker/Windows/pgvector 运行态及迁移 104 已按用户要求暂记完成，后续由用户独立验证。
- Qwen/Ollama 已移出本轮任务和发布门禁；本轮不部署、不配置、不验证，后续如需纳入另建独立任务。纳入本轮范围的 Provider 真实业务会话和错误矩阵尚未授权/执行。
- 浏览器已登录会话完成部分只读 UAT（含本地命中、澄清、no-match、Provider 兜底和高风险确认边界）；逐案例元数据见 [eval-browser-uat-live-20260904.md](../knowledge-engine/eval/eval-browser-uat-live-20260904.md)，但完整 UAT-001、5%→20%→50% 灰度观察、旧库升级/失败回滚演练和可追溯 Git Commit/RC 标签尚未完成。

因此当前发布结论为 `HOLD`。完成上述阻断后，必须重新生成评测报告、baseline manifest、迁移/回滚记录和发布候选，再按[当前 AI/RAG 发布剩余任务清单](../plans/plan_20260905_2257_01_AI发布剩余任务清单.md)逐项签核。
