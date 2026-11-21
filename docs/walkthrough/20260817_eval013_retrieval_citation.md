# EVAL-013 Walkthrough

## 验收入口

```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@127.0.0.1:5432/netops'
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts\knowledge_engine_v2_eval013_retrieval_citation_check.py
```

## 观察点

1. 输出必须声明 `database=postgresql`、`sqlite=not_used`。
2. RET 探针必须报告 FTS、trigram、vector、租户状态隔离、EXPLAIN 和 `rollback=PASS`。
3. V1 baseline 的 Q07 必须为空，Q05 必须返回两个受控 OSPF 版本候选，Q03/Q04 必须分别命中对应版本。
4. `metrics.version_conflict_rate` 必须为 `0.0`，`retrieval_accuracy` 与 `citation_accuracy` 必须为 `1.0`。

## 测试入口

```powershell
.venv\Scripts\pytest.exe tests\knowledge_engine_v2\test_eval013_retrieval_citation.py -q -p no:cacheprovider
.venv\Scripts\pytest.exe -p no:conftest backend/tests/ai/test_ret_001_003_query_normalizer.py backend/tests/ai/test_ret_004_007_product_resolution.py backend/tests/ai/test_ret_011_020_retrieval_contract.py backend/tests/ai/test_cit_001_010_grounding.py -q -p no:cacheprovider
```

预期结果：门禁包装测试 2 passed；纯合约测试 19 passed。历史 SQLite fixture 未加载、未作为验收依据。
