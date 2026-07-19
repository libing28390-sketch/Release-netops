# 终端代理双客户端一键启动改造

## 完成内容

- Windows 发布流水线新增 PyInstaller 单文件构建，产物为 `NexoraTerminalAgent.exe`，使用 `--noconsole`，普通用户双击即可启动。
- Ubuntu 仍使用 `install-terminal-agent.sh`，由 systemd user service 管理生命周期。
- `/api/system/download-terminal-agent` 增加平台参数：`windows` 返回 EXE，`ubuntu` 返回 shell 安装脚本。
- Docker 通过 `TERMINAL_AGENT_WINDOWS_URL` 指向 Windows 发布分支；不把 Windows 二进制塞入 Linux 镜像。
- 个人设置页面将两个下载入口分开显示。

## 使用方式

### Windows

在个人设置点击“Windows 一键启动”，双击下载的 `NexoraTerminalAgent.exe`。代理只监听本机 `127.0.0.1:17890`。

### Ubuntu

下载 Ubuntu 脚本后执行：

```bash
chmod +x install-terminal-agent.sh
./install-terminal-agent.sh
```

## 回滚

删除 `TERMINAL_AGENT_WINDOWS_URL` 后重启后端即可停止远程 EXE 重定向；Python/PowerShell 安装脚本仍保留作为运维回退方案。
