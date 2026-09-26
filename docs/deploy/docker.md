# Docker Compose 部署

适合 Linux 服务器 / 生产环境。一套 compose 拉起 PostgreSQL + 后端 + Nginx + VictoriaMetrics + vmagent + Grafana，脚本默认同时纳入 Redis sidecar，宿主机无需安装 Node.js / Python。

## 入口文件（仓库根目录）

| 文件 | 作用 |
|------|------|
| `docker-compose.yml` | 编排带 pgvector/pg_trgm 的 PostgreSQL 18 + 后端 + Nginx |
| `docker/postgres/Dockerfile` | 基于 pgvector 的 PostgreSQL 镜像（包含 pg_trgm） |
| `Dockerfile` | 后端镜像构建（含前端容器内编译） |
| `.dockerignore` | 构建上下文忽略规则（必须在根目录才生效） |
| `nginx/` | Nginx 配置与 SSL 证书目录 |

`docker-compose.yml` 内置 Redis 7.4.2 Alpine 服务，默认随 Docker 栈启动；Redis 容器和主应用统一读取 `TZ`，未设置时使用 `Asia/Shanghai`。Redis 仅用于 IP 定位等可重建缓存，不能替代 PostgreSQL 的任务状态或事实数据。部署脚本可通过 `NETOPS_REDIS_ENABLED=0` 显式关闭 Redis。

数据库镜像固定基于 `pgvector/pgvector:0.8.6-pg18-bookworm`，并额外安装
`postgresql-contrib-18`，因此迁移 `0104_ai_pgvector_rag` 所需的 `vector` 和
`pg_trgm` 都能在数据库启动前使用。

PostgreSQL 18 官方容器将数据目录设为 `/var/lib/postgresql/18/docker`，因此 Compose 将 `nexora-pgdata` 挂载到父目录 `/var/lib/postgresql`，以持久化该目录下的版本化集群数据。PG17 的旧 volume 不能原样交给 PG18；先备份，再使用 `pg_upgrade` 或 `pg_dump`/`pg_restore` 迁移到新 PG18 集群。

> 这些文件**保持在根目录**，所以下面所有命令都直接在仓库根目录执行，无需 `-f` 指定路径。

## 步骤

1. 克隆仓库并准备环境文件：
   ```bash
   git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
   cd nexora-automation
   # 编辑 .env，至少替换 SECRET_KEY、CREDENTIAL_ENCRYPTION_KEY、POSTGRES_PASSWORD、DATABASE_URL
   ```
2. 构建并启动（前端会在容器内自动编译）：
   ```bash
   bash scripts/deploy-docker.sh install
   ```
3. 访问 `http://localhost`。

## S3 对象存储与 SeaweedFS

Docker 部署默认包含本地 S3 兼容存储 SeaweedFS，不需要 AWS 账号或 AWS 服务。
部署脚本首次运行时会从 `.env.example` 创建 `.env`；默认配置使用
`STORAGE_BACKEND=s3`、内部地址 `http://seaweedfs:8333` 和 Bucket `nexora`，并自动
启用 SeaweedFS Compose profile。脚本会为 `.env` 中的 Access Key ID 和 Secret
生成强随机值；已有真实值会原样保留：

```dotenv
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://seaweedfs:8333
S3_BUCKET=nexora
S3_ACCESS_KEY_ID=replace-with-a-strong-s3-access-key
S3_SECRET_ACCESS_KEY=replace-with-a-strong-s3-secret-key
```

Compose 从部署机上的 `.env` 读取这两个凭据，并把同一组值注入 `netops` 和
`seaweedfs` 容器。后端进程据此连接本地 S3；浏览器和管理页面不读取 `.env`。
`seaweedfs` 是 Compose 网络内的服务名，不能改成 `127.0.0.1`，否则后端容器会
访问自身而不是 SeaweedFS。使用部署脚本安装时只需执行：

```bash
bash scripts/deploy-docker.sh install
# 已有部署使用：
bash scripts/deploy-docker.sh update --force
```

安装后，配置备份和 PAM 录像默认都使用 `.env` 中的本地 SeaweedFS 配置、Bucket
`nexora`，并分别写入 `config/` 和 `pam/` 对象 key 前缀。无需在管理页面再次填写
Access Key ID 或 Secret。打开 **平台管理 → 对象存储**（`/management/storage`）可
查看现有配置。配置备份和 PAM 录像共用当前全局默认存储；新增 S3 配置并设为默认后，
之后的新文件会使用该配置。只有需要连接另一套 S3 服务时，才需要新增配置；新增配置
的凭据会使用 `CREDENTIAL_ENCRYPTION_KEY` 加密保存，请保持该密钥稳定。

S3 的 `/` 是 object key 的虚拟前缀，不需要预建目录。本地 SeaweedFS 会按 `S3_BUCKET`
创建默认 Bucket；连接其他 S3 服务时，需先创建对应 Bucket 并确保凭据有访问权限。
新写入对象会记录实际存储配置、Bucket 和完整 object key；更改全局默认只影响之后的新
文件，已有对象仍关联原位置。被已有对象引用的存储配置不能删除或修改连接参数。

安装、更新和离线启动遇到 `netops` 尚未通过健康检查导致的首次 Compose
失败时，脚本会保留原始错误上下文，显示当前 health 状态并在默认 120 秒内
等待 `netops` 变为 healthy；恢复后自动以 `--no-build --pull never` 补启动
其余服务，不重建容器或删除数据卷。可通过
`NETOPS_STARTUP_RECOVERY_TIMEOUT_SECONDS` 调整等待上限。

如果不通过部署脚本而直接使用 Compose，请确保 `.env` 中的 S3 ID 和 Secret 已
设置为非占位值，并显式启用 SeaweedFS profile：

```bash
docker compose --profile object-storage up -d
```

不要把真实凭据提交到仓库；部署脚本会把本地 S3 凭据保存在部署机的 `.env`。改接
其他 S3 服务时，再按该服务调整 endpoint、Bucket、凭据和 TLS 校验设置。

切换到 S3 不会自动迁移已有的本地文件。原本保存在 `STORAGE_LOCAL_ROOT` 或
`nexora-data` 卷中的 PAM 录像、配置备份等对象仍留在本地存储；需要按仓库的
存储迁移流程单独导入到 S3，完成核对后再清理旧数据。

SeaweedFS 当前没有设置 bucket 总容量配额，Docker named volume 也没有单独的磁盘配额；
S3 可用空间取决于 Docker 数据目录所在文件系统的剩余空间。`weed mini` 的
`volumeSizeLimitMB` 是单个 volume 的上限，不是整个 bucket 的容量限制。
当前应用没有前端容量设置；需要限制总容量时，应在宿主机文件系统配置磁盘配额，
或使用带 bucket quota 的外部 S3 服务。不要把单卷大小误认为 S3 总容量。

Docker Compose 默认启用 Prometheus-compatible 的 VictoriaMetrics 查询路径，
并把 `netops` 编译发布的采集目标、SNMP 认证和 vmagent 配置通过
`nexora-monitoring-artifacts` 共享卷交给 `vmagent` 与 `snmp-exporter`。
如需显式配置，可在 `.env` 中设置：

```dotenv
MONITORING_METRIC_BACKEND=victoriametrics
VICTORIAMETRICS_URL=http://victoriametrics:8428
VICTORIAMETRICS_ALLOWED_HOSTS=victoriametrics
```

首次启动时 `snmp-exporter` 会直接使用镜像内置的无目标、非敏感 bootstrap 配置，`vmagent` 会
使用空的 file-SD 目标正常待命；这两个服务不需要用户手动启动，也不会因为尚未
发布业务采集计划而被判定为部署失败。在页面中完成采集计划编译并发布后，控制面
会原子替换共享 runtime、请求 `snmp-exporter` 热加载认证和模块配置，vmagent
会自动读取新的 file-SD 目标。

可以用以下命令检查链路：

计划只保留系统基线 `plan-generic-ifmib`（界面显示“SNMP 基线采集计划”）；华三、华为、思科的常用 CPU/内存/温度/状态
OID 作为同一计划下的 Module/Variant 维护，配置和来源见
[厂商 OID 目录](../monitoring/vendor_oid_catalog.md)。

```bash
docker compose ps netops victoriametrics snmp-exporter vmagent nginx
docker compose logs --tail=200 snmp-exporter vmagent
```

Nexora 的“监控大盘”通过同源 `/grafana/` 访问 Grafana，Grafana 数据源已自动
指向 `http://victoriametrics:8428`。从 Nexora 登录后，Nginx 的内部鉴权子请求会读取
`nexora_grafana_session`，将它作为 Bearer 凭据交由后端校验，再通过 Auth Proxy 身份头让
Grafana 按请求认证；Auth Proxy 不签发 Grafana 登录令牌 Cookie。Nginx 不会把浏览器 Cookie 转发给后端或 Grafana，以免旧的
`grafana_session` 覆盖代理身份或触发错误跳转；
匿名访问仍关闭，浏览器不会获得 Grafana 管理员密码。
需要在 Nexora 内嵌大盘时，保持 `GRAFANA_ALLOW_EMBEDDING=1`。

Auth Proxy 白名单使用独立内部 Docker 网络的 CIDR。默认网段为
`172.30.254.0/29`；Grafana 和 Nginx 在该网络上由 Docker IPAM 动态分配地址，
避免固定地址与先启动的容器冲突。由于 Grafana 信任该网段内的 Auth Proxy 请求，
`grafana_auth` 网络只应连接 Grafana 与 Nginx，不要将其他服务接入。
如果网段与主机现有 Docker 网络冲突，只需在 `.env` 中调整
`GRAFANA_AUTH_PROXY_SUBNET`，Compose 会同时用它配置网络子网和 Grafana 白名单。
旧 `.env` 中的 `GRAFANA_AUTH_PROXY_NGINX_IP` 已不再使用，可以删除。

旧版统一主机大盘 `07 服务器与主机监控`（UID `nexora-server-metrics`）已被 Linux 与
Windows 专用大盘替代。Docker 部署脚本在安装、升级和离线启动时会尝试删除该旧 UID；
也可以在部署目录中单独执行以下命令。脚本会先核对旧 UID 的标题，只删除这条历史记录。
若容器环境中的 Grafana 凭据与当前登录凭据不一致，手动命令会隐藏提示输入管理员账号和密码；
自动部署不会交互，认证失败或标题不匹配时会报告清理未完成，不会触碰其他大盘。

```bash
bash scripts/deploy-docker.sh prune-legacy-dashboard
```

`GRAFANA_ROOT_URL` 必须填写浏览器实际访问的 HTTPS 地址并保留结尾斜杠，例如
`https://nexora.example.com/grafana/`。不要保留 `%(domain)s`、`localhost` 或
Grafana 内部的 `:3000`；否则 Grafana 会把 iframe 重定向到用户工作站的
`localhost`。Compose 启用 `GF_SERVER_SERVE_FROM_SUB_PATH=true`，Nginx 保留
`/grafana/` 前缀原样转发给 Grafana。使用 `scripts/deploy-docker.sh` 部署时，缺省占位值会自动
根据 `TLS_COMMON_NAME` 生成。

Grafana 到 VictoriaMetrics 的请求走 Docker 内部网络；Compose 会清空
`HTTP_PROXY`/`HTTPS_PROXY` 等主机代理变量，避免内部服务名被转发到外部代理而返回
`502`。这与浏览器访问的域名无关。

后端访问 SeaweedFS S3 时也使用 Docker 内部服务名 `seaweedfs:8333`。Compose 会将
`seaweedfs` 和容器名 `nexora-seaweedfs` 加入后端的 `NO_PROXY`/`no_proxy`，避免内部
S3 请求经过主机代理；外部 S3 兼容 endpoint 仍可按既有代理设置访问。

局域网部署示例（假设服务器地址为 `192.168.1.100`）：

```dotenv
TLS_COMMON_NAME=192.168.1.100
GRAFANA_ROOT_URL=https://192.168.1.100/grafana/
```

局域网用户应访问 `https://192.168.1.100/`；不要让用户访问 `:3000`，也不要把
`127.0.0.1` 写进这个 URL。自签名证书首次访问时需要在浏览器中信任该证书；
正式环境应将 `nginx/ssl` 替换为包含该 IP/域名的受信任证书。

升级时，部署脚本和后端启动流程会自动兼容旧版 SNMP runtime artifact（移除
仅供 Nexora UI 使用、但会被 `snmp-exporter` 拒绝的指标元数据），并在 exporter
恢复后自动启动 `vmagent`；不需要为了这个兼容性修复手动重新应用基线采集计划。

首次登录使用默认账号 `admin`、密码 `admin`。登录后请立即在用户设置中修改密码；已有数据库中的管理员密码会保留，不会因更新或重启而自动改回默认值。

脚本默认会校验并启动 Redis；如果 `.env` 仍使用 sidecar 默认地址，首次安装会生成 URL-safe 的 Redis 密码并同步写入 `REDIS_PASSWORD`/`REDIS_URL`。已部署环境可以使用以下命令检查或查看 Redis：

```bash
bash scripts/deploy-docker.sh redis-status
bash scripts/deploy-docker.sh redis-logs
```

`redis-logs` 显示 Docker 容器 stdout/stderr，并附带 Docker 时间戳。若通过 `redis-cli MONITOR` 查看逐命令流，首列是 Redis 原生 Unix epoch（秒及小数秒），不是 Compose 时区或 `logging` driver 能修改的格式。先按部署需要为 `redis-cli` 配置目标地址和获授权的诊断身份（不要把明文密码写在命令行），再把该流交给格式化器：

```bash
redis-cli MONITOR | python3 scripts/format_redis_monitor.py --timezone=+08:00
```

也可传 IANA 时区，例如 `--timezone=Asia/Shanghai`。格式化器只转换时间列，不连接 Redis；`MONITOR` 需要有权限的诊断连接，并会增加 Redis 开销，排查后应 Ctrl-C 结束。不要为方便长期监控而扩大应用 ACL 权限。

当前 Redis sidecar 的 `nexora` ACL 用户刻意没有 `MONITOR` 权限；如需短时诊断，只能按运维策略使用独立且受控的管理员诊断身份，不要给运行时应用用户增加该权限。参见 [Redis MONITOR 文档](https://redis.io/docs/latest/commands/monitor/)。

## Redis 缓存

IP 定位新流程默认启用，不需要设置额外开关。将 `.env` 中现有的 `REDIS_URL` 保持为 Compose 网络内的服务名即可；Redis 缓存不可用时仍使用 PostgreSQL 事实和任务队列：

```dotenv
REDIS_URL=redis://nexora@redis:6379/0
```

通过部署脚本启动 Nexora 和 Redis（同一 Compose 网络内服务名为 `redis`）：

```bash
bash scripts/deploy-docker.sh update --force
```

sidecar 会关闭 Redis 默认用户，只开放 ACL 用户 `nexora`；其 key 范围限制为 IP 定位缓存 `nexora:*` 和现有 AI 限流键 `ai:ratelimit:*`，命令权限仅包含两个功能当前需要的缓存/计数操作。设置 `REDIS_PASSWORD` 后，sidecar 以密码哈希配置 ACL；同步把用户名和密码写入 `REDIS_URL`，并对密码中的特殊字符进行 URL 编码。独立部署时默认只绑定 `127.0.0.1`，需要跨主机访问时设置 `REDIS_BIND_ADDRESS=0.0.0.0`，并在 Redis 主机防火墙中只允许 Nexora 主机访问 6379。跨不可信网络使用 `rediss://` 和证书校验。

定位缓存 TTL 从原始 `collected_at` 计算：路由/ARP 300 秒新鲜、1800 秒保留；MAC/完整结果 120 秒新鲜、900 秒保留；网段 900 秒新鲜、86400 秒保留；拓扑/LLDP 172800 秒（48 小时）新鲜、259200 秒（72 小时）物理保留；负向定位未命中 15 秒。LLDP 逻辑 freshness 与拓扑图默认证据有效期对齐；过了 48 小时的值即使仍被 Redis 保留，也不会作为新鲜拓扑读取。Redis 重启、淘汰或短时不可用都不会影响 PostgreSQL 事实；定位器会从 PostgreSQL 的完整设备快照重建 Redis 投影。

## 常用命令

```bash
bash scripts/deploy-docker.sh update
bash scripts/deploy-docker.sh redis-status
bash scripts/deploy-docker.sh redis-logs
```

部署脚本会固定使用 Compose 项目名，避免目录名变化影响容器识别。对于旧版脚本已创建的部署，如果 `.env` 未显式设置 `COMPOSE_PROJECT_NAME`，新版脚本会从现有 `nexora-db` 容器的 `com.docker.compose.project` 标签自动沿用历史项目名，再执行数据库备份和更新。需要人工核对时可运行：

```bash
docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' nexora-db
```

如果显式设置 `COMPOSE_PROJECT_NAME`，其值必须与现有容器标签一致；不要为了绕过 `service "db" is not running` 而跳过发布备份或删除数据库容器。

## 完全离线部署

如果目标服务器无法访问 Docker Hub 或其他镜像仓库，请在联网机器上准备好镜像，然后只把镜像归档文件和部署文件传到目标服务器。`save-images` 不会重新构建镜像，也不会访问镜像仓库；它会保存当前本机已存在的 Nexora 镜像，并在 Redis sidecar 启用时一并保存 Redis 镜像。

### 1. 在联网构建机保存镜像

在已经构建好目标版本镜像的部署目录执行：

```bash
bash scripts/deploy-docker.sh save-images \
  ./nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz
```

如果所需镜像已经存在于本机，也不需要先执行 `docker compose build`。脚本会先验证基础镜像和启用的 Redis 标签，再生成归档：

该命令会保存以下镜像，并同时生成 `.sha256` 校验文件：

```text
nexora-netops:latest
nexora-nginx:latest
nexora-postgres:latest
redis:7.4.2-alpine
```

镜像归档不会包含 Compose 文件、运行时环境变量、SSL 证书或数据库数据。请将以下内容传到离线服务器：

```text
nexora-images-*.tar.gz
nexora-images-*.tar.gz.sha256
docker-compose.yml
scripts/deploy-docker.sh
.env.example
nginx/nginx.conf
nginx/ssl/                 # 使用正式 HTTPS 证书时需要
```

不要直接分发包含生产密码和密钥的 `.env`；在目标服务器根据 `.env.example` 创建并填写自己的 `.env`。

### 2. 在离线服务器导入镜像

```bash
bash scripts/deploy-docker.sh load-images \
  /data/packages/nexora-images-20260728.tar.gz
```

如果校验文件与镜像包位于同一目录，脚本会先验证 SHA-256，再执行 `docker load`。导入不会删除或修改镜像归档文件。

### 3. 不构建、不拉取，直接启动

```bash
bash scripts/deploy-docker.sh start-offline
```

等价的原生命令为：

```bash
docker compose up -d --no-build --pull never --remove-orphans
```

离线启动前请确认所需镜像标签都已导入，并确认目标服务器与源构建机的 CPU 架构一致。

离线服务器不要执行 `docker compose up -d --build`、`docker compose pull` 或脚本的 `install`/`update` 命令；这些命令可能尝试构建或访问远程仓库。首次启动会创建新的 Docker volumes 并执行数据库迁移；如果需要迁移原有业务数据，请另外恢复 PostgreSQL 备份和数据卷。

## 服务构成

| 容器 | 镜像 / 来源 | 端口 |
|------|-----------|------|
| `db` | 本地 `docker/postgres/Dockerfile` 构建的 `nexora-postgres:latest`（pgvector + pg_trgm） | 内部 5432 |
| `netops` | 本地 `Dockerfile` 构建 | 内部 8003 |
| `nginx` | `nginx:1.27-alpine` | 对外 80 / 443 |
| `redis`（可选） | `redis:7.4.2-alpine`，定义在 `docker-compose.yml` | 内部 6379 |

> 生产环境的 HTTPS、密钥加固等见根目录 [DEPLOY.md](../../DEPLOY.md)。
