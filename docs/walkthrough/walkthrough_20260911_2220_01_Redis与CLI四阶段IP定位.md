# Redis 与 CLI 四阶段 IP 定位 — 完成记录

## 完成摘要

交付范围说明：下面记录已实现主链路，不表示实施方案所有验收项完成。2026-09-12 最新定向后端 140 项、拓扑 98 项、前端 254 项及生产构建已通过；全后端回归进程在约 39% 以退出码 1 结束，没有 pytest 汇总/失败项。特殊网络域适配、周期维护和容量/现场验收仍有剩余项，详见计划第 14 节。

已按计划实现默认使用的新 IP 定位链路：从核心设备逐跳查询目标路由，直到 Direct 三层终结设备；随后只在网关候选上查询目标 ARP，再沿目标 MAC 的已知拓扑分支逐跳查询，最终仅在具备 Access、Edge、Untagged 等接口证据时确认最末纳管接入点。

定位链路使用 SSH/CLI，不调用 SNMP。Redis 是带 namespace、短超时和熔断的可重建共享缓存；PostgreSQL 保存运行、查询任务、租约、观测、历史和失效 outbox。每条 trace CLI 查询都经 PostgreSQL query-task 去重与设备/部署并发租约协调；进程内按设备复用 SSH 会话，空闲 15 秒后关闭。任务取消、租约续期、迟到结果 fencing 和敏感 CLI 原始输出保留清理均有实现与回归。Redis 不可用时，缓存读取和任务处理仍可降级到 PostgreSQL。

IP 定位直接默认使用新流程，部署时无需添加启用变量；只要配置现有 `REDIS_URL` 即可使用 Redis。旧 `/api/ip-locator/locate` 通过兼容层返回现有页面所需字段；同时提供异步 run API 用于排队、轮询和取消。Redis 不可用时，缓存和任务仍按 PostgreSQL 路径工作。

## 实际修改文件

- .env.example
- backend/core/config.py
- backend/main.py
- backend/schemas/schemas.py
- backend/api/ip_locator.py
- backend/services/ip_locator_cache_service.py
- backend/services/ip_locator_trace_service.py
- backend/services/ip_locator_cli_service.py
- backend/services/ip_locator_session_pool.py
- backend/services/ip_locator_task_service.py
- backend/services/ip_locator_run_worker_service.py
- backend/services/operational_data_service.py
- backend/main.py
- backend/database/migrations/m0219_locator_v2_coordination.py
- backend/database/migrations/m0220_locator_run_deployment_scope.py
- backend/database/migrations/m0221_locator_global_access_slots.py
- backend/database/migrations/m0222_locator_run_leases.py
- backend/database/migrations/m0223_locator_query_task_retention.py
- backend/database/migrations/m0224_network_global_ssh_slots.py
- backend/database/migrations/m0225_locator_invalidation_lease_token.py
- backend/services/network_access_lease_service.py
- backend/services/ip_locator_invalidation_service.py
- backend/services/ip_locator_service.py
- backend/tests/ip_locator/test_invalidation_worker.py
- docker-compose.redis.yml
- scripts/deploy-docker.sh
- docs/deploy/windows.md
- docs/deploy/docker.md
- docs/deploy/docker-release-manual.md
- docs/deploy/README.md
- backend/tests/ipam/test_ip_locator_cache_service.py
- backend/tests/ip_locator/test_trace_service.py
- backend/tests/ip_locator/test_api_scope.py
- backend/tests/ip_locator/test_task_coordination.py
- backend/tests/ip_locator/test_cli_task_execution.py
- backend/tests/database/test_m0219_locator_v2_coordination.py
- backend/tests/database/test_m0223_locator_query_task_retention.py
- backend/tests/release/test_deploy_docker_redis_contract.py
- src/pages/IPLocatorPage.tsx
- src/components/IPLocatorPanel.tsx
- src/utils/ipLocatorRuns.ts
- src/utils/ipLocatorRuns.test.ts
- docs/plans/plan_20260911_2220_01_Redis与CLI四阶段IP定位.md
- docs/walkthrough/walkthrough_20260911_2220_01_Redis与CLI四阶段IP定位.md
- scripts/dev-backend.mjs

工作区中原有的用户改动和与本任务无关的删除/未跟踪文件均未处理。

## 关键实现说明

- 配置：`.env` 基本部署只需现有 `REDIS_URL`；TTL、namespace、连接超时和并发采用代码默认值。IP 定位默认使用新流程，不需要额外启用变量。
- 缓存：Redis key 带作用域摘要；读取不会续期；根据原始 collected_at 计算剩余 retain TTL；异常返回降级状态；支持短 single-flight lock；健康摘要脱敏。
- 四阶段引擎：新增 ip_locator_trace_service.py，复用现有厂商命令目录、CLI 解析和接口规范化；限制 L3/L2 跳数、候选数、设备数；缺少邻居或终端证据时返回 partial/coverage gap。
- 授权与起点：设备凭据仅在服务端先按用户 tenant、asset/site 作用域和允许设备 ID 过滤后解析；站点不匹配不回退。自动起点只选授权设备中的 core；没有核心时返回 needs_context。当前 CMDB 没有网络域绑定，非空 network_domain_id 返回 422，不尝试跨域猜测。
- 设备选择：ARP 只查 Direct 网关候选；MAC 只查 ARP 来源和拓扑逐跳候选；不默认全网拉 ARP/MAC 表。按设备的轻量基础索引周期维护是计划目标，当前仍待补齐，不能当作已完成能力。
- 协调：m0219–m0223 建立 PostgreSQL run/task/observation/device lease、部署级并发槽位、run 恢复租约和 query-task 原始结果保留索引；任务 query key 去重，租约使用 `FOR UPDATE SKIP LOCKED`，迟到 generation 不覆盖新事实。
- 执行边界：每条 trace CLI 操作通过共享 PostgreSQL query-task 执行；设备和部署级租约带续期/fencing。Netmiko SSH 会话按设备独占复用，默认空闲 15 秒关闭；凭据只用于计算进程内会话指纹，不写入任务表或日志。认证回退仅按已配置策略执行，未知平台不回退到 Cisco 命令。
- API：增加 `/api/ip-locator/trace`、`/api/ip-locator/health`、`/api/ip-locator/runs`、run 查询/取消；旧 `/locate` 默认使用新流程的兼容输出。
- 部署：增加 docker-compose.redis.yml，Windows/Docker 文档说明局域网 Redis、密码、防火墙、TTL、Redis 降级和 Compose 服务名。
- 部署脚本：deploy-docker.sh 默认合并 Redis Compose overlay；install/update/start-offline/save-images/load-images/reset-data 会纳入 Redis；增加 redis-status、redis-logs，并保留 NETOPS_REDIS_ENABLED=0 兼容开关。sidecar 默认地址首次安装时自动生成 URL-safe Redis 密码。
- 本地开发启动：dev-backend launcher 在调用方未显式设置时默认关闭自动通知外发，避免开发服务启动时重放告警到真实 webhook；显式配置仍可覆盖。

初始 TTL：路由/ARP fresh 300 秒、retain 1800 秒；MAC/完整结果 fresh 120 秒、retain 900 秒；网段 fresh 900 秒、retain 86400 秒；拓扑 fresh 600 秒、retain 86400 秒；成功未命中 15 秒。

## 验证命令与结果

- pytest backend/tests/ip_locator/test_trace_service.py backend/tests/ip_locator/test_task_coordination.py backend/tests/ipam/test_ip_locator_cache_service.py backend/tests/database/test_m0219_locator_v2_coordination.py -q：19 passed。
- pytest backend/tests/vendor_audit/test_ip_locator_arp_contract.py backend/tests/vendor_audit/test_connection_pool.py backend/tests/vendor_audit/test_network_access_limiter.py -q：45 passed。
- pytest backend/tests -k "topology or lldp or neighbor" -q：98 passed，2377 deselected。
- npm run lint：通过（tsc --noEmit）。
- scripts/validate_postgresql_only.py：0 violation(s)，PASS。
- 相关后端、迁移和 schema 的 Python 编译：通过。
- git diff --check -- . ':!dist'：通过。
- migration 219/220 重复升级、run→共享 task→claim/complete、设备租约、观测 generation 和 invalidation outbox：通过。
- Redis 适配器测试覆盖 namespace/TTL、故障熔断、PostgreSQL no-op、健康摘要脱敏、URL 解析和 single-flight owner lock：通过。
- 四阶段模拟 fixture 覆盖 Core→Aggregation→Access、Direct、ARP、MAC、拓扑终端证据和厂商路由命令：通过。
- Git Bash `bash -n scripts/deploy-docker.sh`：通过。
- `pytest --confcutdir=backend/tests/release backend/tests/release/test_deploy_docker_redis_contract.py -q`：2 passed。
- 最新定向回归（定位引擎/API 授权/任务协调/Redis/迁移/vendor contract）：140 passed in 284.82s，使用可清理的独立 PostgreSQL 源测试库。
- 完整快照缺失项撤销集成回归：`pytest backend/tests/ip_locator/test_task_coordination.py backend/tests/ip_locator/test_trace_service.py backend/tests/vendor_audit/test_ip_locator_arp_contract.py -q --tb=short`，95 passed in 105.08s；PostgreSQL-only 扫描 0 violations，限定文件 `git diff --check` 通过。
- 严格依赖 fence 集成回归：`pytest backend/tests/database/test_m0226_locator_dependency_generation.py backend/tests/ip_locator/test_task_coordination.py backend/tests/ip_locator/test_trace_service.py backend/tests/ip_locator/test_cli_task_execution.py backend/tests/ipam/test_ip_locator_cache_service.py backend/tests/ip_locator/test_api_scope.py backend/tests/vendor_audit/test_ip_locator_arp_contract.py -q --tb=short`，137 passed in 135.96s；删除不允许的 non-PG guard 直接调用后，追加单独迁移回归 2 passed in 42.62s。Python 编译通过、PostgreSQL-only policy 0 violations、限定 diff check 通过。
- 上下文/缓存 scope/freshness fence 回归：`pytest backend/tests/ip_locator/test_trace_service.py backend/tests/ip_locator/test_task_coordination.py backend/tests/vendor_audit/test_ip_locator_arp_contract.py backend/tests/ip_locator/test_api_scope.py -q --tb=short`，127 passed in 108.33s；其中包含 V2 context 补回、不执行额外接口 SSH、过期 Redis observation 不写入 manifest、结果 Redis 缓存 key scope 一致回归。`py_compile` 通过，PostgreSQL-only scanner 0 violations，限定 `git diff --check` 通过。
- 最新拓扑相关回归：98 passed、2449 deselected in 280.18s。
- 最新完整前端回归：65 个测试文件，254 passed；npm run lint 通过；Vite production build 成功，输出到系统临时目录，保留原 dist。
- 较早全后端回归尝试：pytest `backend/tests -q` 进程在约 39% 输出处退出，未产生汇总；该次不作为通过证据。
- 下一跳唯一性及兼容回归：Python 3.13 下 `pytest backend/tests/ip_locator/test_trace_service.py --noconftest -q -p no:cacheprovider -k "route_candidate_truncation_is_reported_and_cannot_look_complete or trace_does_not_guess_when_next_hop_ip_matches_multiple_devices or topology_neighbor_without_id_keeps_duplicate_identity_ambiguous or trace_follows_core_to_direct_then_arp_mac_and_terminal"`：4 passed in 3.77s。覆盖截断、IP 多重映射、无设备 ID 的 hostname/IP 歧义及 Core→Access 既有主链路。Python 3.11 `py_compile`、PostgreSQL-only policy 0 violations 与相关文件 `git diff --check` 通过。
- 最新 Redis 部署契约：3 passed；PyYAML 解析通过，显式 Git Bash 对 deploy-docker.sh 和 Compose 内联 ACL 脚本的语法检查通过。
- 新增 CLI 执行回归覆盖跨运行 query-task 去重、会话复用/空闲释放、认证回退和未知平台拒绝；任务协调回归覆盖租约续期、取消后的迟到结果丢弃及原始结果保留清理。
- 全量后端回归曾完成：2469 passed、8 failed、26 subtests passed。失败出现在 catalog 时序/并发、认证测试、IPAM 测试库缺列、schema 重跑及 terminal-agent 测试；其中 schema 重跑项在 m0221/m0222 文件加入后以新 pytest 进程重跑通过。其余失败涉及本次未修改模块，没有在本任务中处理。
- 当前工作区验证：Python compileall 通过；PostgreSQL-only 扫描 0 violation；`npm run lint` 通过；IP Locator 前端单测 3 passed；Vite production build 成功且输出到系统临时目录；相关文件 `git diff --check` 通过。
- Windows 开发后端 `/api/health` 返回 HTTP 200、status=healthy、数据库 connected、worker active；按当前应用配置调用 Redis cache health probe 返回 status=healthy、available=true，目标为 192.168.204.132:6379，探测延迟约 27 ms。不会在记录中保存或回显 Redis 凭据。
- 最新全后端回归（2026-09-12）：`.venv\\Scripts\\python.exe -m pytest backend/tests -q --tb=short` 完成，`2584 passed, 9 failed, 1 skipped, 26 subtests passed`，退出码 1，用时 3068.25s。失败分别为 1 项 `test_cmd_cache`、4 项 vendor quick-query mock 用例因调用真实 PostgreSQL shared SSH lease 失败，1 项 health metrics 401，1 项 IPAM 测试 schema 缺 `ip.device_id`，2 项 terminal-agent 环境/配置断言。唯一 skip 为需显式授权的 live Redis snapshot round-trip。
- 针对前 5 项 mock-driver 测试补充 no-op lease 注入（生产默认仍 fail closed）；复跑 `pytest --noconftest backend/tests/test_cmd_cache.py::test_send_command_caching_integration backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py -q --tb=short` 为 `74 passed`，独立共享 lease/PostgreSQL 多进程回归 `pytest backend/tests/vendor_audit/test_network_access_limiter.py backend/tests/database/test_m0224_network_global_ssh_slots.py -q --tb=short` 为 `11 passed in 57.33s`。尚未因这两项测试夹具调整重新跑 51 分钟全量套件；其余 4 项未在本任务中改动。

## 未执行验证及原因

- Windows 开发机没有用 Docker CLI 执行 Compose 操作；Ubuntu Docker Redis 的 healthy 状态、端口映射和 Windows Test-NetConnection 成功由用户提供，本轮又从 Windows 应用缓存适配器实测 Redis PING 成功。
- 当前 Windows 没有可用 Docker CLI，因此 deploy-docker.sh 的实际 install/update/offline 运行未执行。
- 未对真实网络设备执行 SSH/CLI 采集，未验证现场厂商命令差异、MAC 老化、VRF/ECMP/堆叠/EVPN 等生产数据。
- 已执行独立子进程争用共享 SSH 租约测试；未执行完整 worker 重启/100 并发/300 设备容量验收、真实设备只读采集、数据库生产迁移、生产灰度或发布。

## 剩余风险与后续建议

- 隔离环境已验证迁移至 225；开发数据库已补齐 lease_token。本轮 Windows 应用到 Ubuntu Docker Redis 的连接已验证，进入生产前仍需目标环境升级演练。新增 Compose 专用 nexora ACL 已做静态/契约验证，但未在 Docker 实机启动验证，也未修改用户现有 Ubuntu Redis 认证方式。
- 扩大并发或进入生产灰度前，补充真实多进程重启/故障注入与容量压测，测量跨 worker 去重、会话峰值、队列等待和恢复边界。
- 通过采集年龄、缓存命中率、队列等待、SSH 峰值、覆盖缺口和 MAC 漂移记录校准 TTL 与并发参数；初始值不是性能保证。
- 设备不支持精确过滤命令、邻居缺失、下游未纳管或二层域不明确时，系统返回 partial/coverage gap；这些情况需要补齐基础拓扑或厂商适配。
- 生产发布前应补齐 Windows .env 覆盖顺序验证、完整后端门禁、Cisco/Huawei/H3C 现场只读证据及经用户授权的灰度观察。

## 交付状态

- 2026-09-12 运行时报错复盘：用户日志中的 locator_invalidation_outbox.lease_token 缺失是真实 PostgreSQL schema 错误，不是 Redis 连通性问题。已新增幂等 m0225 增量迁移；开发库字段存在，失效 worker 直接执行成功。匿名请求 401 是另一类登录态问题，不能归因到 Redis。
- 本轮补齐：共享 SSH 配额与 owner/token fencing；run 读取/取消按当前设备权限重新授权（离线不等于失权）；观测 generation/outbox 与缓存失效；IPv6 拒绝、候选截断/ARP 状态/无 FDB 边界；按设备有界整表 fallback 与邻居快照；Redis Compose 专用 ACL；下一跳及无设备 ID 拓扑邻居的多重身份不再任意选取，候选预算超限不能报告成功。全后端回归未完成，历史全量结果仅作历史参考。
- 完整快照撤销：新增 PostgreSQL-only ARP/MAC snapshot reconciler，仅在显式 `found/not_found + coverage=full` 时按 tenant/scope/network-domain/site/VRF/device/action/source 及采集时间边界撤销缺失正事实。撤销保留 `prior_records`，generation 递增并同事务写 `fact_invalidated` outbox；targeted、partial、failed、截断或缺状态结果均不撤销。
- 严格依赖 fence：m0226 新增 global topology generation 表与 `topology_links` 行触发器（INSERT/UPDATE/DELETE 在同事务推进 generation）；当前 trace 持久化实际 action/parser/schema 指纹与消费的 observation key/generation，所有 Redis observation 快照指针类一致的 PG 依赖 metadata 和 global topology generation。旧 cache 项无版本 metadata 会 miss；CLI query-task key 含版本指纹；运行期依赖改变后的 `completed` 会在与存储同一事务被降为 `partial`。拓扑 generation 暂为 global，因 `topology_links` 没有 tenant/network-domain 列，避免假造分域标识。
- 本次尝试的全后端基线回归已运行至 39% 且无失败标记；由于实现子进程已开始修改共享工作树，主 Agent 主动中止以避免产生混合代码状态的无效证据。因此全后端仍需在代码固定后从头到尾复跑。
- 用户手动登录后，通过 browser 在指定 `http://192.168.96.1:5400/ipam/locate` 提交 `172.16.5.10`；页面显示定位成功，MAC `8e47-5760-0706`，接入 `S6850-5/GE1/0/2`，VLAN 7。V2 response context 修复后，页面额外显示网段 `172.16.5.0/24`、VLAN 来源 `arp_table`、接口描述 `TO-PC-7`、up/up/access、网关 `172.16.5.1/Vlan7`、VRF `default`、直连路由和上联 `S6850-3` 等现存事实；新鲜度卡显示各采集源各自时间。当前 PostgreSQL 的 L3 事实是 connected/Vlan7，与用户提供截图里的 BGP/10.254.0.5 不同，面板按当前保存的事实展示，时效信息显示该 route snapshot 约 3 小时。
- 同一 run `locator-run:fae7c6c2d28e4f73824a98b552b13e94` 的 PostgreSQL 记录为 `completed / managed_access_confirmed / dependency_fence=current`，`cache.route=redis` (route evidence 由 Redis 读取)，`cache.result=miss` (whole-result Redis cache 本次未命中)，`arp=cli, mac=postgres, topology=postgres`。对应 Redis adapter health probe 返回 `backend=redis, configured=true, available=true, degraded=false` (32.3 ms)；该 scope 下当时有 5 个 Redis key (`route=3, result=1, topology=1`)。所以能确认本次实际使用了 Redis route evidence，不代表整个结果命中 Redis。页面当前“实时采集”小标识只看 ARP 缓存，未显示 `cache.route=redis`，是独立的 UI 语义限制。
- 本次只为验证启动隔离 Vite + FastAPI (`--lifespan off`) 和临时 Redis invalidation 消费器，未启动 APScheduler/通用 telemetry loops；验证后已停消费器及前后端测试进程。关闭 Vite 后浏览器 SPA 状态重置为空表单，但 PostgreSQL 中的 completed run 与上述可复核快照保留；没有执行任何设备配置更改。
- 并行收尾分工：主 Agent 维护计划/记录并收集现有全量测试；verify_runtime_final 只读复核服务、开发库字段和 Redis；cleanup_mac_snapshot 仅清理 ip_locator_service.py 被覆盖的重复函数并做定向验证。
- 并行收尾结果：当前开发库 netops 已确认 lease_token 字段存在、迁移 225 已登记；应用 Redis PING healthy、available=true、degraded=false，36.06 ms（仅 PING，不等于业务缓存读写或定位端到端验收）。清理原行 1853–1953 被后置定义覆盖的 101 行重复 MAC 快照函数，保持原有效实现；py_compile 通过，`pytest --noconftest -s -vv backend/tests/vendor_audit/test_ip_locator_arp_contract.py::test_mac_full_snapshot_is_bounded_and_normalized` 为 1 passed。
- 基础事实周期维护缺口复核：设备能力 state 表与 worker service 仍未实现（m0226 现已作为 locator dependency generation，基础采集未来应另取迁移号）。现有 route collector 是全设备 sweep，不能安全直接拿来做逐设备租约刷新；接口单设备采集会附带 VLAN/Prefix 副作用；LLDP 单设备入口还会触发 protocol evidence/聚合采集，存在特权命令以及失败与合法空结果混淆风险。因此本轮没有包装成定时任务；30 分钟接口/路由与 5 分钟邻居的错峰刷新仍未实现，需要先为只读单设备采集建立 typed result/状态语义。
- 服务复查曾先返回 HTTP 200，随后连接拒绝，主线程确认 5310 无监听后按用户既有授权重新启动开发后端。该瞬态不可忽略，启动后的健康结果单独记录；未进行系统关机、生产部署或远端 Redis 配置变更。
- 14:43（Asia/Shanghai）重新启动后的 `/api/health` 实测 HTTP 200、healthy、database=connected、scheduler=running、worker=active。启动日志无 lease_token 缺列错误；出现过一次 run worker 达到 max_instances=1 的跳过警告，这不等于 Redis 连接失败，尚未以此宣称长时间稳定性通过。
- 15:08（Asia/Shanghai）源码热重载后服务曾再次不可达；主线程按既有授权重新启动 `scripts/dev-backend.mjs`，随后 `/api/health` 恢复 healthy、database=connected、worker=active。该服务重启只影响本机开发服务。

- [x] 配置、Redis 适配和部署说明
- [x] PostgreSQL 迁移与任务/租约协调
- [x] 四阶段 CLI-only 引擎与旧定位兼容层
- [x] API、缓存和设备范围回归
- [x] TypeScript lint、PostgreSQL-only 扫描和相关测试
- [x] 共享 query-task 执行与 15 秒 SSH 会话复用（代码及定向并发/生命周期回归通过）
- [x] Windows 应用到 Ubuntu Docker Redis 目标连通性（应用缓存健康探测通过）
- [ ] 多进程重启/高并发压力验证、真实设备只读抽样与生产灰度
- [ ] 提交、推送和发布（未执行）
