# 工作区代码推送与 Actions 验收

## 已完成的准备

- 当前分支为 `main`；开始检查时 `HEAD` 与本地缓存 `origin/main` 都是 `85c63b0c`。
- 工作区共 245 项状态变化，分为业务源码、测试、正式计划/走查文档和本地生成物。计划只提交前 3 类，并排除 `.agents/`、`handoff.md`、`logs/`、`.codex*` 与 `dist*`。
- 读取了仓库发布工作流：每次推送 `main` 会跑后端完整 PostgreSQL 测试、前端 lint/build，并同步净化后的发布树到 `Release-netops`；本次不打版本标签。
- 首次提交 `e810a4e380e504ccd7ec1260541f7cdc4d98d368` 已推送到 `origin/main`；Actions run #750 (`40204705116`) 已完成但失败。

## 当前阻塞

- 推送期间 GitHub HTTPS 连接一度重置，重试后普通 `git push origin main` 成功；用户级 GCM 路径缺失提示不影响系统级凭据助手完成认证。
- GitHub Apps Connector 对源私有仓库返回 404；通过本机 GCM 认证的 GitHub API 获取了 run/job 状态与日志。

## 本地验证基线

- SNMP 开关功能回归：123 项通过；最终探测用例追加回归 20 项通过。
- `npm run lint`、Vite build、`scripts/validate_postgresql_only.py` 均通过；前端全量 171 个文件、715 项通过。
- 本机全量 `pytest backend/tests` 收集到 3968 项，Actions 启动后在 19% 处停止；CI run #750 的后端 pytest gate 在 45 秒后于 collection 阶段失败，尚未执行后续 CI 步骤。

## Actions #750 失败证据与修复

- 失败 job：`Release Ubuntu / Linux (main branch)`，job ID `121203068959`。
- 失败日志指向 `backend/services/scheduled_job_run_service.py:508`：文件结尾包含字面量 `\\n`，Python 将其作为续行符后面的非法字符，导致 30 个测试模块收集失败。
- 日志同时指向 `backend/tests/tickets/test_incident_tickets.py` 的相同文件尾部问题。已从首提交恢复两个文件内容并去掉多余尾缀。
- 定向回归另发现该票据测试 monkeypatch 了 `api.change_orders.core.is_control_sheet_enabled`，但 core 模块并未导入此函数；已删除两处无效 patch。`py_compile` 通过，`test_m5_authorization_runs.py` 与 `test_incident_tickets.py` 共 20 项通过。
- 下一步是创建修复记录并追加推送，跟踪新 Actions run；全绿后再关机。
