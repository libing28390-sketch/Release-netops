# Nexora Terminal Agent

Terminal Agent 运行在操作员工作站上。前端通过本机回环地址调用它，并传递一次性短期令牌。Agent 只监听回环地址，不向局域网开放，也不会把交换到的凭据写入日志。

## Windows 工作站

下载 `NexoraTerminalAgent.exe` 后双击运行，默认监听：

```text
http://127.0.0.1:17890
```

打包后的 Agent 不需要 Python、Qt 或 Pillow。若从源码运行或需要注册登录启动任务，可使用 Python 3.10+：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-terminal-agent.ps1
```

验证服务：

```powershell
Invoke-WebRequest http://127.0.0.1:17890/health
```

Xshell、PuTTY 等终端程序路径仍在个人设置中配置；需要自定义端口时，将 `terminal_agent_url` 设置为 `http://127.0.0.1:<端口>`。

## Ubuntu 工作站

```bash
chmod +x scripts/install-terminal-agent.sh
./scripts/install-terminal-agent.sh
```

标准终端模式调用本机 `ssh`。Xshell、PuTTY 等 Windows 客户端只能在 Windows 工作站上使用。

## Docker / Ubuntu 服务端

后端服务端不需要运行 Terminal Agent。每台需要 SSH 或 Web PAM 的操作员工作站都要运行自己的 Agent。前端调用：

```text
POST http://127.0.0.1:17890/v1/terminal/launch
POST http://127.0.0.1:17890/v1/web/launch
```

生产环境建议限制前端来源并开启回调 TLS 校验：

```text
NEXORA_AGENT_ALLOWED_ORIGINS=https://netops.example.com,http://192.168.56.1:5150
NEXORA_AGENT_TLS_VERIFY=1
```

Agent 始终只绑定 `127.0.0.1`、`localhost` 或 `::1`，不能直接暴露到管理网。

Docker 镜像会携带 `NexoraTerminalAgent.exe` 作为下载附件。自定义镜像如果没有该文件，可通过环境变量指定企业内部可访问的 Windows Agent 地址：

```text
TERMINAL_AGENT_WINDOWS_URL=https://github.com/libing28390-sketch/Release-netops/raw/refs/heads/windows/NexoraTerminalAgent.exe
```

Windows EXE 和 Ubuntu 安装脚本是两个独立下载入口，不能互相替代。

## Web PAM（HTTP/HTTPS 设备页面）

Web PAM 与 SSH 是两类独立会话。用户选择资产中配置好的 HTTP/HTTPS 入口后，后端创建一次性 PAM 会话；Agent 调用工作站已安装的系统浏览器打开目标 URL。

如果检测到 Edge、Chrome、Brave 等 Chromium 浏览器，Agent 会使用临时 profile 打开独立 app 窗口；否则回退到系统默认浏览器。Nexora 不接收、不自动填写设备账号密码，用户直接在设备页面手工输入。

如需指定浏览器可执行文件，可在工作站设置 `NEXORA_BROWSER_PATH`；Agent 会用该进程跟踪窗口生命周期。

使用流程：

1. 在资产管理中只维护 Web 入口：设备管理 IP、`HTTP` 或 `HTTPS`、实际服务端口，以及相对路径（通常为 `/`）。例如 `192.168.56.11 + HTTPS + 443 + /login` 会生成 `https://192.168.56.11:443/login`。
2. 进入“操作工作台 → WEB”，选择 HTTP 或 HTTPS 入口，再选择普通用户/特权用户发起 PAM 会话。资产管理页不提供 Web 登录按钮。
3. Agent 调用系统浏览器打开 URL，用户手工操作设备页面；关闭浏览器窗口后会话结束。

Windows 下 Agent 大约每两秒采集一次浏览器窗口，结束时上传 PNG 帧 ZIP 供 PAM 审计下载，单个录屏最多 50MB。若当前平台无法采集窗口，网页登录仍可用，但录屏状态为 `not_started`。系统默认浏览器回退模式可能保留地址栏和复制能力，本轻量方案不保证屏蔽这些控件。

不需要额外 Web 运行时。旧命令中的 `-InstallWebRuntime` PowerShell 开关和 `NEXORA_INSTALL_WEB_RUNTIME=1` 环境变量仍可传入，但现在只是兼容性空操作，不会安装 PySide6/Pillow。

确认 `/health` 返回的 `capabilities` 包含 `web_access`；只返回 `terminal` 的旧 Agent 需要升级后才能发起 Web PAM。
