# 本地 Terminal Agent 替代浏览器协议启动

## 目标

Docker 和 Ubuntu 服务端无法直接启动用户工作站上的 Xshell、PuTTY 或系统 SSH。此前依赖浏览器 `nexora://` 协议，会触发浏览器原生确认框并产生空白标签页。本次改为回环 HTTP Agent，不再调用自定义协议。

## 实现

- `scripts/terminal_agent.py`：仅监听 `127.0.0.1:17890`，通过一次性会话令牌从后端换取连接信息并启动本地客户端。
- `src/pages/AccessCenterTab.tsx`：远程后端返回 `client_side` 令牌后调用 `http://127.0.0.1:17890/v1/terminal/launch`。
- `src/pages/AssetManagement/index.tsx`：资产终端入口使用同一 Agent。
- `backend/api/system.py`：本地 Windows 后端路径可用时直接启动；远程/Docker 路径不可用时返回短期令牌供 Agent 使用。
- `scripts/install-terminal-agent.ps1` 和 `scripts/install-terminal-agent.sh`：分别提供 Windows 登录启动和 Ubuntu systemd 用户服务安装。
- `Dockerfile`：将 Agent 脚本放入镜像，个人设置可下载。

## 验证

- `npm run lint`：通过。
- `npm run build`：通过；保留既有大 chunk 体积提示。
- `python -m py_compile backend/api/system.py scripts/terminal_agent.py`：通过。
- `pytest backend/tests/test_terminal_agent.py backend/tests/scheduled_jobs/test_system_jobs.py -q`：7 passed。
- Agent `/health` 回环接口：返回 `success=true`。

## 部署注意

Agent 必须运行在使用浏览器的工作站，而不是 Docker/Ubuntu 后端容器。若前端使用 Ubuntu 部署脚本生成的 CSP，已放行 `127.0.0.1:17890` 和 `localhost:17890`。生产环境可通过 `NEXORA_AGENT_ALLOWED_ORIGINS` 限制允许的站点来源。
