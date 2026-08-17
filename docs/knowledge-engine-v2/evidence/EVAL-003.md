# EVAL-003 Evidence

## Task ID

EVAL-003

## 目标

覆盖 Exact、Alias、Prefix、Ambiguous、Typo、Wrong Vendor、Product Conflict 七类 Query 类型，并验证正向、澄清和 fail-closed 结果边界。

## 修改文件

- `docs/knowledge-engine-v2/eval/eval-query-type-coverage-v1.yaml`
- `docs/knowledge-engine-v2/eval/eval-query-type-coverage-v1.manifest.json`
- `docs/knowledge-engine-v2/architecture/EVAL-003-QUERY-TYPE-COVERAGE-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval_query_type_coverage_check.py`
- `tests/knowledge_engine_v2/test_eval003_query_type_coverage.py`
- `docs/walkthrough/20260817_eval003_query_type_coverage.md`

## 实现内容

为七类 Query 建立冻结契约和校验器。正向类型要求 answer、citation 和 Gold；Ambiguous 要求缺失身份并 clarify；Wrong Vendor/Product Conflict 要求 no_match 和空 Gold，并校验查询中的冲突语义。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_query_type_coverage_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval003_query_type_coverage.py -q -p no:cacheprovider
.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('docs/knowledge-engine-v2/eval/eval-query-type-coverage-v1.yaml',encoding='utf-8')); print('type_coverage_yaml=PASS')"
.venv\Scripts\python.exe -m py_compile scripts/knowledge_engine_v2_eval_query_type_coverage_check.py tests/knowledge_engine_v2/test_eval003_query_type_coverage.py
git diff --check
```

## 测试结果

PASS。七类各 12 条；Exact/Alias/Prefix/Typo 为 answer；Ambiguous 为 clarify；Wrong Vendor/Product Conflict 为 no_match；专项测试 `1 passed`；YAML、py_compile、diff 检查通过。

## 数据库影响

无表、无迁移、无生产数据写入。本任务为离线 fixture 校验，没有使用 SQLite；后续持久化测试只接受 PostgreSQL。

## 安全影响

校验器拒绝 API key、密码、Bearer、授权头、租户和 ACL 数据；错误厂商与产品冲突采取 fail-closed 标签。

## 回滚方式

删除 EVAL-003 契约、manifest、校验器、测试和文档即可回滚；EVAL-001 数据集和 V1 运行时不受影响。

## 已知限制

当前验证的是固定输入标签与边界，不执行真实检索指标；Recall、MRR、Citation Accuracy 由后续 EVAL 任务完成。

## 最终结论

PASS
