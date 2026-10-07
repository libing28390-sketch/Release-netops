# Promptfoo 评估路径与失败诊断：执行记录

## 完成摘要

修正 Promptfoo Python provider 相对评估 YAML 的路径，并修复 Promptfoo 0.118.0 数值 `failureReason` 覆盖实际错误文本的脱敏报告问题。

## 实际修改文件

- `docs/knowledge-engine/eval/promptfoo-rag-gate.yaml`
- `scripts/promptfoo_gate_report.py`
- `backend/tests/ai/test_promptfoo_gate_report.py`
- `docs/plans/plan_20261008_0256_01_Promptfoo评估路径与失败诊断.md`
- `docs/fixes/fix_20261008_0256_01_Promptfoo评估路径与失败诊断.md`

## 关键实现说明

provider 路径现从 `docs/knowledge-engine/eval/` 向上回到仓库根并解析到 `scripts/promptfoo_nexora_provider.py`。报告在枚举之外优先分类真实错误文本，仅输出安全类别，不保留错误正文。

## 验证命令与结果

- `.venv\Scripts\python.exe -m pytest backend/tests/ai/test_promptfoo_gate_report.py -q -p no:cacheprovider`：3 passed。
- `.venv\Scripts\python.exe scripts/knowledge_eval_ci_gate_check.py`：PASS。
- `git diff --check`、提交和 GitHub Actions：待完成。

## 未执行验证及原因

Promptfoo smoke/full 需要安装 Node 依赖并使用隔离 PostgreSQL；本地没有 Promptfoo 依赖或独立数据库，所以依赖 workflow 在推送后的运行结果核验。

## 剩余风险与后续建议

需确认 Promptfoo smoke 与完整 50 条评估通过、发布 workflow 通过，并检查公共 Release-netops 同步结果。当前未修改资产导入/LibreNMS 纳管代码；该链路已在 `786c0eab` 中实现，4 个相关专项测试文件通过 72 项。
