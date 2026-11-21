# Guacamole 内网 WebSocket 代理绕行

## 问题现象

本机 RDP profile 已保存，Access Center 可见 RDP 入口，但会话启动后失败。PAM 会话审计记录 `GUACAMOLE_TUNNEL_FAILED`，目标认证尚未开始，录像状态为 `not_started`。

## 根因

远端 `nexora-netops` 容器设置了 `HTTP_PROXY` 与 `HTTPS_PROXY`，运行时 websockets 版本为 17.2。自 websockets 15 起客户端会自动读取代理环境变量；Nexora 到内部 `guacamole:8080` 的 WebSocket 隧道因此尝试经代理连接内网服务。

## 解决方案

- 内部 Guacamole WebSocket 建连显式传入 `proxy=None`。
- 将 `backend/requirements.txt` 的 websockets 最低版本从 12.0 提高到 15.0，以保证所用参数存在。
- 增加回归测试，断言内部隧道禁用代理并保留 Guacamole 子协议和 Origin。

## 实际修改文件

- `backend/api/remote_desktop.py`
- `backend/requirements.txt`
- `backend/tests/pam/test_remote_desktop_tunnel_proxy.py`
- `docs/plans/plan_20261013_0958_01_Guacamole_RDP_VNC纳管.md`
- `docs/walkthrough/walkthrough_20261013_0958_01_Guacamole_RDP_VNC纳管.md`
- 本修复记录。

## 验证

- `\.venv\Scripts\python.exe -m pytest backend/tests/pam/test_remote_desktop_guacamole_service.py backend/tests/pam/test_remote_desktop_recording_file.py backend/tests/pam/test_remote_desktop_log_redaction.py backend/tests/pam/test_remote_desktop_tunnel_proxy.py -q`：10 passed。
- `git diff --check`：通过。
- GitHub Actions、远端重新部署、RDP 登录和录像/S3 验收：待本次提交后执行。

## 风险与回滚

禁用代理只作用于 Nexora 到内部 Guacamole 的 WebSocket 连接；其他外部请求的代理设置不变。若回归检查失败，回退 `proxy=None` 和依赖下限调整；原有 profile、资产凭据及数据库数据保留。
