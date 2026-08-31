# 全量后端 PostgreSQL 单轨化与 SQLite 彻底清理任务清单

## 1. 目标

把 Nexora NetOps 的后端运行时、迁移、维护脚本和自动化测试全部收敛到 PostgreSQL，删除 SQLite/`sqlite3` 代码路径，并建立不可绕过的测试规范和 CI 扫描，防止以后重新使用 SQLite 编写测试。

本轮原则：

- PostgreSQL 是唯一运行时数据库、唯一迁移权威和唯一测试数据库。
- 后端测试全部使用隔离的临时 PostgreSQL 数据库，不再使用 `sqlite3`、`:memory:` 或临时 `.db` 文件。
- 不通过删除有效测试、弱化断言、静态匹配代替数据库行为验证或保留隐藏 fallback 来制造“清理完成”。
- 已发布迁移不改变版本号和顺序；清理兼容分支后，必须验证 fresh install、旧库升级、重复执行和失败回滚。
- 不直接操作生产数据库。测试库必须具有唯一名称、生产目标拦截、连接池回收和强制清理。
- 旧 `.db` 文件属于数据工件，先确认用途与备份状态，再按明确清单删除，不能用广泛通配符清理。

## 2. 当前基线

- 79 个 `backend/tests/**/*.py` 文件直接导入 `sqlite3`。
- 4 个运行时文件直接导入 `sqlite3`：`backend/database/core.py`、`backend/database/backup.py`、`backend/ai/services/knowledge_service.py`、`backend/inspect_db.py`。
- 多个数据库、服务和历史迁移仍包含 `PRAGMA`、`sqlite_master`、`:memory:`、`AUTOINCREMENT` 或 `use_pg=False` 兼容分支。
- 根测试 fixture 会清空 `DATABASE_URL`，导致 pytest 首次把数据库模块固定加载为 SQLite。
- 现有 CI 虽启动 PostgreSQL 16 service，但根 fixture 仍可能把测试切回 SQLite。
- 上一次全量结果 `1885 passed / 27 failed / 55 errors / 2 skipped` 包含 SQLite/PG 环境冲突，不能作为真实业务失败清单。

## 3. 实施任务清单

### 阶段 A：冻结 SQLite 并建立强制规范

- [x] **PG-ONLY-001：新增 PostgreSQL-only 测试规范。** 已创建 `docs/testing/POSTGRESQL_ONLY_TESTING.md`，明确测试数据库、临时库命名、fixture 生命周期、禁止项、迁移验证和失败清理要求。
- [x] **PG-ONLY-002：更新质量门禁技能规范。** 已在 `.agents/skills/netops-quality-gate/SKILL.md` 写明不得新增 SQLite 测试，所有持久化测试必须使用隔离 PostgreSQL。
- [x] **PG-ONLY-003：新增静态扫描脚本。** 已创建 `scripts/validate_postgresql_only.py`，扫描现行 Python 代码中的 `sqlite3`、`sqlite_master`、`PRAGMA`、`:memory:`、SQLite URL/文件数据库和 SQLite-only SQL。
- [x] **PG-ONLY-004：接入本地和 CI 门禁。** backend pytest CI 已先执行临时 debt baseline 门禁；任何新命中都会失败，清零后切换为无 baseline 的零容忍模式。
- [x] **PG-ONLY-005：冻结基线清单。** `docs/testing/postgresql_only_baseline.json` 已冻结 788 个代码级命中；清理期间只允许下降，不允许新增。

### 阶段 B：建立统一、安全的 PostgreSQL 测试基础设施

- [x] **PG-ONLY-006：删除根 SQLite fixture 策略。** `backend/tests/conftest.py` 已不再清空 `DATABASE_URL`、patch dotenv 或创建临时 `.db`。
- [x] **PG-ONLY-007：新增会话级 PG 管理 fixture。** 已校验 PostgreSQL 测试 URL、默认拒绝远程服务器，并建立唯一模板库和 session 库。
- [x] **PG-ONLY-008：新增函数级 schema/data fixture。** `isolated_db` 从不可变 PG 模板克隆独立数据库，避免用例互相污染。
- [x] **PG-ONLY-009：统一连接池生命周期。** 新 helper 在切库前关闭池，测试后恢复 URL、PG 标志和 schema 初始化状态；platform registry 重复 fixture 已删除。
- [x] **PG-ONLY-010：统一失败清理。** setup/断言失败路径均强制删库；首轮失败回归后已验证临时库残留为零。
- [x] **PG-ONLY-011：统一 SQL 参数与行对象。** 测试通过项目数据库封装或 psycopg2 参数化查询，不继续依赖 SQLite `?` 占位符和 `sqlite3.Row`。

### 阶段 C：删除运行时 SQLite 支持

- [x] **PG-ONLY-012：收敛数据库核心。** `backend/database/core.py` 只初始化 PostgreSQL 驱动和连接池；缺失或非 PostgreSQL `DATABASE_URL` 时启动失败并给出明确错误。
- [x] **PG-ONLY-013：删除 SQLite schema 分支。** `backend/database/schema.py`、`backend/database/__init__.py`、兼容入口和查询适配不再访问 `PRAGMA`/`sqlite_master` 或维护 SQLite 连接池。
- [x] **PG-ONLY-014：删除 SQLite 备份/恢复能力。** `backend/database/backup.py` 只保留 `pg_dump`/`pg_restore` 与 PostgreSQL manifest、恢复演练。
- [x] **PG-ONLY-015：删除 SQLite 巡检/容量/重置分支。** consistency、capacity、reset、health、inspect 和相关 API 只报告 PostgreSQL 语义。
- [x] **PG-ONLY-016：删除业务服务兼容分支。** 清理 AI、PAM、WAN、调度、平台识别、知识库等服务里的 SQLite SQL、布尔值和异常兼容逻辑。
- [x] **PG-ONLY-017：清理配置与部署说明。** 删除 `DB_PATH`、`.db` fallback 和 SQLite 环境说明，`.env.example` 明确要求 PostgreSQL URL。

### 阶段 D：清理历史迁移中的 SQLite 分支

- [x] **PG-ONLY-018：盘点迁移条件分支。** 建立每个 `use_pg`/SQLite SQL 分支的清单，区分可直接删除、需转换为 PG SQL和已无效的兼容辅助函数。
- [x] **PG-ONLY-019：迁移执行器强制 PostgreSQL。** migration runner 不再接受 `use_pg=False`，并在非 PG 连接上立即拒绝。
- [x] **PG-ONLY-020：删除迁移 SQLite SQL。** 清理 `PRAGMA`、`sqlite_master`、`AUTOINCREMENT`、SQLite trigger/rename/rebuild 表等实现，只保留对应 PostgreSQL 路径。
- [x] **PG-ONLY-021：保持迁移历史稳定。** 版本号、名称、顺序和已经部署的 PostgreSQL 行为不变；不得因删除 SQLite 分支改变 PG DDL/DML 结果。
- [x] **PG-ONLY-022：验证完整迁移链。** 在空 PostgreSQL 上执行 1→当前最高版本，并验证重复启动不会重复迁移或损坏数据。
- [x] **PG-ONLY-023：验证旧库升级。** 从已保存的 pre-189/pre-190 PG 备份恢复后升级到当前版本，核对 schema、行数、约束和旧表清理结果。
- [x] **PG-ONLY-024：验证迁移失败回滚。** 对注入失败的迁移确认 PostgreSQL DDL/DML 事务回滚，不使用 SQLite 行为作为预期。

### 阶段 E：把全部测试迁移到 PostgreSQL

- [x] **PG-ONLY-025：迁移 79 个直接 SQLite 测试文件。** 按 database、AI、configuration、monitoring、PAM、SNMP、topology、vendor audit 和根测试分批改用统一 PG fixture。
- [x] **PG-ONLY-026：迁移 schema/迁移测试。** 用 `information_schema`、`pg_catalog`、`pg_constraint` 和真实事务验证列、索引、外键、触发器、JSONB 和回滚。
- [x] **PG-ONLY-027：迁移服务单元测试。** 用临时 PG 数据代替手工构造的不完整 SQLite 表，保留成功、空数据、冲突、权限拒绝和依赖失败覆盖。
- [x] **PG-ONLY-028：迁移厂商与采集审计测试。** 保留网络设备和外部服务 mock，只把持久化层换成 PG；不得连接真实设备。
- [x] **PG-ONLY-029：迁移知识库测试。** 文档、修订、分块、检索、跨主机 bundle 和评估全部运行于临时 PG，保持 V1 单轨和数据隔离。
- [x] **PG-ONLY-030：删除无效 SQLite 专属测试。** 仅删除“验证 SQLite 自身兼容性”且在 PG-only 产品中已无需求的用例；其业务覆盖必须已由 PG 测试替代。
- [x] **PG-ONLY-031：消除测试顺序依赖。** 544 个关键测试 node ID 正序、倒序和固定 seed=`20260830` 随机复跑均为 544 passed；三轮后 `nexora_pytest_*` 与恢复演练临时库均为 0，未发现数据库、事务或模块状态泄漏。

### 阶段 F：处理净业务失败

- [x] **PG-ONLY-032：重新生成真实失败清单。** PG 单轨完成后完整运行全量测试；当前最终结果为 1974 passed、0 failed、0 errors。历史 1963/1969 为新增 AI 管理回归前的快照；本次没有失败或瞬时性能抖动。
- [x] **PG-ONLY-033：修复 Playbook 回归。** 对照权限、版本快照、执行状态、参数、超时和回滚契约逐项修复。
- [x] **PG-ONLY-034：修复 vendor audit 回归。** 核对厂商命令、TextFSM 字段、平台别名和只读安全边界，不放宽安全规则。
- [x] **PG-ONLY-035：修复其余真实回归。** 按最小影响范围修改生产逻辑或更新已经过期的测试契约，并记录判定依据。

### 阶段 G：删除 SQLite 工件与最终门禁

- [x] **PG-ONLY-036：盘点 SQLite 数据文件。** 明确根目录 `netops.db`、`data/*.db`、备份和构建产物的来源、是否被引用及是否需要归档。
- [x] **PG-ONLY-037：按确认清单删除 SQLite 工件。** 仅删除已确认不再使用且已备份/可从 Git 恢复的文件，更新 `.gitignore` 和打包配置。
- [x] **PG-ONLY-038：SQLite 零命中门禁。** `scripts/validate_postgresql_only.py` 对现行 `backend/`、`scripts/`、`tests/` 扫描为 0；历史文档只允许描述迁移背景，不得作为可执行方案。
- [x] **PG-ONLY-039：PostgreSQL fresh/upgrade/restore 门禁。** fresh 库重复初始化、pre-189/pre-190 备份恢复并升级到当前 schema 196、迁移失败回滚、并发连接、连接池 overflow/耗尽/失效连接恢复矩阵全部通过；数据库矩阵 31 passed，临时库残留 0。
- [x] **PG-ONLY-040：全量后端门禁。** `pytest backend/tests -q -p no:cacheprovider` 当前最终为 1974 passed、0 failed、0 errors、26 subtests；无 skip、无 warning。
- [x] **PG-ONLY-041：静态与构建门禁。** Python compile、规范扫描、配置校验、TypeScript、49 文件前端测试、生产构建和 `git diff --check` 均通过。
- [x] **PG-ONLY-042：数据安全复核。** 测试和恢复演练均使用隔离 PostgreSQL 临时库，最终临时库残留为零；当前最高 schema 为 196，目标库只做只读核对，未做破坏性清理。
- [x] **PG-ONLY-043：形成 walkthrough 与 handoff。** 记录删除范围、测试迁移数量、命令、通过统计、旧文件处置、回滚方式和剩余风险。

## 2026-08-30 执行结果

实现与最终验收均已完成：运行时、迁移、脚本、测试基础设施、CI 与规范均已收敛到 PostgreSQL-only；扫描器为 0 violations，Python compile、1974 项测试收集、全量 1974 项后端测试、关键顺序复跑、Agent/RAG/一致性 focused 回归及 PostgreSQL fresh/upgrade/restore/并发/连接池矩阵全部通过。知识目录投影修复、前端目录计数修复、AI 管理增强及 49 个前端测试文件的完整回归也已通过。V2 可执行脚本、测试和文档残留已经删除，最终记录见仓库根目录 `handoff.md`。

PG-ONLY-031、032、039、040 已按实际执行结果标记完成。当前全量最终命令为 1974 passed、0 failed、0 errors、26 subtests、无 warning；三组 TestClient 顺序复核为 12/12/12 passed。PG-ONLY-023 另由 `pre_189` 和 `pre_190` 两份隔离备份完成真实恢复升级演练；所有临时数据库已清理。知识目录修复新增 m0195/m0196，AI 管理增强新增 m0193/m0194，当前最高 schema 为 196，相关前后端回归均已通过。

## 2026-08-30 追加：知识目录可见性问题

- [x] **KB-DIR-001：补齐历史文档目录投影。** 对缺失 `knowledge_directory_path` 的文档按类别和厂商补齐路径，保留已有自定义路径。
- [x] **KB-DIR-002：修复官方发布写入。** 新发布文档统一写入目录元数据，避免后续目录树存在但列表为空。
- [x] **KB-DIR-003：修复全局与选中目录计数。** “全部目录”显示全局总数，右侧列表显示当前目录匹配数。
- [x] **KB-DIR-004：页面与回归验收。** 全局 269 篇、`02_commands/h3c` 1 篇；受影响后端 19/19、正序/倒序/随机各 19/19、前端完整 181/181 通过。

## 4. PostgreSQL-only 测试规范必须包含的禁止项

以下内容一旦出现在现行后端或测试代码，静态门禁必须失败：

- `import sqlite3`、`from sqlite3 ...`
- `sqlite3.connect(...)`、`:memory:`、`sqlite:///...`
- `sqlite_master`、`PRAGMA ...`
- `INTEGER PRIMARY KEY AUTOINCREMENT`
- 以 `.db` 文件作为测试数据库
- 通过清空 `DATABASE_URL` 触发数据库 fallback
- 在 fixture 中把 `_USE_PG` 改为 `False`
- 用 SQLite 结果作为 PostgreSQL 迁移、约束、JSONB、索引、事务或并发行为的验收证据

测试编写要求：

- 使用统一 PostgreSQL fixture，不得在单个测试文件自行创建新的数据库策略。
- SQL 必须参数化；动态标识符必须经白名单或 psycopg2 SQL composition 处理。
- 测试库名称必须带固定测试前缀和随机后缀，并拒绝已知生产数据库名称。
- 测试结束必须清理连接池、连接和临时数据库，异常路径同样适用。
- schema 断言使用 `information_schema`/`pg_catalog`，事务和约束必须在真实 PG 上验证。
- 新增迁移必须覆盖 fresh、upgrade、replay 和 failure rollback。

## 5. 执行闸门

1. **闸门一——规范先行：** `PG-ONLY-001`—`PG-ONLY-005` 完成后，新增 SQLite 代码立即被阻止。
2. **闸门二——基础设施可信：** `PG-ONLY-006`—`PG-ONLY-011` 完成且临时库可安全清理后，才批量迁移测试。
3. **闸门三——运行时单轨：** `PG-ONLY-012`—`PG-ONLY-024` 完成后，应用和迁移不再存在 SQLite fallback。
4. **闸门四——覆盖不缩水：** `PG-ONLY-025`—`PG-ONLY-031` 完成，原 SQLite 测试的业务覆盖已由 PG 测试接替。
5. **闸门五——业务修复：** 仅以 `PG-ONLY-032` 的净失败清单修改 Playbook、vendor audit 等业务逻辑。
6. **闸门六——允许交付：** SQLite 零命中、PG 全量测试、恢复演练和数据安全复核全部通过后，才可宣称彻底清理完成。

## 6. 完成标准

- 现行 Python 代码和自动化测试中不存在 SQLite 驱动、SQL、文件数据库和 fallback。
- 所有持久化测试都在隔离 PostgreSQL 上运行，CI 与本地使用同一测试规范。
- PostgreSQL 完整迁移链、旧库升级、失败回滚和恢复演练通过。
- 原有 SQLite 测试覆盖已迁移而不是被静默删除。
- 全量后端测试为 0 failed、0 errors，临时 PostgreSQL 数据库残留为零。
- 测试规范、静态扫描和 CI 会阻止未来重新引入 SQLite。

## 7. 建议提交拆分

1. **提交一：** PostgreSQL-only 规范、扫描脚本、CI 和统一 PG fixture。
2. **提交二：** 运行时数据库核心、备份、巡检和配置去 SQLite。
3. **提交三：** 历史迁移 PostgreSQL-only 收敛与 fresh/upgrade/restore 验证。
4. **提交四：** 79 个 SQLite 测试文件分模块迁移到 PG。
5. **提交五：** Playbook、vendor audit 和其余净业务回归。
6. **提交六：** SQLite 工件清理、全量门禁、walkthrough 与 handoff。
