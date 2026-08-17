# EVAL-002 Evidence

## Task ID

EVAL-002

## 目标

覆盖 Huawei/Cisco 的 VLAN、Interface、OSPF、SSH、NTP、Route 六类网络意图。

## 修改文件

- `docs/knowledge-engine-v2/eval/eval-intent-coverage-v1.yaml`
- `docs/knowledge-engine-v2/eval/eval-intent-coverage-v1.manifest.json`
- `docs/knowledge-engine-v2/architecture/EVAL-002-INTENT-COVERAGE-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval_intent_coverage_check.py`
- `tests/knowledge_engine_v2/test_eval002_intent_coverage.py`
- `docs/walkthrough/20260817_eval002_intent_coverage.md`

## 实现内容

建立 12 个厂商/意图 Track，每个 Track 提供 3 条厂商特有 CLI 语义示例，并与 EVAL-001 的 9 条显式案例、平台/产品/OS/版本元数据和 Gold fixture 建立一致性校验。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_intent_coverage_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval002_intent_coverage.py -q -p no:cacheprovider
.venv\Scripts\python.exe -c "import yaml; yaml.safe_load(open('docs/knowledge-engine-v2/eval/eval-intent-coverage-v1.yaml',encoding='utf-8')); print('coverage_yaml=PASS')"
.venv\Scripts\python.exe -m py_compile scripts/knowledge_engine_v2_eval_intent_coverage_check.py tests/knowledge_engine_v2/test_eval002_intent_coverage.py
git diff --check
```

## 测试结果

PASS。Validator 输出 `track_count=12`、`query_example_count=36`、每个 Track 9 条父数据集案例；专项测试 `1 passed`；YAML、py_compile、diff 检查通过。

## 数据库影响

无表、无迁移、无生产数据写入。本任务是离线 coverage fixture，数据库为 `none`，没有使用 SQLite。后续持久化验收只接受 PostgreSQL 结果。

## 安全影响

CLI 样例仅包含公开命令词和 fixture 标识，不包含 API key、密码、Bearer、授权头、租户、ACL 或设备真实数据；外网访问被禁止。

## 回滚方式

删除 EVAL-002 coverage YAML、manifest、校验器、测试和文档即可回滚；EVAL-001 父数据集与 V1 运行时不受影响。

## 已知限制

当前冻结的是输入覆盖和元数据一致性，不代表检索质量指标已经完成；Recall、MRR、Citation Accuracy 等由后续 EVAL 任务实现。

## 最终结论

PASS
