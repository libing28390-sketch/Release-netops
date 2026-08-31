# AI 知识库 V1 单轨化清理 Walkthrough

日期：2026-08-29（Asia/Shanghai）

## 结果

知识库已完成 V2 数据回迁和运行时单轨化。现行写入、检索、API、前端、CI 和配置均使用 V1/中性 Knowledge 命名；实际 PostgreSQL 已删除旧 `kb_*`、shadow index 和 rollout flag 对象。

## 最终数据路径

1. 官方 URL、本地官方文件、SOP 或手工内容进入统一 ingestion/publish 服务。
2. 当前文档写入 `ai_document`，不可变正文和来源事实写入 `ai_document_revision`。
3. 在线检索只读取 `ai_document` 与 `ai_document_chunk`，并执行租户、ACL、状态和知识库范围过滤。
4. API 统一为 `/api/knowledge`；旧 `/api/v2/kb`、`/api/knowledge-v2` 不再注册。
5. 官方来源 catalog、allowlist 和评估数据统一放在 `docs/knowledge-engine/`。

数据约束见 `docs/knowledge-base-v1-data-contract.md`。

## PostgreSQL 迁移与对账

迁移链：

- `m0189_knowledge_v1_provenance`：创建 V1 来源字段和 `ai_document_revision`。
- `m0190_knowledge_v1_source_observations`：迁移来源观测事实。
- `m0191_knowledge_v1_finalize_cleanup`：迁移剩余关系/生命周期/变更/告警，通过数量闸门后删旧表。
- `m0192_knowledge_v1_current_version_projection`：补齐已提前记录 191 的数据库中的当前修订投影。

实际 PG 最终统计：

| 指标 | 数量 |
| --- | ---: |
| `ai_knowledge_base` | 1 |
| `ai_document` | 283 |
| `ai_document_revision` | 605 |
| `ai_document_chunk` | 2613 |
| `current_version_id` 非空文档 | 271 |
| `document_revision` | 272 |
| `document_source_link` | 26 |
| `source_identity` | 39 |
| `source_observation` | 265 |
| `site_alert` | 3 |

`to_regclass` 复核以下 12 个旧表均不存在：`kb_source_registry`、`kb_source_version`、`kb_document`、`kb_document_version`、`kb_document_source`、`kb_document_lifecycle_event`、`kb_source_refresh_observation`、`kb_source_change_action`、`kb_site_anomaly_alert`、`ai_retrieval_index_shadow_chunk`、`ai_retrieval_index_generation`、`ai_retrieval_rollout_flag`。

## 恢复演练

执行：

```powershell
.venv\Scripts\python.exe scripts\knowledge_restore_rehearsal_pg.py --backup data\backups\knowledge_v1_pre_190_20260829.dump
```

结果为 PASS：

- 恢复文件：72,345,254 bytes。
- 恢复后原始状态：schema 189、270 文档、2613 分块。
- 顺序应用 190–192，共 3 个迁移。
- 升级后：schema 192、282 文档、2613 分块、601 修订。
- 退役表残留：0。
- 演练数据库 `nexora_knowledge_restore_20260829070549_6d1f8e` 已在校验后自动删除。

现网比备份演练多 1 篇文档和 4 条修订，来自备份之后的正常导入/观测，不是恢复缺失。

## 验证证据

| 命令/范围 | 结果 |
| --- | --- |
| V1 导入、API、来源、生命周期、评估 focused regression | 72 passed |
| Agent、passthrough、ingestion pipeline | 20 passed |
| CAT-001 本地官方文件与 collection ops | 16 passed |
| 修复全量运行中暴露的知识库用例 | 39 passed in 86.02s |
| `m0191`/`m0192` fresh-schema、投影、重复执行 | 3 passed in 21.10s |
| `pytest -q tests/knowledge_engine` | 11 passed in 2.61s |
| PostgreSQL V1 固定问题集 | 10/10；检索/引用准确率 1.0；错误厂商/版本冲突率 0；p95 5.4921 ms |
| `knowledge_eval_ci_gate_check.py` | PASS，PostgreSQL，small/full profile |
| `validate_knowledge_test_config.py` | PASS |
| Python `py_compile` | PASS |
| `npm run lint` | PASS |
| `npm run test:frontend -- --run src/api/http.test.ts` | 2 passed |
| `npm run build` | PASS，4258 modules，19.23s |
| 现行运行时 V2/旧表/API 引用扫描 | 0 命中 |
| `git diff --check` | PASS（仅 Windows LF/CRLF 提示） |

全量 `pytest backend/tests -q -p no:cacheprovider` 完整运行 58 分 49 秒，结果为 1885 passed、27 failed、55 errors、2 skipped。55 个 setup error 主要是默认测试环境将明确要求 PostgreSQL 的 platform-registry 用例跑在 SQLite，另有 cross-host fixture 仍引用已不存在的 `_pg_pool`；它们不在本次知识库改动范围。全量中暴露的现行知识库失败已逐项修复并由上表 39 个用例复验；退役 shadow compare 测试随 V2 删除。由于未重新消耗约一小时复跑整个无关套件，不能把仓库全量测试记为全绿。

## 本次补齐的回归缺口

- 文档详情在滚动升级期间缺少 `ai_document_revision` 时返回空历史，不因只读详情直接 500；其他数据库错误仍抛出。
- 发布、替换和回滚文档修订会同步 `ai_document.current_version_id`，回滚 request ID 可幂等重放。
- 官方来源采集恢复 `fetch_started`/`fetch_completed` 审计，仅记录方法、状态、字节数等边界信息，不记录正文。
- 无已解析 CLI 平台的命令、配置、排障查询标记为跨平台歧义，回答必须分平台呈现；带具体型号/版本边界时仍要求澄清。
- URL allowlist 测试改用 V1 中性字段 `matched_catalog`，不保留 `official_entry` V2 别名。

## 保留与删除边界

已删除：V2 运行时服务、影子检索、灰度开关、V2 API 契约/别名、PG V2 表和前端 V1/V2 概念。

保留：已发布数据库迁移及其历史测试、旧 POC/审计脚本和迁移前设计证据。这些文件可能仍含 `v2`、`shadow` 字样，但不被现行应用、CI 或正式 eval 入口引用。`docs/knowledge-engine/README.md` 已明确它们只是历史证据，禁止作为新开发入口。

## 回滚

`m0191`/`m0192` 不重建旧表。回滚必须停止写入，在隔离 PostgreSQL 中恢复 `data/backups/knowledge_v1_pre_190_20260829.dump`（必要时使用 pre-189），校验文档/分块/来源事实后再决定连接切换；不得在现库手工拼装旧 schema。
