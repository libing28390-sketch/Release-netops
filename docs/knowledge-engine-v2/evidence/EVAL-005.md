# EVAL-005 Evidence

## Task ID

EVAL-005

## 目标

定义 Recall@K、Precision@K、MRR、NDCG 和 Entity Resolution Accuracy。

## 修改文件

- `backend/ai/services/evaluation_metrics.py`
- `scripts/knowledge_engine_v2_eval_metrics_check.py`
- `tests/knowledge_engine_v2/test_eval005_metrics.py`
- `docs/knowledge-engine-v2/architecture/EVAL-005-METRICS-CONTRACT.yaml`
- `docs/knowledge-engine-v2/eval/eval-metrics-v1.manifest.json`
- `docs/walkthrough/20260817_eval005_metrics.md`

## 实现内容

提供纯 Python、无状态指标函数和宏平均报告。实现了二值相关性、唯一结果去重、K 分母、no-match fail-closed 约定、NFKC/casefold/分隔符规范化和实体全字段精确匹配。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_metrics_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval005_metrics.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile backend/ai/services/evaluation_metrics.py scripts/knowledge_engine_v2_eval_metrics_check.py tests/knowledge_engine_v2/test_eval005_metrics.py
git diff --check
```

## 测试结果

PASS。五项指标 smoke report PASS；专项测试 `1 passed`；py_compile/diff PASS。示例实体解析准确率为 `0.666667`，no-match 空结果边界符合契约。

## 数据库影响

无表、无迁移、无生产数据写入。指标模块自身不连接 PostgreSQL 或 SQLite；SQLite 未作为验收证据。数据库版评测调用方只能读取 PostgreSQL 数据。

## 安全影响

指标函数只处理 bounded IDs/实体字段，不记录正文、SQL、URL 或凭据；未知实体预测不会被奖励。

## 回滚方式

删除指标模块、smoke report、测试和文档即可回滚；无数据库 rollback。

## 已知限制

当前仅定义离线宏指标，未连接真实检索输出；EVAL-009 将负责可重复完整评测报告。

## 最终结论

PASS
