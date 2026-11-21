# S3 默认存储与 Grafana 免重复登录

## 完成摘要

- 新安装的 Docker 环境默认选择 SeaweedFS S3-compatible 存储；部署脚本为占位的 S3 凭据生成随机值，并让 Nexora 与 SeaweedFS 共用同一组凭据。
- Grafana 继续关闭匿名访问。Nexora 登录后，后端通过 `/grafana` 专用 HttpOnly Cookie 和 Nginx Auth Proxy 验证身份；打开 Grafana 新标签页不再要求输入第二组账号密码。
- 已有会话恢复时会补发 Grafana Cookie；退出登录会请求后端撤销 Nexora 会话并清除 Cookie。
- S3 没有固定的总容量默认值。当前 SeaweedFS 使用普通 Docker named volume，没有 bucket 配额或 Docker 磁盘配额；可用空间受 Docker 数据目录所在文件系统的剩余容量限制。前端和 `.env` 目前均不配置 S3 总容量。
- SeaweedFS `volumeSizeLimitMB` 是单个 volume 的限制，不是整个 bucket 的总配额；需要总量控制时应在宿主机文件系统设置配额，或使用具备 bucket quota 的 S3 服务。

## 实际修改文件

- `.env`（Git 忽略）：备份后配置 `STORAGE_BACKEND=s3`、SeaweedFS endpoint/bucket/region、随机 S3 凭据，以及 Grafana Auth Proxy 内部网段参数；凭据值未写入报告。
- `.env.backup.20260924_170021`：修改前的本机 `.env` 备份，未加入 Git。
- `.env.example`：将存储默认值设为 S3，并加入 Grafana 内部认证网络配置。
- `scripts/deploy-docker.sh`：安装/更新时保留已有 S3 凭据，仅替换空值或占位值。
- `docker-compose.yml`：Grafana 启用 Auth Proxy；Nginx 与 Grafana 连接独立内部网络，并用静态 Nginx 地址限制受信代理；SeaweedFS 与后端共用 S3 凭据。
- `nginx/nginx.conf`：所有 `/grafana/` 请求先通过内部 auth subrequest 验证 Nexora 会话，再覆盖 Grafana 身份头。
- `backend/api/users.py`：登录、MFA、切换用户时设置 Grafana Cookie；新增会话桥接、代理身份验证和退出时撤销/清 Cookie。
- `src/hooks/useAuth.ts`、`src/pages/GrafanaDashboardPage.tsx`：会话恢复与打开大盘前补发 Cookie；退出时通知后端注销。
- `docs/deploy/docker.md`：说明 S3 容量来源、未配置总量配额、Grafana 免重复登录，以及认证网络冲突时的 `.env` 参数。
- `docs/plans/plan_20260924_1638_01_S3默认存储与Grafana免重复登录.md`：同步补充实施计划。

## 验证命令与结果

- PyYAML 读取并解析 `docker-compose.yml`：通过；确认 `grafana_auth` 是内部网络，SeaweedFS 启动参数仍为 `weed mini -dir=/data`，没有设置单卷容量上限。
- Python AST 解析 `backend/api/users.py`：通过。
- 使用 `.venv` 对 `api.users` 执行模块导入：第一次发现 Grafana 路由缺少 `require_role` 导入，已补齐；重试通过。
- `git diff --check`（本次涉及文件）：通过；Git 对 `nginx/nginx.conf` 提示工作区 LF/CRLF 转换警告，没有报告空白错误。
- 检查本机 `.env` 相关键是否存在（只输出是否配置，不输出凭据）：S3 设置、Auth Proxy 网段均已配置；备份文件存在。

## 未执行验证与原因

- `docker compose --env-file .env config --quiet` 未能执行：当前 Windows 工作区没有 Docker CLI。
- 未运行测试、前端构建或实际部署，也未启动/停止容器；遵照当前工作要求，且此机器没有 Docker CLI 可做容器级验证。
- 因此需要在目标 Linux 部署机执行 Compose 配置校验并更新服务后，确认 Grafana iframe 和新标签页的真实登录行为。

## 剩余风险与后续建议

- 如果主机现有 Docker 网络占用 `172.30.254.0/29`，需在 `.env` 同步调整 `GRAFANA_AUTH_PROXY_SUBNET` 和 `GRAFANA_AUTH_PROXY_NGINX_IP`。
- S3 启用不会迁移此前保存在本地的 PAM 录像和配置备份；需按独立迁移流程搬迁和核对。
- 当前没有 S3 总容量配额。如果需要限制空间，应给 SeaweedFS 所在文件系统设置磁盘配额，或切换到提供 bucket quota 的对象存储服务。
- Grafana Auth Proxy 实际运行效果尚未在容器环境中验证；若部署后代理配置异常，可回退 Nginx/Grafana Auth Proxy 配置，恢复独立登录。
