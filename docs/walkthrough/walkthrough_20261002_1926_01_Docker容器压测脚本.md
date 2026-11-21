# Docker 容器逐项压测脚本完成记录

## 完成摘要

新增并根据部署主机的真实运行报告修正 Linux Bash 脚本 `scripts/stress-test-docker.sh`。方法复审后明确其用途为连通性与轻负载预检查：即使所有探测成功，也不能用于确定容量或合理的 limits。脚本按服务逐个运行只读探测并采集资源读数，默认只显示计划，传入 `--run` 才会实际发送请求。

## 实际修改文件

- `scripts/stress-test-docker.sh`
- `docs/plans/plan_20261002_1926_01_Docker容器压测脚本.md`
- `docs/walkthrough/walkthrough_20261002_1926_01_Docker容器压测脚本.md`

## 关键实现

- 覆盖 PostgreSQL、NetOps、VictoriaMetrics、SNMP exporter、vmagent、Docker socket proxy、cAdvisor、Grafana、Nginx、Redis 和可选 SeaweedFS；只对运行中的容器施压。
- PostgreSQL 测试执行 `SELECT 1`，并将会话设为只读；Redis 测试只发 `PING`；HTTP 测试使用 health、query、metrics 或 S3 根 GET。
- 不写业务数据、不制造 OOM、不轮询真实 SNMP 设备、不拉取镜像、不调整 Compose 限额。
- HTTP/数据库/Redis 请求由本机已有 `nexora-netops` Python 镜像中的临时容器生成，并限制为 0.5 CPU、192 MiB；每次只测试一个服务。
- HTTP 负载生成器显式禁用代理，避免 Docker 内部服务别名被主机代理接管；Redis 客户端不再发送 ACL 未授权的 `CLIENT SETNAME`。
- 采样器在后台负载容器存活期间轮询 Docker 状态，修复初版报告只有 `before` 和 `after`、缺少 `during` 峰值样本的问题。
- 默认参数为每服务 15 秒、4 个客户端、最高 20 请求/秒；压测请求和资源样本分别保存在 JSONL 与 CSV 报告中。
- Nginx HTTP 根路径预期返回 301；HTTP 请求不自动跟随重定向，不把自签名 TLS 校验问题与 HTTP 可达性混为一谈。此探测未验证 HTTPS 静态资源、TLS 或业务反向代理容量。
- 帮助、计划、结束信息和 JSONL 均注明预检查范围，JSONL 包含 `capacity_validated: false`。

## 用户部署主机初版结果分析

- 用户提供的首轮运行报告中，11 个服务有 1 个成功、10 个失败。PostgreSQL 的只读 `SELECT 1` 完成 299 次、0 错误，平均 0.35 ms、p95 0.84 ms、最大 5.01 ms；这只说明轻量查询正常，不构成数据库容量基准。
- 其余 9 个 HTTP 阶段均未成功：日志出现大量 502、连接重置；Docker socket proxy 和 cAdvisor 还出现 `Network is unreachable`。这与临时 Python 容器继承代理、把内部 Docker DNS 流量交给代理的表现相符，因此初版结果不能说明这些服务被压到极限。
- Redis 293 次请求全部因 `nexora` ACL 不允许 `CLIENT SETNAME` 失败，与 Redis 负载承受能力无关。
- 用户的 CSV 只有 `before` / `after` 样本，没有 `during` 样本，无法判断压测期间 CPU/内存峰值。NetOps 约 439.2 MiB / 2 GiB（21.44%）是当时的使用量读数，不是有效负载下的峰值。
- `docker-compose.yml` 当前只为 NetOps 声明 `mem_limit: 2g`、`cpus: 2.0`，为 Nginx 声明 `mem_limit: 256m`、`cpus: 1.0`；其他服务没有 Compose CPU/内存硬限制。容器 stats 对无显式内存限制的服务显示主机内存作为 limit，因此不同服务的 `MEM %` 分母不一致，不能直接横向比较。

## 本工作区验证命令与结果

- `& 'C:\Program Files\Git\bin\bash.exe' -n scripts/stress-test-docker.sh`：通过。
- `& 'C:\Program Files\Git\bin\bash.exe' scripts/stress-test-docker.sh --help`：通过，显示选项和默认只读范围。
- `& 'C:\Program Files\Git\bin\bash.exe' scripts/stress-test-docker.sh --dry-run`：通过，列出 11 个服务且未访问 Docker。
- 使用 Python 3.11 对脚本内嵌的请求生成器执行 `ast.parse`：通过。
- 使用 Git Bash 对后台进程采样循环做冒烟检查：通过，能在任务运行期间继续轮询并在结束后退出。
- 复审后的 `bash -n`、`--dry-run` 和内嵌 Python AST：通过。
- 使用 Python 3.11 本地回环 HTTP 服务运行内嵌请求生成器：预期 301 成功、未预期 302 拒绝、正常 200 成功，3 项通过；确认没有访问重定向目的地，且错误代理变量未改变请求目标。未访问外部服务或真实设备。

## 未执行验证及原因

没有在本工作区对修正版运行 `--run`：工作区没有 Docker CLI，也没有部署主机连接。需要在部署主机替换为修正版后复测，以验证内部网络请求成功、Redis PING 权限通过，并确认 CSV 出现 `during` 样本。

## 剩余风险与建议

- 脚本属于低负载服务级压测，不会主动把内存推到 limit；它记录读请求期间的内存变化，不能据此证明容器在 OOM 边缘仍稳定。
- SNMP exporter 测试自身 `/metrics` 页面，不请求 `/snmp`，因此不会给真实网络设备增加轮询。
- SeaweedFS 使用 S3 根 GET，并接受 200 或 403；部署配置若返回其他状态，会在该服务 JSONL 结果中报告失败。
- NetOps 2 GiB / 2 CPU 是否足够，无法由本脚本证明：无论提高当前探测频率还是获得期间采样，都没有覆盖主要业务和持续负载。HTTP 失败的代理原因仍是待部署机复测的推断；旁路实现通过了本地行为验证。
- 预检查复跑仅用于验证网络、权限、探测行为和采样。正式 limits 评估需另行构建代表业务负载的容量测试，不能把预检查通过等同于容量验证。

## 方法审查与正式容量评估要求

主 Agent 审查主要调用链并修正脚本表述与 Nginx 探测；独立子 Agent 只读审查方案和实现，由主 Agent 维护统一记录。

独立审查同样确认：当前工作负载不代表业务容量，15 秒探测不足以证明峰值安全，串行且仅采集请求目标无法评估依赖和宿主机资源竞争；缺少运行时实际限额、CPU 限流、OOM/重启与实际完成 RPS。脚本覆盖当前已知的 11 个容器，并未动态发现 Compose override 中的新增服务。

| 服务 | 现有预检查覆盖 | 正式容量评估需要覆盖 |
| --- | --- | --- |
| NetOps | liveness 固定 JSON | 鉴权后的资产/设备分页查询、告警聚合、拓扑等代表接口及实际后台任务；数据量与并发需对应预期高峰 |
| Nginx | HTTP 重定向 | HTTPS 静态文件与真实 API 代理混合流量、连接复用和响应体大小 |
| PostgreSQL | `SELECT 1` | 实际索引/分页/关联查询、代表性写入与事务、连接池；测试数据库隔离 |
| Redis | `PING` | 代表缓存、限流命令、键量和值大小、内存与驱逐；隔离测试实例 |
| SNMP exporter / vmagent | 自身 `/metrics` | 测试设备或模拟 SNMP 目标并发采集、目标数量、采集间隔、指标量、remote-write 速度与积压 |
| VictoriaMetrics | instant `up` | 合成时序写入速率、活跃序列基数、实际查询区间和并发，使用隔离测试存储 |
| Grafana | `/api/health` | 代表看板的数据源查询，时间范围、面板数、刷新间隔与并发用户 |
| SeaweedFS | 根目录 200/403 | 专用测试实例/桶中的对象上传和下载、文件大小分布、并发、元数据与磁盘 I/O |
| cAdvisor / socket proxy | metrics / `_ping` | 正常采集环境下的容器规模、采集间隔、实际 Docker API 读取；观测开销随规模的变化 |

- 首先明确预期峰值（在线用户、业务数据、设备数、指标量、对象量）与可接受的延迟/错误率。
- 在隔离测试环境执行预热、常态、阶梯升压与持续运行；保持相同数据和场景，才能比较不同限额下的服务表现。15 秒探测及 60 秒上限不足以覆盖长期积压、内存增长、存储维护周期等。
- 同时采集所有依赖容器和宿主机，不能只观察请求目标；记录真实完成吞吐、成功请求延迟 p95/p99、错误率、采样窗口、容器 CPU 限流、内存使用/缓存、OOM、重启，以及队列/写入积压。
- 当前生成器同主机且限制 0.5 CPU / 192 MiB；正式测试要监控生成器是否成为瓶颈。设置 100 RPS 上限并不能证明实际达到 100 RPS。请求失败的耗时不应混入成功延迟得出容量结论。
- 当前 NET I/O / BLOCK I/O 是累积读数，正式评估应按时间差计算吞吐速率，并检查磁盘延迟和宿主机整体资源竞争。

参考：[k6 的测试类型说明](https://grafana.com/docs/k6/latest/testing-guides/test-types/)区分轻负载验证、常态测试、压力测试和长期测试；[Docker stats 说明](https://docs.docker.com/reference/cli/docker/container/stats/)记录读数口径和 Linux 内存缓存扣除；[Docker 资源限制说明](https://docs.docker.com/engine/containers/resource_constraints/)说明 CPU 配额与内存硬限制的作用。
