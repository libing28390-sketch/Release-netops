# EVAL-009 Evidence

## Task ID

EVAL-009

## 目标

实现可重复离线评测命令和机器可读报告。

## 修改文件

- `scripts/knowledge_engine_v2_eval_offline.py`
- `tests/knowledge_engine_v2/test_eval009_offline_evaluation.py`
- `docs/knowledge-engine_v2/eval/eval-offline-report-v1.json`
- `docs/knowledge-engine-v2/architecture/EVAL-009-OFFLINE-EVALUATION-CONTRACT.yaml`
- `docs/walkthrough/20260817_eval009_offline_evaluation.md`

## 实现内容

固定顺序编排 EVAL-001～EVAL-008，严格模式遇到组件失败即返回非零；生成包含 8 个组件结果、边界字段、可复现元数据和 SHA-256 的 JSON 报告。两次运行结果按结构完全相等。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_offline.py --strict
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval009_offline_evaluation.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile scripts/knowledge_engine_v2_eval_offline.py tests/knowledge_engine_v2/test_eval009_offline_evaluation.py
git diff --check
```

## 测试结果

PASS。离线 runner 输出 `status=PASS`、`component_count=8`；专项测试 `1 passed`；重复运行报告相等；JSON、py_compile、diff 检查通过。

## 数据库影响

无表、无迁移、无生产数据写入。Runner 与组件均不连接 PostgreSQL 或 SQLite；SQLite 未作为验收证据。若后续接入数据库样本，只允许 PostgreSQL。

## 安全影响

报告不包含原始正文、凭据、prompt、SQL 或外发内容，只保留状态、计数、bounded component report 和 hash。

## 回滚方式

删除 runner、报告、测试和契约即可回滚；无数据库 rollback。

## 已知限制

当前编排离线契约校验，不执行真实检索请求；CI 小集成门禁由 EVAL-010 完成。

## 最终结论

PASS
