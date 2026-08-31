# Nexora NetOps AI 知识库单轨化 Handoff

更新时间：2026-08-30（Asia/Shanghai）

## 结论

AI 知识库已从“V1 在线文档/分块 + V2 来源治理/版本表 + 影子索引”的双轨结构收敛为单一 V1 运行时：

- PostgreSQL 当前只使用 `ai_knowledge_base`、`ai_document`、`ai_document_revision`、`ai_document_chunk` 作为知识主数据、历史事实和在线检索载体。
- 后端、前端和 CI 的知识库入口统一为 `/api/knowledge`；`/api/v2/kb`、`/api/knowledge-v2` 及 alias middleware 已移除。
- V2 source/document/lifecycle/change 表、shadow generation/chunk 和 rollout flag 已从实际 PostgreSQL 删除。
- V2 feature flag 与 shadow retrieval 运行时服务已删除，RAG 只查询 V1 文档和分块。
- 历史迁移文件继续保留，用于已有 PostgreSQL 顺序升级；它们不代表仍有 V2 运行时。

## PostgreSQL 单轨切换快照（2026-08-29 历史记录）

该切换快照的最新迁移为 `192 knowledge_v1_current_version_projection`；当前工作区在此基础上已顺序增加 m0193—m0196，最高 schema 为 196。下表数字保留为切换快照，不能与当前最终验证数字混用。

| 对象/指标 | 结果 |
| --- | ---: |
| `ai_knowledge_base` | 1 |
| `ai_document` | 283 |
| `ai_document_revision` | 605 |
| `ai_document_chunk` | 2613 |
| 有 `current_version_id` 的文档 | 271 |
| `source_identity` 修订事实 | 39 |
| `source_observation` 修订事实 | 265 |
| `document_revision` | 272 |
| `document_source_link` | 26 |
| `site_alert` | 3 |

上表保留 2026-08-29 单轨切换快照，便于和切换前后对比。本轮全部验证结束后的只读复核为：`ai_knowledge_base=1`、`ai_document=283`、`ai_document_revision=781`、`ai_document_chunk=2613`、有 `current_version_id` 的文档 271；修订事实分类为 `document_revision=272`、`document_source_link=26`、`site_alert=3`、`source_identity=39`、`source_observation=432`、`source_version=9`。2026-08-30 时间窗内新增的 176 条修订和 9 篇文档更新时间均由 `scheduler:knowledge-source-freshness` 标记，符合现行来源新鲜度调度器的写入者；这部分是当前目标库中观察到的调度刷新活动，不归因于测试临时库，也没有在本轮被删除或回滚。所有测试和恢复临时库均使用独立名称，最终残留为 0。

下列旧对象经 `to_regclass` 复核均不存在：

- `kb_source_registry`、`kb_source_version`
- `kb_document`、`kb_document_version`、`kb_document_source`
- `kb_document_lifecycle_event`
- `kb_source_refresh_observation`、`kb_source_change_action`、`kb_site_anomaly_alert`
- `ai_retrieval_index_shadow_chunk`、`ai_retrieval_index_generation`、`ai_retrieval_rollout_flag`

`current_version_id` 为空的 12 篇文档没有正文型 `document_revision`，不是迁移丢失；运行时不会为它们伪造修订。

## 迁移链

- `backend/database/migrations/m0189_knowledge_v1_provenance.py`：给 V1 文档补齐来源/生命周期字段，创建 `ai_document_revision`，迁移 V2 文档与来源事实。
- `backend/database/migrations/m0190_knowledge_v1_source_observations.py`：把来源刷新观测归并进 V1 修订审计。
- `backend/database/migrations/m0191_knowledge_v1_finalize_cleanup.py`：迁移剩余来源关系、生命周期、变更和站点告警，执行数量/映射闸门后删除旧表和专用函数。
- `backend/database/migrations/m0192_knowledge_v1_current_version_projection.py`：修复曾提前记录 191 的数据库，补齐当前修订投影。

历史迁移 `m0116`—`m0188` 不删除、不重写；全新库和旧库均通过顺序迁移到最终 V1 schema。

## 当前运行时文件

- 数据契约：`docs/knowledge-base-v1-data-contract.md`
- V1 来源服务：`backend/services/knowledge_v1_source_service.py`
- 兼容导入名：`backend/services/source_registry_service.py`（只转发 V1 实现，不读写旧表）
- API 契约：`backend/api/knowledge_contract.py`、`knowledge_contracts.py`、`knowledge_response.py`
- V1 基线：`scripts/knowledge_baseline_pg.py`
- 评估入口：`scripts/knowledge_eval_ci_gate_check.py`、`scripts/knowledge_eval_offline.py`
- 测试环境校验：`scripts/validate_knowledge_test_config.py`
- 执行清单：`docs/plans/plan_20260829_1000_01_AI知识库V2回迁V1与单轨化清理.md`

已删除的运行时文件包括 `backend/ai/services/feature_flag_service.py`、`backend/ai/services/retrieval_index_service.py` 和 `backend/api/knowledge_v2_*.py`。

## 已完成验证（V1 单轨历史快照）

| 验证 | 结果 |
| --- | --- |
| V1 导入/API/来源/生命周期/评估 focused regression | 72 passed |
| Agent、passthrough、ingestion pipeline | 20 passed |
| `m0191`、`m0192` fresh-schema、投影、重复执行 | 3 passed |
| 中性命名 eval 测试 | 11 passed in 2.61s |
| CAT-001 本地官方文件与 collection ops | 16 passed |
| 全量运行中暴露的知识库失败修复回归 | 39 passed in 86.02s |
| PostgreSQL V1 固定基线 | 10/10；retrieval/citation accuracy 1.0，wrong vendor/version conflict 0，p95 5.4921 ms |
| `python scripts/knowledge_eval_ci_gate_check.py` | PASS |
| `python scripts/validate_knowledge_test_config.py ...` | PASS |
| Python `py_compile` | PASS |
| `python scripts/validate_postgresql_only.py` | PASS，0 violations |
| `python -m compileall -q backend scripts tests` | PASS |
| `pytest backend/tests --collect-only -q -p no:cacheprovider` | PASS，1963 tests collected |
| `npm run lint` | PASS |
| `npm run test:frontend -- --run src/api/http.test.ts` | 2 passed |
| `npm run build` | PASS，4258 modules，19.23s |
| 隔离 PostgreSQL 恢复并升级 189→192 | PASS；旧表残留 0，临时库已删除 |
| 现行运行时 V2/旧表/API 引用扫描 | 0 命中 |
| `git diff --check` | 无空白错误，仅 Windows LF/CRLF 提示 |

全量 `pytest backend/tests -q -p no:cacheprovider` 的历史快照为 1963 passed、0 failed、0 errors、1 warning、26 subtests，耗时 2677.46 秒（44 分 37 秒）。本次 AI 管理增强后的当前最终结果见文末“当前交付基线”。原始 1924 passed、39 failed 的真实 PostgreSQL 回归已全部处理，没有用 SQLite 替代。

关键顺序复跑使用同一批 544 个已收集 node ID，结果如下；每轮均为 544 passed、0 failed、0 errors、1 warning：

| 顺序 | 结果 | 耗时 |
| --- | --- | ---: |
| 正序 | 544 passed | 818.64 秒（13 分 38 秒） |
| 倒序 | 544 passed | 823.00 秒（13 分 43 秒） |
| 随机，seed=`20260830` | 544 passed | 837.39 秒（13 分 57 秒） |

三轮复跑后的只读检查显示 `nexora_pytest_*` 临时数据库为 0；恢复演练临时库 `nexora_knowledge_restore_*` 也为 0。测试执行过程中没有发现测试数据库、事务或模块顺序泄漏。

PostgreSQL 门禁矩阵已实际执行：fresh 临时库初始化后关闭连接池并重复初始化，两次快照均为 schema 192、192 条迁移记录、核心空库计数一致、退役对象 0；`pre_190` 备份恢复后从 schema 189 顺序升级到 192，得到 282 文档、2613 分块、601 修订、退役表 0；`pre_189` 备份恢复后从 schema 188 顺序升级到 192，得到相同的 282/2613/601，退役表 0，两个临时库均已删除。连接池矩阵覆盖有界 overflow、池耗尽（`PoolError`）、注入失效连接后的恢复和 50 个并发查询，全部通过。数据库矩阵测试批次为 31 passed。

## 备份与回滚

迁移前 PostgreSQL 备份：

- `data/backups/knowledge_v1_pre_189_20260829_101155.dump`（约 69.7 MB）
- `data/backups/knowledge_v1_pre_190_20260829.dump`（约 72.3 MB）

`m0191`/`m0192` 的 downgrade 有意不重建旧表。若必须回滚：

1. 停止应用写入并记录当前数据库连接目标。
2. 新建隔离 PostgreSQL 数据库，先恢复 `pre_190`（必要时使用 `pre_189`）备份并完成校验。
3. 验证文档、分块、V2 来源和版本表数量后，再切换连接；不要在现库手工重建旧表。
4. 修正迁移代码后，从已批准版本重新顺序运行迁移。

备份属于可恢复工件，不应提交到 Git，也不要在未完成恢复校验前删除。

已用 `pre_190` 完成真实隔离恢复演练：恢复后 schema 189、270 文档/2613 分块；顺序应用 190—192 后为 282 文档/2613 分块/601 修订，退役表 0，临时数据库已自动删除。演练工具为 `scripts/knowledge_restore_rehearsal_pg.py`。

## 官方来源与受控阻塞

官方来源清单共 48 条，均有可审计终态：27 个 `active_valid_existing`、12 个 `discovery_only`、4 个 `blocked_robots_policy`、3 个 `blocked_robots_unavailable`、2 个 `blocked_vendor_access`。这些状态继续由 YAML catalog 管理，不再写入独立 V2 registry。

不得通过忽略 robots、放宽 SSRF、允许私网跳转或伪造厂商版本来解除阻塞。Cisco PDF 超时来源优先换成官方 HTML 章节；Huawei robots 阻塞项等待厂商访问条件变化。

## 已知剩余风险

- 全量后端测试和本轮 PostgreSQL fresh/upgrade/restore/并发/连接池矩阵已经全绿；历史单轨验证曾有一个 Starlette/httpx `TestClient` 弃用警告，当前最终全量输出无 warning。浏览器登录后的页面冒烟仍需认证态，见文末“浏览器验收状态”。
- 历史迁移、旧 POC/审计脚本及其测试中仍可能出现 `v2`/`shadow` 名称。这些内容不被现行应用、CI 或正式 eval 入口引用，保留用于已部署数据库升级和审计追溯。
- 当前目标库存在调度器来源新鲜度任务写入的当天观测（见上方只读复核）；本轮未对其做破坏性清理。后续若要核对业务数据基线，应把调度刷新时间窗与切换快照分开比较。
- 当前工作树包含本轮 AI 管理增强及此前工作区改动；发布前按交付记录核对后统一提交，不能使用 `git reset --hard` 覆盖既有改动。

详细实施与验证记录：`docs/walkthrough/20260829_knowledge_engine_v1_cutover_cleanup.md`。

工作树包含本轮知识库改动及此前 Agent 外键修复，不要使用 `git reset --hard`，也不要覆盖 `.codex/config.toml`、`.codex_kb_refs.txt` 等用户文件。

## 2026-08-30 PostgreSQL 单轨化最终收尾

本轮在上述知识库 V1 单轨化基础上，已完成后端数据库运行时与测试基础设施的 PostgreSQL-only 改造，并完成原先剩余的四项发布验收；当前最终验证数字以文末“当前交付基线”为准：

- `backend/database/core.py`、schema、backup、capacity、consistency、reset、迁移执行器和业务服务不再提供 SQLite 运行分支；非 PostgreSQL `DATABASE_URL` 会被拒绝。
- 测试统一使用临时 PostgreSQL 数据库与隔离 fixture；测试规范、CI 和仓库扫描器均明确禁止新增 `sqlite3`、内存 SQLite、`.db` fallback、`PRAGMA`、`sqlite_master` 等实现。
- 已修复 PostgreSQL 参数适配中的字面 `%`、DictRow catalog 重名列、事务失败后查询、布尔值、JSONB、外键和 metadata 探测差异。
- Agent `troubleshooting_agent` 外键故障通过内置 Agent seed 迁移与运行前确保记录解决，focused 回归为 2 passed。
- 删除 52 个旧 `knowledge_engine_v2_*` 脚本、33 个 `tests/knowledge_engine_v2` 测试及 V2 文档/状态/CI 残留；正式入口全部使用中性 `knowledge_*` 名称和 V1 数据契约。
- 删除本轮生成的 193 个 SQLite 兼容迁移临时备份文件及 2 个一次性重写脚本；这些不是产品数据。迁移源码和历史改动仍可由 Git 恢复。

最终门禁结果：

| 门禁 | 结果 |
| --- | --- |
| `python scripts/validate_postgresql_only.py` | PASS，0 violations |
| `python -m compileall -q backend scripts tests` | PASS |
| `pytest backend/tests --collect-only -q -p no:cacheprovider` | PASS，1974 tests collected |
| `pytest backend/tests -q -p no:cacheprovider` | PASS，1974 passed、0 failed、0 errors、无 warning、26 subtests |
| 本轮 TestClient 正序/倒序/随机复跑 | PASS，12/12/12 passed；随机 seed=`20260830` |
| fresh、旧库升级、恢复、失败回滚、并发和连接池矩阵 | PASS；数据库矩阵 31 passed，临时库 0 残留；当前最高 schema 196 |
| 知识目录投影与前端回归 | PASS；全局 269 篇、`02_commands/h3c` 为 1 篇，前端 49 files / 181 tests |
| 本轮转换测试批次 | PASS，92 passed |
| Agent runner | PASS，2 passed |
| RAG/数据库可观测性 focused | PASS，15 passed |
| 数据一致性 focused | PASS，12 passed |
| PostgreSQL 临时测试库泄漏检查 | PASS，0 残留 |
| `git diff --check` | PASS；仅 Git 的 LF/CRLF 转换提示 |
| 显式 test 配置校验 | PASS；使用瞬时安全环境变量，`.env` 未修改 |

四项 PostgreSQL 单轨化剩余任务已闭环：全量 1974 项通过；原始真实 PostgreSQL 回归清单已收敛为 0 failed/0 errors；关键 TestClient 正序、倒序和固定种子随机复跑通过；fresh/upgrade/backup-restore/failure-rollback/concurrency/pool exception 矩阵通过。知识目录空列表问题和 AI 管理增强也已完成代码及自动化验收。全程没有重新引入 SQLite，也没有把当前目标库作为测试库；浏览器登录态冒烟、提交和推送状态单独记录在文末。

## 2026-08-30 知识目录空列表修复与最终复核

此前页面在选中具体目录后显示“0 篇”的根因是：历史 `ai_document.metadata_json` 中只有部分文档带有 `knowledge_directory_path`，官方文档发布流程也没有持续写入目录投影；同时“全部目录”徽标错误复用了当前选中目录的数量。

- 新增 `backend/ai/services/knowledge_metadata.py` 的统一目录投影函数，按文档类别、厂商生成稳定的 `knowledge_directory_path`。
- 新增 `m0195_knowledge_directory_projection`，为历史文档补齐缺失投影；保留已有自定义路径，不修改正文、分块或修订事实。
- 新增 `m0196_knowledge_catalog_master_data_repair`，兼容当前数据库已经把旧目录投影记录为 193、而目录主数据迁移仍需要补跑的状态。
- 官方文档发布流程写入目录元数据；知识库前端分别展示全局总数和当前目录匹配数。
- 当前目标库只读核对：269 篇活动文档，缺失目录路径 0；`01_product=182`、`02_commands=4`、`03_configuration=72`、`05_troubleshooting=11`；`02_commands/h3c=1`。
- 浏览器页面验证：全部目录显示 269 篇，选中 `02_commands/h3c` 显示 1 篇，列表出现 H3C 命令参考文档。
- 受影响后端 focused 19/19 通过，正序/倒序/随机各 19/19 通过；知识目录与 Prompt Center 前端回归 4/4 通过；完整前端套件 49/49 files、181/181 tests 通过。
- 当前全量后端结果为 1974 passed、0 failed、0 errors、26 subtests、无 warning；旧记录中的 1963/1969 是历史计数，不是当前基线。

## 2026-08-31 AI 管理中心后续增强

本轮完成用户指定的七项增强，当前代码、自动化验证和登录后浏览器冒烟均已通过：

- Prompt：支持服务端搜索/场景筛选/启停筛选/分页、复制、不可变版本历史、版本对比、追加式恢复、修改原因、乐观并发校验和分页审计。审计快照只保存哈希/长度等摘要，不返回 Prompt 正文。
- Provider：支持 `search`、`data_region`、`health_status`、`enabled`、`provider_type`、`tag` 以及 `page/page_size` 服务端参数，返回 `facets`；标签按 JSON token 精确匹配；无参数请求保留数组兼容格式。
- 产品目录：增加租户自定义 Model 主数据新增、编辑、软删除接口；官方审核种子只读。写操作受租户范围、RBAC、必填/重复校验、审计和 `expected_updated_at` 乐观并发保护。
- 国际化：Prompt、Provider、产品目录、模型路由和知识库管理页面文案集中在 `src/i18n/aiAdmin.ts`，覆盖中英文预览样例、状态、版本、审计、分页、解析结果、错误反馈和下载文件名；当前引用键已完成中英文成对检查。

新增或涉及的关键迁移为 `m0193_knowledge_catalog_master_data.py` 和 `m0194_ai_prompt_lifecycle.py`；m0195/m0196 为同一工作区此前的知识目录投影与迁移修复记录。官方目录与 Security Vault/API Key 脱敏边界没有被放宽。

### 当前交付基线

| 验证 | 结果 |
| --- | --- |
| 后端收集 | 1974 tests collected |
| 后端全量 | 1974 passed、0 failed、0 errors、26 subtests、无 warning；2674.95 秒（44 分 34 秒） |
| TestClient 顺序隔离 | 正序/倒序/seed=20260830 随机：12/12/12 passed |
| PostgreSQL-only scanner | 0 violation(s)，PASS |
| Python compileall | PASS |
| 前端完整测试 | 49 files / 181 tests passed |
| TypeScript/lint | PASS |
| 生产构建 | PASS，4259 modules，18.95 秒 |
| `git diff --check` | PASS；仅 Windows LF/CRLF 转换提示 |
| 临时测试库 | 测试前后 `nexora_pytest_*` 为 0 |
| 开发服务 | 浏览器验收后已停止；5310/5400 无监听 |

### 浏览器验收状态

已启动项目现有 `npm run dev`，并使用用户提供的管理员账号登录后完成五个目标 URL 的只读冒烟：

- `/ai/knowledge`：全部目录显示 269 篇；选择 `02_commands/h3c` 后显示 1 篇匹配文档，同时出现 H3C / H3C Switches / Comware facet。
- `/ai/catalog`：Vendor → Family → Series → Model 层级可见；选择 Huawei 后显示 CloudEngine 6800 下的 3 个型号。
- `/ai/prompts`：显示 10 个模板，搜索框、场景/状态筛选、版本、审计、预览和编辑入口均可见。
- `/ai/models`：Model Route 标题、路由用途、Provider、默认/生效模型、健康状态和 Fallback 信息均可见。
- `/ai/providers`：区域、健康、启用状态、类型、标签等高级筛选可见；当前实例详情按需展开，API Key 保持脱敏。当前租户实际返回 1 个实例，多实例主从布局由页面结构和自动化测试覆盖。

浏览器运行日志未发现 error-level、5xx、重复 React key 或阻断性可访问性警告；登录后的相关接口返回 200。登录前的 `/api/tags/definitions` 401 属于未认证阶段的预期响应。冒烟完成后已停止开发服务，确认 5310/5400 均无监听。

### 发布状态

- 当前分支：`main`。
- 提交和 push 已获用户明确授权；当前已创建 `feat: complete AI admin enhancements` commit，待远端分支核对后 push，并在 push 成功后记录最终远端结果。
- 本次提交共包含 939 个文件，涵盖当前工作区中已授权的代码、测试、迁移和交付文档改动；不是只提交 AI 页面局部文件。
- `data/backups/`、`.codex/`、`.codex_kb_refs.txt` 等本地/备份工件不作为代码提交内容；提交时显式排除，不使用无差别的 `git add -A`。
