# Nexora 部署指南总览

服务端当前提供 Docker Compose 和 Ubuntu 两种部署路径。部署脚本、Compose、Nginx 和示例环境文件保留在仓库中；本目录的文档按部署方式说明入口和实际运行差异。

## 选择部署方式

| 部署方式 | 适用场景 | 入口文件 | 详细指南 |
|---|---|---|---|
| **Docker Compose** | Linux 主机上的整套容器化部署 | `docker-compose.yml`、`Dockerfile`、`scripts/deploy-docker.sh` | [Docker Compose 部署](./docker.md) |
| **Ubuntu 安装脚本** | Ubuntu 主机或 Codespaces 上的原生进程部署 | `deploy-ubuntu.sh` | [Ubuntu 部署](./ubuntu.md) |

Docker 安装使用根目录 `.env.example`；Ubuntu 安装使用 `.env.ubuntu.example`。两种方式都运行 Nexora 服务端，但附属服务和默认存储、监控、缓存实现不同，不能按组件完全等价处理。

- **v1.0.11 发布说明**：[Linux / Ubuntu / Docker Release Notes](./release-notes.md)
- **Windows 工作站访问**：服务端部署在 Linux 或 Docker 后，Windows 用户可通过浏览器访问；如需本机浏览器和终端集成，安装 [Terminal Agent](./terminal-agent.md)。
- **Windows Agent 开机启动排障**：[Windows Agent startup](./terminal-agent-autostart.md)

## Docker 快速入口

在仓库目录准备 `.env` 后运行：

```bash
bash scripts/deploy-docker.sh install
```

安装脚本以 `.env.example` 初始化配置并生成安装所需的随机凭据。默认入口为 `https://<服务器地址>`；Nginx 同时监听 80 和 443，浏览器访问 HTTP 会跳转到 HTTPS。若尚未放入正式证书，Nginx 会为 `TLS_COMMON_NAME` 生成自签证书，浏览器会显示证书信任提示；生产访问应配置受信任的 TLS 证书。

默认 Docker 栈包括 PostgreSQL 18（含 pgvector 与 pg_trgm）、Nexora 后端、Nginx，以及 VictoriaMetrics、vmagent、SNMP/PostgreSQL Exporter、Grafana、cAdvisor 和 Docker Socket Proxy 等监控组件。另包含 Guacamole 与 `guacd` 远程桌面组件、告警投递 Relay/Worker 和专用告警 Redis。`.env.example` 默认使用 S3 存储并由安装脚本启用 SeaweedFS。

Docker Compose 中有两个用途不同的 Redis：`redis` 是平台缓存，可通过部署脚本的 `NETOPS_REDIS_ENABLED=0` 关闭；`alert-redis` 是告警投递 Broker，使用独立网络、配置和数据卷，不受缓存 Redis 开关影响。不要把两者写成同一个服务或共用用途。

- **Docker 完全离线**：联网机器运行 `bash scripts/deploy-docker.sh save-images <archive-path>`；目标服务器导入归档后运行 `load-images` 和 `start-offline`。启用缓存 Redis 时脚本也会保存并校验对应镜像，具体步骤见 [Docker 完全离线部署](./docker.md#完全离线部署)。
- **Docker 交付手册**：镜像归档、离线升级、数据卷和故障排查见 [Docker 部署与离线交付手册](./docker-release-manual.md)。

## Ubuntu 快速入口

可下载脚本后执行，也可从部署目录运行 `./deploy-ubuntu.sh`。安装脚本安装并配置主机 PostgreSQL、Python 后端、前端构建和 Nginx；默认 `.env.ubuntu.example` 使用本地文件存储、原生 PostgreSQL 监控路径、PostgreSQL 定位缓存和进程内通知 outbox consumer。systemd 可用时注册 `netops.service`；没有 systemd 的容器环境使用兼容启动方式。

Ubuntu 脚本默认让 Nginx 通过 HTTP 80 端口提供入口，不自动生成 Docker 栈使用的自签 TLS 证书，也不默认把 HTTP 重定向到 HTTPS。需要 HTTPS 时，在域名解析与防火墙就绪后按 [Ubuntu 部署指南](./ubuntu.md) 配置 Certbot，例如：

```bash
sudo certbot --nginx -d <你的域名>
```

随后使用 `https://<你的域名>` 访问。Ubuntu 默认不启动 Docker Compose 中的 Redis 缓存、告警 Redis/Worker、Grafana、VictoriaMetrics、Guacamole 或 SeaweedFS 容器；请按目标部署方式阅读组件配置，不要将 Docker 的默认组件表套用到 Ubuntu。

> 根目录的 [README.md](../../README.md) 与 [DEPLOY.md](../../DEPLOY.md) 说明产品入口和其他部署细节。本页不引用会从公开发布树清理掉的内部计划、验收或协作文档。
