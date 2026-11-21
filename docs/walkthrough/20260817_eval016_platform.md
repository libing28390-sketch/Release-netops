# EVAL-016 Walkthrough

## 执行入口

```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/netops'
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval016_platform_check.py
```

## 验收观察点

1. 输出必须声明 `database=postgresql`、`sqlite=not_used`、`fixture_database=none`。
2. Huawei、Cisco、H3C、read-only command、unknown boundary 的 status 都必须为 `PASS`。
3. `fixture_tests.passed` 应为 123，且 fixture runner 使用 `-p no:conftest`。
4. V1 PostgreSQL baseline 应为 10/10，rollback 为 `transaction_rollback`。

## 测试入口

```powershell
.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval016_platform.py -q -p no:cacheprovider
```

预期结果：2 passed；不连接真实设备，不使用 SQLite。
