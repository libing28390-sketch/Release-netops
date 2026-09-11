# Redis 与 CLI 四阶段 IP 定位 — 完成记录

## 完成摘要

已按计划实现可选的 V2 IP 定位链路：从核心设备逐跳查询目标路由，直到 Direct 三层终结设备；随后只在网关候选上查询目标 ARP，再沿目标 MAC 的已知拓扑分支逐跳查询，最终仅在具备 Access、Edge、Untagged 等接口证据时确认最末纳管接入点。

定位链路使用 SSH/CLI，不调用 SNMP。Redis 是带 namespace、短超时和熔断的可重建共享缓存；PostgreSQL 保存 V2 运行、共享查询任务、租约、观测、历史和失效 outbox。Redis 不可用时，读取和任务语义仍可降级到 PostgreSQL。

V2 默认保持关闭（IP_LOCATOR_V2_ENABLED=0），便于目标部署先执行只读验证。启用后，旧 /api/ip-locator/locate 通过兼容层返回现有页面所需字段；同时提供异步 run API 用于排队、轮询和取消。

## 实际修改文件

- .env.example
- backend/core/config.py
- backend/schemas/schemas.py
- backend/api/ip_locator.py
- backend/services/ip_locator_cache_service.py
- backend/services/ip_locator_trace_service.py
- backend/services/ip_locator_task_service.py
- backend/database/migrations/m0219_locator_v2_coordination.py
- backend/database/migrations/m0220_locator_run_deployment_scope.py
- docker-compose.redis.yml
- scripts/deploy-docker.sh
- docs/deploy/windows.md
- docs/deploy/docker.md
- docs/deploy/docker-release-manual.md
- docs/deploy/README.md
- backend/tests/ipam/test_ip_locator_cache_service.py
- backend/tests/ip_locator/test_trace_service.py
- backend/tests/ip_locator/test_task_coordination.py
- backend/tests/database/test_m0219_locator_v2_coordination.py
- docs/plans/plan_20260911_2220_01_Redis与CLI四阶段IP定位.md
- docs/walkthrough/walkthrough_20260911_2220_01_Redis与CLI四阶段IP定位.md

工作区中原有的用户改动和与本任务无关的删除/未跟踪文件均未处理。

## 关键实现说明

- 配置：增加 Redis URL、backend/namespace、连接超时/熔断、路由/ARP/MAC/结果/网段/拓扑 fresh/retain TTL、CLI 并发和任务截止时间校验。
- 缓存：Redis key 带作用域摘要；读取不会续期；根据原始 collected_at 计算剩余 retain TTL；异常返回降级状态；支持短 single-flight lock；健康摘要脱敏。
- 四阶段引擎：新增 ip_locator_trace_service.py，复用现有厂商命令目录、CLI 解析和接口规范化；限制 L3/L2 跳数、候选数、设备数；缺少邻居或终端证据时返回 partial/coverage gap。
- 设备选择：全量设备只维护轻量路由、接口和邻居基础索引；ARP 只查 Direct 网关候选；MAC 只查 ARP 来源和拓扑逐跳候选；不默认全网拉 ARP/MAC 表。
- 协调：m0219/m0220 建立 PostgreSQL-only run/task/subscriber/observation/device lease/history/outbox 模型；任务 query key 去重，租约使用 FOR UPDATE SKIP LOCKED，迟到 generation 不覆盖新事实。
- API：增加 /api/ip-locator/trace、/api/ip-locator/health、/api/ip-locator/runs、run 查询/任务列表/取消；启用开关后旧 /locate 使用 V2 兼容输出。
- 部署：增加 docker-compose.redis.yml，Windows/Docker 文档说明局域网 Redis、密码、防火墙、TTL、Redis 降级和 Compose 服务名。
- 部署脚本：deploy-docker.sh 默认合并 Redis Compose overlay；install/update/start-offline/save-images/load-images/reset-data 会纳入 Redis；增加 redis-status、redis-logs，并保留 NETOPS_REDIS_ENABLED=0 兼容开关。sidecar 默认地址首次安装时自动生成 URL-safe Redis 密码。
- 部署脚本：deploy-docker.sh 默认合并 Redis Compose overlay，save/load/offline 会校验并携带 Redis 镜像；增加 redis-status、redis-logs，并保留 NETOPS_REDIS_ENABLED=0 的兼容开关。

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
- Git Bash `bash -n scripts/deploy-docker.sh`：通过。
- `pytest --confcutdir=backend/tests/release backend/tests/release/test_deploy_docker_redis_contract.py -q`：2 passed。

## 未执行验证及原因

- Docker CLI 当前不可用，未执行真实 docker compose config 或 Redis 容器连通性测试；Compose YAML 已做静态解析。
- 当前 Windows 没有可用 Docker CLI，因此 deploy-docker.sh 的实际 install/update/offline 运行未执行。
- 当前 Windows 没有可用 Docker CLI，因此 deploy-docker.sh 的实际 install/update/offline 运行未执行。
- 未对真实网络设备执行 SSH/CLI 采集，未验证现场厂商命令差异、MAC 老化、VRF/ECMP/堆叠/EVPN 等生产数据。
- 未运行完整 pytest backend/tests 或生产构建；本轮新增代码的直接依赖测试和拓扑/网络回归已通过。
- 未执行 Redis 部署、数据库生产迁移、真实灰度或发布。

## 剩余风险与后续建议

- 启用前先在隔离环境应用迁移 219/220，并配置 IP_LOCATOR_V2_ENABLED=1、局域网 Redis 地址和专用 Redis ACL；健康接口确认连接状态后再做只读设备抽样。
- 通过采集年龄、缓存命中率、队列等待、SSH 峰值、覆盖缺口和 MAC 漂移记录校准 TTL 与并发参数；初始值不是性能保证。
- 设备不支持精确过滤命令、邻居缺失、下游未纳管或二层域不明确时，系统返回 partial/coverage gap；这些情况需要补齐基础拓扑或厂商适配。
- 生产发布前应补齐 Redis Compose 实机验证、Windows CRLF/覆盖顺序实机验证、完整后端门禁和 Cisco/Huawei/H3C 现场只读证据。

## 交付状态

- [x] 配置、Redis 适配和部署说明
- [x] PostgreSQL 迁移与任务/租约协调
- [x] 四阶段 CLI-only 引擎与旧定位兼容层
- [x] API、缓存和设备范围回归
- [x] TypeScript lint、PostgreSQL-only 扫描和相关测试
- [ ] Docker/Redis 目标环境连通性
- [ ] 真实设备只读抽样与生产灰度
- [ ] 提交、推送和发布（未执行）
