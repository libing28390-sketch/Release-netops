# 当前交接：页面卡顿、Docker 资源配额与 300 台容量验证

> 更新时间：2026-10-07 03:10（Asia/Shanghai）。本节优先于下方早期检查点。用户已明确授权完成修复后提交并 push 工作区相关代码、跟进并修复 Actions、登录 Docker 部署机自主修改和验证；任务完成后关闭工作站。下方此前“不要 push/部署/关机”的限制已被这次明确授权取代。

## 当前目标与授权

- 目标：继续执行 handoff 和关联计划，定位监控看板刷新、资产表单打开/保存和 Grafana 卡顿；尽量验证 300 台规模下页面与采集任务的响应、资源使用；所有相关代码推送并确认 Actions 通过，部署验证完成后再关机。
- 允许：远端 Docker 主机只读采样、备份、部署代码/配置/索引迁移和运行测试；提交、push；遇 Actions 失败继续修复。不得更改真实网络设备配置，也不使用无登录态的资产 POST/PUT 或创建 Grafana session 测试生产业务写入。
- 远端 SSH 会话仍在本机终端，会话 ID 72558；登录凭据只通过交互终端输入，没有写入文件或报告。部署前检查发现 `/data/nexora-automation` 的 Git 跟踪树干净；存在多个未跟踪诊断/容量文件，部署同步前必须将与新跟踪路径冲突的文件保存在仓库外，禁止 `git clean`。
- 私有 `main` 的 release workflow 会验证后生成公共 `Release-netops`。远端更新先备份 `.env`、PostgreSQL、Source Manifest、TLS 与配置快照；部署时避免自动删除现有 Grafana dashboard，部署后再做一次 300 秒 API/资源/PG 复测。

## 最新采样结果（部署前旧代码）

- 新增三轮连续约 300 秒多 URL 采样，Asia/Shanghai 窗口为 02:30:17–02:35:17、02:35:33–02:40:33、02:41:18–02:46:18；总计与更早的四轮合为七轮。
- 三轮后端 live p95 为 2.33 秒、0.58 秒、2.26 秒；Nginx p95 为 3.82 秒、0.59 秒、2.17 秒。第一、第三轮各出现一次约 6 秒直连/代理同步超时，第二轮无超时；慢请求约每两分钟成簇。Grafana 与 VictoriaMetrics health p95 保持约 5.6–11.1ms。
- 受保护的资产表单、列表和 11 个 dashboard URL 均因无用户会话返回 401；此延迟不能代表已认证查询、保存或 PromQL 面板的真实响应。没有执行生产资产写入或创建 Grafana session。
- 每轮 `snmp_mib_nodes` 增加 48 次 Seq Scan 和 3,245,376 tuple read；表约 67,612 行。PG 1 秒活动样本最长 active SQL 约 329–513ms，没有 lock wait/blocker。PG 没有可用的 `pg_stat_statements`；该采样可能漏掉短 SQL。
- 第三轮应用容器 CPU p95 99.63%、峰值109.95%，内存约693MiB；数据库 CPU p95 42.8%。7个核心容器 CPU 合计 p95 相当于两核约58.8%；cgroup 没有 CPU throttling/OOM。此资源列表未包括 Redis、SeaweedFS、cAdvisor 和 socket proxy。
- 生产当前只有17台设备、15台带 SNMP 绑定、5,296个 active sensor，因此真实远端不等于300台验证。隔离 PostgreSQL + fake SNMP 的密度校准从143.799秒/186,649 SQL降至26.142秒/529 SQL，但不能保证生产真实网络时延。

## 已完成本地修复与验证

- 新增 MIB `LOWER(node_name)` 表达式索引迁移，修复实测 Seq Scan 对应查询；生产只读 EXPLAIN 在应用迁移前仍是 Seq Scan。
- 传感器样本改为按设备批量写入；新增全空值批次 PostgreSQL 类型 cast；采集器样本落库及采集状态同步记录从 async event loop 移到线程。其他少数同步路径仍保留，不能宣称已消除全部阻塞。
- Compose 为11个容器设置 CPU、内存、PID 上限；Nginx worker 默认1并受 PID 上限约束（1–8）；Uvicorn `WORKERS=1` 保持不变。
- 本轮相邻焦点回归 39 passed；凭据、资产绑定、连接池、迁移、诊断与资源执行回归另 39 passed；PostgreSQL-only 扫描 0 violation；前端已有全量 445 tests、lint、production build 通过。之前95分钟后端全量为3410 passed / 1 failed / 1 skipped / 26 subtests，唯一失败的旧 m0275 版本断言已修复，迁移相邻测试5 passed；全量等待 push 后 Actions 重新执行。

## 尚待执行

1. GitHub Actions run #677 (`37515055183`) 后端测试为2940 passed、1 failed、1 skipped；唯一失败是新并发测试使用 `pytest.mark.asyncio`，而 release runner 未安装 pytest-asyncio。本地已改为 `asyncio.run`；对应健康测试7 passed。
2. 部署服务清单已复核并补入 `docker-socket-proxy` 与 `cadvisor`，配有服务选择契约测试；契约测试4 passed，Git Bash 语法检查通过。
3. 更新计划、walkthrough 和修复记录，精确 stage 相关文件，不包含 `.agents/skills/netops-grafana-dashboards/SKILL.md`、`logs/`、`dist-*`、`.codex-build-validation-*`、fake TEST-MIB 样本等临时/无关文件。
4. 在 `main` 提交并 push；等待新一轮 release Actions 完整通过，若失败先定位并修复。
5. 检查部署主机数据库/磁盘与备份；保全会被新增跟踪文件覆盖的历史诊断文件；从 `Release-netops` 更新、构建并重建服务，跳过破坏性 Grafana 旧 dashboard 清理。
6. 验证 m0276 索引迁移及实际查询计划、容器健康与资源配置、Nginx worker 数；跑部署后300秒重复 URL/PG/资源采样并分析前后变化。
7. 更新实际部署结果并 push 完整记录，确认相应 Actions 通过；完成全部工作后按用户要求关闭电脑。

---

# 历史交接检查点（2026-10-07 02:18）

> 下方内容记录之前的检查状态；其中旧的“暂不提交、不 push、不部署、不关机”授权限制已经被本次对话中的最新用户指示取代。具体技术证据仍保留作历史参考。

## 1. 当前目标和授权边界

- 用户最新请求：接续交接排查页面/资产操作卡顿及疑似 PG 查询慢，用户怀疑设备数量及 SNMP 频率负载。
- 主任务：依据真实 Linux Docker 证据排查 Nexora 页面卡顿，修正后端阻塞调用和连接复用，为所有容器设置可调整资源配额，将 Nginx 默认 worker 改为 1。
- **后端 Uvicorn `WORKERS=1` 保持不变**。用户明确要求“先不要改 worker 数量”；Nginx worker 是另外一个配置。
- **暂不提交、不 push、不部署**。用户“完成后先不要 push，我还有别的问题”的指令仍有效。
- 不修改真实网络设备，不对远端数据库写入、安装扩展、重置统计或重启服务。用户明确授权 SSH 只读检查与采样；已完成四轮各 300 秒的多 URL/PG/容器采样，以及一轮 60 秒的设备和 SNMP 传感器聚合计数，并只读 EXPLAIN 了实际 MIB 精确匹配查询。SSH 已关闭，未持久保存凭据。授权仍不包含部署、配置修改或业务写入。
- 所有本轮代码和配置仍是本地未提交改动，不能宣称真实 Docker 已完成修复。最新资源分配附件只是评估，未自动采纳。
- 工作区：`D:\netops\netsops-main`，当前分支 `main`。本机是 Windows，**没有 Docker 部署环境**。
- 真实部署：Linux `root@devops`，目录 `/data/nexora-automation`，页面 `https://192.168.204.128/monitor/dashboards`。已提供证据显示主机 2 个逻辑 CPU、Docker 可见约 7.709 GiB 内存。
- 遵循 `.agents/AGENTS.md`；按需使用 backend、monitoring-telemetry、quality-gate、release、seaweedfs skills。`handoff.md`、`.agents/`、`.codex/` 是内部协作材料，不进入公有发布树。

## 2. 当前执行状态：完整回归已运行，修复一项迁移测试断言

- 当前工作树执行 `uv run --offline --project backend pytest backend/tests -q --tb=short`，结果为 **3410 passed, 1 failed, 1 skipped, 26 subtests passed**，用时5736.01秒（95分36秒）。唯一失败是 `backend/tests/database/test_m0275_huawei_yunshan_platform.py::test_m0275_registers_scoped_templates_and_preserves_custom_profile`：期望 `MAX(schema_migrations.version)==274`，实际276。
- 原因是本任务新增 m0276 后，m0275 测试的“最新迁移仍是274”前置假设过时。已将其改为确认274已登记、275已删除，再测试重放275；m0275 与 m0276 的相邻迁移测试组随后 **5 passed / 67.04s**。
- 全量回归没有在这项测试断言修正后再跑一次，因此完整全量结果仍按一次失败报告；其余3410个通过项、一个显式要求 Redis 短期 key 授权的跳过项和26个 subtests均来自同一次全量运行。
- SNMP 样本批量 helper 和轮询接入相关聚焦套件 **36 passed**；同规模300台/93,192传感器的端到端测试 **1 passed**。此前初始全量快照中的旧失败项在本次全量中均通过。
- 本轮测试只使用本地隔离 PostgreSQL 与 fake SNMP；没有对业务库运行测试。全量 pytest 进程已结束。

## 3. 已确认的真实 Docker 证据及结论边界

### 正常采样，没有主动复现卡顿

- 用户原始日志：`C:\Users\NINGMEI\Desktop\nexora-container-review-20261006_220737.log`。
- 用户明确回复：“本次没有测试”。采样窗 22:07:37.822～22:08:38.775，约 60.95 秒。
- 解析结果：`logs/validation/perf-container-review-20261006_220737.json`。
- 后端直连 `/api/health/live` 约 5～48.3ms，经 Nginx 约 9.4～119.6ms；不能据此否定其他时段或业务请求的卡顿。
- MIB/raw 表该窗口 seq scan 增量均为 0。事务 rollback +1699，commit +606，无 deadlock。

### 用户实际复现卡顿的采样

- 用户原始日志：`C:\Users\NINGMEI\Desktop\nexora-container-review-20261006_221103.log`。
- 用户确认：“这次有卡顿，确定是旧代码在跑”。窗口 22:11:04.035～22:12:05.975，约 61.94 秒。
- 解析结果：`logs/validation/perf-container-review-20261006_221103.json`。
- 后端直连 live 四次：约 **50.9ms、1931.1ms、5007ms 超时、553.3ms**；经 Nginx 四次约 50～1246ms，TCP 建连约 0.16～1.20ms。
- **绕过 Nginx 的轻量 live 请求也出现秒级延迟和超时，确认卡顿涉及后端请求执行/事件循环/宿主机调度路径。** 不能仅凭这条证据分配每次卡顿的具体代码责任。
- `snmp_mib_nodes`：seq scan +13，扫描行 +878956 = 13 × 67612，有整表扫描证据。
- `interface_telemetry_raw`：seq scan +6，扫描行 +1096436；复合索引扫描 +540、索引读取 +332150。DB commit +835、rollback +2740，block read +54282、hit +410733，窗口命中率约 88.33%。
- 上述扫描与卡顿同窗发生，但没有 SQL 耗时/执行计划和请求时间关联，**不能判定某一张表或 rollup 是全部卡顿的根因**。PostgreSQL block read 也不等于物理磁盘读取耗时。
- 1m rollup 表索引计数无增量，不能声称本窗口确认 rollup 执行。
- 该窗口 Netops CPU 最高约 81.54%，内存约 703～704MiB / 2GiB；PG CPU 最高约 48.33%。未见新增 CPU throttling、OOM、容器重启或锁阻塞。
- activity 捕获到 `idle in transaction / ClientRead`，不是锁等待，也不是持续执行 SQL 的时长。两个窗口 temp bytes 增量都为 9,109,504，不能据此认定卡顿窗口有独有 spill。

### 线上代码和组件审查

- 两次日志镜像、启动时间及配置一致；`engine/orchestrator.py`、`database/core.py`、`main.py` 的源文件 SHA 与本地 HEAD 一致，和当前工作区修复后的内容不同。仅据此确认这三个关键文件未采用本轮补丁，不扩大为所有文件逐一已核验。
- 实际 `WORKERS=1`、`DB_POOL_SIZE=16`、overflow=4，未配置 `DB_POOL_MIN_SIZE`；`STORAGE_BACKEND=s3`，**SeaweedFS 确实在用**。
- PostgreSQL 18.6：`shared_preload_libraries` 为空，`pg_stat_statements` 安装包可用但未启用；未执行安装、重启或统计重置。
- Nginx/Redis/VM 的低 CPU、低内存不能证明业务性能完全没问题；Grafana/VM 轻量 health 正常也不代表业务查询正常。
- 高 rollback 计数不等于同数量的数据库错误：SELECT-only 事务清理、连接回收探测和 `_db_quick()` 都可能贡献；不能把全部 82 万次归给一个函数。
- 历史累计 raw 扫描行最多，只能定位扫描热点，不能替代 SQL 总耗时或 CPU 证据。
- 2h rollup 窗口及每 12 次成功采集维护一次的代码行为已核实，实际间隔还包含采集耗时和休眠，不是严格每 12 分钟。
- 已有 `/api/ai/metrics`（`ai.audit.view`）数据库只读观测可作为扩展起点；已有 pg_stat_statements 可用时 top20 与 activity fallback，但不是完整平台 SQL 历史监控。
- 后续若启用 pg_stat_statements，需单独完成配置和计划重启；它提供调用/耗时/缓冲区信息，不直接提供 SQL CPU 耗时。
- 未盲目新增 trgm 索引、改变 SELECT 提交行为或缩短 rollup 回溯窗口。

## 4. 本轮后端实际改动（全部未提交）

| 文件 | 行为 |
| --- | --- |
| `backend/core/scheduler_lock.py` | 异步锁获取/释放移入线程，shield 并等待重复取消后的清理，保留所有权围栏、心跳和同步入口。 |
| `backend/main.py` | 请求日志中同步 `validate_session_token` 改用 `asyncio.to_thread`，请求 ContextVar 仍在请求协程设置。 |
| `backend/database/core.py` | 增加 `DB_POOL_MIN_SIZE`；默认按 pool size 保留连接，默认 16；上限仍 16+4=20/worker，保留事务清理、失效连接探测及获取超时。 |
| `backend/services/notification_service.py` | 物化收件人/SMTP 配置并释放 DB 连接后发 Webhook/邮件；保留 SMTP 配置失败时 Webhook 独立发送及原错误处理契约。 |
| `backend/api/health.py` | resources/metrics/history 等同步路由由 FastAPI 线程池执行；HTTP 资源读取不同步触发告警；定时采样仍处理告警；告警外发前提交、释放连接。 |
| `backend/engine/orchestrator.py` | A/B 设备查询物化快照移入线程；B-loop 每 12 次成功采集的遥测维护移入线程；保持过滤、顺序、cycle_tick 和设备并发契约。 |
| `.env.example`、`docker-compose.yml` | 增加 DB_POOL_MIN_SIZE，默认随 DB_POOL_SIZE；另含下面资源配额配置。 |

剩余边界：LLDP 同步告警、ConnectionPool.cleanup 因共享状态仍保留原路径；不能宣称全部阻塞已消除。线程运行不能因取消 await 被强制终止。告警先提交后直接外发没有持久化 outbox，提交后崩溃/发送失败仍存在漏发窗口，未在本轮扩大为架构变更。

### 新增/修改回归测试

- 修改：`backend/tests/database/test_scheduler_lock_leases.py`。
- 新增：`backend/tests/database/test_pg_pool_reuse.py`、`backend/tests/security/test_request_logging_execution.py`。
- 新增：`backend/tests/monitoring/test_health_resource_execution.py`、`test_notification_connection_lifecycle.py`、`test_telemetry_orchestrator_execution.py`。
- 覆盖慢鉴权/资源读取时 live 响应可推进、请求上下文、租约取消清理、连接复用/上限、数据库关闭先于外发、SMTP 失败兼容、多循环成功次数和线程执行。

## 5. Docker 配额和 Nginx 当前工作区方案

所有 11 个服务已设置 `cpus`、`mem_limit`、`pids_limit`。CPU/内存有 `.env.example` 可调默认值；CPU 上限不预留独占核，内存上限不预分配。

| 服务 | CPU 上限 | 内存上限 | PIDs |
| --- | ---: | ---: | ---: |
| netops | 2.0 | 2304m | 512 |
| db | 2.0 | 1g | 256 |
| victoriametrics | 2.0 | 768m | 256 |
| grafana | 1.0 | 384m | 256 |
| seaweedfs | 1.0 | 512m | 256 |
| redis | 1.0 | 1g | 128 |
| nginx | 1.0 | 256m | 128 |
| vmagent | 1.0 | 192m | 128 |
| snmp-exporter | 1.0 | 128m | 128 |
| cadvisor | 0.5 | 128m | 128 |
| docker-socket-proxy | 0.25 | 64m | 64 |

- 合计 **6784MiB = 6.625GiB**，按真实主机约留 1.084GiB 给宿主机及余量。Redis 内部 `maxmemory=512mb` 不变，其余内存留给缓冲、AOF 和进程开销。
- Env 前缀：`NETOPS`、`POSTGRES`、`VICTORIAMETRICS`、`GRAFANA`、`SEAWEEDFS`、`REDIS`、`NGINX`、`VMAGENT`、`SNMP_EXPORTER`、`CADVISOR`、`DOCKER_SOCKET_PROXY`，后缀 `_CPUS` / `_MEM_LIMIT`。
- 用户最新资源附件第一版合计 **7872MiB = 7.6875GiB**，在当前主机仅留约 22MiB；附件声称 7.25GB 的加总不正确，**没有采纳**。
- 附件第二版合计 **6976MiB = 6.8125GiB**，较合理但 Redis 从 1GiB 降至 768MiB 要和内部 maxmemory 一起考虑；后续还可评估 PG/SeaweedFS/SNMP 增加余量。没有自动切换到第二版或创建自动资源档位。
- 增加 PostgreSQL 容器内存上限不会自动调优 shared_buffers/work_mem。扩展本身也不能直接推导额外 512MiB 的必要性。

### Nginx 单 worker 实现

- 用户真实 `nginx -T` / `ps`：主配置 `worker_processes auto`，connections 1024，实际 2 个 worker。
- 仓库 `nginx/nginx.conf` 是挂载到 `/etc/nginx/conf.d/default.conf` 的站点配置，不适合写顶层 worker 指令。
- 新文件：`nginx/docker-entrypoint.d/40-configure-workers.sh`，在官方 30 自动调优 hook 之后执行，重写容器 `/etc/nginx/nginx.conf` 的唯一 worker 指令。
- 配置 `NGINX_WORKER_PROCESSES` 默认 1，允许整数 1～1024；非法值、缺失/重复指令明确失败。修改具有幂等性，不改 worker_connections。
- `nginx/Dockerfile` COPY 并 chmod 新 hook；Compose 和 `.env.example` 加入默认值；没有修改后端 WORKERS。
- 新测试：`backend/tests/release/test_nginx_worker_contract.py`，Git Bash 对临时主配置执行实际 hook 函数，覆盖默认、自定义、LF/CRLF、重复执行和拒绝非法输入。
- 未在 Linux 做 Docker 构建、`nginx -t`、重建容器或线上验证。未来应用 Compose 配额/环境和镜像 hook 需要经授权重建相应容器，单纯 restart 不会更新全部配置。

## 6. 已完成验证与未完成验证

| 验证 | 结果 / 日志 |
| --- | --- |
| 首轮后端定向 | 12 passed / 140.26s；`logs/validation/perf-focused-20261006_2054.log`，早于最后两条 pool 测试。 |
| health/通知/pool/groups/outbox 定向 | 29 passed / 约 200s；`logs/validation/perf-notifications-20261006_2054.log`。 |
| SMTP 兼容补丁后通知/groups/outbox | 22 passed / 350.60s；`logs/validation/perf-notifications-final-20261006_2054.log`，临时库已清理。 |
| 遥测线程执行 | 2 passed / 184.15s；`logs/validation/perf-telemetry-loop-20261006_2054.log`，临时库已清理。 |
| Nginx/存储/Redis/监控部署契约 | 首轮 27 passed、2 个新测试 CRLF 字节比较失败；确认 Git Bash sed 的 LF 规范化后调整新测试按规范化内容比较，既有 15 项部署契约已通过。 |
| Nginx 最终新测试 | 14 passed / 4.88s，退出 0；覆盖实际 hook 行为，未删除/削弱业务断言。 |
| 静态检查 | PostgreSQL-only policy scanner 通过；变更 Python AST、Compose YAML/配额默认值、shell `bash -n`、相关 diff whitespace 检查通过。 |
| 全量后端 | **仍运行，65%，2 F / 1 s，最终报告待取得**；session 60701。 |
| Linux Docker 集成/线上性能复测 | **未执行**，本机不具备该环境且没有部署授权。 |

纯配置/部署测试命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/release/test_nginx_worker_contract.py backend/tests/release/test_deploy_docker_storage_contract.py backend/tests/release/test_deploy_docker_redis_contract.py backend/tests/monitoring/test_monitoring_v1_deployment_contract.py -q --confcutdir=backend/tests/release
```

`--confcutdir` 用于这些纯文件/配置测试，避免无关 PostgreSQL 自动 fixture；不能用于绕过实际数据库业务测试。此次没有重复运行前端全量构建，前端已有改动保留。

## 7. 真实 Docker 只读采集脚本和敏感信息

- 本轮脚本：`scripts/diagnostics/collect_nexora_container_review.sh`，默认 60 秒，10 秒采样；只读 SQL、5 秒 statement timeout、1 秒 lock timeout，日志 umask 077、避免覆盖。
- 内容包括配置白名单、源文件 hash、资源/cgroup、DB 表/索引计数增量、活动与阻塞摘要、可用时 pg_stat_statements、后端直连和代理 live 探测。不输出完整 SQL、密码、完整环境或原始业务日志。
- 用户两份日志来自脚本早期版本。最新脚本补充连接数、temp、work_mem/shared_buffers、状态计数和监控文件 hash；已通过语法验证，最新补充项尚未在真实 Linux 复测。
- 传输/执行示例（后续有需要再给用户，不自动执行远端操作）：

```powershell
scp "D:\netops\netsops-main\scripts\diagnostics\collect_nexora_container_review.sh" root@192.168.204.128:/tmp/
```

```bash
DURATION_SECONDS=60 bash /tmp/collect_nexora_container_review.sh
```

- 早期 5 分钟原始采集：`C:\Users\NINGMEI\Desktop\nexora-perf-20261006_203301.log`；保留已有 `scripts/diagnostics/collect_nexora_perf.sh`。
- 相关后端日志附件包含真实 Feishu Webhook。**不要粘贴原始敏感日志、真实 DSN 或凭据到本文件、测试和回复**。

## 8. 并行审查、既有变更与文档入口

- Luna 6 Max 子 Agent `/root/component_perf_audit` 已独立审查截图的九项判断及两份真实容器日志；只读，未修改文件、未触碰远端。
- `/root/latency_health_audit` 完成 health/engine 局部工作与独立审查。后续创建/唤醒部分 Agent 曾遇到 agent thread limit，Nginx/配额由主 Agent 完成；不要声称由子 Agent 实现。
- 最多并行两个子 Agent，不继续嵌套分派；主 Agent 负责共享配置、集成和文档。当前没有已知写代码中的子 Agent。
- 当前工作树还包含更早无线 Grafana/资产首页修改：`backend/api/assets.py`、Grafana generator/presentation/overview/wireless JSON、对应监控和资产测试、`src/pages/HomePage.tsx`/测试、`.gitattributes`、Grafana skill，以及多个 `.codex-build-validation-*`/`dist-*` 目录。**保留，不 reset/clean/revert，也不自动 stage 全工作区**。
- 早期需求包括无线状态绿色、隐藏采集目标/rule_version、无线流量及 Top、AC 前置及在线/离线统计、在线终端名称、移除资产 ID、首页数量与资产管理一致；具体已改行为和验证以 1934 walkthrough 为准。
- 22:29 工作树出现 `backend/vendor/librenms/mibs/cisco/TEST-MIB-*`，可能来自正在执行的 MIB fixture；先等待测试 cleanup，不能当作生产 MIB 发布或立即清除。
- 根目录 `handoff.md` 旧记录保留在下面；不要把历史已经推送、部署之类的状态套用到这次工作。

当前计划/验证文档：

- `docs/plans/plan_20261006_1934_01_无线面板排序与首页资产数量一致性.md`
- `docs/walkthrough/walkthrough_20261006_1934_01_无线面板排序与首页资产数量一致性.md`
- `docs/plans/plan_20261006_2054_01_API请求阻塞与连接复用.md`
- `docs/walkthrough/walkthrough_20261006_2054_01_API请求阻塞与连接复用.md`
- `docs/walkthrough/walkthrough_20261006_2148_01_页面卡顿与PostgreSQL证据审查.md`
- `docs/plans/plan_20261006_2223_01_Docker资源配额与Nginx进程.md`
- `docs/walkthrough/walkthrough_20261006_2223_01_Docker资源配额与Nginx进程.md`
- `docs/deploy/docker.md`：资源配额、Nginx hook、未来重建/核验说明。

## 9. 接手后的下一步顺序

1. **完成**：结束并记录全量后端 pytest 结果；继续保留10项失败的原始证据，局部定向验证通过不覆盖全量红灯。
2. **完成**：按用户要求执行四轮各5分钟的远端多 URL 采样，补充60秒 SNMP binding/sensor 聚合统计，整理结果见本节和 walkthrough。
3. **完成**：用生产只读连接对 `_resolve_mib_symbol` 对应的精确 SQL 执行 EXPLAIN；计划为 `snmp_mib_nodes` Seq Scan。下一步在隔离 PostgreSQL 验证表达式索引和迁移，然后做 fake SNMP 的300台合成规模核验。
4. 当前能确认周期性应用级停顿与 MIB seq scan 同期出现，但不能确认因果。资产和 Grafana 业务 API 采样未登录、返回401；获得登录态后可再同步复现 dashboard 刷新及资产表单加载，并关联 request ID、PG耗时及 event-loop lag/连接池等待。
5. 如继续做只读远端核验，优先确认设备硬件 discovery/capability 的版本新鲜度、probe/discovery 模块的线上源文件指纹，以及 MIB scan 每轮触发的设备数；不启用扩展或重置 PG 统计。
6. Docker 资源配额方案、Nginx worker 调整、后端阻塞补丁和新 MIB 索引仍是本地工作区候选，尚未部署；保持 Uvicorn worker 1。
7. **继续保持不提交、不 push、不部署、不改真实设备或采集频率**，直到用户更新授权。提交前按项目规则补 `docs/fixes/` 并剔除内部协作文件和测试产物。

## 10. 页面、资产、Grafana 与 SNMP/PG 最新排查结果（2026-10-06）

- 用户报告的触发点：打开/刷新监控看板；资产添加/修改表单打开和保存；Grafana 偶发慢。错误文字未知。本轮没有通过浏览器完成真实登录态操作。
- 采样器按真实前端调用链重复 GET `/api/racks`、`/api/cmdb/sites`、`/api/credentials`、资产 summary/list、Grafana auth gate，以及前端 dashboard 页面列出的11个 Grafana URL；同时探测后端直连和 Nginx health、Grafana/VictoriaMetrics health。请求间隔分别为 health 5秒、API 15秒、dashboard 30秒，超时6秒；没有 Authorization/Cookie，不读响应体，也没有调用有 session 副作用的 `POST /api/grafana/session`。
- 完成两个连续的300秒窗口和一个60秒只读聚合计数窗口。原始脱敏数据：`logs/validation/remote-pg-latency-20261006_230914.jsonl` 及 `.resources.jsonl`、汇总 `...230914.summary.json`；`logs/validation/remote-pg-latency-20261006_231514.jsonl` 及 `.resources.jsonl`、汇总 `...231514.summary.json`；计数窗口 `logs/validation/remote-pg-latency-20261006_232243.jsonl` 及 `.resources.jsonl`。
- 两个300秒窗口都出现应用 live 与多个 API 同时变慢/超时的簇，重复间隔约110秒。窗口1后端直连56次，p50 7.1ms/p95 4175ms/max 6007ms、2次超时；Nginx 56次，p50 20.8ms/p95 5840ms/max 6041ms、2次超时。窗口2后端直连57次，p50 11.3ms/p95 4019ms/max 6006ms、1次超时；Nginx 57次，p50 21.4ms/p95 4001ms/max 6011ms、1次超时。Grafana/VM health 在两个窗口保持快速成功，第二窗口 p95 分别10.4ms/5.5ms。
- 受保护的资产 API 与11个 dashboard URL 没有用户会话，绝大多数请求返回401；部分在同一停顿簇中超时。这只能证明这些 URL 的请求也碰到同一应用级停顿，不能代表认证后的资产查询/保存或 Grafana PromQL 页面耗时。没有发起资产 POST/PUT 保存请求（保持只读授权）；未读取、保存或输出响应体和凭据。
- 两轮 PostgreSQL activity 分别采样298/299次，最长 active SQL 年龄约341/412ms，没有采样到锁等待或阻塞。`pg_stat_statements` 未启用，1秒采样也可能漏掉短 SQL。两轮 `snmp_mib_nodes` 都增加42次 seq scan、读取2,839,704行（表约67,612行），集中在约110秒节律的扫描簇；`interface_telemetry_raw` 两轮 seq scan 均为0，以索引读取为主。现有证据没有给出这些 MIB 查询的单次耗时，不能据扫描行数断言它独自导致卡顿。
- NetOps 容器 CPU p95 两轮约92%/101%，峰值约103%/106%，约为一个 CPU；容器 quota 是2 CPU。cgroup 未见 throttling/OOM。PostgreSQL、Grafana、VictoriaMetrics、SNMP exporter 没有持续满载迹象。应用容器存在周期性 CPU/阻塞负担，但当前不能定位到单条 SQL。
- 60秒只读 fleet 汇总：17台设备，15台有 SNMP community/credential 绑定；A/B native loop 候选各17台。硬件传感器表有5,296条 active sensor、涉及15台设备。V1 assignment 按间隔为30秒/15台、120秒/1台、900秒/15台；native 与 V1 资产是否重叠未知，`explicit_snmp_profiles=0` 也不代表没有 SNMP。这些计数表明采集负载值得关注，但不等于5,296个独立 SNMP 包。
- 代码路径证据（工作区）：B-loop await `process_device_slow`；若设备/硬件发现被判 stale，会触发自动 `discover_device_oid_config`，经 LibreNMS hardware probe 解析 MIB 符号；`_resolve_mib_symbol` 在 async 探测路径里同步执行 `LOWER(node_name)` SQL，计划含 `Seq Scan snmp_mib_nodes`。这是比常规 active sensor 轮询更直接的扫描路径。active sensor 轮询另会同步加载传感器清单并 await SNMP walk。周期性全表扫描与 API 停顿节律吻合，使自动硬件发现/MIB 查找成为首要疑点，但远端本轮源文件指纹未包括 discovery/probe 模块，且没有查询耗时/请求 ID关联，仍未证实根因。
- 资产表单的 `/api/credentials` 原先按每条 credential 单独读取关联 devices。`backend/services/credential_service.py` 已改为单次 `ANY(array)` 批量读取，新增 `backend/tests/configuration/test_credential_list_batching.py`；这只减少表单选项加载的 N+1。`backend/api/assets.py` 另修复独立 SNMP credential 的 community 不再误建 SSH credential binding，对应资产绑定单测单独重跑通过。所有这些改动均未部署。
- 当前完整后端回归为3410 passed、1 failed、1 skipped、26 subtests passed；唯一失败是 m0275 测试对“最高 migration version=274”的旧假设。该断言已修复，m0275+m0276相邻迁移组5 passed；全量没有因测试-only修复再跑一次。诊断 helper 为14 passed；硬件样本批量相关聚焦组36 passed；PostgreSQL-only scanner 为0 violations。
- 下一步需要用户登录态下同步复现 dashboard 刷新及资产表单打开/保存，关联浏览器时间、请求 ID、已认证 API 耗时，并补充 event-loop lag/连接池等待观测，才能分开页面、授权、SQL和采集的因果关系。未启用扩展、未重置 PG 统计、未重启容器、未部署、未改采集频率或设备。

## 11. 加长采样与 MIB 精确查询计划（2026-10-07）

- 用户要求把远端采样延长到约5分钟、多次重复调用页面/API URL。基于该授权新增完成两轮300秒窗口（23:47:26–23:52:26、23:53:30–23:58:30），与既有两轮构成四轮；追加采样覆盖资产表单的 `/api/racks/validate-u` 哨兵 GET。远端原始文件保留在 `/tmp/remote-pg-latency-20261006-2347-r1*`、`/tmp/remote-pg-latency-20261006-2353-r2*`，早期窗口见 `...230914*` 和 `...231514*`。
- 新窗口后端直连 live p95 为2,196ms/2,751ms，Nginx p95 为1,794ms/3,489ms；Grafana/VM health p95 为8.4/11.5ms和5.9/6.7ms。两轮 `snmp_mib_nodes` 均新增42次 seq scan、读取2,839,704行。最新两轮 PG activity 活跃查询最大年龄约266/396ms，无 lock wait/block；应用容器 CPU p95约97.6%/85.3%，没有 CPU throttling 或 OOM。
- 当前生产规模仍是17台设备、15台 SNMP 绑定设备、5,296条 active hardware sensor，远低于300台目标；不得将线上真实采样描述成300台验证。
- 用户给出的浏览器当前无登录态；资产及Grafana受保护路由仍返回401。真实保存 POST/PUT、登录后 PromQL/业务查询和浏览器请求关联未测试，不能用未认证 gate 延迟代替。
- 对照 `snmp_hardware_probe_service._resolve_mib_symbol` 精确过滤/join/order/limit 的只读 `EXPLAIN (FORMAT JSON)`：顶层 Limit→Sort→Hash Join；`snmp_mib_nodes` 为 Seq Scan，估算成本约5323、匹配336行；没有执行 ANALYZE。计划使用表达式索引 `LOWER(node_name)` 进行隔离验证。诊断 helper 已加入该精确计划探针及回归测试（14 passed）。
- 新增计划与 walkthrough：`docs/plans/plan_20261007_0004_01_SNMP符号查询与300台容量验证.md`、`docs/walkthrough/walkthrough_20261007_0004_01_SNMP符号查询与300台容量验证.md`。`LOWER(node_name)` 表达式索引迁移已通过3万条合成 MIB nodes 的隔离 PG planner 测试；默认 planner 选择该索引，fresh schema 和重复迁移测试通过。迁移尚未部署到生产。
- 300台合成轮询基线为143.799秒、186,649条 SQL、样本 SQL 118.712秒；批量候选同场景为26.142秒、529条 SQL、批量样本 SQL 12.464秒，93,192个样本全部写入成功。测试覆盖隔离 PostgreSQL 与 fake SNMP，不能外推为生产时延承诺。
- 批量 helper/轮询接入回归36 passed；300台复测1 passed；前端 lint、独立目录 production build、首页测试及配置/部署契约测试通过；PostgreSQL-only scanner 为0 violations。完整后端回归3410 passed、1 failed、1 skipped、26 subtests；m0275测试断言修正后相邻迁移组5 passed，完整套件未重跑。
- 只读业务 URL 因没有登录态仍为401；资产保存 POST/PUT 和登录后 Grafana/业务查询时延尚未复现。SSH 已关闭。
- 依据当前授权边界继续保持本地未提交状态；不 push、不部署、不关机。

---

# 历史交接记录（原文保留，以下不代表当前执行状态或授权）

# Nexora Monitoring V1 P0 交接记录

- 日期：2026-09-16
- 范围：`Nexora_Monitoring_V1_详细架构与落地实施方案.md` 的 P0-T01～P0-T20
- 状态：`REPOSITORY IMPLEMENTATION COMPLETE / RUNTIME POC PENDING`
- 分支：`main`

## 已交付

### Backend / Control Plane

- `backend/database/migrations/m0232_monitoring_v1_control_plane.py`：Collector、SNMP Module、Module Variant、Monitoring Plan、Assignment、MetricDefinition、Config Version、Target Snapshot、Shadow Compare，以及 SNMPv3 加密字段。
- `backend/services/monitoring_compiler.py`：CMDB/Collection Plan → Assignment → Target Snapshot → vmagent/snmp_exporter Artifact；包含 interval、timeout、冲突、duplicate-walk、Auth Alias、Manifest/checksum/YAML 校验。
- `backend/services/metric_provider.py`：Native、Shadow、VictoriaMetrics Provider、Canonical Metrics、Counter Wrap 和 Shadow Compare。
- `backend/services/collector_artifact_service.py`：Current/Previous、Last Known Good、原子发布和回滚。
- `backend/services/monitoring_health_service.py`：Collection Health 和错误分类。
- `backend/api/monitoring_v1.py`：Module/Variant、Plan、Collector、Assignment、Artifact、Metrics、Collection Health、Shadow Compare API，含 RBAC、租户隔离和审计。
- 现有 Collection Plan 已支持 `devices.collection_policy_json.monitoring` 扩展。

### Frontend

- `/monitor/collection-plans`：Plan 创建、JSON 配置、编译测试。
- `/monitor/modules`：Module/Variant 创建、测试、发布、校验。
- `/monitor/collectors`：Collector 创建、测试、编译、校验、发布、回滚。
- `/monitor/collection-health`：Assignment 健康率、状态和错误明细。
- 新增入口图标：采集计划 `Layers3`、模块目录 `Boxes`、采集器管理 `CloudCog`、采集健康 `Gauge`。
- Network Monitoring 支持 Native / Shadow / VictoriaMetrics 切换。

### Docker Compose

已加入固定版本服务：

```text
victoriametrics/victoria-metrics:v1.103.0
victoriametrics/vmagent:v1.103.0
prom/snmp-exporter:v0.26.0
```

已配置 VM 持久化、vmagent disk queue、Remote Write、健康检查、Generic IF-MIB/System Module 和 `/etc/nexora-collector` Target Snapshot 路径。

## 验证证据

```text
pytest -q backend/tests -k "monitor or snmp or alert or probe" 162 passed
pytest -q backend/tests/vendor_audit/test_collection_plan_service.py backend/tests/vendor_audit/test_collection_plan_bulk_api.py 46 passed
pytest -q backend/tests/database/test_m0232_monitoring_v1.py 1 passed
pytest -q backend/tests/monitoring 64 passed
npx vitest run --config vitest.config.ts src/utils/routeContext.test.ts 8 passed
npm run lint PASS
npm run build PASS
python scripts/validate_postgresql_only.py PASS / 0 violations
python scripts/monitoring_poc_preflight.py PASS（静态配置）
```

## 现场验收阻塞

当前工作主机没有 Docker CLI，且没有 H3C/Huawei/Cisco 实验设备，因此尚未执行真实 Docker runtime、设备矩阵、vmagent 断链补传和 300 台压测。强制预检结果为：

```text
python scripts/monitoring_poc_preflight.py --require-runtime
Docker CLI not found (exit 2)
```

## 下一步

1. 在 Docker 验收机执行 `python scripts/monitoring_poc_preflight.py --require-runtime`。
2. 执行 `docker compose up -d`，确认 db、redis、netops、VictoriaMetrics、vmagent、snmp_exporter、nginx 健康。
3. 导入 POC CMDB 设备和 SNMPv2c/v3 Credential Binding，执行 Collector compile → validate → publish。
4. 按方案执行 GATE-01～GATE-18，全部通过后再将 `MONITORING_METRIC_BACKEND` 从 `native` 切换为 `shadow`，最后切到 `victoriametrics`。

## 安全与回滚

- Target Snapshot 只保存 opaque `auth_<hash>`，不保存 community/password。
- Artifact 校验或编译失败不得覆盖 Last Known Good。
- 保留 Native Provider 和旧配置版本，现场失败时回滚到上一版本。
- `.env`、真实凭据和 `.tmp/` 不应提交。

## 2026-09-25 Grafana 会话与接口流量断点排查

- 发布提交 `0a8a96d3e5a14abf289503cc3510b0a54db7b653` 已推送至 `origin/main`；远端 `v1.0.9` 已按用户授权强制更新，annotated tag peeled commit 与该提交一致。标签推送触发 `.github/workflows/release.yml`，工作流结果尚未检查。
- Grafana 重复 `/grafana` 的浏览器根因：普通窗口禁用缓存仍复现，无痕正常，删除浏览器的原生 `grafana_session` 后恢复。Nexora 专用 `nexora_grafana_session` 应保留。仓库改动已调整 Grafana 子路径代理并在 Nginx 上游剥离浏览器 Cookie，同时让内部鉴权子请求单独校验 Nexora 会话；这批 Cookie 隔离改动尚未在服务器部署验证。
- 接口流量图缺样：vmagent 曾报告 R3/R4 `generic_ifmib_interface_std` 采集因 SNMP exporter 请求超时返回 HTTP 500；后续人工探测两台设备都曾返回 HTTP 200，说明故障间歇发生。
- 近 30 分钟 VictoriaMetrics range 查询中，`topk(10, ...)` 与去掉 `topk` 的 PromQL 输出缺样时间完全一致，并同时影响所有接口及入/出方向：R3 两段 90 秒间隔；R4 多段 90–150 秒间隔。原始计数器中也存在同步采集间隔。结论：断点来自 SNMP 目标采集不连续，不是 `topk` 截断；设备响应耗时、SNMP exporter 超时与模块轮询负载仍待进一步定位，尚未修复。
- 后续：本地 Cookie 隔离改动需在服务器部署验证；SNMP 断点需另行检查各轮 scrape 错误时间、exporter 日志及设备响应。此次发布工作流仍在远端异步运行，不能从本地 ref 核验推断 CI/制品发布成功。

## 2026-09-25 Grafana Dashboard 方案 A

- 状态：本地实现与静态核对已完成。方案细节见 `docs/plans/plan_20260925_2323_01_Grafana方案A视觉优化.md` 和 `docs/walkthrough/walkthrough_20260925_2323_01_Grafana方案A视觉优化.md`。
- 生成器更新并生成 9 份 JSON，包括新增接口详情页 `nexora-interface-detail.json`。接口状态码 `1/2` 显示绿色 `Up` / 红色 `down`，`0`、`3–7`、空值和 NaN 显示灰色 `UNKNOWN`。
- CMDB interface role/阈值契约、Monitor V1 metric relabel、IF-MIB 高容量包计数器和 `ifLastChange` 采集已接入；详情页按接口 profile 阈值计算动态状态。
- CMDB 接口列表/更新使用 asset tenant/site scope；没有持久化 skeleton 主键的 IP 库合成行不可编辑。详情页 `ifAlias` join 使用不含接口过滤标签的设备 selector。
- 验证：Python 编译、生成器运行、9 份 JSON 结构与面板网格检查、SNMP YAML/metric relabel 静态检查、`git diff --check` 均通过。当时未运行测试套件；本次合并复核补跑迁移和快照隔离的隔离 PostgreSQL 用例（2 passed）。未应用数据库迁移、未部署 Grafana 或连接真实设备。
- 遗留验收：Grafana 12.1.0 页面实际渲染、部署后 PromQL 结果、CMDB 迁移及 vmagent runtime 行为尚未验证。04 多接口 Gauge 使用平台默认阈值；单接口详情状态使用 CMDB 配置阈值。Last Change 年龄需要同设备 `sysUpTime`，默认基线包括 system 模块。

## 2026-09-26 S3 存储排查与配置说明

- 已审查对象存储配置/连接测试、默认存储解析、config 快照及 PAM 录像的上传、读取、重试和删除路径。
- 修复 S3 `NoSuchBucket` 被误归类为对象缺失的问题；对象下载/元数据查询现在将缺 Bucket 作为存储错误，并在 S3 操作错误中保留安全的错误码和 HTTP 状态摘要。
- 配置快照对象读取失败现在写入安全诊断日志；查看/下载 API 对确实缺失的对象返回 404，对存储不可用返回 503，不再静默返回空内容。
- 前端用途说明标明默认 Bucket 的 `config/` 与 `pam/` 前缀、知识库尚未接入、Bucket 需预先创建；固定 S3 类型改为静态文本，Endpoint 增加 S3 API 地址提示。
- 验证：存储模块独立测试 15 passed；修改的 Python 文件编译通过；`npm run lint` 和 `git diff --check` 通过。常规 pytest 全局初始化受工作区待迁移版本 253 阻挡；未对真实 SeaweedFS 做上传/读取验证。
- 只读复核 `docker-compose.yml` 确认 netops 的 `NO_PROXY`/`no_proxy` 已包含 SeaweedFS 服务别名；endpoint 路径仍开放以兼容路径前缀反代，前端提示不应把 Bucket 和业务目录作为 URL 路径。
- 上述 S3 修改当时未提交或推送；已纳入 2026-09-26 当前 `main` 工作区的统一复核、提交和推送。

## 2026-09-26 当前工作区统一复核

- m0253 原先会覆盖非空内置 IF-MIB 配置；现改为对空配置完整 seed、对非空配置只追加缺失的 `ifLastChange`，保留已有 OID/metrics 并重算 JSON hash。新增隔离 PostgreSQL 回归覆盖运维编辑保留、hash 更新和幂等。
- `ifLastChange` 是只读 SNMP GET 采集目录项；没有执行 SNMP SET 或修改真实设备配置。
- 配置快照内容/下载加入 asset tenant/site scope，越权访问返回与不存在 ID 相同的 404；新隔离 PostgreSQL 用例验证跨租户拒绝。
- Grafana PPS 图现显示入向、出向、单播、组播、广播 5 类曲线。PPS 使用已有 Counter64 `ifHC*Pkts` 指标；设备不暴露该指标族时显示无数据。
- 验证：隔离 PostgreSQL 用例 2 passed；存储服务聚焦用例 15 passed；Python 编译、Grafana 生成与 JSON 静态检查、SNMP YAML 解析、`npm run lint`、PostgreSQL-only 扫描、`git diff --check` 均通过。隔离 PG 服务在本次运行前有 13 个既存 `nexora_pytest_*` 测试库；本次运行新增残留为 0，既存库未触碰。
- 未应用数据库迁移，未做 Grafana 在线渲染/PromQL、真实设备采集或真实 S3 上传下载。PPS 缺少 Counter64 计数器时无数据。
- 当前 `main` 改动已完成最终暂存审查，并按用户授权统一提交、推送至 `origin/main`。

## 2026-09-26 Grafana 九个看板重复核查与接口流量修复

- 逐一检查全部 9 个实时看板，并对无数据项和关键查询重复执行只读 Explore 验证。详细记录在 docs/plans/plan_20260926_1105_01_Grafana接口流量与状态排查.md 与对应 walkthrough。
- 设备下拉旧名称的原因已确认：当前 live 变量仍通过历史 ifOperStatus|up 时序的 label_values 拉取 hostname。重开 04 展开后仍有 23 个选项，包括 F1090-10、R10/R11/R12/R13/R14。新生成的变量用当前 up 目标分组查询，重复验证得到 13 个当前 SNMP 目标且不含这些旧名。Grafana 未 reload 本地生成物，本次没有更改运行实例。
- 04 实时流量卡和趋势仍显示数据暂不可用；面板 422 细节确认 SW6/Gi0/3/TO-R4 的 group_left 右侧同一 ifName 序列因 interface_role/利用率阈值标签有无形成重复。生成源已聚合 join 元数据；修正查询在 Explore 返回流量样本。
- 01 状态条件改成管理启用且运行状态明确 DOWN，并解释统计的是当前状态；接口角色显示“接口用途”，unclassified 显示“用途待确认”。03 无线面板缺指标时不再回退为 0。
- 采集端当前无网络设备 CPU、内存、温度和无线指标样本。05 失败数为 0 与在线状态一致；06 选择有效的 R1/Et0/0 后各流量面板有数据；02、08 与 09 的其余主要数据按计划显示。
- D07 与 D09 表格首次观察只见表头；重复打开后 D07 显示 3 个挂载点，D09 显示 R1/Et0/0 带宽 10 Mb/s，未复现持续缺数。首次未呈现的瞬时原因不能从只读页面确认。
- 改动：monitoring/grafana/generate_dashboards.py、9 份 monitoring/grafana/dashboards/nexora-*.json、backend/tests/monitoring/test_domestic_and_wireless_monitoring.py，以及本次 plan/walkthrough。
- 验证：聚焦 pytest 6 passed；Python 编译与 dashboard generator 通过；git diff --check 通过。没有保存、reload、部署或发布 live Grafana。
- 下步：待 Grafana 实例采用本次生成 JSON 后，再在 live 04 重验变量选项与流量面板，并确认新中文标签及 01 状态说明生效。

## 2026-09-26 设备与接口看板参考样式及光模块支持核查

- 02 设备详情把 CPU/内存当前值改为所选设备各实体中的最高值 Gauge；最高温度卡取消跨设备通用温度阈值。04 接口看板新增过去 5 分钟平均入向/出向速率 Top10 Bar gauge，原利用率表与质量/状态面板保留并重排。
- 光模块：LibreNMS 的当前 Comware 发现配置未定义 H3C Rx/Tx 功率传感器，`mibs/h3c/HH3C-TRANSCEIVER-INFO-MIB` 路径未找到。H3C 厂商文档存在对应 MIB/OID，但用户要求以 LibreNMS 支持为准，因此没有添加 SNMP exporter 指标、CLI 采集或 Grafana 面板。
- 验证：生成器和 Python 编译通过；9 份 dashboard JSON 结构/ID/网格/datasource 校验通过；02 Gauge 与 04 Top10 查询契约验证通过；`git diff --check` 通过（保留既有 handoff 行尾警告）。
- Live Grafana 只读仍显示旧 01 总览：硬件平均图无数据，稳定 Down 计数仍是 216；本地生成文件尚未 reload/deploy。本次未写入 Grafana，也未操作设备。
- 当前修改文件包括 `monitoring/grafana/generate_dashboards.py`、设备和接口 dashboard JSON，以及 plan/walkthrough：`docs/plans/plan_20260926_1315_01_设备与接口看板参考样式.md`、`docs/walkthrough/walkthrough_20260926_1315_01_设备与接口看板参考样式.md`。

## 2026-09-27 Grafana 九个看板深度复核

- 范围：只读核对 9 份 provisioned Grafana JSON、生成器、SNMP OID/采集器契约、Grafana 访问链及相关监控数据表；本轮未改 dashboard 或业务代码。
- 静态健康：9/9 JSON 均与生成器内存输出相等，panel ID/变量名无重复；SNMP catalog 与 Linux/Windows exporter 指标引用未发现拼写缺项。当前 admin/oper 状态表的 1=绿色 Up、2=红色 down 背景填充符合预期。
- 高风险待处理：SNMP/服务器目标携带 `tenant_id`，但 9 个 dashboard 查询均无 tenant selector；Grafana session/auth proxy 对 Viewer 开放且共用 VictoriaMetrics datasource。多租户下存在跨租户指标可见性风险。单纯加入可编辑 dashboard 变量不能形成安全隔离；需要 datasource/proxy 级租户约束，或先限制到全局受信角色。
- 其他复核发现：Linux/Windows 多处按 hostname 聚合并丢弃 site_name；健康/主机资源摘要用 `or vector(0)` 混淆无数据与真实零；ifOperStatus 的 testing/dormant/notPresent/lowerLayerDown 被映射为 UNKNOWN；Outbound 固定阈值与 CMDB profile 阈值可能冲突；Windows“关键服务”查询目前覆盖全部服务。`filtered_interface_join` 的多重名称/描述冲突及无线在线 AP 大于总量导致负离线数仍缺真实数据验证。表格 unit override 的 rename 后匹配也需 Grafana 12.1 页面确认。
- 验证：`.venv` 下 dashboard/无线测试 6 passed，编译/部署契约测试 6 passed；Agent 运行网络 dashboard + compiler 聚焦测试 28 passed；9/9 generator sync、SNMP metric selector 静态匹配及 `git diff --check` 通过。
- 未验证：本机没有可用 Docker/promtool，localhost VictoriaMetrics/Grafana 不可访问；未执行实时 PromQL、Grafana 页面渲染、真实设备采集。
- 后续建议：优先定义并实施 Grafana 租户隔离；新看板优先考虑设备风扇/电源/部件健康（现有 OID 有数据但厂商覆盖有限），以及 WAN 链路 SLA/容量（现有 PostgreSQL 样本、coverage、P95 基线和事件可用，但当前 Grafana 只有 VictoriaMetrics datasource）。
- 05“SNMP 在线目标”此前发现过把 `up=0` 失败目标计为在线的缺陷；当前生成器和生成 JSON 已使用 `up == 1` 后再计数，失败目标卡片使用 `up == 0`，静态查询语义已修正，仍需随部署版本在 Grafana 页面验证。

## 2026-09-27 新增 10–12 监控大盘与运行时验收

- 新增 `GET /metrics` 内部聚合导出，供 collector-local 抓取 API/数据库连接、出口拨测、告警生命周期、通知投递和 outbox 指标；不导出租户、设备、目标、地址、告警正文或收件人标签。WAN 查询复用有时间索引的每轮汇总样本，导出语义限于系统级出口拨测质量。
- vmagent 运行时编译器仅对 `collector-local` 添加 API、VictoriaMetrics、vmagent、SNMP exporter 和 Grafana scrape jobs；静态样例与编译产物一致，远端 collector 不包含这些服务 DNS。
- 新增 10 监控平台健康、11 互联网拨测质量、12 告警运营与通知有效性三个 Grafana dashboard，并在 Nexora dashboard 选择器新增入口。探测耗时不代表 ICMP RTT；本轮没有实现线路绑定 SLA、真实丢包或抖动。
- Agent 分工：metrics router 与 dashboard builders 分别独立实现；coordinator 完成 `main.py`/运行时 compiler 接入、验证、生成与审查。
- 验证：后端编译、vmagent 静态/运行时配置对比、12 份 dashboard JSON 与生成器同步/唯一 panel ID/VictoriaMetrics UID 检查、26 个聚焦 pytest 和 `npm run lint` 均通过；`git diff --check` 仅保留既有 CRLF 转换提醒。
- 运行时：已用浏览器复验并保留 `https://192.168.204.128/monitor/dashboards`。当前部署显示 `v1.0.9`、只有 01–08，仍有本地已删除的三个显示模式按钮；旧 04 流量图有实时值，但没有“接口管理与运行状态”面板。直达 `nexora-platform-health` 返回 `Dashboard not found`。Windows 环境没有 Docker CLI，WSL 无可用发行版，未执行容器重建/重启；新增看板等待目标部署更新后再做在线 smoke test。
- 后续边界：当前三个新看板只读聚合指标，无用户/租户下钻；真实链路 SLA 仍需按 WAN binding/source route 的探测采样。此前发现的既有 Grafana 多租户 datasource 隔离问题未纳入本次修改。

## 2026-09-27 本地逻辑验收边界补充

- 用户明确要求：新改代码目前只验证本地逻辑；等用户更新部署后再验证运行时。本轮不再对 Docker/部署页做新代码验收。
- 本地证据：聚焦 PostgreSQL 后端测试 44 passed，新增 P95 指标断言单测 1 passed；TypeScript lint 与独立目录 production build 成功；12/12 dashboard JSON 与生成器一致；Compose/vmagent 静态核对、PostgreSQL-only 扫描（0 violations）及 `git diff --check` 通过。
- 浏览器此前看到的部署是更新前 `v1.0.9`，仅作为基线；它没有新大盘或新接口状态面板，不能作为新代码运行时通过/失败的证据。待用户更新后再对部署版做 smoke check。
- pytest session fixture 在本地 source PostgreSQL 上应用了待执行的 migrations 0257–0259；其中 0257/0259 是工作区既有的告警租户/通知变更，可能已调整 source DB 告警规则或通知配置数据。本轮没有回滚。

## 2026-09-27 监控平台全量容器指标排查

- 大盘六行是六个 `platform_*` scrape 端点，不是 Docker 容器总数。已将 cAdvisor CPU/内存/磁盘指标查询改为按全部非空容器名聚合，并新增 `container_last_seen` 容器观测数/清单；观测不等价于容器健康状态。
- 用户现场输出确认 vmagent 访问 `grafana:3000/metrics` 被转发到 `192.168.31.253:10808` 后返回 502；Compose 现清空 vmagent/cAdvisor 代理变量并设置内网 `NO_PROXY`。cAdvisor 重启的高概率原因是 `--disable_metrics` 带有 v0.60.6 不支持的 `accelerator` 值，已移除，仍需部署后验证。
- VictoriaMetrics 固定 v1.103.0；`vm_total_disk_space_bytes` 从 v1.124.0 才引入，存储面板改为已用数据量 `sum(vm_data_size_bytes)`，不再显示虚假的空间占用率。
- 聚焦部署契约测试 7 passed；12 份 dashboard JSON 解析和目标生成同步检查通过；`git diff --check` 通过。监控目录全套测试运行约 38% 后中止，不计为通过。
- 未更新或重启目标机容器，也未在线写入 Grafana。部署后应验证 Grafana/cAdvisor scrape 状态、cAdvisor 容器资源时序和动态清单数量；详情见 `docs/plans/plan_20260927_2013_01_监控平台容器指标全量采集.md` 与对应 walkthrough。
