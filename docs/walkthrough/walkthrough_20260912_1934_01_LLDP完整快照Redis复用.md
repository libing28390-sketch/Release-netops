# LLDP 完整快照 Redis 复用 — 走查记录

## 完成摘要

- 将周期拓扑采集的完整 per-device LLDP 快照接入 IP Locator：PostgreSQL 保存权威邻居事实和采集 generation；成功提交后向 Redis 发布 generation-qualified snapshot key；Redis miss 时定位器从同 generation 的 PostgreSQL 事实重建并回填，不再仅因 locator 自己没有 neighbor observation 就回源 CLI。
- 采集开始即递增设备 generation 并标为 `collecting`，使旧 key 立即失效；成功正快照和明确成功空快照原子完成；解析失败、截断、命令失败、过期 worker 不会把邻居清空或发布负快照。
- IP Locator 默认 LLDP/topology freshness 与拓扑图 48 小时证据 TTL 对齐；`.env.example` 明确为 172800 秒新鲜、259200 秒 Redis physical retain。超过 48 小时的 key 即使仍保留也不会被当作新鲜数据。
- 已用真实配置 Redis 对隔离 PostgreSQL 生成的合成 LLDP 快照完成发布、GET 读回和删除验证。测试结束确认临时 key 已清理；没有采集真实设备或部署应用。

## 实际修改文件

- `backend/database/migrations/m0227_topology_lldp_snapshot_fence.py`
- `backend/services/topology_lldp_snapshot_service.py`
- `backend/services/topology_service.py`
- `backend/services/neighbor_collection_contract.py`
- `backend/services/ip_locator_trace_service.py`
- `backend/services/ip_locator_task_service.py`
- `backend/core/config.py`
- `.env.example`
- `docs/deploy/docker.md`
- `backend/tests/database/test_m0227_topology_lldp_snapshot_fence.py`
- `backend/tests/ip_locator/test_topology_lldp_snapshot_service.py`
- `backend/tests/ip_locator/test_task_coordination.py`
- `backend/tests/ip_locator/test_trace_service.py`
- `backend/tests/platform_registry/test_consumer_registry_paths.py`
- `backend/tests/topology/test_topology_lldp_snapshot.py`
- `backend/tests/vendor_audit/test_lldp_collection_contract.py`
- `docs/plans/plan_20260912_1934_01_LLDP完整快照Redis复用.md`
- `docs/walkthrough/walkthrough_20260912_1934_01_LLDP完整快照Redis复用.md`

本地 ignored 文件 `backend/tests/test_topology_offline_skip.py` 也更新了测试夹具：显式填入平台、返回 `no_neighbors` 完整状态，并 mock Redis publisher；该文件被 `.gitignore` 的 `backend/tests/*.py` 规则忽略，不会进入 Git 跟踪。

## 关键实现

1. PostgreSQL 增量迁移 m0227 新建 `topology_device_lldp_snapshots`，记录设备代次、状态、完整性、观察数和命令/parser/schema 指纹。
2. 所有 `discover_device_neighbors()` 入口在设备 I/O 前开始 generation attempt；只有 token 仍为当前代次才可在写 `topology_observations` 的同一事务内完成快照。迟到 worker 被拒绝；失败状态使旧缓存不可读，但保留上次 PostgreSQL topology observation。
3. 命令结果经 `classify_lldp_status` 区分成功、明确无邻居、解析失败、命令不支持/失败和分页截断。只有 `success/no_neighbors` 可发布 complete snapshot；命令无异常但 parser miss 不再等同于空拓扑。
4. Redis key 以 device/site scope 和 generation 分区，payload 只包含规范化 neighbor 字段、采集时间、generation 与版本指纹，不含 raw CLI 或凭据。成功 collection 在 PG commit 后预热 Redis；日志通过 `event=lldp_snapshot_publish ... status=confirmed` 表示 Redis SET 获确认。locator 每次先读 PG generation fence，再读取 Redis；miss/eviction 从 PG observations 重建并回填。
5. Locator 将被使用的每设备 generation 写入 run dependency manifest；run 完成事务重验当前 marker，期间如果开始了新扫描/失败/代次变化，结果会降为 partial。强制刷新绕过 snapshot cache。普通定位时若端口已有强 access/terminal 证据且无拓扑邻居，则不为了再次证明“无邻居”而执行 LLDP CLI。

## 验证命令与结果

- PostgreSQL snapshot service、空/正快照、generation fence、topology offline fixture 与 LLDP 合约定向回归：`14 passed, 1 skipped`；skip 为需要显式 Redis 授权的 opt-in 用例。
- IP Locator trace 与 platform registry collector：`41 passed`（`--noconftest` 纯 mock 回归）。共享 LLDP Redis 命中断言来源为 Redis、`queried_devices.lldp` 为空，CLI mock 若被调用即失败；强制刷新分支另有测试验证仍走 CLI。
- Locator cache/API scope/task coordination 并行回归：`59 passed, 2 deselected`。
- 拓扑/LLDP/邻居筛选并行回归：`114 passed, 1 skipped, 2479 deselected`。skip 是下面单独执行的真实 Redis opt-in 测试。
- 迁移与在线/离线拓扑定向回归：`4 passed`；m0227 覆盖重复升级、PostgreSQL 列类型/默认值、约束和外键级联。
- 真实 Redis opt-in：`NETOPS_VERIFY_LIVE_REDIS=1 pytest backend/tests/ip_locator/test_topology_lldp_snapshot_service.py::test_published_snapshot_round_trips_through_configured_redis -q --tb=short`：`1 passed in 65.54s`。测试使用隔离 PG 中的合成 LLDP 观察，经真实配置 Redis adapter 写入；GET 确认 generation/neighbor 内容与 PG 一致，`finally` 断言临时 key 删除成功。
- 单独 adapter sentinel `SET/GET/DEL` round-trip：Redis available、写入确认、读回匹配、删除成功、删除后不存在；只输出布尔结果，不输出 Redis URL/凭据。
- `scripts/validate_postgresql_only.py`：0 violation(s)，PASS。Python `py_compile` 通过；限定文件 `git diff --check` 通过（仅有仓库 CRLF 转换提示，无空白错误）。

## 未执行验证及原因

- 首次 Chrome 访问 `http://192.168.96.1:5400/ipam/locate` 时返回 `ERR_CONNECTION_REFUSED`；确认 `192.168.96.1` 是本机 VMware Host-Only 地址，且当时 5310/5400 没有监听。随后启动本机 Vite `:5400` 与 FastAPI `:5310`（`--lifespan off`，未启动 APScheduler，也未触发自动拓扑采集/迁移）；最终 Vite 仅绑定 `192.168.96.1:5400`，API 仅绑定 `127.0.0.1:5310`。`/api/health` 返回 HTTP 200、database=connected、scheduler=stopped、overall status=degraded。
- 浏览器可访问性读取和用户截图均显示已登录 `admin`，`172.16.5.10` 定位成功：MAC `8e47-5760-0706`，接入 `S6850-5 GE1/0/2`，VLAN 7，页面上下文包含网段、网关、VRF、接口状态及业务信息。持久 run `locator-run:7c7f4af106bd4517959e5c4e7901d508` 状态为 `completed`；其 `result.cache` 记录 `route=cli, arp=cli, mac=cli, result=miss`，且 `queried_devices.lldp=[]`。因此这次页面成功不能作为“本次命中 Redis”或“本次读取 LLDP Redis 快照”的证据。
- 本次 CLI 路由查询后确实向当前 scope 的 Redis 写入了 3 个 route payload（设备 `S6850-2`、`S6850-1`、`S6850-5`；各含 2 条记录）；读取时 Redis PING `available=true`，键剩余物理 TTL 约 1260 秒，payload 年龄约 532–539 秒。当前 route fresh 阈值为 300 秒，所以这些键虽仍物理保留，已不应作为新鲜路由复用。这解释了该 run 的 CLI source，并不代表 Redis SET 失败。
- LLDP 专用缓存仍未有真实快照：当前配置 Redis 中 `nexora:production:locator:v1:topology_snapshot:*` 为 0 个键；当前 `netops` PostgreSQL 的 m0227 表存在，但 complete snapshot 标记为 0。此前合成 snapshot 的真实 Redis round-trip 测试证明 publisher 写入能力，不证明设备 LLDP 事实已发布。
- 页面时间差已定位：同一 run 的 `result_json.timestamp=2026-09-12T13:22:31+00:00` 与 `context.freshness.collected_at=2026-09-12T21:22:31+08:00` 表示同一时刻。`src/pages/IPLocatorPage.tsx` 成功横幅直接对 timestamp 执行 `.replace('T', ' ').slice(0, 19)`，截掉 UTC 标记而未转换；上下文 `formatExactTime()` 使用 `Date` + `Intl.DateTimeFormat` 转成本机时区，所以显示差 8 小时。截图页同样复现；尚未修复。
- Computer Use Windows helper 仍因无法可靠确认 Chrome 当前 URL 而在输入前停止；本次定位结果由浏览器可访问性读取、用户截图和持久 run 只读核验，未由我重新提交。
- 未触发拓扑手工采集、连接网络设备或将真实 LLDP 邻居写入 Redis；本轮未主动执行 m0227 或部署应用（只读检查发现当前 `netops` 数据库中的 m0227 表已存在）。迁移的完整升级/约束验证仍是在隔离 PostgreSQL 完成。
- 后端全量 `pytest backend/tests` 已由回归子进程启动；最近报告进度 41%、暂无失败输出，尚无最终汇总，不能算通过。此前定向拓扑/LLDP/邻居与 locator/task/migration 回归已通过；前端全量 254 项及 lint 通过。

## 交付后的实际启用条件与风险

- 新 migration 应随应用启动/发布应用到目标数据库；之后下一次成功的完整拓扑 LLDP 采集会把真实设备快照发布 Redis。旧 PG topology_links 的正邻接在 48 小时 freshness 内已可复用；因为旧版 collection 没有可靠 complete-generation marker，迁移不会把旧空结果伪装成可信空快照。
- 当前工作树生效 freshness 为 172800 秒、retain 为 259200 秒；若部署 `.env` 显式覆写 `IP_LOCATOR_TOPOLOGY_FRESH_SECONDS` / `IP_LOCATOR_TOPOLOGY_RETAIN_SECONDS`，需要同步改为不短于采集周期/TTL 的配置。读取当前本地 Settings 的值为 172800 / 259200。
- 真实 Redis 验证仅写入并删除带唯一设备 scope 的测试 key；没有保留临时 Redis key，也没有更改 Redis ACL 或 `MONITOR` 权限。

## 最新收尾核验（2026-09-12）

- 为避免 `cache.route/arp/mac` 的多设备 last-writer 单值掩盖混合来源，trace 响应新增兼容字段 `cache_provenance`，按阶段、设备、VRF、variant 记录 Redis/PostgreSQL/CLI 来源和已尝试 Redis SET 的 ACK；整体结果 Redis 命中/写入也纳入来源记录。`cache.backend=postgres` 时不再错误标成 Redis SET 尝试。旧 `cache` 汇总保留，避免破坏既有消费者。
- 修复 whole-result Redis 命中分支浅拷贝嵌套字典导致污染缓存对象的问题；ARP 正向 CLI 回源明确初始化并记录本次目标 key 的 SET ACK，避免沿用前一阶段写入状态或触发未初始化局部变量。
- 定向 trace 全文件回归（最新代码）：`.venv\Scripts\python.exe -m pytest backend/tests/ip_locator/test_trace_service.py -q --tb=short`，`33 passed`；新增分支确认 CLI 回源会记录 SET ACK，而 Redis 命中保留 Redis 来源且不伪报本次发生 SET。前端子进程 `npm run lint` 通过，`npm run test:frontend -- --run` 为 `65` 个测试文件、`254 passed`；隔离目录 `npm run build -- --outDir <临时目录>` 构建通过。
- Redis MONITOR 时间格式器回归：`.venv\Scripts\python.exe -m pytest backend/tests/release/test_redis_monitor_formatter.py -q --tb=short`，`3 passed`；策略扫描 `python scripts/validate_postgresql_only.py` 为 `0 violation(s)`，Python `py_compile` 和限定文件 `git diff --check` 通过。
- 全后端子进程完整运行结果为 `2584 passed, 9 failed, 1 skipped, 26 subtests passed`。其中 5 项 mock-driver 用例随后改为注入 no-op shared-lease adapter，定向复跑 74 项通过；PostgreSQL lease 集成 11 项通过。修正后没有重跑完整 51 分钟套件，故全量门禁仍记为未全绿。余下失败涉及 health API 401、IPAM fixture 缺 `ip.device_id`、两个 terminal-agent 配置/允许来源断言。
- 当前 Chrome 可访问已登录 `admin` 的 `/ipam/locate` 标签，但页面处于刚加载的空表单状态；此前已完成的持久 run `locator-run:fae7c6c2d28e4f73824a98b552b13e94` 有 `cache.route=redis`、`cache.result=miss`，说明 Redis 被用于路由证据读取，但整体定位结果未命中 Redis。新增逐设备来源字段尚未通过这次空表单页面重新提交进行 UI 现场展示；不将之前的截图误当作新字段的验收证据。
- 时间偏差仍是显示格式问题：`13:22:31+00:00` 与 `21:22:31+08:00` 是同一时刻，横幅截掉了 UTC offset，而详情按本地时区格式化；本轮没有修改该时间显示。
- 状态徽标修正：有逐阶段来源时展示 Redis/PostgreSQL/CLI 的事实来源；只有显式 `force_refresh` 才提示“已请求强制实时刷新”；旧结果没有来源字段时显示“采集来源未记录”，不再因缓存标志缺失而默认宣称实时。常规查询保持新鲜度校验后的缓存优先，用户可用“实时刷新”主动要求绕过缓存；本轮未通过浏览器现场重新提交验证新文案。
- 运行态拓扑复核（只读）：PostgreSQL m0227 marker 表有 0 条记录，仍有 42 条旧 active LLDP observations（不能证明其为完整快照）；Redis 健康，但 `{namespace}:topology_snapshot:*` 为 0。启用的 NSOT job 当前 cron 是每天 02:00、run_count=0、last_run 为空；本地 API 以 `--lifespan off` 启动，APScheduler 未运行。未启动调度、手动拓扑发现或设备采集。
- 额外发现的运维观测缺口：周期 gather 会收集异常对象但当前 workflow 未据此汇总逐设备失败，可能把部分设备失败的周期任务记为 success；拓扑状态接口仍报告旧 job_id/interval，与当前 NSOT cron 不一致。真实快照必须在授权设备环境成功采集后，再核验每设备 marker 和对应 generation Redis key；健康 PING 或定时任务 success 不能代替该验证。
- 定位页来源徽标更新后，尝试再次只读检查 Chrome 页面；`mcp__cua_repl.getState()` 连续两次返回 `Unable to load browser request-header policy`，未能验证当前浏览器中的最终文案，也未提交新的定位请求。该项仍待浏览器工具恢复后验收。
- 随后浏览器可读检查恢复，当前截图对应的 run `locator-run:1ed09bc2b5764d37b6377c2b6687be09` 已持久化；`cache_provenance` 为 SQL NULL，旧汇总为 `route=postgres / arp=cli / mac=postgres / result=miss`。因此“采集来源未记录”是因为当前运行后端写入的 run JSON 没有新来源字段，并非页面断言所有证据都为实时；本次实际来源为 PostgreSQL 与 CLI 混合。用户将自行重启服务，重启后再提交同一 IP 核验字段是否持久化，主 Agent 不重启服务。

## 连续定位仍未命中 Redis 的根因与修复

- 新进程的浏览器 run `locator-run:5ccdc46b2ee043c9b0c709b343c2fd8b` 在 23:36:36+08 完成；route/ARP/MAC 均为 CLI 且 Redis `SET` ACK 为 true。对应 `fact_changed` outbox 事件在 23:36:43–23:36:53 创建，却在 23:37:26 才处理。
- 下一 run `locator-run:f31a2800a0a0415dbc066fa11380423d` 于 23:37:41 查询相同 scope/目标；Redis 路由键已被 outbox 的宽前缀删除，因此 route 与 MAC 转为 PostgreSQL 复用，ARP 再 CLI 回源。两次 run 的 authorized device count/hash 和缓存 scope 相同；不是 scope mismatch。Redis PING healthy，outbox 最终均 processed。
- 根因：`services/ip_locator_invalidation_service.py` 在新 observation 的 SET ACK 之后处理 outbox，并按整个 scope 删除 route/ARP/MAC/topology 事实键，异步失效把刚发布的当前 generation 一并删掉。现已改为 outbox 只删除可能过期的整体结果键；事实缓存由 pending-outbox gate、PostgreSQL observation generation、pipeline version 及 LLDP marker 检验决定是否可读，避免异步宽删竞争。旧事实键若 generation/version 不匹配仍会被读取校验拒绝并重写，TTL 负责最终回收。
- 当次只读扫描还观察到 route logical fresh=300 秒、物理 retain=1800 秒；超过 5 分钟后，即使 Redis key 仍存在也应回 PG/CLI，不能当作 Redis hit。修复后需在 fresh 数据写入后 5 分钟内重复定位，验证应有 route/ARP/MAC Redis source；当前用户服务进程仍需加载本轮 outbox 修复后再验收。
- `backend/tests/ip_locator/test_invalidation_worker.py`：`4 passed`，新增回归确认 outbox 清理结果键但保留 generation-fenced route key；locator trace 全文件 `33 passed`。浏览器截图中 `PostgreSQL 复用 + CLI 采集来源 + 整体结果未命中 + Redis 写入已确认` 表示 read-through/write-through，不是 Redis read hit。
- 另一独立收尾项：周期拓扑汇总现在报告逐设备 snapshot complete 与 Redis publish ACK；`success/no_neighbors` 且 Redis 写入确认才算 complete，异常/跳过/未确认写入归为 partial。`backend/tests/topology/test_topology_scheduler_outcome.py` 为 `4 passed`，没有启动调度或采集设备。
