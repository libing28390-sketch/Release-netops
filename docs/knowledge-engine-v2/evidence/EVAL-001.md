# EVAL-001 Evidence

## Task ID

EVAL-001

## 目标

建立 100～200 条固定、可脱敏、可复现的首批 Query 数据集。

## 修改文件

- `docs/knowledge-engine-v2/eval/eval-query-dataset-v1.yaml`
- `docs/knowledge-engine-v2/eval/eval-query-dataset-v1.manifest.json`
- `docs/knowledge-engine-v2/architecture/EVAL-001-FIXED-QUERY-DATASET-CONTRACT.yaml`
- `scripts/knowledge_engine_v2_eval_dataset_check.py`
- `tests/knowledge_engine_v2/test_eval001_query_dataset.py`
- `docs/walkthrough/20260817_eval001_fixed_query_dataset.md`

## 实现内容

冻结 120 个 Query 案例，覆盖 Huawei/Cisco、VLAN/Interface/OSPF/SSH/NTP/Route，以及 exact、alias、prefix、ambiguous、typo、wrong_vendor、product_conflict、version_exact、version_conflict、no_match 十类输入。每条记录包含期望结果、版本关系、厂商/平台条件、fixture 文档 ID 和引用要求。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_dataset_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval001_query_dataset.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile scripts/knowledge_engine_v2_eval_dataset_check.py tests/knowledge_engine_v2/test_eval001_query_dataset.py
git diff --check
```

## 测试结果

PASS。Validator 输出 `case_count=120`、每种 Query 类型 12 条、每种意图 20 条、`secrets=false`、`database=none`、`sqlite=not_used`；专项测试 `1 passed`。

## 数据库影响

无表、无迁移、无生产数据写入。本任务是离线 fixture 校验；没有使用 SQLite。任何后续数据库测试必须连接 PostgreSQL。

## 安全影响

禁止 API key、密码、Bearer、授权头、租户/ACL 数据；校验器扫描序列化案例并拒绝敏感标记。

## 回滚方式

通过文档提交删除 fixture、manifest、校验器和专项测试即可回滚；不需要数据库 rollback，也不会影响 V1。

## 已知限制

当前只冻结输入与期望标签，不执行检索评分；评分、版本覆盖、延迟和质量门禁由后续 EVAL 任务完成。

## 最终结论

PASS
