# Docker 容量测试

入口：`bash scripts/stress-test-docker.sh`。默认只展示计划，不访问 Docker；加 `--run` 才执行。

当前工具版本为 1.1.4，可用 `bash scripts/stress-test-docker.sh --version` 核对。该版会把 NetOps 登录超时标记为 `api_login_timeout`，记录每档 warmup 结果，并在未通过时停止正式压测；失败报告还会收集测试 NetOps、PostgreSQL、Redis 容器的脱敏日志尾部。它保留 `POSTGRES_USER`、one-shot CPU 连续样本计算、VictoriaMetrics 预检类型修复及安全异常定位，不输出异常消息或凭据。报告会把影响容量结论的关键资源缺项与网络、块 I/O、PID 数等辅助指标缺项分开列出。

## 在部署机运行

将下面文件一起同步到部署机，保持目录结构：

- `scripts/stress-test-docker.sh`
- `scripts/stress-test-docker-probe.sh`
- `scripts/docker_capacity/` 下的 Python 文件

需要 Linux、主机 Python 3.10+、本地 Docker CLI/Unix socket，以及已运行的 Nexora 源容器。主机 Python 只使用标准库；数据库、Redis、S3 等客户端使用现有 NetOps 镜像中的依赖。工具不拉镜像，不执行 pip 安装，不读取 `.env`。

```bash
# 先查看数据规模、场景和档位
bash scripts/stress-test-docker.sh --dry-run

# 默认完整测试：每场景 5、20、50 RPS，每档测量 120 秒
bash scripts/stress-test-docker.sh --run

# 每档持续五分钟，可观察更多采集周期和内存变化
bash scripts/stress-test-docker.sh --run \
  --stages 5,20,50 --stage-seconds 300 --concurrency 8

# 只压业务/API链路，依赖仍自动创建
bash scripts/stress-test-docker.sh --run \
  --services netops,nginx,db,redis --stages 10,30,60

# 更大的数据库、指标和模拟设备规模；先确保测试主机有足够资源
bash scripts/stress-test-docker.sh --run \
  --rows 100000 --redis-keys 100000 --series 50000 \
  --snmp-targets 32 --interfaces 48 --stage-seconds 300

# 原有低负载预检查仍可用；该模式不做容量评估
bash scripts/stress-test-docker.sh --probe --run
```

默认同时生成所有 11 个场景。`--stages` 的 RPS 是**每个场景**的请求/操作速率，不是总速率。例如全部场景在 20 RPS 档位时，请求上限约为 11 × 20 操作/秒；SQL事务、S3上传下载、SNMP walk、Grafana面板查询的每次操作成本不同。`--concurrency` 是每场景客户端上限，不是宿主机 CPU 核数。

若要分别比较各容器在自己场景下的限额，逐个单独运行（每次会启动它的依赖，但只对指定场景施压）：

```bash
for service in db netops redis victoriametrics snmp-exporter vmagent \
  docker-socket-proxy cadvisor grafana nginx seaweedfs; do
  echo "===== $service ====="
  if bash scripts/stress-test-docker.sh --run --services "$service" \
      --stages 5,20,50 --stage-seconds 120; then
    echo "PASS: $service"
  else
    echo "FAILED: $service (see the report path printed above)"
  fi
done
```

这会顺序执行并清理 11 次隔离测试栈；单个场景失败时继续跑其他服务，报告分别保存在各自 `/tmp/nexora-capacity-*` 目录。该结果用于比较各服务单独承压时的资源占用。默认的一次全场景运行用于评估混合负载下的整套系统。

## 隔离方式

工具只读检查 `nexora-*` 源容器，取当前镜像的 immutable image ID 和实际内存/CPU/PID 限额，创建 `nexora-capacity-<run_id>` 前缀的新容器、新 internal 网络和新持久化卷。源容器不被停止、重新配置或写入；不挂载原 PostgreSQL、Redis、应用或对象存储数据卷，也不复制生产秘密。

所有测试业务写入都发生在新实例中：临时 PostgreSQL 数据库、独立 Redis、独立时序存储与 S3 桶。SNMP 目标是工具自己的 UDP 模拟设备，internal 网络阻止测试容器访问真实外部设备。

NetOps API 场景使用没有管理 IP 的合成资产记录，避免隔离应用的后台 A-Loop 把 API 数据集当作真实设备探测；SNMP 报文由独立 exporter 场景发往内部模拟器。

cAdvisor 与只读 socket proxy 使用宿主机现有 `/sys`、Docker 根目录和 socket 的只读挂载，以测试实际容器规模下的观测工作。socket proxy 仅开放 GET 读取所需的容器/信息 API，关闭 POST；普通负载生成器没有 Docker socket。Docker socket 的只读挂载本身不是权限控制，限制写操作由 proxy 的 API 规则实施。

测试栈与源栈仍共享宿主机 CPU、内存和磁盘，因此适合在测试主机或维护窗口运行。工具同步观察宿主机和源容器；当宿主机可用内存低于默认 10% 或 256 MiB、有限额测试容器内存达到默认 95%，或测试服务发生 OOM/异常退出时停止。可通过 `--min-host-available-percent`、`--max-container-memory-percent` 调整。

Ctrl+C / SIGTERM 会进入清理，删除前核对唯一运行标签。SIGKILL、断电或 Docker daemon 中断时可能留下临时对象；报告中的 `run_id`、`cleanup`、`resource_prefix` 用于定位。清理时只能操作对应 `nexora.capacity.run=<完整run_id>` 的资源，不要删除原 `nexora-*` 容器/卷。

## 实际负载

| 场景 | 测试内容 |
| --- | --- |
| NetOps | 创建测试账户并正常登录；带鉴权的设备分页、告警汇总、拓扑链接查询 |
| Nginx | HTTPS 首页、实际 JS/CSS 静态资源、真实业务 API 代理；临时 TLS 证书仅在隔离客户端中允许自签名 |
| PostgreSQL | 合成业务设备数据与有索引的测试表；分页/聚合/索引查询及写事务 |
| Redis | 一万键默认数据集；GET/SET/INCR/Lua 缓存与限流混合操作，AOF 与 512 MiB Redis maxmemory |
| SNMP exporter | 通过 `/snmp` 对多端口模拟 SNMPv2c 设备实际 GETBULK/walk，多接口计数器会变化 |
| vmagent | 真实抓取模拟 SNMP 和 cAdvisor；同时通过 Prometheus import 接口接收测试批次并 remote-write 到独立 VictoriaMetrics |
| VictoriaMetrics | 合成活跃时序与历史点；写入、时间范围查询，使用固定序列编号避免无限增长基数 |
| Grafana | 通过 `/api/ds/query` 向已配置 Prometheus 数据源发起真实范围查询，并检查查询结果 |
| SeaweedFS | 独立 S3 桶内对象上传与下载，检查内容；默认 32 个 256 KiB 对象 |
| cAdvisor | 实际宿主机容器指标采集与并发读取，检查 CPU/内存指标存在 |
| Docker socket proxy | 实际允许的 Docker 容器列表/daemon 信息读取，与 cAdvisor 共同观察代理开销 |

启动后先准备数据和账户、检查各真实场景，再采基线。每档包含预热、测量和恢复；所有选中场景同时运行。预热结果不进入该档的成功延迟统计。测量过程中同时观察全部源容器、测试容器和生成器。

## 报告与判断

报告默认写入 `/tmp/nexora-capacity-<UTC时间>-<run_id>/`，也可用 `--output-dir /data/capacity-report-01` 指定一个空目录。

- `report.md`：阶段结果、来源限额、资源峰值、诊断和清理结果，并分别列出关键指标缺失和其他可选指标未提供。
- `report.json`：完整场景结果、阈值判断、真实数据量、运行时配置与资源汇总；`critical_missing_metrics` 会使通过结果变为 `incomplete`，`optional_missing_metrics` 仍保留在报告中但不单独阻止容量结论。
- `report.json` 的 `warmups`：每档测量前的预热摘要；预热未通过会记录结果并停止，不再进入正式阶段。
- `report.json` 的 `container_diagnostics`：失败或启动超时的测试容器状态、退出码、OOM 与最多 100 行/16000 字符的脱敏日志尾部；该信息在删除测试容器前收集。日志不可用时会显示对应错误码，`Config.Env` 不进入报告。
- 每阶段 `run-stage-*.json`：实际完成/成功/失败/丢弃请求数、实际成功 RPS、成功请求 p50/p95/p99/max；失败耗时不混入成功延迟。
- `container-stats.csv` 与原始指标 JSONL：CPU、原始内存与扣除缓存后的内存、真实限额、CPU限流、网络/块I/O计数与速率、OOM/重启。
- `host-stats.csv`：宿主机可用内存、swap、CPU、I/O wait、load 与报告磁盘空间。

默认每档要求：错误率不超过 1%、成功请求 p95 不超过 1000 ms、实际成功速率至少达到目标的 90%，且没有生成器丢弃请求。可用 `--max-error-percent`、`--max-p95-ms`、`--min-rate-percent` 定义符合自己业务的 SLO。任一场景失败后停止继续升压，保留已完成档位。

退出码：0 为本次场景与关键资源指标完整的阈值通过；1 为负载阈值或容器故障失败；2 为缺少前提、被保护停止、关键资源指标不完整或清理失败。关键资源指标包括各源/测试容器 CPU 与内存、Docker stats 采样和主机可用内存/CPU。网络、块 I/O、PID 数、CPU throttling 等其他缺失仍会列出，但不单独阻止容量结论。`passed` 的含义是本次给定数据与场景满足阈值，不能理解为所有生产业务都满足。

生成器默认 2 CPU / 1 GiB。若它的 CPU 接近配额、丢弃请求或达不到请求速率，先排除生成器瓶颈，再评估目标服务。通过 `--generator-cpus` 和 `--generator-memory-mib` 调整，但要计入宿主机共享资源预算。

根据每档的成功速率、延迟、限流和内存峰值比较限额，而不是比较不同分母的 `MEM %`。无显式内存限制的服务会记录为“无显式硬限制”。CPU限流或长期内存接近硬限额时，先查对应业务和依赖瓶颈，再选择调整限额；工具不自动执行 `docker update`。

## 结论边界

这是完整可执行的**合成容量场景工具**，覆盖当前 11 个服务的实际操作路径。生产的数据量、流量比例、文件大小、设备延迟、采集间隔和看板复杂度仍需要由测试参数匹配。默认规模并不代表用户生产规模。

NetOps 保留源数据库连接池和 worker 参数；为了隔离外部存储，测试应用使用本地存储，S3 路径由独立对象场景压测。Grafana 数据源查询使用测试管理员 Basic Auth，没有复刻浏览器渲染或生产认证代理。SNMP 使用v2c模拟设备，不能据此推断SNMPv3加密或真实设备的承载能力。测试数据库与时序存储为新数据，不能模拟积累数月后的全量存储。

需要观察长期内存增长/积压时，增大 `--stage-seconds`（最多 3600 秒）和数据集；需要90天保留容量时，还要匹配实际活跃序列与历史样本、对象总量和业务表规模。最高通过档位仅适用于本次条件。

本工作区没有 Docker，已在本地验证编排、协议、请求处理和指标计算；具体部署镜像的首次启动和整体性能仍以部署机实际执行结果为准。

若报告包含 `TEST_NETOPS_STARTUP_FAILED` 且 `stages` 为空，或 `api_login_timeout` 且阶段请求数为 0，则测试未形成有效容量结果。使用 v1.1.4 单场景低档位复测，并查看 `warmups`、`container_diagnostics.netops` 和 `container_diagnostics.db` 的日志定位问题：

```bash
bash scripts/stress-test-docker.sh --run --services netops \
  --rps 5 --stage-seconds 30 --warmup-seconds 5 --baseline-seconds 3 \
  --rows 1000 --redis-keys 1000 --series 1000 --history-points 5
```

启动或登录失败的报告不能用来决定提高容器内存或 CPU 限额。
