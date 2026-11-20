# EVAL-009 可重复离线评测命令

## 目标

把 EVAL-001～EVAL-008 的数据集、覆盖、指标、安全和人工标注校验串成一个固定顺序的离线命令，并输出可被 CI/质量门禁消费的 JSON 报告。

## 命令

```powershell
$env:PYTHONPATH='backend'
.venv\Scripts\python.exe scripts/knowledge_engine_v2_eval_offline.py --strict
```

默认报告为 `docs/knowledge-engine/eval/eval-offline-report-v1.json`。严格模式要求 8 个组件全部 PASS；报告包含每个组件的状态和报告、数据库/外网安全边界、生产写入标记、固定命令版本和 SHA-256。

## 可重复性

报告不写当前时间或随机数，输入数据集和组件报告均带 hash；测试在同一工作树连续运行两次并要求 JSON 完全相等。报告 hash 是去掉自身 hash 后的规范 JSON SHA-256。

本任务是离线 runner：数据库为 `none`，SQLite 为 `not_used`，不访问外网、不写生产。未来如果评测 runner 读取数据库样本，必须使用 PostgreSQL。

## 结果

8 个组件全部 PASS，机器可读报告生成成功，重复运行结果一致。
