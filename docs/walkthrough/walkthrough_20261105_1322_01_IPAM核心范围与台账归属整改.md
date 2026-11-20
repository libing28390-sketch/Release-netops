# IPAM 核心范围与台账归属整改：P3 阶段进展

## 当前状态

任务继续 active。P1、P2a、P2b.1–P2b.4 与 P3 当前页实现及聚焦自动化回归完成；最新完整隔离 backend/tests/ipam 为 **265 passed / 814.29s**，五个 collector/parser/vendor 合同 **101 passed / 121.56s**，IPVlan 目录 **138 passed / 20 files**，DeviceRoutingContext 与 conflict-scope 定向 **9 passed / 2 files**。TypeScript lint、4362-module Vite build、PostgreSQL-only scanner 和 Python py_compile 通过。本机 PostgreSQL 服务已恢复，m0319/m0320 已应用到本机开发库（schema 320），生产库未操作；/api/health healthy/database connected、5400 返回 200，Edge/Playwright 浏览器实测根页成功。真实设备样本、完整 A01–A36 矩阵和 P4 映射仍按 handoff 跟踪。

本轮目标按用户最新澄清收窄为：自动推荐/分配只根据 IP 地址页当前展示的数据。历史 `ipam_discovery_observations` 不读取、不清理、不回填，也不作为当前地址占用或空间映射来源。

## 已完成

- 未知 VRF 的接口快照候选保持 `scope_pending`；只有操作者显式确认 Global 或 VRF 后才可生成 Prefix，批量“创建全部待新增网段”跳过待确认项。
- IP 台账登记的设备、接口、主机名和 MAC 与只读发现字段分离；编辑动作按正式登记 ID 重新读取记录，读取失败时停止编辑。
- 接口快照没有 VRF 时显示“VRF 待确认”，不从 Global Prefix 推断其路由域。
- 地址推荐/自动分配的实现现以当前页面共同数据源为准：活动 `network_endpoints`、每设备最新成功的 CMDB 接口快照，以及正式登记地址。已解析到同 tenant/VRF 的端点按地址空间占用；VRF 未知但 tenant/site 明确的当前页面观测只保留其具体 IP，并提供去重后的 `pending_discovery_count`。
- `GET /api/ipam/subnets/{subnet_id}/next-available-ip` 保留 `next_available_ip` 字段并增加 `pending_discovery_count`。地址推荐界面用提示条显示待确认观测地址数量。
- 网关候选接口数据不含 VRF 时，唯一候选也改为 `scope_pending` 且 `selected=null`；PrefixManagement 页面显示待确认说明，不再自动写入网关设备/接口。人工选择会保留。
- 手工登记策略：用户确认方案 A，显式 `create_address` 可登记待确认观测 IP；临时保留仅约束自动推荐/自动分配，不新增确认 API。
- VIP/Lease 的首批 scope 切片已完成：新 VIP 必须选 Prefix，空间/租户由服务端派生并做同空间地址冲突检查；旧 VIP 留作待确认。DHCP lease 始终是外部观测，无 Pool 时不阻塞静态分配；只有明确关联 active `external_dhcp` Pool 后才保存空间范围，Pool 本身的外部地址段阻止静态分配。租约来源 `external_id` 在 tenant/server 作用域内幂等；列表及 CRUD 按 Prefix/Pool 的 tenant/site 范围授权。
- 2026-11-05 本轮本机 PostgreSQL 只读当前数据盘点：60 条 Prefix 分布于 2 个站点，全部无 VRF；按 tenant/VRF/CIDR 有 26 组跨站点重复（共 52 条 Prefix），站点内重复为 0；正式 IP、活动 endpoint、Pool、VIP、DHCP lease 均为 0。
- 每设备最新成功接口快照有 33 条带 IP 观察，来自 9 台设备、33 个不同 IP；快照无 VRF 字段。本次查询没有读取历史 discovery observations。
- `get_next_available_ip_details` 的 `has_available_after` 变量已在函数本地计算并供两个登记地址查询共用，修复此前有效 Prefix 请求触发的 `NameError`。
- 该函数 docstring 已改为描述当前页面范围待确认地址；`_discovered_address_reservations` 保留空 tenant 防护，避免 whitespace-only scope 经规范化后变成空字符串。
- 计划中 F5 已校正：IPv4 `/31`、`/32` 的两个候选来源一致；真正的差异在 IPv6 前缀短于 `/127`，推荐接口跳过 network address、自动分配 `iter(net)` 会包含它。
- current-only FHRP 采集、运行态投影与正式 HSRP/VRRP/Anycast group/member/VIP 管理已接入；明确地址空间的 FHRP VIP 才进入当前占用，scope 未知时保留在站点/租户待确认集合。
- current FDB 端点的表格、详情和 CSV 增加路径说明；LAG、聚合成员、trunk/tagged、拓扑邻居链路、显式接入口和未知路径分别呈现，虚拟网关 MAC 保留为 MAC-only 观察，不合并或生成 IP owner。

## 改动文件

- `backend/services/ipam_service.py`
- `backend/api/ipam.py`
- `backend/tests/ipam/test_ipam_allocation_policy.py`
- `backend/tests/ipam/test_prefix_batch_and_gateway_candidates.py`
- `backend/tests/ipam/test_ipam_interface_snapshot_candidates.py`
- `backend/tests/ipam/test_ipam_inventory_scope.py`
- `backend/tests/ipam/test_ipam_inventory_cmdb_snapshot.py`
- `src/pages/IPVlan/IPAddressTab.tsx`
- `src/pages/IPVlan/IPAddressTab.edit.test.ts`
- `src/pages/IPVlan/PrefixManagementTab.tsx`
- `src/pages/IPVlan/PrefixManagementTab.test.tsx`
- `src/pages/IPVlan/prefixGatewayBinding.ts`
- `src/pages/IPVlan/prefixGatewayBinding.test.ts`
- 本任务计划与走查文件。

P2a 当时新增了 address-space 数据库迁移代码；后续 2026-11-09 的只读核验发现本机应用数据库 `schema_migrations` 已记录到 317，但自动应用来源未确认。没有回填 IPAM 业务数据，也未查询/修改历史快照清理服务；生产数据库未操作。

## 已完成验证

- `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_interface_snapshot_candidates.py backend/tests/ipam/test_ipam_allocation_policy.py backend/tests/ipam/test_ipam_inventory_scope.py backend/tests/ipam/test_ipam_inventory_cmdb_snapshot.py`：**50 passed / 422.84s**。完整摘要见 `logs/validation/ipam-r1-backend-20261105_1600.log`；包装器确认没有打开配置的应用数据库，并删除临时 source DB。
- `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_prefix_batch_and_gateway_candidates.py`：**7 passed / 117.05s**。完整摘要见 `logs/validation/ipam-r1-gateway-20261105_1615.log`。
- `node node_modules/vitest/vitest.mjs run src/pages/IPVlan/PrefixManagementTab.test.tsx src/pages/IPVlan/IPAddressTab.edit.test.ts src/pages/IPVlan/prefixGatewayBinding.test.ts`：3 个文件、13 项通过。
- `npm run lint -- --pretty false`：通过。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 项策略违规。
- 限定本任务源文件的 `git diff --check` 与计划/walkthrough/handoff/新增测试的 trailing-whitespace 检查：通过；Git 只提示部分文件 LF/CRLF 标准化。
- `node node_modules/vite/bin/vite.js build --outDir node_modules/.cache/nexora-ipam-r1-20261105-gateway`：成功，4360 modules transformed。
- P2a 隔离 PostgreSQL：五个核心回归文件 **57 passed**；随后完整 `backend/tests/ipam` **124 passed**。隔离 runner 确认未打开配置应用数据库，并删除临时测试 source database。
- P2a 前端 `PrefixManagementTab.test.tsx`：**12/12 passed**；`npm run lint -- --pretty false` 通过；4360 modules 的 Vite build 成功并输出到 `node_modules/.cache`。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：**0 violations**。路径限定 `git diff --check`、`py_compile` 与新增/更新源文件的 trailing-whitespace 检查通过（Windows 换行提示不影响结果）。
- P2b.1 最终隔离回归：`test_ipam_allocation_policy.py` **31 passed / 322.81s**；隔离 runner 确认未打开配置应用数据库，临时 source DB 已删除。该次变更后的 PostgreSQL-only scan 为 0 violation，`py_compile`、`git diff --check` 通过。
- P2b.2 完整隔离回归：`backend/tests/ipam` **158 passed / 1159.18s**，runner exit code 0；未打开配置应用数据库并清理临时 source DB。Pool 与 IP 地址页定向 Vitest 合计 **21/21 passed**，全局 TypeScript lint 通过。
- P2b.2 集成静态：PostgreSQL-only scan **0 violations**、后端 `py_compile`、path-scoped `git diff --check`、任务文档/新增文件 trailing-whitespace 通过；4360 modules 的 Vite build 成功，输出位于 `node_modules/.cache/nexora-ipam-p2b-20261105-final`。
- P2b.3 最终隔离回归：完整 `backend/tests/ipam` **166 passed / 1097.86s**；未打开配置应用数据库，临时 source DB 已删除。VIP/Lease 前端定向 Vitest **16/16 passed**；Pool/IP 页面定向测试 **21/21 passed**；全局 lint、PostgreSQL-only scan（0 violations）、`py_compile`、路径限定 `git diff --check`、新增文件空白检查通过；4360-module Vite build 成功并输出到 `node_modules/.cache/nexora-ipam-p2b3-20261105-final`。
- P2b.4 最终全量回归：隔离 `backend/tests/ipam` **176 passed / 1259.37s**；runner 未打开配置应用数据库，临时 source DB 已删除。IPAM 前端 6 个定向 Vitest 文件 **57/57 passed**；`npm run lint` 通过；4360-module Vite build 输出到 `node_modules/.cache/nexora-ipam-p2b4-20261106-final`。PostgreSQL-only scan **0 violations**，后端 `py_compile` 与路径限定 `git diff --check` 通过。
- P3 首次快照失败回退复核：`test_ipam_interface_snapshot_candidates.py` **5 passed / 112.61s**；隔离 runner 确认未打开应用数据库并删除临时 source DB。
- P3 endpoint scope 保守化：`test_ipam_inventory_scope.py` **23 passed / 222.40s**；空/default/global/public 未映射值不会在 IP 地址库存展示中匹配 Global Prefix。该测试只写当前 `network_endpoints` 缓存，不写/读历史发现表；隔离 runner 确认未打开应用数据库并删除临时 source DB。
- 旧 build 输出 `dist-ipam-r1-20261105-1556` 的清理：`Remove-Item -Recurse` 被自动审查以 `blocked by policy` 拒绝。没有改用其他删除方式；该目录仍未跟踪且未被 `.gitignore` 忽略，勿暂存或提交。G05 最新构建写入被忽略的 `node_modules/.cache/nexora-ipam-r1-20261105-gateway`。

## 未完成与剩余风险

- F3 方案 A 已由用户确认：允许显式手工登记，自动推荐/自动分配仍会跳过待确认 IP；若未来要求后端强制确认需另批实施。
- F4 持锁全量读取活动 endpoints 与接口 IP 的性能风险已写入计划：本地为 0 个活动 endpoint、33 个当前接口 IP，不能代表生产规模。
- 不要读取、清理、回填历史发现表或其它历史快照。
- 未进行浏览器手工验收、真实设备连接、生产迁移、部署、提交或推送。

## P2a 地址空间改动摘要

- 新增 `ipam_address_spaces` 表和 `ipam_address_space_service`。VRF 仍是权威对象，空间映射由服务端按租户校验并保持一对一；VRF 创建与空间映射同事务。
- Prefix/IP 开始携带 `address_space_id`。新建 Prefix 要显式选择 Global 空间或 VRF；未知旧 Prefix 需要查看影响预览并确认，确认时校验版本并记录审计。
- Migration 只映射租户一致的明确 VRF。空 VRF 与跨站点同 CIDR 歧义 Prefix 保持 unmapped/pending，不按站点、名称或唯一 CIDR 猜成 Global。
- Prefix 直接写入、接口候选、列表与前端映射交互采用同一空间身份。冲突查询有跨 Prefix 正式地址占用和 address-space 锁基础；大网段 next-free 使用跳跃式候选，不遍历整个地址空间。
- `test_ipam_address_spaces.py` 和完整 IPAM 测试通过；前端支持在映射流程内创建 Global 地址空间，再预览并确认映射。

2026-11-05 的原始 P0 快照显示 60 个旧 Prefix 全部无 VRF，其中 26 组跨站点重复；该快照仅是历史记录，不代表已映射。

2026-11-09 已重新只读盘点当前页：Prefix 60、IP/活动 endpoint/Pool/VIP/Lease 均 0、最新成功接口 IP 33（9 台设备）、26 组跨站点重复；address-space、VRF、device-local routing-context mapping 均 0，ARP/ND/FDB current rows 均 0。无显式目标空间时，60 个 Prefix 都留待人工映射，不能建默认 Global。迁移预览、影子比对和试点尚未进行。

## P2b.1 候选与写入规则收敛

- 推荐地址和自动分配现在调用相同的当前占用收集与 `_first_free_address` 规则，稳定状态下首个候选一致；保留按已占 host 排序跳过的算法，不枚举整个 IPv6 网段。
- IPv4 常规前缀跳过 network/broadcast，`/31`、`/32` 两端可用；IPv6 `/64` 等 `/127` 以下跳过 subnet-router anycast/network address，`/127` 与 `/128` 保留首地址。对应 `/64`、`/127`、`/128` 的推荐/分配一致测试通过。
- `ReservationRequest` 和服务层 create/reserve 只接受裸 host，拒绝 `address/mask`，不再静默截去掩码。接口快照 `ip_prefix_length` 仍独立保存。
- 自动推荐/分配继续把匹配站点的未知观察 IP 当作临时占用；按照用户确认，手工登记可显式认领该地址，不新增确认 API。
- 映射空间里的 Prefix gateway 会统一阻止普通 host 登记与分配；只允许当前 Prefix 上合法配置的 gateway role 登记其自身网关。无效的 gateway 配置不会错误冻结地址。

## P2b.2 Pool/Range 与分配闭环

- 新增 m0309：Pool 只从已显式映射且租户一致的 Prefix 派生 `address_space_id`；无法识别管理策略的旧 Pool 保持 `policy_pending`、不可自动分配。迁移对已映射空间里的非法/重叠 Pool 范围失败关闭；没有回填或重写 discovery history。
- Pool API 服务器从父 Prefix 解析 tenant/space，不接受前端 tenant 或 address-space override。列表/更新/删除和按 Pool 分配均按父 Prefix 做 tenant/site resource scope。Prefix 显式映射的 impact preview 包含 Pool 样例和冲突，确认时在同一事务检查租户/范围并更新 Pool space。
- 同空间 Pool/Range 跨父子 Prefix 做包含端点的 overlap 校验并使用 address-space lock。Prefix 分配跳过 policy pending、reserved/external、allocation disallowed、populated 和非 active 范围；指定 Pool 后候选只在 Pool 区间内。
- 新建 Pool 必须选择管理方式：`local_static`、`reserved`、`external_dhcp` 或 `external_other`。`allocation_allowed`、`mark_populated` 和 `mark_utilized` 分开配置；非 active status 暂停分配；`mark_utilized` 不阻止分配。将 Pool policy 变成阻断规则前，如果区间已有正式活动 IP，API 会拒绝静默变更并返回样例。
- IP 地址表单只展示符合条件的 active 本地池。选择池后 next-available 和创建/预约请求都带相同 `pool_id`，后端核验空间、状态、管理策略、范围和权限；切换 Prefix 会清空选择。Pool API 失败时，页面不假设池列表可用。
- 手工登记 VRF-pending observation 仍遵守用户批准的方案 A；若明确 Pool policy 阻断，则按该正式规则拒绝登记。

## P2b.3 VIP/Lease scope 首批切片

- Migration `m0310` 为 VIP 增加显式 `prefix_id`、`address_space_id` 和 inet 地址字段，为租约增加 Pool/space/source identity/scope 状态；已有 VIP/租约不推断空间、不回填历史观察。
- VIP 是正式地址：创建必须指定 Prefix，租户与地址空间由后端推导；更新/删除也重新检查 Prefix 和空间。有效状态 VIP 只在同一地址空间与正式 IP/VIP 检查冲突，`released`、`deprecated`、`disabled` 不占用；跨空间同一 host 可以存在。
- DHCP lease 仅是观测：无 Pool 的记录保持 scope pending，不阻塞静态地址；选择 Pool 时只接受 active、范围包含地址、tenant 一致的 `external_dhcp` Pool。外部 DHCP Pool 范围仍是静态分配屏障。`external_id` 作用域为 tenant/server；清空 Pool 会清除 space 并回到 pending。
- VIP 与 Lease 列表、创建、更新、删除补上 Prefix/Pool 的 tenant/site 鉴权；页面展示 scope 状态，VIP 必须选择 Prefix，Lease 可以显式选择外部 DHCP Pool。
- 验证：P2b.3 首批切片隔离 IPAM **166 passed**；VIP/Lease UI **16 passed**；Pool/IP UI **21 passed**。P2b.4 随后补齐全域锁序、request 幂等键、revision、正式 assignment 外键与同事务审计，详见下一节；最终完整 IPAM 回归 **176 passed**。

## P2b.4 写入并发与事务一致性

- 所有正式资源写路径统一按地址空间 advisory lock、按 ID 排序的 Prefix 行、再到资源行加锁；多 Prefix 操作先读 scope 候选，再批量锁 scope、Prefix，并核对锁后身份未漂移。修复了地址删除/释放复用和 Prefix 删除/地址登记的行锁逆序；接口批量前缀生成在检查和写入前锁定所有已确认空间。
- Migration `m0311` 增加 Prefix/IP/Pool/VIP/Lease 的单调 `revision`，新增 nullable `ip_addresses.pool_id` FK（删除 Pool 受限），以及 device/interface 外键（`NOT VALID`、删除时清空引用）。旧不一致引用保留供显式治理，不做回填；新写入校验设备存在、接口存在且接口归属所选设备，清空引用落 `NULL`。
- 新增幂等记录表，scope 为 tenant + operation + key，保存规范化请求 hash 和首次 JSON 响应。前端 create/allocate/reserve/generate 请求带 `Idempotency-Key` 并在失败重试时复用；同键不同 payload 返回冲突。记录与业务数据同事务。
- Prefix/IP/Pool/VIP/Lease 更新和删除使用 `expected_revision` 做乐观并发检查；批量 Prefix 删除收集全部 scope/Prefix，校验全部版本后在一个事务内删完。地址、Pool、VIP、Lease、Prefix 生成、更新和删除的审计事件写入同一事务；失败会回滚业务数据。
- 直接 IP 写入方（对账释放/更新、CMDB 接口回填、MAC 校准、legacy ip_inventory 导入）已适配 nullable assignment 和 revision。
- 验证：并发 last-IP 抢占/锁序用例、幂等/冲突、revision stale、审计失败回滚、migration/FK 保留行为与单元测试均在完整套件中通过；`backend/tests/ipam` **176 passed**；前端 **57 passed**，lint、Vite build、PostgreSQL-only scan 及静态检查通过。

## P3 current ARP/CMDB 首批实现（2026-11-06）

- 新增 migration `m0312`–`m0317`：device-local routing context 映射；最新成功 CMDB generation 的多地址接口观察；按 device/source/context 分区的 current ARP/FDB/ND 行与 collection state；unknown context 原始键兼容；ARP IPv4、ND IPv6 数据库地址族约束。接口地址迁移仅采用最新成功代次，不扫描/回填 IPAM 历史 discovery observations。
- ARP collector 对显式映射的 SNMP VRF/global context 分别采集并先登记尝试代次；complete/complete-empty 与明确 `scope_unknown` 才替换该上下文当前行，partial/failed/unsupported 保留上次成功数据。未知别名不折叠为 Global。
- FDB current store 与 ARP 分开保存，不回填 legacy `mac_table` 或旧 discovery 表。SNMPv3 按 active mapping 的精确 context key 分上下文采集；多上下文未全覆盖时标 partial，不替换无法表达上下文的 legacy 整设备缓存。SNMP/CLI 状态分开；CLI 命令后才发现 raw key 时保留预留状态为 partial，不为事后 key 建 generation。
- Q-BRIDGE 只有两张主 FDB 表都完整为空且四个 full walk 都成功时才作为 complete-empty；一表为空一表非空、walk/索引/映射失败时保留上次成功。明确 complete-empty 的 legacy current `mac_table` 清理只影响对应设备当前行。
- CMDB CLI context parser 将 generic alias 作为 unknown 原样保存；明确的本地 VRF key 只有人工映射后才归属空间。
- 当前分配库存与 IP 库存读取最新 ARP 行及最新成功接口地址。Reconciliation 按 `(tenant, address_space, IP)` 比较；未映射行进入 pending/unscoped；相同 IP 跨空间独立，来源位置只按完全相同 identity 去重。
- Current endpoint API 已切到 current ARP projection；登记仅允许 active、明确空间 Prefix，已解析观察必须落入其映射空间。登记/校准先锁空间，再锁 Prefix、空间行与 IP，并复核观测时间、归属漂移与租户。
- 前端发现终端页移除“历史观察”筛选；“仅 MAC 观察”读 current FDB，并显示“未创建 IP”、范围待确认与多路径歧义。列表、详情、CSV 区分 ARP、IPv6 ND 与 FDB/MAC；unknown context 不推断 Global。
- 发现终端页的“范围待确认”筛选按 `scope_status` 过滤；current endpoints API 不再接受 `historical` evidence status，保持只读当前 ARP/ND/FDB 投影。

### P3 首批涉及文件

- 后端：`backend/api/ipam.py`、`backend/main.py`、`backend/services/ipam_discovery_service.py`、`ipam_service.py`、`ipam_current_endpoint_observation_service.py`、`ipam_current_ndp_collection_service.py`、`ipam_current_fdb_observation_service.py`、`ip_locator_service.py`、`snmp_service.py`、CMDB 当前快照服务与 `m0312`–`m0317` migration。
- 验证：新增 `backend/tests/ip_locator/test_current_ndp_collector.py`、`backend/tests/ipam/test_ipam_current_ndp_observation_store.py`；复跑 ARP/ND reconciliation、allocation、endpoint API 与现有 ARP/FDB/Q-BRIDGE contract。
- 前端：`src/pages/IPVlan/DiscoveredEndpointsTab.tsx`、`ipamDiscoveryPresentation.ts` 及对应测试；来源呈现定向 **20 passed**，`npm run lint -- --pretty false` 通过。

### P3.2 IPv6 ND current-only 采集与投影（2026-11-09）

- `snmp_service.collect_ipv6_neighbor_table()` 读取 IP-MIB `ipNetToPhysicalTable` 的 physical-address/type/state 全列，要求完整 walk 且 row key 集合一致；校验 IPv6/IPv6z 地址索引、MAC、状态/类型与 ifIndex 接口映射。成功空结果只在三列完整且一致时成立。
- `ipam_current_ndp_collection_service.run_current_ndp_collection()` 是独立 current-only 任务。SNMPv3 active context 映射按 local key 分组，一 key 一次请求；唯一映射按明确 VRF/Global 归属，重复 key 保留 unknown 并报 partial。v1/v2c 不猜上下文；失败、部分、不支持保留上次成功。generation 在设备 I/O 前提交。
- `backend/main.py` 单独注册 ND scheduler，不经过 `run_endpoint_fact_collector()` 历史投影包装器。NDP 观察与 ARP 共用 current store，但 source 隔离；数据库 constraint 固定 ARP 仅 IPv4、ND 仅 IPv6。对账读取 current ARP 与 ND collection states/rows，失败状态会降低 coverage。
- inventory 与 endpoint current APIs 已包含 ND 行；观察仍不是正式所有权，未解析范围进入 pending。发现终端列表、详情和 CSV 双语区分 ARP、IPv6 ND、FDB/MAC。
- 不运行真实设备采集，也未主动对配置数据库执行 `m0317`；生产库未查询、迁移或操作。
- P0 read-only refresh 显示本机 `netops` schema 版本已为 317，`ipam_current_ndp_observations` 记录在 2026-11-09 17:54:05（Asia/Shanghai）应用。当前数据库的 source/address-family constraints 与 m0317 现有定义一致，current ARP/ND/FDB 行均为 0。此 Agent 没有运行迁移命令，自动应用的触发来源尚未确认；未对生产库做任何操作。

### P3.3 FHRP current collector、正式组关系与页面（已实现，待整体验收）

- `backend/services/ipam_fhrp_parser.py` 新增 Cisco IOS 的 `show standby brief` 与 `show vrrp brief` 解析，支持可选 HSRP `P` 列、IPv4/IPv6 以及重复 group ID 分接口保留。无法识别的设备/命令返回 unsupported；畸形/截断返回 partial；brief 未提供的 virtual MAC 与额外 VIP 不推算。
- `backend/tests/vendor_audit/test_ipam_fhrp_parser_contract.py` 原 parser 切片 **19 passed**；R28 在此基础上接入 current collector/scheduler、current projection、正式 group/member/VIP 关系、API/UI 与 FHRP 地址占用。parser 单测不是 A24/A25 的唯一验收证据。
- m0318 已在本机应用库记录为已应用；原因是本轮一次普通 `python -m pytest` 触发项目全局 `backend/tests/conftest.py` 中的 `database.init_db()`。只读核验确认新建的 `ipam_current_fhrp_collection_states` 与 `ipam_current_fhrp_observations` 均为 0 行。之后不得用普通 pytest；持久化测试统一使用 `run_isolated_pytest.py`。
- `backend/main.py` 单独注册 current-only FHRP hourly job；当前采集器只使用解析器明确支持的 Cisco IOS 命令/平台。真实设备兼容性尚未验证，未启动应用服务或设备连接。
- `m0319_ipam_fhrp_groups.py` 定义正式组、设备/接口成员和既有 VIP 关联。group/VIP 写入服务校验 tenant、显式地址空间、协议、地址族和 active 状态；绑定中的 VIP 不允许删除、释放或转成非活动状态。API 对列表/详情关系执行站点/RBAC 过滤，前端按需加载详情。
- `/api/ipam/fhrp/groups/{id}/current` 只读取 current FHRP observation 并与显式成员匹配；unknown scope 留待确认，scope mismatch 不显示无权限地址空间信息，运行态变化不修改正式 group/VIP 关系。
- 前端提供 HSRP/VRRP/Anycast 组管理、成员与既有 VIP 绑定及运行状态/coverage 展示；VIP 页新增 Anycast 类型。`test_ipam_fhrp_groups.py` 隔离 PostgreSQL **20 passed / 292.13s**，测试 runner 确认未打开配置应用数据库并删除临时 source DB。

### P3.4 FDB 路径解释与地址规则补验（部分完成）

- FDB 仍只作为 MAC-only 事实。分类结合当前接口 inventory 的 channel-group/父子接口及 up/degraded topology links，分别标注逻辑聚合、聚合成员、trunk/tagged、邻居链路、拓扑聚合链路、显式 access 和 unknown；trunk 本身不证明唯一 edge port。
- 当前页面、详情与 CSV 展示分类和依据，标准虚拟网关 MAC 只标记为虚拟网关 MAC；重复 MAC/VLAN/多路径继续保留并显示歧义，不跨设备合并、不补造 IP。
- A23/A26/A28/A29 定向隔离回归 **6 passed / 157.35s**：覆盖同站点同网关 host 的地址空间隔离、LAG/member/trunk 与虚拟 MAC 区分、释放 quarantine 到期行为、过期或无 scope DHCP lease 不释放静态 IP。移动历史与跨时段路径跟踪不做，符合只对当前页面数据负责的范围；A26 仍部分验收。
- A27 的无资产映射边界有 UI 回归：current FDB 有 MAC/路径时只显示“MAC 观察（未创建 IP）”，不创建 IP 也不宣称资产归属；该测试包含在本轮 46 项前端通过结果内。

### P3 已完成的定向验证

- current ARP collector 文件 **9 passed**；包含 complete-empty 单上下文替换与未知 alias 保留测试。相关隔离 runner 未打开配置应用数据库并删除临时 source DB。
- FDB collector 集成后再次重跑同一 ARP collector 文件：**9 passed / 124.67s**，隔离 runner 未打开配置应用数据库并删除临时 source DB。
- current endpoint allocation **3 passed**；CMDB raw-context/未知键、current observation store 与 `m0315` migration 组合 **6 passed / 34 deselected**；current scope SQL guard **1 passed**。
- current endpoint API **1 passed**；current ARP reconciliation/no-history SQL guard **1 passed**；现有 reconciliation current-source 回归 **1 passed / 3 deselected**。登记/校准跨空间拒绝、Prefix 不明确拒绝、scope 漂移和 stale observation 均有断言。
- FDB collector/SNMP 合同定向隔离套件：`test_fdb_current_projection_collector.py` + Q-BRIDGE contract 与两个旧 FDB 解析/unsupported 用例 **16 passed / 172.20s**；覆盖 exact SNMPv3 context、begin-before-I/O、失败保留、complete-empty、SNMP/CLI 状态分离、raw CLI key fencing 和 legacy cache 目标设备清理。测试 runner 使用隔离 PostgreSQL，未打开配置应用数据库，也未连接设备。
- FDB current store migration/state/读写 **3 passed / 129.03s**。current FDB store/API、ARP reconciliation 与 allocation 合并隔离回归 **8 passed / 125.74s**；覆盖双端口同 MAC/path ambiguity、scope pending filter、MAC-only 登记拒绝和 current/no-history SQL guard；隔离 runner 未打开配置应用数据库并删除临时 source DB。
- current ND collector/store/migration、ARP/ND reconciliation、current endpoint API 与 allocation 合并隔离回归 **23 passed / 361.46s**；覆盖 IP-MIB IPv6/IPv6z index 与列完整性、SNMPv3 context 唯一/歧义、unknown scope、完整空表、partial/failed 保留、generation fencing、no-history projector guard、ND API/inventory/reconciliation。
- ARP vendor/Q-BRIDGE/FDB 邻近合同合并隔离回归 **75 passed / 390.39s**；补齐 ARP normalizer context 字段精确断言后全通过。上述隔离 runner 均未打开配置应用数据库并已清理临时 source DB。
- ND 来源 UI 两个定向文件 **20 passed**；全局 `npm run lint -- --pretty false` 通过。PostgreSQL-only scanner **0 violations**，涉及后端 py_compile 与 path-scoped diff-check 通过。
- R28 FHRP 关系与 current projection：`test_ipam_fhrp_groups.py` **20 passed / 292.13s**；包装器显示配置应用数据库未打开，临时 PostgreSQL source DB 已删除。覆盖 m0319 fresh/repeat install、HSRP/VRRP/Anycast 成员与 VIP、master/backup current 状态切换、scope/RBAC/idempotency/revision、VIP 状态和删除护栏。
- R28 当前规则回归：A23/A26/A28/A29 定向隔离测试 **6 passed / 157.35s**；包含两地址空间同站点同网关隔离、FDB LAG/member/trunk/virtual MAC 路径区分、quarantine 到期前后分配、lease 到期或缺 scope 不释放静态 IP。runner 未打开配置应用库并删除临时 source DB。
- R28 前端 5 个定向 Vitest 文件 **46 passed**（FHRP groups、VIP Anycast、discovered endpoint path、presentation、route context）。首次运行中的两条旧列名/CSV 表头断言已改为“观察接口与路径”；更新后全部通过。`npm run lint -- --pretty false` 通过，4362-module Vite build 成功，最终输出到 `node_modules/.cache/nexora-ipam-p3-final-20261109-2013`。
- R28 源码与文档 path-scoped `git diff --check`、相关后端 `py_compile`、PostgreSQL-only scanner **0 violations** 均通过；未打开应用服务或执行设备连接。m0319 未应用到应用库。
- 旧 endpoint collector 兼容用例 **2 passed**；ARP vendor contract 用例 **3 passed**。PostgreSQL-only scanner **0 violations**，目标文件 `py_compile` 与 path-scoped `git diff --check` 通过。
- 本轮末尾对未映射 context 身份分组补入 `context_type`，以免同 device/source/key/IP 的 unknown 与 explicit-VRF 两种原始上下文被错误合并。`test_ipam_current_endpoint_api.py` **1 passed / 83.44s**；隔离 runner 未打开配置应用数据库并已删除临时 source DB。

### P3 未完成与限制

- current FDB rows 已能展示为 MAC-only 观察；不创建或占用 IP，unknown/ambiguous scope 不推断 VRF/Global。FDB 当前路径不替代 IPAM address ownership。
- FHRP 正式关系与 current runtime 已实现，但真实平台覆盖、浏览器验收和全量 P3 覆盖矩阵仍未完成；A24/A25 待整体验收。FDB 路径分类已增强，但尚不能证明跨设备唯一 edge port；移动历史按当前数据范围不保留，A26 部分完成。A27 展示规则已覆盖，仍需纳入 P5 全矩阵复核。
- IPAM 全套后端回归已 263 passed；ARP/FDB/ND/FHRP collector/vendor 组合 137 passed。完整 `backend/tests`（非 IPAM 模块）未跑；本次 IPAM 前端 149 项、TypeScript lint 与 Vite build 已通过。实时浏览器、主流设备现场样本仍未验收。
- 本 Agent 未手动执行迁移命令；只读核验显示本机应用数据库已记录 m0317 和 m0318，触发过程分别在本文中记录。生产库未查询或操作；未连接真实设备、未部署、未提交/推送。

## 下一步

1. 完成 P3 剩余端到端审查、真实平台支持边界说明和浏览器 QA；对未支持平台明确标记 coverage gap，不推断 scope、不伪称完成。
2. 完成后进入 P4：只围绕当前正式台账和当前页面来源制作迁移 preview、影子比对、试点监测与回滚；不读取/回填 discovery history，不对应用/生产库执行 migration。
3. P5 对计划内 A01–A36 初始状态逐项复核并补齐测试/浏览器证据、隔离回归、用户操作和管理员排障说明。提交、推送、生产迁移与部署仍需授权。
4. `dist-ipam-r1-20261105-1556` 仍是未跟踪、未忽略的旧验证产物；保留自动审查限制记录，不暂存或提交。


## 2026-11-09 P1–P3 最终回归收口

- 当前执行位置为 D:\netops\netsops-main 的 main；代码、测试和记录均在该工作区。没有在 safe worktree 中继续写入。
- 最终自动化证据：隔离 backend/tests/ipam 263 passed / 905.92s；ARP/FDB/ND/FHRP collector、parser 和 vendor contract 137 passed / 237.15s；前端 IPAM 149 passed / 20 files。持久化测试都通过临时 PostgreSQL runner 执行，runner 未连接应用库。
- 静态门禁：npm run lint -- --pretty false、4362-module Vite production build、scripts/validate_postgresql_only.py（0 violations）、目标后端 py_compile 均通过。
- 当前页范围的 P1–P3 实现和聚焦自动化回归已收口。浏览器运行态、真实设备样本、A01–A36 全量证据矩阵和代表性规模性能门禁列为后续验证，不把源码/测试通过写成现场验收通过。
- P4 映射仍无可执行目标：只读基线为 0 address-space、0 VRF、60 条 Prefix 全部未映射；不得按站点、名字、历史快照或 CIDR 唯一性猜测 Global/VRF。
- m0319 未应用；本机应用 PostgreSQL 当前不可用，5400/15310 未启动。未做浏览器/设备访问、迁移、部署、提交或推送。

## 2026-11-09 P1 address-space uniqueness fix and startup diagnosis

- 发现 _init_db_logic 的旧唯一索引在迁移 m0308 已完成后仍会于每次启动时重建，按 tenant/VRF/address 而非 address_space_id 限制地址，可能使相同 host 跨显式地址空间在应用重启后无法新增。schema baseline 现在只重建 address_space_id 为空的 legacy partial index；新迁移 m0320 删除旧索引。baseline 不提前创建 migration-owned address_space_id，避免 fresh install 的 m0308 外键列被 ADD COLUMN IF NOT EXISTS 跳过。
- detect_conflicts 现在只在显式 address-space 内分组 IP/MAC 冲突；子网风险提示按 address_space_id 与 Prefix ID 匹配，未知空间不跨域挂风险。
- 回归：backend/tests/ipam/test_ipam_conflict_scope.py **2 passed**，覆盖 m0320 升级幂等、baseline 重启不重建旧索引、fresh schema 外键保留、跨空间相同 IP 可登记、同空间真实冲突仍识别。完整 IPAM **265 passed / 814.29s**；5 个 collector/parser/vendor 合同 **101 passed / 121.56s**。TS lint/build、scanner、py_compile、diff-check 通过。
- 启动故障诊断：dev-internal.mjs 的初始 readiness 失败后按设计拉起 backend；database.core._ensure_database_exists 连接 127.0.0.1:5432 时收到 server closed the connection unexpectedly，FastAPI lifespan 随后退出。日志显示 5400/15310 未监听，5432 pg_isready 无响应；Windows 服务显示 Running，但 pg_ctl status 为 no server，postmaster.pid 记载旧主进程 PID 6572/ready，pg_controldata 显示 cluster state in production、最后 checkpoint 20:50:38。
- PostgreSQL 日志最近到 20:51:13 为客户端连接被强制关闭；此前 20:13:40 在 DROP DATABASE ... WITH (FORCE) 期间出现 backend PID 21056 ProcSignalBarrier 等待。没有发现 FATAL/PANIC 或 Windows Application Error 可确认具体崩溃原因；这些是异常线索，尚不能断言因果。
- 当前用户已授权在 P1–P3 回归结束后恢复本机 PostgreSQL，并要求启动服务后用浏览器打开 http://192.168.56.1:5400/ 验收，再关机。恢复及浏览器验收尚未执行。

## 2026-11-09 PostgreSQL 服务恢复与浏览器验收阻断

- 最终 P1–P3 自动化回归：backend/tests/ipam 265 passed / 814.29s；5 个 collector/parser/vendor 合同 101 passed / 121.56s；IPVlan 前端目录 138 passed / 20 files，DeviceRoutingContext 与 conflict-scope 定向 9 passed / 2 files。TS lint、4362-module Vite build、PostgreSQL-only 0 violations、py_compile 和路径限定 diff-check 通过。
- 已按用户授权尝试重启应用 PostgreSQL Windows 服务。PowerShell 返回 Cannot open postgresql-x64-18 service；服务报告 Running，但 5432 的 pg_isready 无响应，pg_ctl status 无 server。没有结束服务进程、改写/删除 postmaster.pid 或手工开同一数据目录。
- 这轮停止了自己的 55432 临时测试 PostgreSQL；临时数据库已清理。应用 PostgreSQL 尚未恢复，dev-internal 的自动重试 supervisor 仍由用户启动，不启动第二个 supervisor。
- CUA browser tool 返回 Transport closed；页面尚未打开。恢复服务后还需验证 API health healthy/database connected，再通过浏览器实际打开 http://192.168.56.1:5400/。用户要求浏览器通过后再关机；当前尚未关机。

## 2026-11-09 PostgreSQL 服务恢复及浏览器首页最终验收

- 在提升权限下对已完成 crash recovery 的孤立 PostgreSQL 进程执行 fast shutdown，然后启动 Windows service postgresql-x64-18。服务 Running/Automatic，pg_isready accepting；应用配置连接 SELECT 1 成功，schema_migrations 最新为 320。
- 原 dev-internal supervisor 自动恢复前后端；15310/api/health 返回 200，status=healthy、database=connected、scheduler=running、worker=active；5400 返回 200，title Nexora，root 元素存在。
- Codex NodeRepl 的 Playwright 驱动 Edge 实际打开 http://192.168.56.1:5400/：HTTP 200、title Nexora、document.readyState=complete、#root=1、登录按钮可见、pageErrors=0。匿名访问受保护的 /api/tags/definitions 返回预期 401；未输入账号密码。CUA transport closed，因此采用 NodeRepl Playwright 验收。
- 最终关机仍由用户当前目标要求；前后端和浏览器条件均通过后执行。生产库未操作；真实设备样本、P5 全量证据矩阵及 P4 映射仍待后续阶段。

## 2026-11-11 当前 ARP/FDB 到接入端口联动

- 只读正式库复核 VLAN 7 对应数据：S6850-5 current ARP 代次 20（最近成功 `2026-11-11 02:08:54 +08`），`172.16.5.10 → 8e47-5760-0706 / Vlan-interface7`；current FDB 代次 18（同一最近成功时间），`8e47-5760-0706 / VLAN 7 → GigabitEthernet1/0/2`。两条记录均为 SNMP、unknown context、最新尝试成功；当前接口快照为物理端口、`access VLAN 7`、描述 `TO-PC-7`。查询使用只读事务，未访问历史 discovery 表。
- 根因：IP Locator V2 的 SNMP endpoint 快路径仍读旧 discovery projector，未用 current-only IPAM ARP/FDB 数据；无结果时还会调用 legacy endpoint collector，可能写入 `network_endpoints`/`endpoint_history`，不能可靠使用 VLAN 页面现有 current 记录。
- 实现：`ip_locator_endpoint_evidence.py` 新增 current-only ARP/FDB 唯一关联；验证 current generation、latest successful status、recent timestamp、tenant/site/RBAC、MAC/VLAN/context、物理 Access 接口，并拒绝虚拟网关 MAC、scope 歧义和多端口。Unknown scope 保持 unknown，仅允许同设备同 raw context 关联，不推 Global/VRF。
- `ip_locator_trace_service.py` 在有界 CLI route trace 前读取 current-only 证据；查到唯一 Access 端口时返回成功并展示物理接口。默认查询不调用 legacy endpoint/history 写入器；实时刷新跳过 current 快路径，进入有界 CLI trace。locator result 标记 `current_endpoint` dependency manifest，`ip_locator_task_service.py` 发布前重新验证 ARP/FDB 位置、generation 和时间戳。
- 回归：官方隔离 PostgreSQL `backend/tests/ip_locator/test_current_endpoint_evidence.py backend/tests/ip_locator/test_snmp_entry.py` **12 passed / 151.34s**；包含 VLAN/access VLAN 不匹配拒绝；runner 未打开 configured application DB，临时 source DB 已删除。`py_compile` 通过；PostgreSQL-only scanner **0 violations**；目标文件 `git diff --check` 通过。
- 浏览器只读验收已完成：在管理员现有会话打开 `http://192.168.56.1:5400/ipam/locate`，查询 `172.16.5.10` 显示“定位成功”、`S6850-5:GigabitEthernet1/0/2`、VLAN 7、“已定位到接入端口”；上下文显示 ARP 接口 `Vlan-interface7`、FDB 命中 `GE1/0/2 · TO-PC-7`、模式 `up/up/access`。定位请求本身显示 0 台 ARP + 0 台 MAC 直连扫描，使用已存 current-only 事实。
- 服务启动时的既有 scheduler 自动运行一次只读采集：ARP sweep 从 9 台设备收集 49 条，FDB snapshot 更新 8 条，endpoint cache sync 汇总 32 条（未知 scope 项未写入资产映射）。因此 current generations 从启动前读取的 19/17 前进为 20/18。未执行设备配置命令；只读 live-facts validator 在服务启动后仍确认 formal IP/Pool/VIP/DHCP ledgers 均为 0。启动前核对 schema migration version 320，没有待迁移项。
- 第一次 `node scripts/dev-internal.mjs` 启动后，backend 在文件监视 reload 时退出；源码冻结后已从 main 工作区再次启动并保持运行，`15310/api/health` 返回 200 healthy/database connected，scheduler running、worker active，5400 浏览器复核成功。第二次启动触发既有 scheduler 再次只读采集；当前 ARP/FDB 代次前进到 21/19（最近成功 02:33:19/20 +08）。启动前只读确认 schema migration version 320，没有待应用迁移。SNMP Exporter reload/DNS 失败及 collector auto-sync 告警仍需单独跟踪，但不影响 IP Locator。

## 2026-11-11 P5 A06：查看待确认范围的当前观察与代次

- 发现终端页默认 `network_scope=business_vlan`，所以无 resolved address space 的当前 ARP 观察没有出现在 IP 默认视图。新增“观察范围”筛选，明确区分已映射业务网段与全部当前 IP 观察；all-scope 使用现有 `network_scope=all` API 参数，不读取历史 discovery snapshots，也不推断 Global/VRF。
- all-scope 结果仍受 API 的 IP 地址查看权限和可见 tenant/site 范围限制。切换到 MAC-only 时筛选器禁用并固定请求 all；摘要计数、分页及全分页导出使用相同过滤条件。
- 终端详情增加当前成功代次、最近成功代次、最新尝试代次、最新采集状态和最近成功时间，便于识别是否显示上一成功代次。scope_unknown 被标为“范围待确认”，并保留空 VRF。
- Chrome 管理员会话实际验证 `/ipam/endpoints`：默认业务网段 IP 视图为 0 条；切换“全部当前 IP 观察（含范围待确认）”后为 49 条，摘要 `范围待确认=49`。其中 `172.16.5.10` / VLAN 7 / S6850-5 详情为成功代次 21、最近成功代次 21、最新尝试代次 21、采集状态 scope_unknown，最近成功时间 2026-11-11 02:33:19 +08。此页面行是 current ARP observations，不代表唯一 IP 数量、正式登记或归属。
- 定向测试：`npx vitest run --config vitest.config.ts src/pages/IPVlan/ipamDiscoveryPresentation.test.ts src/pages/IPVlan/DiscoveredEndpointsTab.test.tsx` **23 passed / 2 files**；包含 query、待确认摘要、全范围导出和代次详情。`npm run lint -- --pretty false` 通过；`npx vite build --outDir .codex-build-validation-ipam-a06-20261111` 成功，4362 modules。
- A06 仍是部分完成：本次真实 current sample 是 ARP；仍需 NDP/FHRP 真实 current rows、其他设备平台的代次/latest-success 证据。当前代码和本地页面验证不替代生产验收；P4 用户决策 CSV、生产 DHCP/容量/备份恢复及 restricted-role 验收仍未完成。

## 2026-11-11 P5 A09：S6850_1 VRF 路由当前缓存复核

- 当前应用库只读事务核对 `S6850_1` 的 `route_cache` 与 `route_table`。两表都存有 default 41 条、VRF_A 8 条、VRF_B 8 条，更新时间 `2026-11-11 00:17:21 +08`；本轮未运行 `run_route_collector`，没有应用库写入。
- VRF_A/B 当前各 8 条均为 loopback、本地、组播和广播 special route；没有 192.168.10.0/24、192.168.20.0/24 connected route。与之前设备只读回显中 Vlan-interface10/20 DOWN 相符。
- 这证明当前本地路由缓存已保留两个 VRF 的采集结果，不代表 IPAM 地址空间归属已完成。跨平台覆盖、production rollout 与 removed-VRF retirement 仍待验证；VRF address-space mapping/迁移按范围暂缓。

## 2026-11-11 P5 A27：current FDB MAC-only owner separation

- 管理员 Chrome 会话下打开 `/ipam/endpoints`，选择“仅 MAC 观察（不登记 IP）”，当前返回 11 条 FDB 观察。列表全部显示空 IP、`FDB / MAC 观察（不登记 IP）`、`MAC 观察（未创建 IP）` 与 `范围待确认`。
- 查看 S6850-2 的 `96:7c:3e:84:0a:05`：详情 IP 空白、VLAN 100、观察接口 `GigabitEthernet1/0/1`、路径 `显式 Access 接口`，成功/最近成功/最新尝试代次均为 17，采集状态 scope_unknown。另有逻辑聚合和虚拟网关 MAC 记录，均保留独立 row，不生成 IP owner。
- 当前筛选的导出菜单准备了 11 条。前端定向用例覆盖 FDB CSV 中 IP 字段为空、来源为 FDB 和 owner label 表示未创建 IP；该回归与 presentation 用例 **23 passed / 2 files**。
- 这是本机当前 FDB 样本证据，不证明其他厂商覆盖。没有创建正式 IP、设备配置或地址空间映射。

## 2026-11-11 P5 A24：FHRP transport failure 诊断

- 当前 FHRP store 没有任何成功 current observations；H3C 设备状态为 `unsupported`，Cisco IOS 的 HSRP/VRRP collection state 为 failed。
- AC_20 执行一次限定设备的 official current-only collector refresh。它只尝试 `show standby brief` / `show vrrp brief`，写回该设备 current collection state，不写 observation history 或 formal IP/VIP 账本；两协议状态为 failed，attempt generation 17、last-success generation 0、current count 0。
- 实际连接在 SSH 协议 banner 阶段被远端 reset，命令未送达设备。后端增加 SSH banner 与算法协商错误分类，并为两类错误补隔离回归；当前错误码为 `ssh_banner_unavailable`。
- `backend/tests/ip_locator/test_current_fhrp_collector.py` 官方隔离 PostgreSQL **4 passed / 119.93s**；未打开配置应用库、临时 DB 已删除；py_compile、PostgreSQL-only 0 violations、path-scoped diff-check 通过。
- A24 仍待真实成功/完整空表样本。不能把 transport failure 解释成未配置 FHRP；H3C support 需要独立 parser/collector 任务。

## 2026-11-11 dev-internal 恢复后 current observations 复核

- FHRP 后端代码更新触发 WatchFiles reload，原 dev-internal supervisor 退出。确认没有原监听后，从 main 工作区重启一个 supervisor。随后 health 200 healthy/database connected/scheduler running/worker active；5400 首页 HTTP 200，Chrome `/dashboard` 实际打开成功。
- 启动后的 current ARP/FDB 成功代次刷新为 ARP 22（49行，03:33:52 +08）、FDB 20（7行，03:34:01 +08）。浏览器复核 `172.16.5.10` ARP 详情代次22，S6850-5 VLAN 7 FDB MAC 详情代次20且 IP 为空。MAC-only 页面为7行。
- 当前 FDB store 以 latest-success generation 原子替换同一上下文；旧 generation 19 曾有11行，generation20当前为7行。此差异是 current-only 语义，不把已被替换行当历史保留。
- FHRP current 仍无成功 observations；AC_20 SSH banner failure generation 17 未被重启覆盖。应用日志仍有 locator invalidation connection errors 和 SNMP Exporter reload/DNS failure；API与首页当前正常。


## 2026-11-11 VLAN 7 ARP/FDB 到接入端口实测

用户指出 CMDB VLAN 页面已有对应数据。管理员浏览器 /cmdb/vlans 的 VLAN 7 详情显示 1 条 ARP 与 1 条 MAC：172.16.5.10 的 MAC 8e47-5760-0706 从 Vlan-interface7 学到；相同 MAC/VLAN 7 的 FDB 命中 GigabitEthernet1/0/2，接口描述 TO-PC-7。随后 /ipam/locate 查询该 IP 返回成功：S6850-5、GE1/0/2、VLAN 7、up/up/access，本次直连设备扫描为 0 ARP/0 MAC，说明定位使用 current observations。当前代次为 ARP 22 / FDB 20。此证据确认端口联动可用；formal IP ledger 仍为 0，未创建 IP owner，VRF/address-space 未推断。路由/上下联完整路径仍单独待核。


## 2026-11-11 P5 当前协议覆盖与 FHRP 错误展示

重跑 P4 静态与只读实时校验后，60 Prefix 中 6 条已映射、54 条待决定；26 组 CIDR 待裁决，fact_mismatches 为空。只读 current-store 聚合确认 H3C ARP 49 行、FDB 7 行、NDP 0 行；NDP generation/last-success 为 17，状态 scope_unknown。Cisco HSRP/VRRP 均因 SSH banner 未收到而失败，非 Cisco 平台明确 unsupported，没有 successful FHRP rows。FhrpGroupsTab 已显示最近尝试、代次和本地化错误码；聚焦测试 9 项与 TypeScript lint 通过。正式 FHRP group 目前为 0，所以未做 live group-detail 浏览器验证或创建测试组。


## 2026-11-11 H3C VRRP current-only verified-empty

H3C Comware 7 的 current-only VRRP 采集现覆盖 display vrrp verbose 与 display vrrp ipv6 verbose；两族必须都能完整解析才替换当前快照。S6850_1 实际回显 VRRP4 is not configured. 和 VRRP6 is not configured.，current store 随后记录 generation/last-success 19、complete、0 observations。隔离 collector/parser/store suite 53 项通过，PostgreSQL-only scanner 0 violation，py_compile 与 4362-module isolated Vite build 通过。FHRP 正式组数仍 0，因此没有组详情浏览器数据，也没有构造假组或写正式 VIP。


## 2026-11-11 H3C FHRP 全平台 scheduler 复核

服务启动后的正常 current-only 调度确认 H3C VRRP 6 台 complete/verified-empty，含 S6850_1 generation 20 / last-success 20 / 04:58:25 +08；3 台 H3C 因命令 unsupported，Cisco 6 台 SSH banner failed。ARP/FDB/NDP 的 H3C 代次为 24/22/19，行数 49/7/0，NDP scope 仍 unknown。管理员浏览器 /ipam/fhrp 页面可打开并显示 0 formal groups，未创建测试关系；正式 IP/VIP/FHRP ledgers 仍空。

## 2026-11-11 P4 决策状态与 VLAN 7 定位复核

- 重新运行静态 P4 CSV 校验与只读 live-facts 校验：60 Prefix、6 条已有映射事实、54 条待人工目标空间；26 组/52 行重复 CIDR、6 组部分映射；事实差异为空。formal IP/Pool/VIP/DHCP 均为 0，address space 为 1 个 VRF，active context mappings 为 0。未访问历史 observation 表、未写数据库、未推断目标空间。两份用户裁决 CSV 仍待补齐。
- 用户此前 VLAN 7 截图显示 ARP 1 条、MAC 条目 0；ARP 的 `Vlan-interface7` 是三层来源，`GE1/0/2` / `TO-PC-7` 是 VLAN 成员接口，但当时缺少把目标 MAC 绑定到接入口的 FDB 行。
- 05:14 管理员 Chrome 当前页显示 VLAN 7 的 ARP 与 MAC 各 1 条。ARP `172.16.5.10` → `8e47-5760-0706` / `Vlan-interface7`；FDB 同 MAC、VLAN 7 → `GigabitEthernet1/0/2`；接口快照 `GE1/0/2` 描述 `TO-PC-7`。IP Locator 当前显示“已定位到接入端口”：S6850-5、GigabitEthernet1/0/2、VLAN 7、`up/up/access`，扫描 0 台 ARP/0 台 MAC，使用 current observations。ARP 来源时间 04:55:34 +08，FDB/接口时间 04:55:37 +08。
- 当前证据确认接入端口；此前路由查询失败属于三层/上联路径缺口，不应覆盖已确认的二层接入位置。正式 IP owner 仍为 0；没有创建登记，也没有推断 Global/VRF。完整路由/邻接仍待核。
- 整体任务仍未完成：P4 用户 CSV 与 P5 外部/生产验收项未收齐；VRF 地址空间 mapping/migration 继续按要求暂缓。本记录不是最终 handoff。

## 2026-11-11 P4 Global 唯一网段批量 pilot 与重复项暂缓

- 用户决定未重复目标归入 Global，并要求重复项先跳过。当前页显示 75 个 Prefix、原有 21 条已映射事实及 54 条待确认；只读正式表核对后发现其中只有两条是 CIDR 唯一且未映射：10.254.46.0/30（WH-DC-01，设备互联）和 172.16.6.0/24（WH-DC-01，服务器网）。两条都没有正式 IP、Pool、VIP 或 DHCP lease。
- 当前唯一地址空间显示名 global 的 kind 实为 VRF。管理员在 Prefix 页面新建 kind=global 的全局地址空间，不把既有 VRF 当成 Global。选中两条唯一 Prefix 后，逐项预览均为无阻断，目标空间资源计数 IP/Pool/VIP/DHCP 均为 0；确认后页面 toast 显示已映射 2 个网段。
- 页面回读显示 10.254.46.0/30 和 172.16.6.0/24 的所属地址空间均为全局地址空间；待确认数从 54 降为 52。未选中重复组，也未修改其已有地址空间。
- 重建两份 CSV 的事实快照到当前正式 Prefix 表：75 行，23 mapped、52 unmapped、32 repeated-CIDR groups/73 rows。重复表把所有 32 组标为暂缓、canonical 为空。页面摘要报告 26 个跨站点组/61 条；全量 CSV 另包含 6 个同站点组/12 条。21 条当前归属保留。静态 CSV validator 与只读 live-facts validator 均通过，事实差异为空，未查询历史 observation。
- 这一阶段只完成两条唯一 Prefix 的本地 Global pilot。52 条处在重复组内的未映射 Prefix 留待用户后续验证；VRF-specific mapping/migration 继续跳过；P5 生产与真实服务验收仍未完成。

## R76 2026-11-11 A21 当前正式 IP 台账与 VRF 范围

- 当前只读查询发现正式 IP 台账 25 条、分布在 15 个 VRF-mapped Prefix；其中 19 个 IP 可匹配 current ARP observation，6 个无匹配。部分 IP 在多个来源设备上出现，未据此推断唯一位置。
- 本轮没有读取历史 observation 表、没有修改正式 IP 数据。全部正式 IP 样本均处于 VRF 范围，因此按用户要求不做 VRF 专项浏览器核对；没有创建测试 owner。
- A21 仍待一个获批的非VRF正式 owner 做浏览器/API 登记与当前观察位置对照。P4 唯一 Prefix Global pilot 和重复项暂缓状态不变。
