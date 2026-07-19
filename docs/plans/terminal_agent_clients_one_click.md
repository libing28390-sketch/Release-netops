# Terminal Agent 双客户端与一键启动改造计划

## 目标

让 Docker/Ubuntu 后端部署下的终端登录对普通用户足够简单，同时明确区分 Windows 与 Ubuntu 工作站：

- Windows：下载 `NexoraTerminalAgent.exe`，双击即可启动本机回环代理。
- Ubuntu：下载 `install-terminal-agent.sh`，通过 systemd user service 常驻运行。
- Docker：只负责签发一次性会话令牌，不在容器内启动本机代理。

## 实施项

1. Windows CI 使用 PyInstaller 构建独立的 `NexoraTerminalAgent.exe`，同步到 Windows 发布分支。
2. 后端下载接口增加 `platform=windows|ubuntu`，Windows 优先返回 EXE；Docker 无本地 EXE 时从 Windows 发布分支代理为附件下载，Ubuntu 返回 systemd 安装脚本。
3. Docker 镜像保留 Ubuntu 安装脚本，并提供可配置的 `TERMINAL_AGENT_WINDOWS_URL`，私有仓库可以替换为内部地址。
4. 个人设置下载入口同时展示 Windows 一键启动和 Ubuntu 安装脚本，避免用户下载错误平台文件。
5. 文档补充小白用户操作、运维人员自动启动方式、服务端与工作站职责边界。

## 验收标准

- Windows 浏览器点击 Windows 入口后得到 `NexoraTerminalAgent.exe`，双击后 `GET /health` 返回成功。
- Ubuntu 浏览器点击 Ubuntu 入口后得到 `install-terminal-agent.sh`，执行后 systemd user service 监听 `127.0.0.1:17890`。
- Docker 后端不会尝试绑定 `127.0.0.1:17890`；平台入口不会互相返回错误类型的安装包。
- 下载接口对未知平台返回明确错误；未配置远程 Windows 地址时返回可诊断错误。
