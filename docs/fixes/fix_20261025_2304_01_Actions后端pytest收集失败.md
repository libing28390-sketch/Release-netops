# 修复记录：Actions 后端 pytest 收集失败

## 问题现象

工作区提交 `e810a4e380e504ccd7ec1260541f7cdc4d98d368` 推送后，Actions #750 的 Linux 后端 pytest gate 在 collection 阶段失败，后续前端构建、知识引擎评估和发布树同步步骤均未运行。

## 根因

提交前清理两个文件的尾部空行时，PowerShell/Python 转义处理错误，将字面量 `\\n` 写到文件末尾，导致 Python 在 `backend/services/scheduled_job_run_service.py:508` 抛出 `SyntaxError: unexpected character after line continuation character`。同样的尾缀也出现在票据测试文件中。

定向复测还发现票据测试对 `api.change_orders.core.is_control_sheet_enabled` 做 monkeypatch，但该函数不在 core 模块中，也不由该测试调用。

## 解决方案

- 从首提交恢复 `backend/services/scheduled_job_run_service.py` 与 `backend/tests/tickets/test_incident_tickets.py`，移除错误字面量及多余空行，保留标准行结束符。
- 删除两处对 core 模块中不存在的 `is_control_sheet_enabled` 属性的 monkeypatch；保留对 core 模块实际导入的 `is_template_required` 设置。
- 将修复追加到 `main`，不重写或强制更新远端历史。

## 实际修改文件

- `backend/services/scheduled_job_run_service.py`
- `backend/tests/tickets/test_incident_tickets.py`
- 本修复记录及工作区推送 walkthrough

## 验证命令与结果

- `python -m py_compile backend/services/scheduled_job_run_service.py backend/tests/tickets/test_incident_tickets.py`：通过。
- `pytest backend/tests/scheduled_jobs/test_m5_authorization_runs.py backend/tests/tickets/test_incident_tickets.py`：20 项通过。
- Actions #750 的 job log 明确显示上述语法错误导致 30 项收集错误；修复提交的 Actions 需重新运行完整后端、前端与发布 gate。

## 未验证项、风险与回滚方式

- 修复提交对应的 GitHub Actions 尚未运行；只有该提交所有必需 job 成功后才关机。
- 如后续 Actions 失败，按新 job 日志继续修复并追加提交；必要时可用 `git revert <commit>` 回滚，不使用 reset 或 force push。
