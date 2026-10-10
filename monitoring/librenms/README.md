# LibreNMS 原生运行时

该目录记录 Nexora 可选的完整 LibreNMS Docker 运行时锁定信息与安全初始化约定。此配置只搭建 LibreNMS 官方 Web/API、dispatcher、专属 MariaDB 和专属 Redis；Nexora 仍用 PostgreSQL，且不复用 Nexora Redis。

## 版本锁定

LibreNMS 官方 Docker 仓库发布 `26.9.1.1-r1` 指向提交 `afb3e410afbbf8a10a2204a957f16160943fcf3f`。发布镜像 `librenms/librenms:26.9.1.1` 的 Docker Registry OCI manifest digest 于 2026-10-07 核验为 `sha256:814e3fb8d837c65ac51c1d9659ca5f551ed8ea47661ea7de6afbe2081207909b`。Compose 中 Web 和 dispatcher 使用同一标签与 digest；完整记录见 [image-lock.json](image-lock.json)。

MariaDB 与 Redis 同样使用核验过的固定版本和 manifest digest。LibreNMS 官方该版本的 Compose 示例仍使用浮动的 `mariadb:10` 和 `redis:7.2-alpine`；本项目选择了当前固定补丁版本，正式接入设备前仍须完成小规模验证，并在 LibreNMS 容器内运行 `php validate.php`。不要把 `docker compose config` 通过视为 MariaDB 或 SNMP 设备兼容性验收。

## 网络与启动边界

所有四个服务都在 `librenms-native` profile 下，普通 `docker compose up` 不会启动它们。LibreNMS 数据库和 Redis 只连 `librenms_internal`；Web/API 与 Nexora 通过仅含 `netops` 和 `librenms` 的 `librenms_control` 通信。dispatcher 另外连接仅由它和 VictoriaMetrics 共用的 `librenms_metrics`，用于后续配置原生数值输出；这条内部网络不提供设备管理路由。现有 VictoriaMetrics 配置了 `-influx.databaseNames=librenms` 以响应 Influx v1 `SHOW DATABASES`。该兼容设置不是数据通道验收；实际 LibreNMS Influx 设置、路径和时序值仍须通过 POC 验证。MariaDB、Redis 不发布宿主机端口。LibreNMS Web 只绑定 `127.0.0.1:18000`，不能从公网接口直接访问。

dispatcher 是唯一加入 `librenms_device_management` 的服务。它引用 `.env` 的 `LIBRENMS_DEVICE_NETWORK_NAME`，默认名称为 `nexora-librenms-device-management`，且要求该 Docker 网络预先存在并能路由到设备管理网。网络需由部署方按现场路由、地址冲突和防火墙策略创建或映射；Compose 不会把 `monitoring_internal` 当成 SNMP 路由，也不会自动创建外部网络。启动前应确认该网络非 `internal`，且只有预期 dispatcher 连接到设备管理地址。

`librenms` 主服务与 dispatcher 共享专属命名卷 `/data`；数据库和 Redis 另有各自的数据卷。升级、备份和恢复需把这些卷作为 LibreNMS 自有状态一起处理。此提交不启动容器、不创建 Docker 网络或卷，也不注册真实设备；profile 必须在运维审核后显式启用。

CPU/内存上限和 poller 并发尚未设置成生产值，需经小规模设备 POC 测量后再确定；不要直接将本地 profile 当作大规模正式采集配置。

## 密钥和首次初始化

仅将以下新变量填入部署主机的本地 `.env`，不要把真实值写回 `.env.example`：

- `LIBRENMS_APP_KEY`：`base64:` 前缀加 32 个随机字节的 Base64 编码。可用 `openssl rand -base64 32` 生成编码部分；同一 LibreNMS 集群的所有节点必须使用同一个值。
- `LIBRENMS_DB_PASSWORD`、`LIBRENMS_DB_ROOT_PASSWORD`、`LIBRENMS_REDIS_PASSWORD`：分别用独立密码生成器产生至少 32 字符的值，不得互相复用。
- `LIBRENMS_DEVICE_NETWORK_NAME`：现场已存在的、能到设备管理网的 Docker 网络名。

本地 `.env` 是既有部署数据，更新时不得用 `.env.example` 覆盖。Web 与 dispatcher 启动前的 guard 会检查 APP_KEY 格式及密钥长度，并拒绝示例占位符；MariaDB 与 Redis 也会对自己的密码做同类拒绝。Nexora 的 `netops` 服务会显式清空这些 LibreNMS 密钥环境变量，避免当前广义 `.env` `env_file` 把它们传入后端进程。Nexora 核心仍不保存 LibreNMS 的 SQL 凭据或 API token。

确认配置后，运维可以先只渲染检查（不会启动任何容器，也不打印已渲染配置中的密钥）：

```powershell
docker compose --profile librenms-native config --quiet
```

首次初始化 Web 界面仅供服务器本机访问 `http://127.0.0.1:18000`；远程操作使用 SSH 本地端口转发。先由运维创建首个管理员，再单独创建供 Nexora 集成使用的服务账号/API token。token 不自动生成、不放入 Compose 或 `.env`，后续应由 Nexora 凭据保险库按租户与实例边界管理。只有在已明确允许设备采集且管理网已验证后，才可显式启动 profile；LibreNMS 首次启动本身不会添加设备。

## 参考上游

- [LibreNMS 官方 Docker 26.9.1.1-r1 发布](https://github.com/librenms/docker/releases/tag/26.9.1.1-r1)
- [该发布的官方 Compose 示例](https://github.com/librenms/docker/blob/26.9.1.1-r1/examples/compose/compose.yml)
- [该发布的 Docker image 文档](https://github.com/librenms/docker/blob/26.9.1.1-r1/README.md)
- [LibreNMS 官方 Docker 安装文档](https://docs.librenms.org/Installation/Docker/)
