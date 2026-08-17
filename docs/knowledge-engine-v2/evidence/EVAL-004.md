# EVAL-004 Evidence

## Task ID

EVAL-004

## 目标

覆盖指定版本、未指定版本、冲突版本和未知版本。

## 修改文件

- `docs/knowledge-engine-v2/eval/eval-version-coverage-v1.yaml`
- `docs/knowledge-engine-v2/eval/eval-version-coverage-v1.manifest.json`
- `docs/knowledge-engine-v2/architecture/EVAL-004-VERSION-COVERAGE-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval_version_coverage_check.py`
- `tests/knowledge_engine_v2/test_eval004_version_coverage.py`
- `docs/walkthrough/20260817_eval004_version_coverage.md`

## 实现内容

复用 EVAL-001 的指定/未指定/冲突版本案例，并增加 12 条显式未知版本 fixture。校验器要求未知 release 不在 supported_versions，且冲突/未知都 fail-closed 为 no_match、空 Gold。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_version_coverage_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval004_version_coverage.py -q -p no:cacheprovider
.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('docs/knowledge-engine-v2/eval/eval-version-coverage-v1.yaml',encoding='utf-8')); print('version_coverage_yaml=PASS')"
.venv\Scripts\python.exe -m py_compile scripts/knowledge_engine_v2_eval_version_coverage_check.py tests/knowledge_engine_v2/test_eval004_version_coverage.py
git diff --check
```

## 测试结果

PASS。specified/unspecified/conflict/unknown 各 12 条；未知版本覆盖 12 个厂商/意图组合；专项测试 `1 passed`；YAML、py_compile、diff 检查通过。

## 数据库影响

无表、无迁移、无生产数据写入。本任务为离线版本 fixture，没有使用 SQLite；后续持久化测试只接受 PostgreSQL。

## 安全影响

版本样例为公开格式和 fixture 标识，不含凭据、租户或 ACL；冲突与未知版本均明确 fail-closed。

## 回滚方式

删除 EVAL-004 契约、fixture、manifest、校验器、测试和文档即可回滚；EVAL-001 和 V1 不受影响。

## 已知限制

当前验证版本分类和标签，不执行真实文档检索；版本匹配指标和质量统计由后续 EVAL 任务完成。

## 最终结论

PASS
