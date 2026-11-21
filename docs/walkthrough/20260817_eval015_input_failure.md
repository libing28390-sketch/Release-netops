# EVAL-015 Walkthrough

## 执行入口

```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/netops'
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval015_input_failure_check.py
```

## 验收观察点

1. 输出必须是 `database=postgresql`、`sqlite=not_used`。
2. `success.status`、`invalid_input.status`、`permission_denial.status`、`empty_data.status`、`dependency_failure.status` 均为 `PASS`。
3. `pure_tests.passed` 应为 69；这些测试以 `-p no:conftest` 运行，不加载 SQLite fixture。
4. Provider、Reindex、duplicate-content、V1 baseline 探针都应报告 PostgreSQL 与 rollback。
5. `excluded_sqlite_fixture` 必须是 `test_kui_012_document_actions.py`，不得把它加入验收命令。

## 测试入口

```powershell
.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval015_input_failure.py -q -p no:cacheprovider
```

预期结果：2 passed；无 SQLite 连接或 SQLite 验收证据。
