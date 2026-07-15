# CMDB 与 IPAM 企业级架构整改实施计划

## 任务目标

将当前 Nexora NetOps 从“功能较完整的网络运维平台”升级为“适合中大型企业长期运行的 CMDB + IPAM 核心平台”。本计划重点解决数据权威性、一致性、并发安全、权限审计、任务调度、可观测性和前端领域化维护问题。

本计划后续作为主路线图使用。执行时应按任务编号拆分实现，例如 `ENT-001`、`IPAM-003`、`CMDB-002`。每个落地任务都需要单独生成对应 `docs/plans/plan_*.md` 和 `docs/walkthrough/walkthrough_*.md`。

## 当前判断

当前架构方向是合理的，已具备中大型网络运维平台的功能骨架：

- 后端采用 FastAPI，已有 `backend/api/`、`backend/services/`、`backend/database/`、`backend/drivers/` 等分层。
- 数据库以 PostgreSQL 为生产核心，已有迁移目录 `backend/database/migrations/`。
- CMDB 已覆盖 tenant、site、VRF、VLAN、credential、rack、physical asset、device。
- IPAM 已覆盖 prefix、IP address、pool、VIP、DHCP lease、utilization、reconciliation。
- 网络侧已有 SSH、SNMP、TextFSM、拓扑、诊断、配置备份、巡检等能力。
- 前端已有资产、CMDB、IPAM、监控、自动化、告警、PAM、工单、报表等页面。

主要短板是：部分数据模型仍偏“功能拼接”，还没有完全形成企业级数据权威源、强约束、强审计和强可观测的底座。

## 总体原则

1. PostgreSQL 语义优先，SQLite 仅作为测试或兼容场景保留。
2. CMDB 是确认后的权威资产与逻辑资源，Discovery 是观测数据，IPAM 是地址规划与分配权威。
3. 发现数据不得直接覆盖 CMDB/IPAM 权威数据，必须通过 reconciliation 流程闭环。
4. 涉及 IP 分配、资源占用、机柜上架、批量任务状态流转的操作必须具备事务和并发保护。
5. 所有高风险操作必须有 RBAC、审计日志、错误码和回滚路径。
6. 每一阶段先补数据结构和后端契约，再补前端体验，最后补测试与文档。

## 分阶段路线图

| 阶段 | 目标 | 建议优先级 | 预期结果 |
|---|---|---:|---|
| Phase 0 | 基线梳理与风险冻结 | P0 | 明确现状、数据关系、接口契约和风险边界 |
| Phase 1 | CMDB/IPAM 权威数据模型 | P0 | 解决“谁说了算”的核心问题 |
| Phase 2 | PostgreSQL 原生 IPAM 与并发安全 | P0 | IP 分配、prefix 查询和冲突检测可用于生产 |
| Phase 3 | Discovery 与 Reconciliation 闭环 | P1 | 网络发现数据可审计地进入 CMDB/IPAM |
| Phase 4 | 企业级任务系统 | P1 | 批量巡检、扫描、备份、对账具备统一任务生命周期 |
| Phase 5 | RBAC、租户、站点和审计增强 | P1 | 满足中大型企业权限和合规要求 |
| Phase 6 | 前端领域化与体验收敛 | P2 | 页面更稳定，API contract 更清楚 |
| Phase 7 | 可观测性、部署和高可用 | P2 | 支撑多实例、生产监控、故障定位 |
| Phase 8 | 性能压测与企业验收 | P2 | 有明确容量边界和上线标准 |

## 2026-07-13 执行状态

| 阶段 | 状态 | 完成说明 |
|---|---|---|
| Phase 0 | 已完成 | 数据关系/权威矩阵与企业整改 backlog 已建立 |
| Phase 1 | 已完成 | 资产-设备-接口关系、复合唯一规则、引用审计和确定性回填已落地 |
| Phase 2 | 已完成 | PostgreSQL CIDR/INET 迁移、Prefix 规则、原子分配和生命周期已落地 |
| Phase 3 | 已完成 | Discovery observation、finding、action 和审批写入闭环已落地 |
| Phase 4 | 已完成 | 统一 Job/step/target/artifact/event、限流、重试和取消语义已落地 |
| Phase 5 | 已完成 | resource/scope/action 权限与统一 before/after 审计已落地 |
| Phase 6 | 已完成 | CMDB/IPAM client、类型、领域 hooks 和四类企业工作流入口已落地 |
| Phase 7 | 已完成 | request_id、指标、健康检查、调度锁、多实例基础与网络访问预算 |
| Phase 8 | 已完成 | 全量回归、网络并发/连接池测试与企业验收基准 |

Phase 0–6 的统一交付记录见：

- `docs/plans/plan_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`
- `docs/walkthrough/walkthrough_20260713_2009_01_CMDB_IPAM_Phase0至Phase6连续整改.md`

---

## Phase 0：基线梳理与风险冻结

### ENT-001：建立 CMDB/IPAM 数据关系图

目标：明确当前所有 CMDB、IPAM、Discovery、Device、Asset、Interface 之间的数据关系。

影响范围：

- `backend/database/schema.py`
- `backend/database/migrations/`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/api/cmdb.py`
- `backend/api/ipam.py`
- `backend/services/cmdb_service.py`
- `backend/services/ipam_service.py`
- `backend/services/endpoint_tracker_service.py`
- `backend/services/topology_service.py`

具体任务：

1. 盘点核心表：`physical_assets`、`devices`、`interfaces`、`sites`、`vrfs`、`vlans`、`prefixes`、`ip_addresses`、`ipam_pools`、`ipam_vips`、`ipam_dhcp_leases`、`network_endpoints`、`arp_table`、`mac_table`、`route_table`。
2. 标注每个字段的权威来源：人工录入、网络发现、系统生成、外部导入。
3. 标注重复字段，例如 hostname、IP、MAC、VLAN、site、device_id、interface_name。
4. 输出一份数据关系图和字段权威矩阵。

交付物：

- `docs/architecture/cmdb_ipam_data_model.md`
- `docs/architecture/cmdb_ipam_authority_matrix.md`

验收标准：

- 每张核心表都有用途说明。
- 每个重复字段都有权威归属。
- 明确哪些字段后续需要迁移、废弃或转为外键。

### ENT-002：建立企业级整改任务看板

目标：将本计划拆成可执行任务，避免一次性大改。

具体任务：

1. 按本文件任务编号创建执行清单。
2. 标记 P0/P1/P2 优先级。
3. 标记依赖关系。
4. 标记每项任务是否需要数据库迁移、前端改造、后端接口、测试、手工验证。

交付物：

- `docs/architecture/enterprise_refactor_backlog.md`

验收标准：

- 每个任务都有负责人角色建议：backend、frontend、data-migration、network、quality。
- 每个任务都有“完成定义”。

---

## Phase 1：CMDB/IPAM 权威数据模型

### CMDB-001：定义 CMDB、IPAM、Discovery 三层事实源

目标：从架构上明确三类数据的边界。

建议定义：

- CMDB：确认后的资产、站点、机柜、设备、接口、租户、VRF、VLAN。
- IPAM：prefix、address、pool、VIP、DHCP lease、地址状态、地址生命周期。
- Discovery：ARP、MAC、LLDP/CDP、路由表、SNMP 采样、在线终端、临时观测。

具体任务：

1. 增加架构文档说明三层事实源。
2. 明确 Discovery 数据不能直接覆盖 CMDB/IPAM。
3. 所有自动发现写入 CMDB/IPAM 的动作必须走 reconciliation decision。
4. 为每类数据定义可信等级：manual、imported、discovered、confirmed、stale。

建议新增字段：

- `source_type`
- `source_ref`
- `confidence`
- `last_confirmed_at`
- `last_observed_at`
- `confirmed_by`

验收标准：

- 文档中能清楚回答“IP 地址、MAC、hostname、VLAN、site 到底谁说了算”。
- 后续 API 设计均引用该事实源定义。

### CMDB-002：设备、资产、接口关系重构

目标：解决 `physical_assets`、`devices`、`interfaces` 之间职责重叠的问题。

建议模型：

- `physical_assets`：物理资产生命周期、采购、维保、机柜、功耗、序列号。
- `devices`：可管理对象，包含平台、状态、凭据、管理地址、监控开关。
- `interfaces`：设备接口事实表，包含接口名、索引、MAC、速率、状态。
- `device_asset_links` 或继续使用 `devices.asset_id`，但必须约束一对一关系。

具体任务：

1. 审查 `physical_assets` 与 `devices` 重复字段。
2. 明确哪些字段只保留在资产，哪些同步到设备，哪些通过 JOIN 展示。
3. 为 asset-device 关系增加唯一约束或一致性检查。
4. 为接口建立更强的设备内唯一约束：`(device_id, interface_name)`。
5. 将 IP 绑定逐步从 `interface_name` 字符串迁移到 `interface_id`。

建议影响文件：

- `backend/database/schema.py`
- `backend/database/migrations/`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/api/interfaces.py`
- `backend/services/inventory_synchronizer.py`
- `src/types.ts`
- `src/pages/AssetManagement/`
- `src/pages/InventoryDevicesTab.tsx`

验收标准：

- 一个资产最多关联一个可管理设备。
- 一个设备可以有多个接口。
- IP 可以绑定到设备，也可以进一步绑定到接口。
- 删除资产、设备、接口时行为明确，不产生孤儿数据。

### CMDB-003：站点、租户、VRF、VLAN 关系增强

目标：让 CMDB 支撑多租户、多站点、多 VRF 的中大型企业网络。

具体任务：

1. 审查 `tenants`、`sites`、`vrfs`、`vlans` 的唯一性约束。
2. 将 VRF 唯一性从全局 `vrf_name` 逐步调整为 `(tenant_id, vrf_name)`。
3. 将 VLAN 唯一性明确为 `(site_id, vlan_id)`，必要时增加 tenant 维度。
4. prefix 必须明确绑定 tenant、VRF、site 的规则。
5. 删除 tenant/site/VRF/VLAN 前必须检查引用，禁止静默破坏生产数据。

验收标准：

- 同名 VRF 可以在不同 tenant 下存在。
- 同一 VLAN ID 可以在不同 site 下存在。
- 删除基础 CMDB 对象时能给出可理解的阻断原因。

---

## Phase 2：PostgreSQL 原生 IPAM 与并发安全

### IPAM-001：IPAM PostgreSQL 原生字段迁移

目标：让 prefix 和 address 查询、包含关系、冲突检测可以依赖 PostgreSQL 能力。

建议新增字段：

- `prefixes.prefix_cidr CIDR`
- `prefixes.ip_version INTEGER`
- `prefixes.prefix_len INTEGER`
- `ip_addresses.address_inet INET`
- `ip_addresses.ip_version INTEGER`

兼容策略：

1. 第一步新增 nullable 字段。
2. 第二步从现有 `prefix`、`address` 回填。
3. 第三步为新写入接口同时写旧字段和新字段。
4. 第四步将查询逐步迁移到新字段。
5. 第五步补 NOT NULL 和索引。

建议索引：

- `(tenant_id, vrf_id, prefix_cidr)`
- `(tenant_id, vrf_id, address_inet)`
- `GIST(prefix_cidr inet_ops)` 或适配 PostgreSQL 实际可用索引策略。

验收标准：

- prefix 和 IP 地址格式在数据库层可校验。
- 查询某 IP 所属最具体 prefix 不再依赖全量 Python 遍历。
- 迁移可重复执行，不破坏现有数据。

### IPAM-002：prefix 重叠和层级约束

目标：企业级 IPAM 必须明确允许哪些重叠，禁止哪些冲突。

规则建议：

- 不同 VRF 下允许相同 prefix。
- 同一 VRF 下允许父子 prefix。
- 同一 VRF 下禁止兄弟 prefix 重叠。
- 同一 VRF 下禁止完全重复 prefix。
- 默认 `0.0.0.0/0` 和 `::/0` 作为容器 prefix 时要特殊标记。

具体任务：

1. 在 `create_subnet` 和 `update_subnet` 增加重叠校验。
2. 将层级重建逻辑从全量 O(n²) 优化为按 VRF/IP version 分组。
3. 增加 prefix 状态：container、active、reserved、deprecated。
4. 增加单元测试覆盖 IPv4、IPv6、不同 VRF、父子 prefix、非法重叠。

验收标准：

- 用户无法在同一 VRF 下创建非法重叠 prefix。
- 合法父子 prefix 可创建并正确形成树。
- 更新 prefix 时同样执行冲突校验。

### IPAM-003：原子 IP 分配接口

目标：解决多人或批量任务同时申请 IP 时抢占同一个地址的问题。

建议新增接口：

- `POST /api/ipam/subnets/{subnet_id}/allocate-next`
- `POST /api/ipam/subnets/{subnet_id}/reserve`
- `POST /api/ipam/addresses/{address_id}/release`

事务要求：

1. 开启事务。
2. 锁定目标 prefix：PostgreSQL 使用 `FOR UPDATE` 或 advisory lock。
3. 计算可用 IP。
4. 插入 `ip_addresses`。
5. 写审计日志。
6. 提交事务。

建议请求字段：

- `hostname`
- `device_id`
- `interface_id`
- `mac_address`
- `purpose`
- `requested_by`
- `expires_at`

验收标准：

- 并发 20 个请求分配同一 subnet 时不会重复分配。
- 失败时事务回滚。
- 审计日志记录分配者、目标 subnet、分配地址。

### IPAM-004：IP 地址生命周期模型

目标：让地址从“是否存在”升级为“生命周期状态”。

建议状态：

- `available`
- `reserved`
- `allocated`
- `dhcp`
- `vip`
- `deprecated`
- `released`
- `quarantine`

具体任务：

1. 扩展 `ip_addresses.status` 的语义和校验。
2. 增加释放后保留期，避免刚释放地址被立即复用。
3. DHCP lease 与静态 IPAM 记录建立关联或冲突检测。
4. VIP 地址纳入统一冲突检测。

验收标准：

- 释放 IP 不等于硬删除。
- DHCP、VIP、静态分配之间能检测冲突。
- 前端显示地址状态和生命周期操作。

---

## Phase 3：Discovery 与 Reconciliation 闭环

### REC-001：建立观测数据标准模型

目标：统一网络发现结果，减少 ARP/MAC/topology/endpoint 各自为政。

建议新增或规范表：

- `discovery_observations`
- `endpoint_observations`
- `interface_observations`
- `topology_observations`

通用字段：

- `id`
- `run_id`
- `source_device_id`
- `source_type`
- `observed_type`
- `observed_key`
- `payload_json`
- `confidence`
- `first_seen_at`
- `last_seen_at`
- `is_active`

验收标准：

- 同一类发现数据具备统一 run_id。
- 能追溯某条发现数据来自哪台设备、哪个任务、哪个时间。

### REC-002：IPAM 对账中心升级

目标：把当前 `/api/ipam/reconciliation` 从查询型能力升级为闭环处置能力。

建议新增对象：

- `reconciliation_runs`
- `reconciliation_findings`
- `reconciliation_actions`

发现类型：

- `undocumented_endpoint`
- `stale_ip_address`
- `mac_mismatch`
- `hostname_mismatch`
- `vlan_mismatch`
- `vrf_mismatch`
- `duplicate_ip`
- `prefix_not_found`

处置动作：

- register IP
- update IP metadata
- release IP
- mark stale
- ignore once
- ignore rule
- create ticket

验收标准：

- 每条差异都有状态：open、accepted、rejected、ignored、resolved。
- 每次处置都有审计记录。
- 用户可以批量确认低风险差异。

### REC-003：Discovery 到 CMDB/IPAM 的审批写入

目标：自动发现只能产生建议，写入权威表必须可审计。

具体任务：

1. 为 reconciliation action 增加审批/确认人。
2. 支持手动确认写入 `ip_addresses`。
3. 支持手动确认更新 hostname/MAC/interface。
4. 高风险变更走变更单或管理员确认。

验收标准：

- 自动发现不能静默覆盖人工确认字段。
- 所有写入 CMDB/IPAM 的发现结果都能追溯来源。

---

## Phase 4：企业级任务系统

### JOB-001：统一后台任务模型

目标：统一批量巡检、扫描、配置备份、拓扑发现、IPAM 对账、报表生成的任务生命周期。

建议表：

- `jobs`
- `job_steps`
- `job_targets`
- `job_artifacts`
- `job_events`

任务字段：

- `id`
- `job_type`
- `status`
- `created_by`
- `created_at`
- `started_at`
- `finished_at`
- `progress`
- `total_targets`
- `success_count`
- `failed_count`
- `cancel_requested`
- `error_summary`

状态：

- queued
- running
- succeeded
- partially_failed
- failed
- cancelled
- timeout

验收标准：

- 所有长耗时任务都能查询进度。
- 任务失败原因可查看。
- 用户可以取消未完成任务。

### JOB-002：Worker 与限流策略

目标：避免大规模设备任务压垮后端、网络设备或数据库。

具体任务：

1. 评估当前 background thread、scheduler、async task 使用方式。
2. 引入统一 worker 抽象。
3. 增加并发限制：全局、site、vendor、device。
4. 增加 retry、timeout、backoff。
5. 避免 FastAPI 请求线程执行长耗时网络任务。

验收标准：

- 500 台设备批量任务不会阻塞 API。
- 单设备不会同时执行多个冲突任务。
- 任务取消后不会继续写入过期结果。

---

## Phase 5：RBAC、租户、站点和审计增强

### SEC-001：细粒度权限模型

目标：满足企业中不同团队、站点、租户和操作类型的授权要求。

建议权限维度：

- resource type：device、asset、prefix、ip_address、credential、job、change_order
- scope：global、tenant、site、device_group
- action：read、create、update、delete、execute、approve、export

具体任务：

1. 审查 `backend/core/rbac.py`。
2. 增加资源级鉴权 helper。
3. IPAM 删除、批量释放、配置变更、设备命令执行必须使用更高权限。
4. 前端根据权限隐藏或禁用操作。

验收标准：

- 普通 Viewer 无法调用写接口。
- Operator 无法执行高风险删除或发布。
- Administrator 操作仍有审计。

### SEC-002：统一审计事件标准

目标：让所有核心动作可追踪、可检索、可用于合规。

审计字段：

- `event_type`
- `category`
- `severity`
- `status`
- `actor_username`
- `actor_role`
- `target_type`
- `target_id`
- `target_name`
- `request_id`
- `source_ip`
- `before_json`
- `after_json`
- `details_json`

覆盖动作：

- CMDB 创建/修改/删除
- IP 分配/释放/保留
- Discovery 对账确认
- 设备命令执行
- 配置变更
- 凭据访问
- PAM 会话
- 批量导入导出

验收标准：

- 任意核心资源能看到变更历史。
- 审计日志不包含真实密码、token、SNMP community。

---

## Phase 6：前端领域化与体验收敛

### FE-001：抽离 CMDB/IPAM API client 与领域 hooks

目标：减少页面内散落的 fetch 和重复类型定义。

建议新增：

- `src/api/cmdb.ts`
- `src/api/ipam.ts`
- `src/types/cmdb.ts`
- `src/types/ipam.ts`
- `src/hooks/useCmdbLookups.ts`
- `src/hooks/useIpamPrefixes.ts`
- `src/hooks/useIpamAddresses.ts`
- `src/hooks/useIpamReconciliation.ts`

具体任务：

1. 先抽 IPAM prefix/address API。
2. 再抽 CMDB tenants/sites/vrfs/vlans API。
3. 页面只保留交互状态和渲染。
4. 统一错误处理、loading、empty、permission denied。

验收标准：

- IPAM 页面不直接散落大量 fetch。
- API contract 修改时只需要改 API client 和类型。
- `npm run lint` 和 `npm run build` 通过。

### FE-002：CMDB/IPAM 工作流体验升级

目标：让企业用户围绕日常工作流使用，而不是只做表格 CRUD。

建议工作流：

- 站点初始化向导：tenant -> site -> rack -> VRF -> VLAN -> prefix。
- IP 分配向导：选择 site/VRF/prefix -> 推荐 IP -> 绑定设备/接口 -> 确认审计。
- 对账处理台：发现差异 -> 风险分类 -> 批量确认/忽略 -> 写入权威表。
- 资产上线流程：staging asset -> connectivity verify -> managed device -> production。

验收标准：

- 新用户能按向导完成一个站点的基础 CMDB/IPAM 初始化。
- IP 分配过程不需要手工切换多个页面。
- 对账差异有清晰处置入口。

---

## Phase 7：可观测性、部署和高可用

### OPS-001：结构化日志与 request_id

目标：生产故障能快速定位。

具体任务：

1. 为每个 API 请求生成 request_id。
2. 日志统一包含 request_id、user、route、status、duration。
3. 后台任务日志包含 job_id、target_id、device_id。
4. 前端错误提示中保留 request_id，便于排查。

验收标准：

- 用户报错截图能通过 request_id 追踪后端日志。
- 批量任务失败能定位具体设备和步骤。

### OPS-002：指标监控和健康检查

目标：支持中大型企业运行监控。

建议指标：

- API latency
- DB connection usage
- worker queue length
- job success/failure count
- device polling duration
- SNMP/SSH failure rate
- IPAM allocation conflict count
- reconciliation finding count

验收标准：

- `/api/health` 能区分数据库、worker、scheduler 状态。
- 平台自身问题能被监控系统发现。

### OPS-003：多实例与无状态 API 准备

目标：为高可用部署打基础。

具体任务：

1. 清理 API 进程内不可共享状态。
2. 将后台任务从 API 进程中逐步拆出。
3. 文件型 artifact 规划共享存储或对象存储。
4. session/token 策略适配多实例。
5. 定时任务确保只有一个 leader 执行。

验收标准：

- 两个 API 实例同时运行不会重复执行同一个调度任务。
- 用户请求可在多个实例之间负载均衡。

---

## Phase 8：性能压测与企业验收

### QA-001：建立标准测试矩阵

目标：每个阶段都有明确质量门槛。

后端测试：

- CMDB CRUD
- IPAM prefix overlap
- IP allocation concurrency
- reconciliation actions
- RBAC permission denial
- audit logging
- migration upgrade

前端测试：

- `npm run lint`
- `npm run build`
- 核心页面手工 walkthrough
- 权限禁用态
- 空数据态
- 大数据分页态

验收标准：

- P0 阶段不得跳过后端测试。
- 涉及前端契约必须运行 lint/build。
- 跳过项必须写入 walkthrough。

### QA-002：容量基准

目标：明确平台适用边界。

建议压测规模：

- 500 devices
- 5,000 interfaces
- 50,000 IP addresses
- 2,000 prefixes
- 100,000 endpoint observations
- 1,000 concurrent IP allocation attempts in batches

验收指标：

- IPAM prefix 列表查询小于 2 秒。
- IP 分配接口 p95 小于 500ms。
- 对账任务可后台运行，不阻塞 API。
- 前端 IPAM 页面分页和搜索不卡顿。

---

## 推荐执行顺序

第一批 P0，建议优先执行：

1. `ENT-001` 数据关系图和权威矩阵。
2. `CMDB-001` 三层事实源定义。
3. `IPAM-003` 原子 IP 分配接口。
4. `IPAM-002` prefix 重叠和层级约束。
5. `SEC-002` 审计事件标准。

第二批 P1：

1. `IPAM-001` PostgreSQL 原生字段迁移。
2. `REC-002` IPAM 对账中心升级。
3. `JOB-001` 统一后台任务模型。
4. `SEC-001` 细粒度权限模型。

第三批 P2：

1. `FE-001` 前端领域 hooks 与 API client。
2. `OPS-001` 结构化日志与 request_id。
3. `OPS-002` 指标监控和健康检查。
4. `QA-002` 容量基准。

## 每项任务的标准执行流程

后续执行本计划中的任何任务时，必须遵循：

1. 创建任务专属计划：`docs/plans/plan_[任务名].md`。
2. 检查 `git status`，确认不覆盖用户未提交修改。
3. 选择最小必要 skills：
   - 后端/API：`netops-backend`
   - 数据结构/迁移：`netops-data-migrations`
   - 前端页面/API contract：`netops-frontend`
   - 设备/发现/驱动：`netops-network-drivers`
   - 验证：`netops-quality-gate`
4. 先改数据模型和后端契约，再改前端。
5. 每个数据库变更必须包含迁移、fresh schema 对齐和升级验证思路。
6. 运行风险相称的测试。
7. 创建完成报告：`docs/walkthrough/walkthrough_[任务名].md`。

## 风险与回滚

主要风险：

- 数据迁移影响已有生产数据。
- 旧前端依赖旧 API response shape。
- IPAM 新唯一约束可能暴露历史脏数据。
- 后台任务抽象改造可能影响现有巡检、备份、拓扑发现。
- 权限增强可能导致原有管理员以外用户无法操作。

回滚策略：

- 数据库变更采用“新增字段 -> 回填 -> 双写 -> 切读 -> 约束”的渐进策略。
- API 变更保持旧字段兼容至少一个版本。
- 前端页面逐步迁移到新 API client，不一次性重写。
- 任务系统先接入新任务类型，再迁移旧任务。
- 权限策略先记录 deny candidate，再正式拦截。

## 企业级完成定义

当以下条件满足时，可认为平台具备中大型企业 CMDB/IPAM 生产落地基础：

- CMDB、IPAM、Discovery 三层事实源清晰。
- IPAM 支持 PostgreSQL 原生查询、冲突检测和并发分配。
- 自动发现差异必须通过 reconciliation 审批写入权威表。
- 长耗时任务具备统一 job 生命周期、进度、取消、重试和审计。
- 核心操作具备细粒度权限和统一审计。
- 前端 API contract 领域化，页面具备 loading、empty、error、permission 状态。
- 平台具备 request_id、结构化日志、健康检查和基础指标。
- 有容量基准和标准测试矩阵。
