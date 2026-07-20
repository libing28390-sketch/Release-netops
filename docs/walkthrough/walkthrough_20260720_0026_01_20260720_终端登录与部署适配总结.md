# 2026-07-20 终端登录与 Docker/Ubuntu 部署适配总结

## 一、今天发现的问题

### 1. 浏览器反复弹出外部协议确认框

在操作工作台登录本地终端时，浏览器反复显示：

> 是否打开 Nexora Terminal Assistant？

同时页面会短暂打开一个空白标签页。原因是前端使用 `nexora://` 自定义协议调起 Windows 客户端，而浏览器对每次外部协议调用都执行安全确认。该确认框属于浏览器安全策略，无法通过 React、`localStorage` 或普通 JavaScript 强制关闭。

### 2. Windows 本地部署和 Docker/Ubuntu 部署的能力不一致

- Windows 本地部署时，后端可以直接访问本机的 Xshell、PuTTY 或 SSH 可执行文件，因此可以直接启动终端。
- Docker/Ubuntu 后端运行在服务器或容器中，无法启动用户 Windows 工作站上的终端程序。
- 继续依赖 `nexora://` 会导致浏览器确认框、空白标签页和不同浏览器兼容性问题。

### 3. 远程启动时不能把密码交给浏览器

终端需要设备凭据，但密码不能放进前端 URL、浏览器存储或普通接口响应中长期保存。必须继续使用一次性、短时效会话令牌，由本地组件向后端换取凭据并立即启动客户端。

## 二、今天完成的改造

### 1. 新增本地 Terminal Agent

新增 [scripts/terminal_agent.py](../../scripts/terminal_agent.py)：

- 仅监听 `127.0.0.1:17890`，不暴露到局域网。
- 提供 `GET /health` 健康检查。
- 提供 `POST /v1/terminal/launch` 启动接口。
- 接收一次性会话令牌，不保存密码。
- 由 Agent 向 Nexora 后端的 `/api/system/exchange-token` 换取一次性凭据。
- 支持系统 SSH、Xshell、PuTTY、SecureCRT、MobaXterm。
- 使用参数数组启动进程，不使用 shell 拼接命令，降低命令注入风险。
- 支持 CORS、Private Network Access 和可选的 `NEXORA_AGENT_ALLOWED_ORIGINS` 来源限制。

### 2. 前端移除 `nexora://` 调用

以下入口统一改为 HTTP 调用本地 Agent：

- [src/pages/AccessCenterTab.tsx](../../src/pages/AccessCenterTab.tsx)
- [src/pages/AssetManagement/index.tsx](../../src/pages/AssetManagement/index.tsx)

新的调用流程：

```text
前端请求后端创建会话
    ↓
后端返回一次性 session_token
    ↓
前端请求 127.0.0.1:17890/v1/terminal/launch
    ↓
Agent 向后端交换凭据
    ↓
Agent 在用户工作站启动 SSH 客户端
```

因此前端不再创建 `about:blank` 标签页，也不再导航到 `nexora://`，浏览器不会再出现外部协议确认框。

### 3. 保留 Windows 本地后端直启能力

当后端和终端程序运行在同一台 Windows 电脑上，后端会优先直接启动本地可执行文件；只有后端无法访问该路径时，才返回会话令牌交给本地 Agent。

同时将 `CREATE_NEW_CONSOLE` 改为跨平台兼容写法，避免 Ubuntu 环境因不存在 Windows 常量而失败。

### 4. Docker 和 Ubuntu 发布适配

- [Dockerfile](../../Dockerfile) 将 Agent 脚本放入镜像，便于个人设置下载。
- [deploy-ubuntu.sh](../../deploy-ubuntu.sh) 的 CSP 已允许访问 `127.0.0.1:17890` 和 `localhost:17890`。
- 新增 [scripts/install-terminal-agent.ps1](../../scripts/install-terminal-agent.ps1)，用于 Windows 登录时自动启动 Agent。
- 新增 [scripts/install-terminal-agent.sh](../../scripts/install-terminal-agent.sh)，用于 Ubuntu systemd 用户服务启动 Agent。
- 新增 [docs/deploy/terminal-agent.md](../deploy/terminal-agent.md)，记录安装、配置、验证和安全要求。
- 个人设置中的旧助手下载入口已改为下载 `terminal_agent.py`。

## 三、部署方式

### Docker 后端

重新构建镜像并启动：

```bash
docker compose up -d --build
```

然后在实际打开浏览器的工作站上启动 Agent，而不是在后端容器中启动。

### Windows 工作站

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-terminal-agent.ps1
```

验证：

```powershell
Invoke-WebRequest http://127.0.0.1:17890/health
```

### Ubuntu 工作站

```bash
chmod +x scripts/install-terminal-agent.sh
./scripts/install-terminal-agent.sh
```

标准 SSH 模式会调用系统 `ssh` 命令。Xshell、PuTTY 等 Windows 客户端仍然只能在 Windows 工作站运行。

## 四、凭据和安全边界

- 浏览器只接触一次性 `session_token`，不接触明文密码。
- 后端仍然根据普通账号/管理员账号解析资产凭据。
- Token 交换后立即消费，不能重复使用。
- Agent 默认仅绑定回环地址。
- 可通过 `NEXORA_AGENT_ALLOWED_ORIGINS` 限制站点来源。
- 可通过 `NEXORA_AGENT_TLS_VERIFY=1` 开启后端 HTTPS 证书校验。
- 旧的 `nexora_handler.py` 和协议下载接口暂时保留，作为兼容代码，但当前前端流程已经不再调用它们。

## 五、验证结果

已完成以下验证：

- `npm run lint`：通过。
- `npm run build`：通过，退出码为 0。
- `python -m py_compile backend/api/system.py scripts/terminal_agent.py`：通过。
- `pytest backend/tests/test_terminal_agent.py backend/tests/scheduled_jobs/test_system_jobs.py -q`：7 passed。
- Agent `/health` 回环接口：返回 `success: true`。
- `git diff --check`：无代码空白错误。

构建仍有既有的大 chunk 体积提示，属于性能优化项，不影响本次终端登录功能。

## 六、后续验证建议

1. 执行 `docker compose up -d --build` 更新 Docker 前端和后端镜像。
2. 在实际 Windows 工作站安装并启动 Terminal Agent。
3. 访问操作工作台，分别测试普通账号、管理员账号、标准 SSH 和 Xshell/PuTTY。
4. 确认浏览器不再出现 `Nexora Terminal Assistant` 协议确认框。
5. 确认 Agent 未运行时，页面显示清晰的“请启动 Terminal Agent”错误，而不是打开空白页。
