# EVAL-010 Evidence

## Task ID

EVAL-010

## 目标

在 CI 中执行小型固定评测集，并将完整评测集接入发布门禁；数据库测试环境统一选择 PostgreSQL，SQLite 不得作为 Nexora Knowledge Engine V2 的验收证据。

## 修改文件

- `.github/workflows/knowledge-engine-v2-eval.yml`
- `.github/workflows/backend-pytest-check.yml`
- `.github/workflows/release.yml`
- `scripts/knowledge_engine_v2_eval_offline.py`
- `scripts/knowledge_engine_v2_eval_ci_gate_check.py`
- `tests/knowledge_engine_v2/test_eval010_ci_gate.py`
- `docs/knowledge-engine-v2/architecture/EVAL-010-CI-RELEASE-GATE-CONTRACT.yaml`
- `docs/knowledge-engine-v2/eval/eval-offline-small-report-v1.json`
- `docs/knowledge-engine-v2/eval/eval-offline-report-v1.json`
- `docs/knowledge-engine-v2/eval/eval-ci-gate-v1.manifest.json`
- `docs/walkthrough/20260817_eval010_ci_release_gate.md`

## 实现内容

- EVAL-009 runner 新增 `small` / `full` profile，固定小集为 EVAL-001、003、005、007；默认仍为完整集，保持既有调用兼容。
- 新增 PostgreSQL-only EVAL workflow：PR/main push 执行小集和聚焦回归测试，使用 PostgreSQL 16 service 与 `postgresql://` URL。
- 后端通用 CI 的数据库 URL 改为 PostgreSQL 16 service；发布 Ubuntu job 在清理发布树前执行完整评测门禁。
- 新增文本级 CI 合同校验器，拒绝三个受检工作流中的 SQLite URL/`sqlite3`，并校验 profile、PostgreSQL service 与发布步骤。
- 离线评测仍然不连接任何数据库、不访问外网、不写生产；其安全字段明确为 `database=none`、`sqlite=not_used`，而不是把离线报告冒充数据库测试。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval_ci_gate_check.py
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval_offline.py --profile small --strict
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval_offline.py --profile full --strict
.venv\Scripts\python.exe -m pytest tests\knowledge_engine_v2\test_eval001_query_dataset.py tests\knowledge_engine_v2\test_eval003_query_type_coverage.py tests\knowledge_engine_v2\test_eval005_metrics.py tests\knowledge_engine_v2\test_eval007_security_metrics.py tests\knowledge_engine_v2\test_eval009_offline_evaluation.py tests\knowledge_engine_v2\test_eval010_ci_gate.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile scripts\knowledge_engine_v2_eval_offline.py scripts\knowledge_engine_v2_eval_ci_gate_check.py tests\knowledge_engine_v2\test_eval010_ci_gate.py
$env:PYTHONPATH='backend'; .venv\Scripts\python.exe -c "import yaml; from pathlib import Path; paths=['.github/workflows/knowledge-engine-v2-eval.yml','.github/workflows/backend-pytest-check.yml','.github/workflows/release.yml','docs/knowledge-engine-v2/architecture/EVAL-010-CI-RELEASE-GATE-CONTRACT.yaml']; [yaml.safe_load(Path(p).read_text(encoding='utf-8')) for p in paths]; print('YAML PASS', len(paths))"
git diff --check
```

## 测试结果

PASS。

- CI gate validator：`status=PASS`，`small_ci_profile=small`，`full_release_profile=full`，`database_url_scheme=postgresql`，`postgres_service=true`，`sqlite_references=0`。
- 小型严格评测：`status=PASS`，4 components，report SHA-256 `396f4cace175d191696555dd4ea463116a998cec435292173680275a41c12c64`。
- 完整严格评测：`status=PASS`，8 components，report SHA-256 `9d48238cbc53ebaafddf8298361c4b194edc74923585a3d5b62e01c91892b02d`。
- EVAL-001/003/005/007/009/010 回归：`7 passed`。
- Python compile：PASS。
- 三个工作流 YAML 解析：PASS（GitHub Actions 结构由同一文本合同检查覆盖）。
- `git diff --check`：PASS。

## 数据库影响

- 新增/修改的 CI job 仅启动临时 PostgreSQL 16 service，使用合成测试库 `nexora_kb_v2_eval` / `nexora_kb_v2_ci`。
- 没有 migration、生产连接或生产数据写入。
- 离线评测不连接 PostgreSQL；这是明确的无数据库单元评测，不使用 SQLite 伪装数据库验证。

## 安全影响

- CI 使用合成密码和占位密钥，未提交真实凭据。
- 评测报告只包含状态、计数、边界配置和 hash，不包含正文、prompt、SQL 或密钥。
- `--strict` 任何组件失败都会使 job 非零退出。

## 回滚方式

删除 EVAL-010 workflow、profile 参数、合同校验器、测试和报告；恢复 backend/release workflow 的原有测试配置即可。无数据库回滚操作。

## 已知限制

- GitHub Actions 运行时本身需由 CI 执行；本地验证覆盖了工作流文本合同、profile 选择、严格 runner 和回归测试。
- 仓库中历史 V1 单元夹具可能直接构造本地连接，但它们不属于 EVAL-010 的 PostgreSQL 验收证据；EVAL-010 workflow 与发布门禁不选择该路径。

## 最终结论

PASS
