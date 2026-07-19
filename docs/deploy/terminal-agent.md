# Nexora Terminal Agent

Docker 和 Ubuntu 部署时，Web 后端无法直接启动用户电脑上的 Xshell、PuTTY 或 SSH。浏览器也不能直接执行本地程序，因此部署环境使用本机回环地址上的 Terminal Agent，不再使用 `nexora://` 协议。

## Windows 工作站

在工作站上准备 Python 3.10 或更高版本，然后在项目目录执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-terminal-agent.ps1
```

脚本会创建 `NexoraTerminalAgent` 登录启动任务，并监听：

```text
http://127.0.0.1:17890
```

验证：

```powershell
Invoke-WebRequest http://127.0.0.1:17890/health
```

个人设置中的终端程序路径仍然填写工作站上的 Xshell/PuTTY 可执行文件路径。若需要自定义端口，可设置 `terminal_agent_url` 为 `http://127.0.0.1:<端口>`。

## Ubuntu 工作站

如果浏览器也运行在 Ubuntu 工作站上，可执行：

```bash
chmod +x scripts/install-terminal-agent.sh
./scripts/install-terminal-agent.sh
```

标准终端模式会调用系统 `ssh`。Xshell、PuTTY 等 Windows 客户端只能在 Windows 工作站上使用。

## Docker / Ubuntu 服务端

Docker 构建必须在仓库根目录执行，构建上下文需要同时包含 `Dockerfile`、`scripts/terminal_agent.py` 和 `backend/`。如果出现 `COPY scripts/terminal_agent.py ... not found`，说明服务器仍是旧代码或使用了错误的子目录作为构建上下文，请先同步 `main`：

```bash
git fetch origin main
git reset --hard origin/main
docker compose build --no-cache netops
```

后端服务端不需要运行 Terminal Agent。用户从自己的工作站访问 Nexora 时，Agent 必须运行在该用户的电脑上。前端通过一次性短期令牌调用：

```text
POST http://127.0.0.1:17890/v1/terminal/launch
```

Agent 再向当前 Nexora 后端交换令牌并启动客户端，密码不会返回浏览器，也不会写入 Agent 日志。

生产环境可设置允许的站点来源：

```text
NEXORA_AGENT_ALLOWED_ORIGINS=https://netops.example.com,http://192.168.56.1:5150
NEXORA_AGENT_TLS_VERIFY=1
```

Agent 只允许监听 `127.0.0.1`，不能通过局域网直接暴露。
