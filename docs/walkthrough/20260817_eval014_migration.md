# EVAL-014 Walkthrough

## 执行入口

```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/netops'
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval014_migration_check.py
```

脚本会在 PostgreSQL server 上创建 `nexora_eval014_<随机后缀>` 临时库，完成检查后自动删除；不会写入当前 `netops` 库。

## 验收观察点

1. `matrix.fresh_install.first_applied` 应为 150，`pending_after_first` 为空。
2. `matrix.repeated_execution.second_applied` 应为 0，V1 表计数保持不变。
3. `matrix.backfill.rows_after_repeat` 应显示 `empty/null/blank` 为 `[]`，有效数组不变，且 rollback 为 true。
4. `matrix.constraints.all_rejected` 应为 true。
5. `matrix.recovery` 应显示首次失败未应用、部分 DDL 已回滚、修复重试应用 2、历史漂移阻断。
6. 输出必须是 `database=postgresql`、`sqlite=not_used`，并且临时库清理成功。

## 测试入口

```powershell
.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval014_migration.py -q -p no:cacheprovider
```

预期结果：2 passed。数据库验收完全依赖 PostgreSQL 临时库，不加载 SQLite fixture。
