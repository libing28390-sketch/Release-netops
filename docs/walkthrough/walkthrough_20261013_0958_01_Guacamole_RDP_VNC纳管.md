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

尚未完成真实 RDP/VNC 建连、断开、录像生成/回放或 S3 对象验收，因为部署环境当前没有已配置的远程桌面 profile 和指定目标。S3 后端及录像归档配置已确认，但不能据此声称已写入实际录像对象。完成真实会话验收需要先配置一台可访问的 RDP 目标和一台 VNC 目标。

## 回滚

将 `.env` 中 `NETOPS_REMOTE_DESKTOP_ENABLED` 设为 `0`，运行常规部署更新；部署脚本会停止新增 Guacamole 服务。需要恢复代码时回退本次 Guacamole 路由、前端入口和 Compose profile。保留 PAM 审计数据、已归档录像及 PostgreSQL/录像命名卷；不要执行 `docker compose down -v`。

## 官方参考

- [Apache Guacamole 1.6.0 JSON 认证](https://guacamole.apache.org/doc/gug/json-auth.html)
- [Apache Guacamole 1.6.0 Docker 部署](https://guacamole.apache.org/doc/gug/guacamole-docker.html)
- [Apache Guacamole 1.6.0 连接与录像参数](https://guacamole.apache.org/doc/gug/configuring-guacamole.html)
- [Apache guacd 1.6.0 Dockerfile（UID/GID 1000）](https://github.com/apache/guacamole-server/blob/1.6.0/Dockerfile)
