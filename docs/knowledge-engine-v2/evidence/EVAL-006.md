# EVAL-006 Evidence

## Task ID

EVAL-006

## 目标

定义 Product、OS、Version Match、Wrong Vendor、Official Source 和 Citation Accuracy。

## 修改文件

- `backend/ai/services/evaluation_metrics.py`
- `scripts/knowledge_engine_v2_eval_quality_metrics_check.py`
- `tests/knowledge_engine_v2/test_eval006_quality_metrics.py`
- `docs/knowledge-engine-v2/architecture/EVAL-006-QUALITY-METRICS-CONTRACT.yaml`
- `docs/knowledge-engine-v2/eval/eval-quality-metrics-v1.manifest.json`
- `docs/walkthrough/20260817_eval006_quality_metrics.md`

## 实现内容

新增六项质量/来源指标，明确 exact、unspecified、conflict、unknown、ambiguous、no-match 和引用异常行为，并复用 EVAL-005 的实体规范化规则。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_quality_metrics_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval006_quality_metrics.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile backend/ai/services/evaluation_metrics.py scripts/knowledge_engine_v2_eval_quality_metrics_check.py tests/knowledge_engine_v2/test_eval006_quality_metrics.py
git diff --check
```

## 测试结果

PASS。Product/OS Match 为 `0.666667`，Version Match 为 `1.0`，Wrong Vendor/Official Source/Citation Accuracy 均按故意错误样例得到 `0.333333/0.666667/0.666667`；专项测试 `1 passed`，py_compile/diff PASS。

## 数据库影响

无表、无迁移、无生产数据写入。指标模块不连接 PostgreSQL 或 SQLite；SQLite 未作为验收证据。数据库版评测调用方必须读取 PostgreSQL。

## 安全影响

官方来源和引用指标要求可追溯 Gold；错误厂商、未知实体和非官方引用不被计为成功；不记录正文、SQL 或凭据。

## 回滚方式

删除 EVAL-006 新增函数、smoke report、测试和文档即可回滚；无数据库 rollback。

## 已知限制

当前使用离线 citation metadata；真实 Source Registry 官方状态接入由后续 EVAL-009/012 评测负责。

## 最终结论

PASS
