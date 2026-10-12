# Nexora：网络工程师的现代化网络运维自动化平台

作为网络工程师，你是否每天还在重复这些工作？

- 逐台登录交换机，手动执行 `display current-configuration` 或 `show running-config` 备份配置；
- 遇到故障后，通过 SSH 查路由、查 ARP、查接口，再人工拼接排障结论；
- 写了很多 Python 脚本，却没有统一的网页界面，团队成员无法共同使用和查看结果。

Nexora 是一款面向网络工程师的网络运维自动化平台，将设备资产、SNMP 监控、自动化命令下发、配置备份、版本 Diff、LLDP 拓扑和路径诊断集中到一个现代化 Web 平台中。

本文基于当前仓库的 Docker Compose 配置，介绍如何在 Linux 服务器上完成部署。宿主机不需要安装 Python、Node.js 或 npm，前端会在 Docker 构建阶段自动编译。

## 一、核心能力

- **设备资产与凭据管理**：统一维护交换机、路由器、防火墙和服务器资产，保存管理地址、厂商平台、SSH 凭据、SNMP 参数、设备角色和标签。
- **多厂商 CLI 自动化**：基于 Netmiko 和 TextFSM，支持华为 VRP、华三 Comware、Cisco IOS 等常见网络设备。
- **配置备份与版本 Diff**：定时备份设备配置，保留历史版本，直观对比新增、删除和修改内容。
- **SNMP 监控与告警**：采集 CPU、内存、接口状态、流量、错误计数和可用性指标。
- **LLDP 拓扑与路径诊断**：发现邻居关系，并结合路由、ARP、接口状态和实时探测分析网络故障。

## 二、Docker 部署架构

当前 `docker-compose.yml` 默认启动三个服务：

| 服务 | 作用 | 对外端口 |
| --- | --- | --- |
| `db` | PostgreSQL 18 数据库 | 不直接暴露 |
| `netops` | FastAPI 后端、任务调度、设备采集和前端静态文件 | 容器内部 8003 |
| `nginx` | HTTPS 入口、静态文件、API 和 WebSocket 反向代理 | 80、443 |

宿主机只需要访问 Nginx，后端 8003 仅在 Compose 网络内使用。平台使用以下 named volumes 持久化数据：

- `nexora-pgdata`：PostgreSQL 数据；
- `nexora-data`：运行数据；
- `nexora-backup`：设备配置备份；
- `nexora-dist`：前端构建产物。

网络设备需要能够从 `netops` 容器访问，因此部署服务器必须能够连接设备的 SSH、SNMP 和必要的网络管理端口。

## 三、部署前准备

建议使用 Ubuntu 22.04/24.04 或其他主流 Linux 发行版，并准备：

- Git；
- Docker Engine；
- Docker Compose v2，即 `docker compose` 命令；
- OpenSSL；
- 至少 2 vCPU、4 GB 内存和足够的磁盘空间；
- 防火墙放行 TCP 80/443；
- 服务器到网络设备管理网段可达。

检查环境：

```
docker --version
docker compose version
git --version
openssl version
```

如果 Docker 需要普通用户执行，可以将当前用户加入 `docker` 用户组，然后重新登录：

```
sudo usermod -aG docker "$USER"
```

## 四、从 GitHub 拉取代码

```
git clone https://github.com/libing28390-sketch/Release-netops.git netops-automation
cd netops-automation
```

## 五、推荐方式：一键部署

项目内置 `scripts/deploy-docker.sh`，会自动完成：

1. 检查 Docker Compose v2、Git 和 OpenSSL；
2. 从 `.env.example` 初始化 `.env`；
3. 生成随机 PostgreSQL 密码；
4. 生成 `SECRET_KEY` 和 `CREDENTIAL_ENCRYPTION_KEY`；
5. 将容器内数据库地址设置为 `db:5432`；
6. 创建 Nginx TLS 目录；
7. 构建后端和 Nginx 镜像；
8. 后台启动容器并展示状态。

执行：

```
bash scripts/deploy-docker.sh install
```

也可以指定部署目录：

```
bash scripts/deploy-docker.sh install /opt/netops-automation
```

脚本会修改当前目录下的 `.env`。该文件包含数据库密码和应用密钥，切勿提交到 Git 或公开发布。

## 六、手动 Docker Compose 部署

如果需要自行控制环境变量，也可以不用部署脚本。

### 1. 创建并配置环境变量

```
cp .env.example .env
chmod 600 .env
```

至少修改以下配置：

```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=替换为高强度数据库密码
POSTGRES_DB=netops

SECRET_KEY=替换为随机应用密钥
CREDENTIAL_ENCRYPTION_KEY=替换为随机凭据加密密钥
ENVIRONMENT=production

# Docker Compose 中必须使用服务名 db，而不是 localhost
DATABASE_URL=postgresql://postgres:替换为高强度数据库密码@db:5432/netops

# 域名或服务器 IP；没有正式证书时用于生成自签名证书
TLS_COMMON_NAME=你的域名或服务器IP
```

生成随机密钥：

```
openssl rand -hex 32
```

生产环境不要使用默认密码、占位密钥或 `localhost` 数据库地址。数据库密码如果包含特殊字符，需要正确进行 URL 编码；使用部署脚本生成的十六进制密码最简单。

### 2. 校验并启动

```
docker compose config --quiet
docker compose up -d --build
```

首次构建会执行前端依赖安装和生产构建，耗时取决于服务器 CPU、磁盘和网络环境。

## 离线镜像部署：在线准备，离线导入

如果生产服务器无法访问镜像仓库，建议将部署拆成两个阶段：在联网构建机上构建并保存镜像，在离线服务器上导入镜像并启动。离线服务器不安装 Node.js/Python，不执行 Docker build，也不拉取外部镜像。

### 1. 在联网构建机保存镜像

在已经成功启动 Nexora 的部署目录执行：

```
bash scripts/deploy-docker.sh save-images /tmp/nexora-images-$(date +%Y%m%d-%H%M%S).tar.gz
```

脚本会保存以下 Compose 镜像，并生成同名 `.sha256` 校验文件：

```
nexora-netops:latest
nexora-nginx:latest
nexora-postgres:latest
```

将镜像包、校验文件以及部署目录中的以下文件传到离线服务器：

```
nexora-images-*.tar.gz
nexora-images-*.tar.gz.sha256
docker-compose.yml
.env
nginx/ssl/
```

### 2. 在离线服务器导入镜像

```
bash scripts/deploy-docker.sh load-images /data/packages/nexora-images-20260728.tar.gz
```

脚本会在导入前校验 SHA-256，并确认三个 Compose 镜像标签都存在。

### 3. 离线启动

```
bash scripts/deploy-docker.sh start-offline
```

原生命令等价于：

```
docker compose up -d --no-build --pull never --remove-orphans
```

离线启动前请确认源构建机和目标服务器的 CPU 架构一致，例如都为 `x86_64`。不要在离线服务器执行 `docker compose up -d --build`，否则 Docker 会尝试构建或获取缺失的基础镜像。

## 七、检查部署是否成功

查看容器状态：

```
docker compose ps
```

正常情况下，`db`、`netops` 和 `nginx` 都应该处于 `running`，并逐步变为 `healthy`。

查看后端健康接口：

```
curl -k https://127.0.0.1/api/health/live
```

查看后端和 Nginx 日志：

```
docker compose logs -f netops
docker compose logs -f nginx
```

## 八、访问平台与首次初始化

浏览器访问：

```
https://你的服务器IP
```

如果尚未配置受信任的 TLS 证书，Nginx 会在 `nginx/ssl/` 中自动生成自签名证书，浏览器会提示证书不受信任。测试环境可以继续访问；生产环境建议将正式证书和私钥放入：

```
nginx/ssl/netops.crt
nginx/ssl/netops.key
```

然后重启 Nginx：

```
docker compose restart nginx
```

首次登录账号为 `admin / admin`。首次登录后请立即修改默认密码。

## 九、首次使用建议

1. 添加第一台交换机或路由器；
2. 填写管理 IP、厂商平台、SSH 用户名/密码和必要的 Enable/Admin 凭据；
3. 配置 SNMP 版本、团体字或 SNMPv3 凭据；
4. 执行连接测试和基础信息采集；
5. 执行 LLDP 发现，确认邻居设备和接口名称正常；
6. 手动执行一次配置备份；
7. 选择两个配置版本进行 Diff；
8. 创建只读巡检 Playbook，确认命令输出和 TextFSM 解析结果；
9. 再配置定时备份、SNMP 轮询和告警规则。

## 十、常用运维命令

```
docker compose ps
docker compose logs -f
docker compose logs --tail=200 netops
docker compose restart netops
docker compose restart nginx
docker compose down
docker compose up -d
```

`docker compose down` 默认不会删除数据卷；不要随意使用 `docker compose down -v`。

## 十一、升级版本

推荐使用部署脚本：

```
bash scripts/deploy-docker.sh update
```

脚本会保留 `.env`、数据库数据卷、运行数据卷、配置备份数据卷和 `nginx/ssl/` 下的证书。需要强制重建镜像时使用：

```
bash scripts/deploy-docker.sh update --force
```

手动升级：

```
git pull
docker compose up -d --build
docker compose ps
```

## 十二、数据库和配置备份

导出 PostgreSQL 数据库：

```
docker compose exec -T db pg_dump -U postgres netops > nexora-db-$(date +%Y%m%d-%H%M%S).sql
```

如果修改了 `POSTGRES_USER` 或 `POSTGRES_DB`，请将命令中的用户和数据库名替换为实际值。

查看 Docker 数据卷：

```
docker volume ls | grep nexora
```

生产环境建议将数据库导出文件、设备配置备份和关键环境配置纳入独立备份计划。

## 十三、常见问题排查

### 1. 页面提示 502 Bad Gateway

通常是 `netops` 后端容器没有启动成功，或者仍在初始化：

```
docker compose ps
docker compose logs --tail=200 netops
docker compose logs --tail=200 db
```

确认 `db` 已经 `healthy`，再检查后端是否存在数据库连接错误、环境变量错误或 Python 启动异常。

### 2. PostgreSQL 密码认证失败

PostgreSQL 第一次启动时会使用当时的 `POSTGRES_PASSWORD` 初始化数据卷。之后单独修改 `.env` 中的密码，不会自动修改已经初始化的数据卷密码。

生产环境应恢复原密码或执行经过验证的数据库密码迁移。只有在没有重要数据的测试环境中，才考虑清空数据卷重新初始化：

```
docker compose down
docker volume rm nexora-pgdata
docker compose up -d
```

### 3. 浏览器提示证书不可信

这是默认自签名证书的正常现象。测试环境可以手动信任证书；生产环境请替换 `nginx/ssl/` 下的证书，然后执行：

```
docker compose restart nginx
```

### 4. 服务器无法访问镜像仓库

不要在离线服务器执行构建或拉取。请在联网构建机执行 `save-images`，将镜像包和校验文件传入目标服务器，再执行 `load-images` 和 `start-offline`：

```
bash scripts/deploy-docker.sh load-images /data/packages/nexora-images-20260728.tar.gz
bash scripts/deploy-docker.sh start-offline
```

如果导入失败，先检查镜像包的 SHA-256 校验值、磁盘空间和 CPU 架构；如果提示镜像标签缺失，重新导入包含 `nexora-netops:latest`、`nexora-nginx:latest` 和 `nexora-postgres:latest` 的完整归档。

### 5. 页面正常，但设备连接失败

确认设备管理地址、容器到设备的路由、防火墙端口、SSH 权限、厂商平台类型和 SNMP 参数。可以从后端容器测试 TCP 端口：

```
docker compose exec netops python -c "import socket; s=socket.create_connection(('设备管理IP', 22), 5); print('SSH reachable'); s.close()"
```

### 6. ICMP 路径诊断失败

路径诊断除了路由、ARP 和接口状态，还会执行实时探测。如果容器所在主机或 Docker 安全策略限制了 ICMP 原始套接字，需要检查容器的 ICMP 能力；同时先确认 SSH/CLI 路径诊断能够访问源设备和中间设备。

实时探测失败时，不要只根据历史拓扑或旧 ARP 记录判断链路正常，应优先查看诊断页面中的实时接口状态、探测轮次和证据一致性结果。

### 7. 忘记管理员密码

如果是刚部署且没有重要数据，可以删除 PostgreSQL 数据卷后重新初始化；生产环境不要直接删除数据卷，应通过管理员恢复流程或数据库运维流程处理。

## 十四、数据清理命令：谨慎使用

项目提供了完整重置命令：

```
bash scripts/deploy-docker.sh reset-data --yes
```

该命令会停止当前 Compose 项目，并删除项目数据卷、构建镜像和生成的 TLS 文件。它适合全新测试环境，不适合生产环境日常维护。执行前必须完成数据库和配置备份。

## 十五、部署完成检查清单

- [ ] `docker compose config --quiet` 校验通过；
- [ ] `db`、`netops`、`nginx` 容器均为 healthy；
- [ ] `https://服务器IP` 可以打开登录页；
- [ ] 默认管理员密码已修改；
- [ ] PostgreSQL 数据和配置备份已纳入备份计划；
- [ ] 设备管理网段可以从后端容器访问；
- [ ] 至少一台设备连接测试成功；
- [ ] SNMP 采集和接口状态显示正常；
- [ ] LLDP 拓扑发现结果与实际网络一致；
- [ ] 配置备份和版本 Diff 已验证；
- [ ] 已配置升级、日志和故障处理流程。

## 结语

网络运维不应该长期依赖个人脚本、零散命令和人工记忆。Nexora 通过 Docker Compose 把设备资产、监控、自动化、配置备份、拓扑和故障诊断集中到一个统一入口，让网络工程师把时间用在架构优化和问题决策上，而不是重复登录设备和复制粘贴命令。
