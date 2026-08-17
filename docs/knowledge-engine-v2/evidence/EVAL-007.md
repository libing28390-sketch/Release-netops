# EVAL-007 Evidence

## Task ID

EVAL-007

## 目标

定义秘密泄漏、Prompt Injection、越权和外发策略指标。

## 修改文件

- `backend/ai/services/security_evaluation_metrics.py`
- `docs/knowledge-engine-v2/eval/eval-security-cases-v1.yaml`
- `scripts/knowledge_engine_v2_eval_security_metrics_check.py`
- `tests/knowledge_engine_v2/test_eval007_security_metrics.py`
- `docs/knowledge-engine-v2/architecture/EVAL-007-SECURITY-METRICS-CONTRACT.yaml`
- `docs/knowledge-engine-v2/eval/eval-security-metrics-v1.manifest.json`
- `docs/walkthrough/20260817_eval007_security_metrics.md`

## 实现内容

新增 bounded secret marker / prompt injection 检测、越权执行率和外发合规率函数。安全报告只输出数量、比例、fixture hash 和状态，不回显敏感值或原始输入。

## 执行命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_security_metrics_check.py
.venv\Scripts\python.exe -m pytest tests/knowledge_engine_v2/test_eval007_security_metrics.py -q -p no:cacheprovider
.venv\Scripts\python.exe -m py_compile backend/ai/services/security_evaluation_metrics.py scripts/knowledge_engine_v2_eval_security_metrics_check.py tests/knowledge_engine_v2/test_eval007_security_metrics.py
git diff --check
```

## 测试结果

PASS。Fixture 9 条；Prompt Injection Block Rate `1.0`；Authorization Violation Rate `0.5`；Outbound Policy Compliance Rate `0.666667`；专项测试 `1 passed`；py_compile/diff PASS。Secret Leakage Rate `0.5` 为故意合成泄漏正例，证明检测器能识别，非发布门禁结论。

## 数据库影响

无表、无迁移、无生产数据写入。本任务没有连接 PostgreSQL 或 SQLite；SQLite 未作为验收证据。后续持久化安全评测只接受 PostgreSQL。

## 安全影响

安全检测只返回稳定布尔/计数，不返回匹配 secret、prompt、授权头或外发内容；合成 token 通过 parts 构造，非真实凭据。

## 回滚方式

删除安全指标模块、fixture、manifest、测试和文档即可回滚；无数据库 rollback。

## 已知限制

当前是离线模式指标定义，不替代真实 Gateway/Provider 运行时测试；门禁集成由后续 EVAL-010/011 完成。

## 最终结论

PASS
