# RDP WebSocket 握手与会话状态修复

## 问题现象

LEERBON（Windows 10 Pro）上的 RDP 凭据、NLA 和固定证书指纹均有效，但 Nexora 访问中心一直显示“正在建立受控会话…”。guacd 建立 RDPDR 后因客户端不响应而断开。最初的 PAM 记录停在 `connecting` 或被标为 `connection_error`，即便后续 GUI 已能显示。

## 根因

FastAPI 图形隧道接受了 WebSocket，但没有回显 Guacamole.js 请求的 `guacamole` 子协议，浏览器客户端没有按预期发送协议帧。恢复双向帧传输后，实机日志还显示会话已发送画面 `sync` 指令，而后端仅在识别到 `ready` 时更新 PAM 活动态，造成状态与可见桌面不一致。

## 解决方案

- 只接受请求了 `guacamole` 子协议的客户端，并在 WebSocket 握手中显式协商该子协议。
- 保留脱敏诊断：只记录少量已知指令名称和计数，不记录帧参数、票据、用户名或凭据。
- 识别 Guacamole `ready`，或服务端首个画面 `sync`，作为图形会话已进入交互态的证据；解析可解码为 UTF-8 的二进制帧以兼容协议传输。
- 不更改 Windows 会话策略、不注销用户。真实测试前用 `tsdiscon` 断开本机活动桌面，保留本机应用。

## 修改文件

- `backend/api/remote_desktop.py`
- `backend/tests/pam/test_remote_desktop_tunnel_proxy.py`
- `docs/plans/plan_20261013_0958_01_Guacamole_RDP_VNC纳管.md`
- `docs/walkthrough/walkthrough_20261013_0958_01_Guacamole_RDP_VNC纳管.md`

## 验证

- `.venv/Scripts/python.exe -m pytest backend/tests/pam/test_remote_desktop_tunnel_proxy.py -vv --tb=short`：5 passed。
- 相关 PAM、Guacamole、录像、profile 指纹与 m0285/m0286 迁移测试：21 passed。
- `.venv/Scripts/python.exe -m py_compile backend/api/remote_desktop.py`：通过。
- `git diff --check`：通过。
- 将模块复制到授权的 Ubuntu 环境；容器内 `py_compile` 通过，远端与工作区 SHA-256 一致，重启后 Nexora 健康接口返回 HTTP 200。
- 真实 RDP：Windows 事件确认 NLA 成功；`quser` 确认 `test` 的 RDP 会话 Active；页面状态为“RDP 已连接”，画面显示 Windows 桌面。最终会话 `pam-rdp-46c1e3bdc8b64d119843a722f4eeeb17` 在活动时数据库状态为 `active`，断开后为 `closed/upstream_closed`；录像 `uploaded`，存储状态 `READY`，后端为 S3。

## 未验证项与风险

- VNC 尚未实机验证；LEERBON 当前没有 VNC Server 或 5900—5910 端口监听。
- 当前本机 `tete` 与测试 `test` 会话保持断开状态，没有被注销；尝试以当前权限执行 `tscon 1 /dest:console` 返回 Access Denied。两账户的登录会话与应用仍保留，需本机管理员操作恢复控制台。

## 回滚

在 Ubuntu 主机上将 `/tmp/nexora-remote-desktop-pre-sync-ready.py` 复制回 `nexora-netops:/app/backend/api/remote_desktop.py` 并重启 `nexora-netops`。回滚不更改资产凭据、Windows 用户、数据库迁移或 S3 录像。
