# Nexora IPAM 对标 NetBox 审查与整改意见书

审查日期：2026-11-20（同日复核补齐源码细项）。Nexora 基线：`cedf5cd1`，另核对工作区相关文件。对标对象：NetBox 官方 IPAM 文档及可用资源 API 源码。本文以 IPAM 对标 NetBox 为主，并一并收录同期网工验收关联的堆叠资产导入与凭据轮换整改事项（后两项可按独立子计划跟踪，不阻塞 IPAM 试点收口）。本次为只读源码审查，现场状态使用历史验收记录，未重新运行测试或连接设备。

## 结论

**Nexora 已支持日常 IP 台账和大部分核心规划操作，但与 NetBox 在对象覆盖、对象生命周期及可用容量口径上仍有差异。现阶段适合按地址空间试点，尚不能作为 NetBox 完整替代。** 两个产品的主要差别，一是 NetBox 以 IP 对象、VRF 和 CIDR 包含关系组织台账，Nexora 目前把正式 IP 绑定到确定的 Prefix；二是 Nexora 将设备采集、定位和对账引入台账流程，这部分应保留并严格区分来源与正式记录。

## 功能逐项对照

| 能力 | Nexora 当前实现 | 判定与用户影响 |
| --- | --- | --- |
| Global、VRF、重叠地址 | CMDB 有 VRF 和 RD。IPAM 使用显式地址空间，Prefix/IP 唯一性按地址空间约束，设备采集需要匹配其路由上下文。 | **核心可用，语义不同。** NetBox 将未选 VRF 的正式对象归入同一个 Global，并支持每个 VRF 的重复对象策略。Nexora 支持多个独立 Global 空间，也保留未确认归属状态。迁移时应先做空间对应表，合并 Global 空间前必须检查相同 CIDR/IP。未见独立 Route Target 及 VRF 进出口关系的等价维护能力。 |
| IPv4/IPv6 Prefix 及层次 | 网段 CRUD、父子树、站点和 VLAN 关联、候选网关、接口快照导入、地址空间批量确认与迁移预览。 | **主流程基本覆盖。** 树通过 `parent_prefix_id` 建立，正式 IP 关联具体网段。NetBox 按地址包含关系自动组织，并有独立的 Aggregate、RIR 和可维护的 Prefix/VLAN Role。网段用途不等同于独立角色目录。 |
| 正式 IP 台账 | 按 Prefix 登记和分配，支持状态、用途、设备接口、预约与释放。默认地址列表查询正式记录，采集来源可单独展开。 | **常用功能覆盖，模型部分等价。** NetBox IP 原生保留主机掩码，且 IP 可以独立存在并指向设备接口、VM 接口或 FHRP 组。Nexora 写入路径拒绝地址携带 CIDR，未见等价的 VM 接口、双栈 Primary IP 与 NAT 内外 IP 关系。 |
| 地址范围 | 地址池维护起始/结束地址及管理方式、分配许可、`mark_populated`、`mark_utilized`。 | **相近，规则不同。** Nexora 增加了静态、保留、外部 DHCP 等分配策略；NetBox IP Range 和 Prefix 自身的 `Is a Pool` 是不同功能。不能根据已有地址池推断 Prefix 端点地址策略完全等价。 |
| 可用 IP 和子网 | Next IP 推荐、单 IP 事务分配及预约；Next Prefix 推荐；Pool 区间与已登记地址、协议证据共同参与分配。 | **日常可用，批量语义有缺口。** NetBox 原生提供可用 IP/Prefix 列表，以及用同一请求分配多个对象。Nexora 有单 IP 原子分配 API，界面及 Prefix 流程存在先推荐再提交的行为，不应把推荐结果当作已预占。 |
| 利用率 | 按全部或业务网段汇总，排除容器、主机路由及点对点前缀等场景的可分配容量。 | **部分覆盖，数字不可直接互换。** 当前统计与分配使用的占用集不同，NetBox 还按子 Prefix 计算容器占用、按 IP/Range 计算普通 Prefix 占用。 |
| VLAN | CMDB 有 VLAN CRUD、站点筛选、业务绑定和现场采集，Prefix 可关联 VLAN。 | **基础覆盖。** 未找到可等价维护 VLAN Group 的作用域与 VID 范围、VLAN Translation Policy/Rule 的产品模型、API 和页面。 |
| VIP、FHRP、Anycast | VIP 对象，主备设备、独立 FHRP/Anycast 组、设备接口成员与虚拟地址关联，另有当前状态投影。 | **部分覆盖及产品扩展。** NetBox 将 VIP 作为 IP 对象赋给组，支持设备和 VM 接口及成员优先级。Nexora 的独立 VIP 台账和正式 IP 分离，需要单独定义交换或迁移规则。采集代码支持 Cisco IOS 系列及 H3C Comware 的明确路径，覆盖程度以实测为准。 |
| DHCP 租约 | 租约 API 和页面，外部池绑定及观测状态。路由可进入，现有 IPAM 侧栏未暴露独立入口。 | **Nexora 扩展。** NetBox 原生模型提供范围规划与 DHCP 地址占用表达，DHCP 租约采集或同步以集成为基准。真实租约源的新增、续租和过期需要单独验证。 |
| 终端发现、IP 定位、对账 | 当前 ARP/ND/FDB、接口快照、来源筛选、终端登记及对账。 | **Nexora 扩展。** 这些是现场核查和登记入口。是否能定位、是否有采集结果、是否已登记，是不同状态，不能用任选一项替代另两项。 |
| 其他 NetBox 原生 IPAM 对象 | 核对 IPAM/CMDB 路由、模型和页面，未找到可操作的 RIR/Aggregate、ASN/ASN Range、Route Target、应用服务/模板、独立 Prefix/VLAN Role、VLAN 翻译的等价入口。 | **未覆盖或证据不足。** 先确认当前业务是否需要跟踪公网分配、ASN、MPLS/EVPN 路由导入导出和跨系统迁移，再决定优先级。命令模板出现字段名不能证明具备对应台账。 |

相关实现：[IPAM API](../../backend/api/ipam.py)、[CMDB VLAN API](../../backend/api/cmdb.py#L1068)、[IPAM 页面](../../src/pages/IPAMManagementTab.tsx#L103)、[地址空间索引](../../backend/database/migrations/m0308_ipam_address_spaces.py#L268)、[FHRP 采集平台映射](../../backend/services/ipam_current_fhrp_collection_service.py#L24)。

## 当前源码发现与整改要求

### 0. 先修数据完整性：自动发现映射 Prefix 后可能漏挡重复 IP

发现任务以明确 VRF 匹配到唯一的旧 Prefix 时，只更新 Prefix 的 `address_space_id`，没有同步其已有 IP。若子 IP 仍是空空间，正式写入查重的明确空间分支看不到这条旧 IP，旧范围分支及两套部分唯一索引也不能弥补这处不一致。例如在后来建好的同空间父网段或子网段登记同一个主机，存在同空间重复登记的路径。此判断来自源码，现场存量是否已触发仍待查。

**整改：** 自动发现保留候选，由统一的归属确认服务在一个事务内校验并同步更新 `prefixes`、`ip_addresses`、`ipam_pools` 及关联的 `ipam_vips`（不留空空间子记录）。补只读审计，找出 Prefix 和子记录的空间、租户或 VRF 不匹配情况，经人工核对后修复。验收覆盖自动发现匹配旧 Prefix、已有子地址冲突、事务失败和重复执行。证据：[发现写入](../../backend/services/prefix_discovery_service.py#L338)、[正式 IP 查重](../../backend/services/ipam_service.py#L925)、[统一归属服务](../../backend/services/ipam_address_space_service.py#L660)、[映射和旧数据索引](../../backend/database/migrations/m0308_ipam_address_spaces.py#L268)。

### 1. 高优先级：网段删除会级联删除正式 IP，且改写 CIDR 与前缀树重算存在完整性缺口

`delete_subnet` 及批量路径显式删除关联的 `ip_addresses`。页面有破坏性操作提示，这是现有业务规则，但对于计划替换 NetBox 或迁移存量的团队属于高风险语义差异。典型触发是清理旧网段、重新拆分地址块或去掉重复 Prefix。NetBox 的 IP 归属由 CIDR 包含和 VRF 推导，IP 模型没有指向 Prefix 的外键。

同时源码复核还发现两处相邻缺口：
1. `update_subnet` 允许缩小或改写 `prefix` CIDR，但只做网段重叠校验，未校验已有 `ip_addresses`、`ipam_pools` 和 `ipam_vips` 是否仍在新网段范围内，可能导致子记录越界孤立。
2. `rebuild_prefixes_hierarchy` 目前为全表 O(N²) 扫描且内部强行 `conn.commit()`：`create_subnet`、`update_subnet`、`delete_subnet` 及地址空间迁移都在主事务提交后才重算树，若重算失败，主写已落库但树状态漂移；而 `delete_subnets` 反而依赖其内部 `commit()` 才提交整批删除。

**整改：** 默认阻止删除仍有正式 IP、地址池、VIP 或租约依赖的 Prefix。提供删除影响预览，按正式 IP、地址池、VIP、租约分别计数，明确移交目标后再迁移。`update_subnet` 变更 CIDR 时在同一事务内校验所有活跃子 IP、地址池起止地址及 VIP 均被新网段包含。将 `rebuild_prefixes_hierarchy` 改为按受影响的 `address_space_id`（或旧范围）局部重算并支持 `commit=False`，纳入主写事务统一提交。验收覆盖单条与批量删除、CIDR 缩容越界拦截、依赖出现后的重试、多范围权限和层次重算事务一致性。证据：[单条删除](../../backend/services/ipam_service.py#L3116)、[批量删除](../../backend/services/ipam_service.py#L3184)、[网段更新](../../backend/services/ipam_service.py#L2929)、[树重算](../../backend/services/ipam_service.py#L1113)、[NetBox IP 模型](https://github.com/netbox-community/netbox/blob/main/netbox/ipam/models/ip.py#L872)。

### 2. 高优先级：已匹配网段的终端仍可能无法登记

后端返回 `suggested_subnet_id` 和 `vrf_context_status`，但发现终端页 `normalizeEndpoint` 未保留这些字段就将该行传给登记弹窗。对于地址空间已确认的行，弹窗依赖 `suggested_subnet_id` 判断是否可自动选网段。字段丢失会误入“没有唯一匹配的网段”分支并禁用确认。对于未映射但来源确认是 Global 的记录，前端也会失去目的网段类型判断所需的字段。

**整改：** 按明确 DTO 透传登记所需字段，后端继续在提交时校验观察时刻、地址空间、网段和权限。用同一份 API fixture 走完“已识别 Global → 选中唯一活动网段 → 确认登记”，再覆盖无合适网段、多候选、不同 VRF 和来源已更新。证据：[后端原始响应](../../backend/services/ipam_discovery_service.py#L2028)、[页面转换](../../src/pages/IPVlan/DiscoveredEndpointsTab.tsx#L80)、[弹窗匹配及禁用逻辑](../../src/pages/IPVlan/EndpointRegistrationDialog.tsx#L86)。

### 3. 高优先级：当前终端去重可将不同地址空间的记录折叠

去重先按来源类型、租户、站点、IP、MAC、VLAN 分组，地址空间被放到后面的上下文比较维度。两个明确地址空间在同站点复用同一 IP/MAC/VLAN、采集时间不同，较旧的记录会被从列表去掉。将原去重函数以两条合成记录单独调用，输入空间 A、B，输出仅剩采集时间较晚的 B。去重在设备筛选之前运行，因此 A 的设备仍可被选中，列表却可能没有记录。影响限于列表投影，未发生正式台账删除。

**整改：** 将明确的 `address_space_id` 纳入终端身份分组。归属未知时按采集设备与本地上下文隔离，只有存在同一来源上下文迁移的依据时才替换旧记录。验收覆盖不同 VRF 的复用、同一明确空间的重复采集、相同时间戳及按设备查询。证据：[去重分组](../../backend/services/ipam_discovery_service.py#L1084)、[筛选与去重顺序](../../backend/services/ipam_discovery_service.py#L2659)。

### 4. 高优先级：利用率不能直接代表还能分配多少 IP

目前看板的已用地址统计只查直接绑定该 Prefix 的正式 IP，再计入网关。实际分配还考虑同地址空间的占用、VIP、现场证据与地址池范围政策。一个被外部 DHCP 池完全覆盖的网段可能仍显示低登记利用率，同时自动分配没有候选。

**整改：** 将“登记利用率”“保留或不可分配”“实际可分配”“容器子网占用”分成明确指标，共用分配服务的占用和边界规则计算实际容量。明确 IPv4、IPv6、短前缀、已填满范围、重叠父子前缀的分母。验收同一组数据下列表、详情、导出、推荐和分配结果一致。证据：[登记占用](../../backend/services/ipam_service.py#L462)、[利用率](../../backend/services/ipam_service.py#L5126)、[分配占用](../../backend/services/ipam_service.py#L4310)、[NetBox IPAM 利用率](https://netboxlabs.com/docs/netbox/features/ipam/)。

### 5. 高优先级：Prefix 写入缺少 VLAN 范围校验、目标站点写权限及批量混租户拦截

1. **VLAN 范围校验缺失**：Prefix 创建 API 校验操作者对目标 Prefix 的权限，但服务直接写入输入的 `vlan_id`，更新也将该字段作为普通值写入。读取时以 VLAN 主键关联名称。即使数据库有外键，也只能保证行存在，不能保证 VLAN 属于兼容站点和租户。能维护 Prefix 的调用者若提交其他站点的 VLAN 主键，服务层没有拒绝该关联。
2. **更新 `site_id` 缺少目标站点权限校验**：`PUT /ipam/subnets/{subnet_id}` 允许修改 `site_id`，但入口仅对修改前的站点执行 `enforce_resource_scope`，未校验调用者对目标 `body.site_id` 的写权限，站点受限角色可能将 Prefix 迁移到无权写入的站点。
3. **批量地址空间接口仅按首条记录取租户**：`address-space-batch-preview` 和 `address-space-batch-resolve` 仅取首条 Prefix 的 `tenant_id` 校验目标地址空间，未在 API 入口拦截混合租户批次。

**整改：** 所有 Prefix 创建与更新入口统一校验 `vlan_id` 的存在性、租户和站点兼容性；更新 `site_id` 时对目标站点补做 `enforce_resource_scope` 校验并复核已绑定的 `vlan_id`；批量地址空间接口在入口拒绝混合租户批次。建立目标资源权限用例，加入跨站点、跨租户、无站点和修改 Prefix 站点的回归。现有 VLAN 同站点查重不覆盖无站点值，决定好无组 VLAN 可否复用及其标识规则后再添加约束。NetBox 允许未入组 VLAN 复用 VID，单凭“重复”不能认定不一致。证据：[API Prefix 创建](../../backend/api/ipam.py#L884)、[API Prefix 更新](../../backend/api/ipam.py#L1069)、[API 批量地址空间](../../backend/api/ipam.py#L1021)、[写入关联](../../backend/services/ipam_service.py#L2848)、[查询关联](../../backend/services/ipam_service.py#L1213)、[VLAN 查重](../../backend/services/cmdb_service.py#L5240)、[NetBox VLAN Group](https://netboxlabs.com/docs/netbox/models/ipam/vlangroup/)。

### 6. 中优先级：设备网络归属缺少从现有采集结果确认的流程

当前页面已经增加设备搜索，但创建映射仍要求操作者自己填 CLI/SNMP、本地上下文标识和目标地址空间。熟悉交换机配置的人也难以从表单知道系统实际读到了哪个标识。

**整改：** 从最新成功快照按设备列出已发现的默认路由表与 VRF，显示最后采集时间、覆盖情况和归属状态。网工只确认目标地址空间，技术字段放进高级区。没有可靠证据时保持待确认，避免把未知记为 Global。先核对每个厂商和协议的键值匹配，再做批量选择。证据：[当前设备选择及回写](../../src/pages/IPVlan/DeviceRoutingContextTab.tsx#L306)、[人工表单](../../src/pages/IPVlan/DeviceRoutingContextTab.tsx#L622)。

### 7. 中优先级：租约到期时间与显示状态可能分离

租约记录支持外部编号的幂等写入，页面按已保存的 `lease_state` 显示，列表按该字段筛选。现有路径未见根据 `lease_end` 自动推导有效状态。外部同步停更时，过期记录可能仍出现在活动列表。未明确关联外部 DHCP 池的租约也不会参与自动分配的占用判断；这属于现有数据边界，需要在 UI 说明。

**整改：** 保留来源状态，另按有效期、来源时效和空间映射显示当前有效性。若业务需要生产 DHCP 对账，再接入有明确权威来源的租约同步。验收覆盖新租、续租、释放、到期、源中断、错误映射和同 IP 跨空间。证据：[租约 API](../../backend/api/ipam.py#L1568)、[租约持久化](../../backend/services/ipam_service.py#L6663)、[页面显示](../../src/pages/IPVlan/DHCPLeaseTab.tsx#L477)。

## 发现终端与设备网络归属

| 问题 | 当前证据 | 整改及验收 |
| --- | --- | --- |
| 选中一台来源设备后，无法直接切换另一台 | 来源设备候选已改为按授权和站点构建。历史浏览器记录显示，从 S6850-5 可以直接切到 S6850-6，无需先选全部设备。 | A/B 设备、空结果、搜索、分页和切站点分别回归。设备候选独立于当前设备和列表筛选，越权设备不可见。 |
| 采集 4 条，列表只看到 2 条 | 历史样本的 4 条 IP 采集记录包括 2 条终端和 2 条设备接口 IP。默认终端视图只显示前两条。当前列表数应取实际查询总数。 | 使用「当前列表」和「采集到的 IP 记录」区分口径。通过「更多筛选 → 终端类型」看设备 IP。复核默认、全类型、换设备和分页。保留已删除的两个独立入口的处理结果。 |
| 筛选和排版复杂 | 现有页面将低频条件放在「更多筛选」。 | 首屏以站点、来源设备和 IP/MAC 搜索为主。统一字号层级、标签和按钮对齐，地址可用等宽字体。默认表格突出 IP、MAC、设备、端口、上次采集时间，详细证据进详情。验收默认、低分辨率、空结果和高级筛选展开状态。 |
| 「所属网络待确认」不清楚去哪处理 | 「未登记」表示还未入正式台账。「所属网络待确认」表示采集记录尚未映射到可靠的地址空间，可能缺少设备本地 VRF 对应关系。 | 从该记录的详情或行内操作进入「设备网络归属」（`/ipam/routing-contexts`），预选来源设备及可确定的本地上下文。候选列出采集到的默认路由表或 VRF、协议和采集时间。网工核对后选择目标空间；未知上下文继续待确认。回到终端页复核归属和登记资格。 |

历史验证记录见[筛选与排版](walkthrough_20261116_1447_01_发现终端筛选与排版.md)、[运维文案与归属指引](walkthrough_20261116_1504_01_发现终端运维文案与归属指引.md)、[删除两处提示入口](walkthrough_20261116_1609_01_发现终端移除提示入口.md)及[首屏信息精简](walkthrough_20261116_2104_01_发现终端首屏信息精简.md)。[当前发现终端页源码](../../src/pages/IPVlan/DiscoveredEndpointsTab.tsx)。

## IP、MAC 和聚合口定位

### ARP 与 MAC 表的采集边界

| 现场场景 | ARP 来源接口 | MAC 表与定位 |
| --- | --- | --- |
| 三层聚合承载直连邻居网段 | 当 SNMP 返回逻辑聚合口的 `ifIndex`，并且 IF-MIB 能解析名称，就能采到 `Route-Aggregation`、三层 `Port-channel` 或 `Eth-Trunk` 等逻辑接口。 | 纯三层聚合一般没有该网段的本机二层 FDB。需要其他已采集的下游证据才能定位终端接入口。 |
| VLAN 三层接口做网关，流量经二层聚合转发 | ARP 通常显示 VLAN 三层接口，如 `Vlan-interface7`。 | 在对应 VLAN 中查 MAC。设备可能上报逻辑聚合口，也可能上报成员口。记录设备原始上报，并核对成员与聚合组的关系。 |
| 纯二层接入交换机 | 终端的 ARP 通常从三层网关采集。接入交换机的管理 ARP 反映其自己的三层邻居。 | 通过 VLAN 和 MAC 查询二层转发端口，可能命中接入口，也可能命中上联聚合或 Trunk。 |
| 服务器双网卡直接做 LACP 聚合 | ARP 来源由网关的接口决定。 | 有服务器直连证据时可显示逻辑聚合接口。ARP 和 FDB 无法单独验证一次流量走了哪个物理成员。 |

现有 IPv4 ARP 采集按 IP-MIB 的 `ifIndex` 关联 IF-MIB 接口名，允许保存逻辑接口。IPv6 邻居发现使用独立路径。MAC 表采集按 VLAN、桥端口和接口索引还原接口名。需特别注意：`_load_arp_sweep_devices` 采用白名单筛选，**仅纳入 `access` / `access-layer-switch` / `接入交换机` / `ap` / `wireless-ap` / `无线ap` / `无线接入点`**，不仅排除了通用 `switch` 角色，也排除了 `core`、`distribution`、`aggregation`、`router`、`firewall` 等三层网关设备；这与“纯二层接入终端的 ARP 通常需从三层网关采集”存在采集范围缺口，需在批次 4 中明确三层网关 ARP 的定时采集策略或纳入候选范围。遇到空结果，依次核对三层网关、采集范围、SNMP 权限及 VRF 上下文、快照时效和设备是否确有该邻居项。接口索引无法映射时，现有 SNMP ARP 路径会报告失败。采集失败、没有记录和未采集应显示为各自的状态。[ARP 采集](../../backend/services/snmp_service.py#L1994)、[MAC 表采集](../../backend/services/snmp_service.py#L2098)、[定时采集范围](../../backend/services/ip_locator_service.py#L4880)、[IP-MIB RFC 4293](https://www.rfc-editor.org/rfc/rfc4293.html)、[Q-BRIDGE-MIB RFC 4363](https://www.rfc-editor.org/rfc/rfc4363.html)。

### 统一定位流程

1. **输入 IP**时，按站点、地址空间和 VRF 找 ARP 或 IPv6 ND，取 MAC 和来源接口，再查可信 VLAN 内的 MAC 转发表。无法确定 VLAN 时保留候选与来源。
2. **输入 MAC**时，统一归一化冒号、连字符和点分格式，按授权站点查询 FDB，必要时反查 ARP/ND 补充关联 IP。相同 IP 或 MAC 跨空间、站点或 VLAN 出现时列出候选。当前页面支持 IP 定位和 MAC 记录筛选，独立 MAC 路径追踪属于待做项。
3. **命中聚合或 Trunk**时，沿 LLDP 或已确认拓扑找到下一跳并查同一 VLAN 的 MAC。成员口可用来匹配所属聚合及拓扑邻居。只有上联证据、没有对端快照或出现多个候选时，显示最后查实的设备和端口、未定位原因及采集时间。
4. **结果先显示能采取行动的信息。** 给出站点、VLAN、设备、接入口或最后查到的端口，再展开「ARP 来源接口」「MAC 表命中端口」「定位路径」。无证据、陈旧快照和多路径要能一眼区分。台账登记继续经独立流程确认。

目前 IP 定位已能利用聚合及成员关系寻找拓扑邻居。现有聚合分类用例覆盖逻辑口、成员口和 Trunk。历史现场样本中，`172.16.5.10` 的 ARP 来源为 `S6850-5 / Vlan-interface7`，同一 MAC 在 VLAN 7 的 `GE1/0/2` 命中，属于普通接入口样本，可作为两类接口分别展示的回归基线。[现有定位入口](../../src/pages/IPLocatorPage.tsx#L1371)、[聚合邻居匹配](../../backend/services/ip_locator_service.py#L2585)、[聚合追踪停止条件](../../backend/services/ip_locator_service.py#L4494)、[聚合分类测试用例](../../backend/tests/ipam/test_ipam_current_endpoint_api.py#L733)、[历史现场样本](walkthrough_20261110_0955_01_IPAM_P4-P5非VRF推进.md#L354)。

### 现场验收清单

设备侧用同一时段的只读 CLI 和 SNMP 快照对照。每个样本记下站点、设备型号及软件版本、VRF/地址空间、VLAN、IP/MAC、接口名和 `ifIndex`、聚合组及成员、LLDP 对端和采集时间。CLI 能看到但采集未取得记录时，核对协议权限、上下文以及桥端口或接口索引映射，记录差异发生在哪一步。

| 场景 | 通过条件 |
| --- | --- |
| VLAN 三层接口 + 二层聚合 | ARP 显示 VLAN 三层接口，FDB 显示设备实际报告的聚合或成员口。具备完整邻居和下游 FDB 时能追到接入口。 |
| 三层聚合直连 | 在该设备支持暴露对应 ARP 项时，采集记录与设备上报的聚合接口一致。没有下游证据时停在已查实的接口。 |
| 纯二层接入 | 从网关拿 IP/MAC，从接入交换机拿端口。只有 FDB 时，用 MAC 查询也能返回已查实的端口和时间。 |
| 聚合对端缺失或采集超时 | 显示最后查实的聚合口和具体限制。旧证据带时效标识，终端在线状态不由本次观测推定。 |
| 同地址跨 VRF、同 MAC 多 VLAN、IPv6 ND | 候选各自保留范围和来源，路径不串线。无权限范围的数据不可见。 |
| 直接连接服务器的聚合 | 能展示有证据的逻辑聚合或已观测成员，不把哈希选路推断成确定的终端物理端口。 |

现场三类聚合样本仍待核验。本次合并仅整理既有审查结论和验收项。

## 堆叠设备导入与成员台账

**当前录入方式。** 多台交换机组成一个逻辑堆叠并共用管理 IP 时，在「资产管理 → 导入资产」的网络设备表中只录入一行。例如 `WH-ACC-STACK01` 使用 `10.10.10.21`，整组以这个 IP 作为 SNMP、SSH、备份和定位的管理入口。同 IP 填多行会触发重复检查并跳过重复行。已登记的堆叠直接在原资产查看或同步机箱 SN。配置有效的 SNMP Profile 后可以读取设备上报的机箱信息，导入后需核对成员数量和序列号。[导入去重](../../backend/api/assets.py#L4547)、[SNMP 机箱采集](../../backend/services/snmp_import_identification_service.py#L760)、[资产列表展示](../../src/pages/AssetManagement/index.tsx#L2229)。

**整改目标。** 一组堆叠保留一个逻辑管理入口，同时让每台机箱可以独立盘点、定位机柜位置和记录更换。现有机箱表按资产与 SNMP 实体索引保存采集结果。成员编号和实体索引分别表示设备配置及采集位置，成员台账应保留独立业务标识和历史。不同设备、系统和 SNMP 视图的成员覆盖情况需要现场核对。[机箱观察表](../../backend/database/migrations/m0302_asset_chassis_members.py#L22)、[成员采集识别边界](../../backend/services/snmp_chassis_serial_reader.py#L704)。

| 项目 | 整改要求 |
| --- | --- |
| 导入模板 | 「网络设备」一组堆叠填一行，保存堆叠资产编号、主机名、站点、管理 IP 和采集配置。「堆叠成员」每个机箱填一行，通过堆叠资产编号关联，填写成员号、物理资产编号、SN、型号、机柜、起始 U 位及高度。 |
| 导入校验 | 预览显示新增成员、已有成员、冲突及无法匹配的堆叠。校验堆叠归属、成员号、资产编号、已知 SN 和机柜位置。同一堆叠重复导入不增加设备或成员，冲突指明文件行号和字段，用户确认后再执行成员变更。管理 IP 仍由逻辑设备负责校验。 |
| SNMP 对账 | 按逻辑设备采集一次，优先用已确认的 SN 对账，保留成员号、实体索引和采集时间供核对。缺 SN、读表不全或发现未登记机箱时标出差异，保留已登记的资产编号、位置和历史。 |
| 成员更换与定位 | 同一成员号换机后保留旧机箱的退出记录，新机箱录入新 SN 并继承经确认的位置。逻辑堆叠维持原管理 IP 和采集目标。定位仍显示逻辑设备及端口，有可靠的端口与成员映射时补充成员号及机柜位置。 |

**验收样本。** 用两台机箱共用一个管理 IP 的堆叠导入并重复导入，预期始终为一个管理目标、两条成员台账。再核对成员编号冲突、跨堆叠重复 SN、采集只返回部分成员、管理主控切换及更换一台机箱的表现。普通单机导入和独立设备的 IP 冲突检查一并回归。现场对照设备成员清单、采集结果、资产详情及实际机柜位置。

## 凭据轮换页面与自动更新策略

**当前实现。** `/management/credentials` 对应「凭据轮换」页面，支持查看设备账号的到期状态和手动轮换。源码默认密码轮换周期为 **90 天**，临期窗口为 **14 天**。90 天用于成功轮换后计算新的到期时间。当前自动轮换由部署配置控制，源码默认关闭；**启动阶段当 `PASSWORD_ROTATION_ENABLED=False` 时，APScheduler 根本不会注册 `password_rotation_sweep` 任务**；开启后，调度器每天 02:00 扫描到期记录。源码复核还发现一处**严重逻辑脱节**：`rotate_password()` 成功后只写分角色列（`normal_password_expires_at` / `admin_password_expires_at` / `enable_password_expires_at`），**从未更新旧列 `devices.password_expires_at`**，但 `check_expiring()` 和 `run_rotation_sweep()` **只查询 `devices.password_expires_at`**——这会导致旧列已过期的设备开启自动轮换后每晚重复改密，而仅维护分角色到期时间的设备完全漏扫。页面没有独立开关，也未显示部署的实际生效策略。页面目前固定以 14 天显示临期状态，现有功能证据可证明页面提示及临期查询，主动通知需单独验收。本次未核对现场部署覆盖值。[配置默认值](../../backend/core/config.py#L163)、[调度注册](../../backend/main.py#L544)、[到期时间计算](../../backend/services/password_rotation_service.py#L755)、[分角色写库](../../backend/services/password_rotation_service.py#L760)、[临期查询](../../backend/api/devices.py#L2555)、[页面状态](../../src/components/PasswordRotationPanel.tsx#L82)。

| 项目 | 整改要求 |
| --- | --- |
| 首屏和字体 | 顶部显示当前生效策略、轮换周期、提醒提前量和下次扫描时间。首屏突出临期、已过期和失败的账号，列表展示设备/凭据组、账号类型、到期时间、状态和操作。将账号明细与设备关联放在展开区，统一字号和状态标签。手动批量轮换放在独立操作区，与自动开关拉开距离。 |
| 自动更新密码开关 | 管理员可在页面控制定时轮换。新部署默认关闭，已有部署按当前生效策略初始化，避免升级改变现场行为。**调度层改为进程启动时始终注册 `password_rotation_sweep`（执行前读持久化生效策略决定是否跳过），或页面切换时动态注册/移除任务**，确保无需重启即可生效。开启前显示影响的设备、账号类型和已过期数量，说明系统将在调度窗口实际修改设备密码。关闭后停止新一轮定时执行，保留到期提醒和手动轮换。页面显示实际生效状态，记录修改人、时间和前后值。 |
| 到期提醒 | 初始默认提前 14 天，页面和通知读取同一生效策略。关闭自动更新时提示「到期后需手动轮换」。开启时说明预计执行窗口，并通过已配置通知渠道提醒临期、到期未完成和轮换失败。通知提供设备、账号类型、到期时间及处理入口，按到期事件去重。 |
| 调度与账号范围 | 保存策略后，由调度器读取同一份生效状态，任务执行前再校验开关、账号范围和到期时间。**修复 `check_expiring()` 与 `run_rotation_sweep()` 只读旧列 `password_expires_at` 的缺陷**，统一按纳入范围的角色（`normal` / `admin` / `enable`）扫描各自的 `*_password_expires_at`，杜绝重复轮换和漏扫。旧记录没有到期时间时显示「未配置周期」，由管理员确认策略。自动轮换失败后记录设备状态及登录验证结果，并显示后续处理入口。 |

**验收。** 检查默认 90 天周期、14 天临期、部署覆盖值、保存后刷新与服务重启。覆盖开关关闭时只提醒、开启后按窗口轮换、关闭后不发起新任务、已过期存量预览、账号范围、无权限操作、任务并发与失败通知去重。先用模拟设备或隔离环境验证改密、用新密码重新登录和凭据库入库的一致性，再按授权设备范围试点。[到期扫描](../../backend/services/password_rotation_service.py#L212)、[轮换入口默认账号](../../backend/services/password_rotation_service.py#L243)、[定时执行](../../backend/services/password_rotation_service.py#L945)、[现有凭据页面](../../src/components/PasswordRotationPanel.tsx#L686)。

## 建议的交付顺序和验收

| 批次 | 交付范围 | 验收标准 |
| --- | --- | --- |
| 1. 先保住台账 | 修复发现流程映射一致性、登记字段透传、终端跨空间去重、网段删除保护、CIDR 缩容子记录校验、局部前缀树事务提交、Prefix/VLAN 范围与目标站点写权限校验及批量混租户拦截。 | 旧 Prefix 和已有 IP/Pool 同时归属；有正式子 IP/Pool 的网段无法误删，CIDR 改写不产生越界子记录；已确认归属的终端可登记；两个空间复用相同 IP/MAC/VLAN 时均可查到；跨授权范围的 VLAN 关联与跨站点迁移被拒绝；树重算与主写同事务。 |
| 2. 统一可用性 | 区分正式登记数和实际可分配数，梳理 Pool 边界及建议/实际分配契约。 | 同范围的 IPv4、IPv6、外部 DHCP 池、父子 Prefix 冲突和并发竞争结果一致。成功分配返回明确对象。 |
| 3. 完成可控试点 | 选一个已确认的 Global 空间，再选一组重叠地址的 VRF；完成存量比对、设备映射候选和回滚演练。 | 旧/新台账逐条对账，未确认记录有负责人，受限角色看不到越权数据，恢复后重复编号、归属及审计记录符合预期。 |
| 4. 完成现场定位闭环 | 复用 IP 定位路径，补独立 MAC 输入；修正三层网关定时 ARP 采集范围缺口；按上述清单验证二层和三层聚合，并完成发现终端及待确认归属的页面回归。 | 同一设备样本的 CLI、采集和页面结果一致；查不到接入口时仍能看清最后一跳、采集时间和原因。 |
| 5. 完成堆叠资产导入与盘点 | 复用单一管理入口，新增成员台账导入及 SNMP 对账。 | 两个机箱共用一个 IP，重复导入后仍只有一个管理目标、两条成员。部分采集保留已登记资产，更换机箱可追溯。 |
| 6. 完成凭据页面与轮换策略 | 增加自动更新开关和到期提醒，修正调度启动期注册逻辑与分角色到期时间扫描脱节，统一页面、调度与账号范围。 | 关闭时仍能提醒，开启后无需重启即可在生效窗口按角色处理到期账号且不重复轮换，失败可见且有通知。 |
| 7. 按业务场景补齐原生模型 | 需要多站点和多 VRF 时优先 VLAN Group、Route Target；需要运营商资源时补 RIR、Aggregate、ASN；需要资产服务关系时再补 VM 接口、Primary IP、NAT 和应用服务。 | 每个新增模型都有明确业务场景、独立写入契约和一条迁移/验收样例。按实际范围承诺等价程度。 |

现有 [A01–A36 证据矩阵](../plans/ipam_p5_evidence_matrix_20261110.csv) 记录了隔离 PostgreSQL 的并发、幂等和批量回滚证据。该记录中的设备样本、角色、生产 DHCP、迁移及恢复状态均有适用范围，不能当作 2026-11-20 新验收。继续沿用 [原对标实施方案](../plans/plan_20261105_1322_01_IPAM核心范围与台账归属整改.md) 记状态，按最新现场事实更新待映射与重复 CIDR 清单。此次仅产出审查意见书，未修改业务代码、运行测试、操作数据库或设备。

官方基线：[NetBox IPAM 功能](https://netboxlabs.com/docs/netbox/features/ipam/)、[对象目录](https://netboxlabs.com/docs/netbox/models/ipam/)、[VRF](https://netboxlabs.com/docs/netbox/models/ipam/vrf/)、[Prefix](https://netboxlabs.com/docs/netbox/models/ipam/prefix/)、[IP 地址](https://netboxlabs.com/docs/netbox/models/ipam/ipaddress/)、[IP 范围](https://netboxlabs.com/docs/netbox/models/ipam/iprange/)、[FHRP 成员](https://netboxlabs.com/docs/netbox/models/ipam/fhrpgroupassignment/)、[VLAN Group](https://netboxlabs.com/docs/netbox/models/ipam/vlangroup/)、[可用资源 API](https://github.com/netbox-community/netbox/blob/main/netbox/ipam/api/views.py#L321)。
