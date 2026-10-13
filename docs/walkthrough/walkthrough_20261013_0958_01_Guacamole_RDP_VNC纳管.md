# Guacamole RDP/VNC 纳管实施记录

## 完成概要

已按用户选定的 Guacamole 容器化方案实现 Nexora 的浏览器内 RDP/VNC 纳管：复用现有 FastAPI、用户身份、资产权限、凭据中心、PAM 审计和录像存储；Guacamole Web 与 guacd 固定为 1.6.0，并通过 `remote-desktop` profile 按需启动。

- 资产可分别配置 RDP/VNC 端口、普通/管理员凭据引用、RDP 域与安全模式、剪贴板策略； profile 接口不返回密码。
- 会话创建验证资产范围和凭据；管理员访问校验现有 PIN/TOTP；使用短时一次性随机票据和数据库哈希，在 WebSocket 消费时重验授权并原子认领会话。
- FastAPI 代理图形 WebSocket；Guacamole JSON 认证、目标凭据和授权 Token 留在服务端；访问日志、错误响应和 PAM 审计不写入密码或 Token。
- RDP/VNC 原生 `.guac` 录像写入共享卷，结束后归档至现有 PAM 存储；不稳定文件保持待处理，存储任务可重试，录制完成前不可播放。
- 访问中心增加协议入口、普通/管理员会话申请、用途/MFA、图形客户端全屏/缩放/键鼠焦点和断开清理；PAM 审计支持 `.guac` 原生播放器。
- Compose 默认不启动新增容器；启用时使用内部网络、独立出向网络及共享录像卷，不向宿主机发布 8080/4822。部署脚本仅在功能启用时生成/校验独立 JSON 密钥。
- 按 Apache 1.6.0 官方镜像 UID 1000 设置 guacd 用户，并让 guacd 等待 Nexora 先初始化 UID 1000 的共享录像目录。

## 主要改动

### 后端与数据库

- 新增 `backend/database/migrations/m0285_pam_remote_desktop.py`。
- 新增 `backend/services/guacamole_service.py`、`backend/services/pam_remote_desktop.py`、`backend/api/remote_desktop.py` 和 `backend/core/request_log_redaction.py`。
- 集成 `backend/main.py`、`backend/api/pam.py`、`backend/services/pam_recording_storage.py` 中的路由、租约恢复、审计和录像存储。
- 新增迁移、JSON 认证、日志脱敏和录像稳定性测试。

### 前端

- 新增 `src/api/pamRemoteDesktop.ts`、`src/components/access/RemoteDesktopClient.tsx`、`src/components/access/RemoteDesktopAccessModal.tsx`、`src/components/access/GuacRecordingPlayer.tsx`、`src/pages/AssetManagement/components/RemoteDesktopProfileEditor.tsx`。
- 集成 `src/pages/AccessCenterTab.tsx`、导出数据、资产类型与 `src/pages/PAMAuditTab.tsx`。
- 本地 vendoring Apache Guacamole 1.6.0 客户端资源及其 License、NOTICE 和来源说明，避免依赖公网 CDN。

### 部署与文档

- 更新 `docker-compose.yml`、`.env.example`、`Dockerfile`、`nginx/nginx.conf`、`scripts/deploy-docker.sh` 和 `docs/deploy/docker.md`。
- 新增部署 profile、容器网络和录像卷，并扩展发布契约测试。
- 本计划和本 walkthrough 跟踪当前任务；工作区中原有其他用户修改保持原样。

## 验证结果

- 聚焦 pytest：17 passed，涵盖 Guacamole JSON 服务、票据日志脱敏、录像文件状态、PAM Web 会话、m0285 PostgreSQL 迁移和 Docker 部署契约。
- Compose 权限与录像卷启动顺序调整后，`backend/tests/release/test_deploy_docker_remote_desktop_contract.py` 再次通过。
- `npm run lint` 通过。
- Vite 生产构建通过，构建产物写入临时隔离目录 `.codex-build-validation-guacamole-20261013`，没有覆盖已有 `dist`。
- 本次变更的 Python 文件 `py_compile` 通过；`scripts/validate_postgresql_only.py` 输出 0 项违规。
- `bash -n scripts/deploy-docker.sh` 与 `git diff --check` 通过。

## Linux 部署环境验收

本机为 Windows，未在本机运行 Docker。GitHub Actions 全部通过后，按用户授权连接 Linux 部署主机 `192.168.204.128`，执行 `bash scripts/deploy-docker.sh update` 更新发布代码；首次更新所在的旧 checkout 未启动新加入的可选远程桌面 profile。随后在已同步的新 checkout 执行 `bash scripts/deploy-docker.sh update --force`，完成镜像构建并启动 profile。远端结果：

- `nexora-guacamole` 使用 `guacamole/guacamole:1.6.0`，状态为运行中；`nexora-guacd` 使用 `guacamole/guacd:1.6.0`，状态为运行中且健康检查通过。
- Nexora、Guacamole 和 guacd 容器中的开关已启用，JSON 密钥存在且格式有效（密钥值未输出）；`STORAGE_BACKEND=s3`。
- Nexora 容器访问 Guacamole 内部 HTTP 返回 200；`https://127.0.0.1/api/health/live` 返回 200；未认证的远程桌面 profile API 返回 401，说明路由受认证保护。
- 数据库查询确认 `asset_remote_desktop_profiles` 表与 `pam_sessions.remote_desktop_protocol` 字段存在；当前 profile 数为 0。
- Nexora 和 guacd 挂载同一个 `nexora-remote-desktop-recordings` 持久卷，guacd 以 UID 1000 运行且录像目录可用。

S3 后端及录像归档配置已确认。本机 profile 已保存。FreeRDP 指纹格式修正后，Windows 自签名证书校验通过，guacd 报告 `RDPDR user logged on`，Windows 事件日志确认 RDP 会话重连成功。Windows 随后以“被其他连接替换”断开会话；录像已成功归档到 S3。后续已分别完成 RDP 稳定桌面和 VNC 实机验证。

## 本机 RDP 联调进展（2026-10-13）

- 按用户授权新增本机 Windows 10 Pro 资产 `LEERBON`（`192.168.204.1`），归属 `WH-DC-02`，资产上绑定原有普通凭据 `tete` 与特权凭据 `admin`；未读取或更改这两项密码。
- 远程桌面 profile 编辑器最初因请求 body 多带 `protocol` 返回 Extra inputs 错误。修复并部署后，RDP profile 成功保存：启用 Access Center、端口 3389、Windows 域 `LEERBON`、凭据继承资产绑定项。Access Center 显示 `LEERBON` 的 RDP 已启用。
- 首条真实会话审计为 `GUACAMOLE_TUNNEL_FAILED`，录像 `not_started`。原因定位为远端容器有 HTTP(S) 代理，websockets 17.2 自动读取代理环境变量。
- 按用户要求不等 Actions，已将代理绕行修复模块临时注入 Ubuntu 容器，SHA-256 与工作区文件一致；重启后健康接口 HTTP 200。真实重试已不再出现 `GUACAMOLE_TUNNEL_FAILED`，guacd 日志显示 RDP 客户端创建、WebSocket 用户加入和录像启动，证明内部隧道修复通过实机验证。
- 最新审计 `pam-rdp-6c15cac31cab4e2c84dd466e589ee232` 以 `connect_timeout` 结束；guacd 的明确错误为 `Certificate validation failed` / `SSL/TLS connection failed (untrusted/self-signed certificate?)`。尚未进入凭据拒绝阶段，所以当前证据不支持“密码错误”，也没有创建本机测试账号。
- guacd 在共享卷实际生成 80 字节录像，但文件为无扩展名 `<session_id>`，Nexora 期待 `<session_id>.guac`，归档状态因此为 `ERROR`（`PAM recording spool is missing`），S3 尚无该录像对象。已修复连接参数，录像名现在附加 `.guac`；录像、Guacamole 参数、profile 指纹和 m0286 迁移相关的本地定向测试共 14 passed，待部署后验证 S3 对象和原生播放器。
- 用户选择为 LEERBON 固定证书指纹。Windows `LocalMachine\\Remote Desktop` 的 RDP-Tcp SHA-1 thumbprint 与当前 TLS 握手证书一致；证书 DER SHA-256 为 `4CE56BB09B6F1B96A521AE58EFCEA743ECBB632A9C8D29F999D01CE47F9FF80E`。FreeRDP 2.11.7 只比较冒号分隔的摘要字节；后端已适配该格式，同时保持 `ignore-cert=false`。定向服务测试 9 passed，远端复测已越过证书校验并进入 Windows 登录会话。
- Windows TerminalServices 事件 25 记录从 `192.168.204.128` 重连成功；事件 40 reason code 5 是“被其他连接替换”。本机 `query user` 显示 `tete` 控制台会话活动，因此此前未得到稳定图形桌面。为 LEERBON 固定的 SHA-256 pin 已写入 RDP profile；最新后端日志确认 pin 已配置，guacd 未再报告证书错误。Windows Security 4625 记录 `TargetUserName=test`、`TargetDomainName=LEERBON`、`Status=0xc000006d`、`SubStatus=0xc000006a`，确认本次连接已进入 NLA，但凭据密码不匹配。test 账号已启用、加入 Remote Desktop Users，账户本身永不过期（密码仍遵循 Windows 本机密码到期策略）。Nexora 凭据 `test-rdp-leerbon` 已存在且保存了非空加密密码；未读取密码明文。编辑表单要求输入旧密码和新密码，当前等待用户亲自校正。失败会话 `pam-rdp-5dd121aeb5fe4efb8c3a84faec419b2e` 的录像也已上传到 S3（`storage_status=READY`）。当时本机只读检查未发现 VNC 服务/进程，也没有 5900—5910 端口监听；后续已由用户授权安装 TightVNC，实测结果见“VNC 实机验证收尾”。

## RDP 实机验证收尾（2026-10-13）

- 用户在 Nexora 凭据中心校正了永久测试凭据 `test-rdp-leerbon`。最新 RDP 会话 `pam-rdp-46c1e3bdc8b64d119843a722f4eeeb17` 使用已固定的 RDP 证书指纹和 NLA，Windows `quser` 确认 `test` 会话为 `Active`，前端状态显示“RDP 已连接”，截图实际显示 Windows 桌面与任务栏。验证证明 RDP/NLA/图形显示均成功，不需要在目标机器安装 Nexora Agent。
- 黑屏根因定位为 FastAPI 下游 WebSocket 接受时没有协商浏览器请求的 `guacamole` 子协议。修复为验证并回显该子协议后，诊断帧统计从 0 个客户端帧变为正常双向通信，Guacamole.js 开始显示桌面。随后发现后端只将 `ready` 标记为活动态，而实际会话已开始发送屏幕 `sync`；将 `ready` 或首个 `sync` 都作为活动态证据后，最终会话数据库在连接期间为 `active`。
- 最终测试关闭后数据库记录为 `closed` / `upstream_closed`，`recording_status=uploaded`、`storage_status=READY`（S3）。相关 PAM、Guacamole、录像、profile 指纹及 m0285/m0286 迁移定向测试合计 **21 passed**；其中 WebSocket 代理测试 **5 passed**。`py_compile` 和 `git diff --check` 通过。Ubuntu 容器内语法检查通过，远端模块 SHA-256 与工作区一致；Nexora 健康接口返回 HTTP 200。
- Windows 10 Pro 只有一个活动交互桌面。按用户授权运行 `tsdiscon 1` 断开本机 `tete` 会话，没有注销该用户或关闭应用；测试期间 `test` 活动。结束后两者都显示 `Disc`。恢复 `tete` 到本机控制台的 `tscon 1 /dest:console` 被 Windows 返回 Access Denied，因此本机用户需用管理员权限重新接回该会话；会话仍保留。
- `test-rdp-leerbon` 凭据按用户要求保留。VNC 实机验证结果见下节。

## VNC 实机验证收尾（2026-10-13）

- 用户授权在 LEERBON 安装 VNC Server。已从 TightVNC 官方站点下载 2.8.90 64 位安装包并验证 Authenticode 签名有效；用户完成本机安装、许可和服务口令设置。服务以 Windows 服务运行，TCP 5900 监听。
- LEERBON 的 Windows Defender 防火墙配置文件均处于关闭状态，因此没有把新增防火墙规则误当作有效隔离。用户授权的来源限制通过 TightVNC 自身 IP 访问控制实现：首条规则只放行 `192.168.204.128`，后续 IPv4 全地址规则拒绝其余来源；重启服务后读取到规则值且服务仍运行。应用层规则没有开启或修改整机防火墙。
- Nexora 中为 LEERBON 启用了 VNC Access Center 入口，端口 5900，复用已有凭据引用 `test-rdp-leerbon`；VNC 连接只使用其密码字段，不发送用户名。没有在代码、文档或日志中记录密码值。
- 从 Nexora 操作工作台发起普通级别的 VNC 会话，前端显示“LEERBON VNC 已连接”，实际显示 Windows 桌面。会话 ID 为 `pam-vnc-5adeb00d914f4f928951263e738da7fe`，持续 21 秒后主动断开；“我的历史记录”显示状态“已关闭”、方式“VNC 图形会话”、录像“可用”。
- 数据库记录为 `closed`、`recording_status=uploaded`、`storage_status=READY`、对象键存在、录像大小 `1,401,015` 字节；这确认本次 `.guac` 录像已归档到现有 S3 兼容存储。
- TightVNC 的传统 VNC 认证有效密码最多使用 8 个字符，且本次测试口令较弱，只适合受限测试环境。生产使用前应改为高熵唯一口令，并继续保持仅可信网关可达；当前 Windows 防火墙仍关闭。详见[官方 TightVNC 文档](https://www.tightvnc.com/whatsnew.php)。
## 回滚

将 `.env` 中 `NETOPS_REMOTE_DESKTOP_ENABLED` 设为 `0`，运行常规部署更新；部署脚本会停止新增 Guacamole 服务。需要恢复代码时回退本次 Guacamole 路由、前端入口和 Compose profile。保留 PAM 审计数据、已归档录像及 PostgreSQL/录像命名卷；不要执行 `docker compose down -v`。

## 官方参考

- [Apache Guacamole 1.6.0 JSON 认证](https://guacamole.apache.org/doc/gug/json-auth.html)
- [Apache Guacamole 1.6.0 Docker 部署](https://guacamole.apache.org/doc/gug/guacamole-docker.html)
- [Apache Guacamole 1.6.0 连接与录像参数](https://guacamole.apache.org/doc/gug/configuring-guacamole.html)
- [Apache guacd 1.6.0 Dockerfile（UID/GID 1000）](https://github.com/apache/guacamole-server/blob/1.6.0/Dockerfile)
