# AI/RAG 整改预发布说明与迁移/回滚须知

日期：2026-09-03（最后复核：2026-09-04）  
状态：`HOLD — NOT A RELEASE CANDIDATE`

本说明与 [AI/RAG 配置、Kill Switch 与回滚清单](../knowledge-engine/runbooks/AI-RAG-RELEASE-CONFIG-AND-ROLLBACK-20260903.md) 配套。当前工作区完成了主要代码和自动化门禁；按测试环境授权，仓库已包含明确标记为 `test_only=true` 的合成 400 条 CI 夹具，但真实人工 Gold、真实 sidecar、CI 实跑、Provider live sample、浏览器 UAT、生产迁移/回滚和 Git 发布提交尚未完成，禁止将测试夹具或本说明解释为生产放行。

## 已交付的代码范围

- 50 条锚点评测已经从“业务状态通过”改为安全门禁与质量门禁分离，并纳入 Gold 命中、Recall、MRR、NDCG、引用身份代理、延迟和错误率。
- Reranker、Docling、Langfuse 的边界适配、超时、白名单、降级和 metadata-only 契约已接入；默认仍为 legacy/off，Shadow 不覆盖生产 baseline。
- 迁移 0202 增加实验运行、案例结果、灰度指针和 Shadow 观察的 PostgreSQL-only 持久化；OBS-002 API/UI 只展示脱敏摘要。
- Promptfoo 已固定 Node 22.22.2 / Promptfoo 0.118.0 的独立 CI 工作流，并复用仓库内带 pgvector/pg_trgm 的 PostgreSQL CI 镜像；本机验证不替代 GitHub Actions 实跑证据。

## 当前验证证据

| 门禁 | 结果 |
| --- | --- |
| `pytest backend/tests/ai -q` | `535 passed`（当前代码既有回归证据） |
| `pytest backend/tests -q` | `1744 passed, 26 subtests passed，退出码 0；隔离 PostgreSQL 本次复核` |
| 前端全量 Vitest | `53 files / 195 passed` |
| 前端 KUI/OBS-002 定向测试 | `5 passed` |
| `npm run lint` | `PASS` |
| `npm run build` | `PASS`，`4265 modules transformed` |
| PostgreSQL-only 扫描 | `0 violation(s) PASS` |
| CI 配置静态检查 | `PASS` |
| 50 条真实锚点评测 | `safety=PASS, quality=FAIL, overall=FAIL`；38/50，Recall@5/10=`0.7143` |
| 400 条 Gold 检查 | 普通合同检查 `PASS`，`case_count=400`；数据集为 `test_only=true` 合成夹具，生产模式 `--require-production` 为 `FAIL`，真实人工 Gold `NOT_READY` |

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

- 50 条案例仍有 50 条待人工 reviewer/reviewed_at/annotation_status，42 条缺显式 Feature 标注，6 个 Ruijie Gold ID 在隔离 PostgreSQL 中未解析；当前召回未达阈值。
- 400 条真实人工审核 Gold Dataset 尚未提供；当前 `eval-golden-400.yaml` 仅是用户授权的 `test_only=true` 合成 CI 夹具，普通字段/分布合同检查可通过，但生产模式明确拒绝。Feature Pollution、Version Conflict 和真实 Citation 指标尚未完成全量测量。
- 当前机器无 Docker CLI，BGE、Docling、Langfuse 真实服务、模型加载和资源验收尚未完成。
- Qwen/Ollama 未配置；DeepSeek 真实业务会话和 Provider 错误矩阵尚未授权/执行。
- 浏览器已登录会话完成部分只读 UAT（含本地命中、澄清、no-match、Provider 兜底和高风险确认边界）；逐案例元数据见 [eval-browser-uat-live-20260904.md](../knowledge-engine/eval/eval-browser-uat-live-20260904.md)，但完整 UAT-001、5%→20%→50% 灰度观察、旧库升级/失败回滚演练和可追溯 Git Commit/RC 标签尚未完成。

因此当前发布结论为 `HOLD`。完成上述阻断后，必须重新生成评测报告、baseline manifest、迁移/回滚记录和发布候选，再按主任务清单 DOD-001 至 DOD-010 逐项签核。
