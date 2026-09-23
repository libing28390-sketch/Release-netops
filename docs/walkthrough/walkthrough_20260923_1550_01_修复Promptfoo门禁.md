# 完成摘要

定位到当前本机 PostgreSQL 测试库中的 Promptfoo Provider 契约没有业务失败：同一份 50 条 YAML 用例逐条调用 Provider 后为 `50/50` 通过。GitHub 日志只暴露 `0/50` 聚合结果，没有显示 Provider 异常类别，因此本次先补充安全的错误分类诊断，供 tag runner 重新执行时直接定位根因。

# 实际修改文件

- `scripts/promptfoo_nexora_provider.py`：Provider 捕获异常时仅记录异常类型和固定阶段，不输出 SQL、连接串、响应体或敏感参数；将安全字段放入 metadata。
- `scripts/promptfoo_gate_report.py`：兼容 Promptfoo 的 `error` 字段，脱敏报告保留 `error_type`/`error_stage`，并在 CI 日志输出聚合失败类别。
- `backend/tests/ai/test_promptfoo_gate_report.py`：增加错误字段与异常类型脱敏回归断言。

# 验证命令与结果

- `python -m pytest --noconftest backend/tests/ai/test_promptfoo_gate_report.py -q -p no:cacheprovider`：1 passed。
- `python -m py_compile scripts/promptfoo_nexora_provider.py scripts/promptfoo_gate_report.py`：通过。
- `python scripts/validate_postgresql_only.py`：0 violations。
- 本机 PostgreSQL `nexora_promptfoo_ci` 测试库中逐条执行 Promptfoo Provider 契约：50/50 cases pass。

# 未执行验证及原因

- 当前 Windows 主机无法运行 Linux Promptfoo runner；本机 Node 24 也没有 `better-sqlite3` 的 Node 24 原生绑定，不能直接启动 Promptfoo CLI。GitHub workflow 使用 Node 22，并会执行 `npm rebuild better-sqlite3`。
- 需要 tag runner 再执行一次，确认新增诊断输出中的真实 `error_type`/`error_stage`；本次没有降低断言或跳过失败。

# 剩余风险/后续建议

- 如果重跑仍失败，优先根据新的失败类别检查 GitHub Python 依赖、PostgreSQL 连接池或 Promptfoo Python wrapper；本地业务 Provider 已通过 50/50。
- 若重跑通过，本次红色门禁属于 runner/依赖瞬态问题；若仍失败，继续按类别修复而不改弱质量标准。
