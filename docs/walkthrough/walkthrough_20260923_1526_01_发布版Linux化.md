# 完成摘要

v1.0.9 已将 Nexora 服务端发行形态收敛为 Linux / Ubuntu / Docker：移除 Windows 原生服务端桌面包、pgvector Windows 运行时和 Windows 服务端发布 job；同时保留 Windows 浏览器访问 Linux 服务端所需的 Workstation Agent、Web PAM 浏览器拉起、Windows 终端 Agent 自启动和 Windows 资产/WinRM 管理能力。

# 实际修改文件

- 删除根目录 Windows 桌面启动器、PyInstaller spec、Windows EXE、Windows pgvector 资源及 Windows 部署文档。
- 更新 `.github/workflows/release.yml`：Linux release 只发布 Linux/Docker 归档；tag 触发独立 `release-windows-workstation-agent` job 构建并挂载 `NexoraTerminalAgent.exe`，不恢复 Windows 服务端包。
- 更新 `backend/api/system.py`、`.env.example`、`docker-compose.yml`：按浏览器工作站平台下载 Linux 安装脚本或从 `TERMINAL_AGENT_WINDOWS_URL` 流式返回 Windows Agent。
- 保留并公开 Windows Agent 的 PowerShell 安装、自启动排障文档和 Terminal Agent Web PAM 浏览器能力。
- 更新 README、DEPLOY、Gitee/部署导航和 `docs/deploy/release-notes.md`，明确 v1.0.8 是最后一个 Windows 原生服务端版本，v1.0.9 的 Windows Agent 仅用于工作站接入。
- 更新 Knowledge Engine release target matrix、门禁检查和前端版本 fallback；保留既有存储、SNMP hostname sync、CI 日志改造。

# 关键实现说明

服务端启动入口和 `package.json` 生产命令仅保留 Linux 路径。Docker 镜像不再打包 Windows 桌面 EXE；Windows 浏览器在个人设置下载 Agent 时使用 `/api/system/download-terminal-agent?platform=windows`，API 读取内网可配置 URL，默认指向 v1.0.9 Release 的独立 Agent 资产。Web PAM 仍由工作站 Agent 调用本机系统浏览器，未被 Linux-only 服务端清理误删。

# 验证命令与结果

- `python scripts/knowledge_eval_ci_gate_check.py`：PASS，并刷新 release workflow SHA-256 证据。
- `python scripts/validate_postgresql_only.py`：0 violations，PASS。
- `python scripts/validate_knowledge_test_config.py --file docs/knowledge-engine/governance/test-environment.example --environment test`：PASS。
- `python -m py_compile backend/api/system.py backend/main.py scripts/terminal_agent.py`：PASS。
- `python -m pytest --noconftest backend/tests/pam/test_web_agent_runtime.py backend/tests/pam/test_terminal_agent_autostart.py backend/tests/security/test_terminal_agent_boundaries.py -q -p no:cacheprovider`：19 passed。
- `python -m pytest tests/knowledge_engine/test_eval010_ci_gate.py -q -p no:cacheprovider`：2 passed。
- `npm run lint`：PASS。
- `npm run test:frontend -- --run`：71 files / 272 tests passed。
- `npm run build`：PASS，生成前端 `dist/index.html`。
- Python YAML 解析 `.github/workflows/release.yml`：PASS。
- `git diff --check`：PASS（仅 Git 提示跨平台换行即将转换）。

# 未执行验证及原因

- 完整 `backend/tests` 未在当前 Windows 工作站执行：仓库要求 PostgreSQL 测试夹具，当前环境未提供 `DATABASE_URL` 对应的测试 PostgreSQL 服务；非数据库 Agent 测试已单独通过。
- Docker 构建和 Windows GitHub runner 的 PyInstaller 实际构建未在本机执行：当前主机无 Docker，Windows Agent 构建由 tag workflow 在 `windows-latest` 执行。

# 剩余风险/后续建议

- 发布前确认 `Release-netops` tag 下的 `NexoraTerminalAgent.exe` 已被 Windows job 挂载，且生产 `.env` 的 `TERMINAL_AGENT_WINDOWS_URL` 指向可访问的内网地址。
- v1.0.8 保留作为 Windows 原生服务端回滚点；v1.0.9 以后只支持 Linux/Ubuntu/Docker 服务端部署。
