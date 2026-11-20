# SNMP 优先 NSOT 采集与 CLI 回退

## 目标

让 NSOT 中每个网络事实范围都按“SNMP 首采、CLI/TextFSM 兜底”执行。只有该范围的 SNMP 凭据缺失、MIB 不支持、视图不完整、walk 失败或数据映射不完整时，才为该范围启动 SSH/CLI。完整 SNMP 数据应直接入库，不能再为补采同一事实建立 SSH 会话；SNMP 与 CLI 都失败时保留上次成功快照。

单纯增加 SNMP helper 不算完成：所有 NSOT 调用入口必须先判定 SNMP 结果并在 SSH 连接/端口探测之前完成成功分支，同时确认数据库只替换成功采集的事实范围。

## 现状与问题

- ARP 已有 IP-MIB 首采；活动终端定位中的 MAC/FDB 已有 Q-BRIDGE-MIB 首采。需确认空/不完整表的判定与所有结果写库路径。
- IF-MIB 已采接口基础字段，但接口状态服务和 scheduler 仍会无条件执行部分 CLI；IP 地址/前缀和 VLAN 成员应由 IP-MIB、Q-BRIDGE-MIB 先采并按 ifIndex/bridge port 映射。
- 默认路由已尝试 IP-FORWARD-MIB；非默认 VRF 路由和 BGP 路由表仍有 CLI 主采路径。
- BGP、OSPFv2/v3、IS-IS 邻居已有标准 MIB helper，但需让空表/协议未启用与 MIB 不支持可区分，并审查每协议失败后的局部回退和历史保留。
- LLDP 已具备 SNMP 快照与 SSH fallback，需核实 NSOT 定时入口实际使用该路径、SNMP 成功时不连接 SSH、完整 walk 无应用层行数上限。
- 拓扑的 LAG/端口聚合父子关系有独立 SNMP helper，但实际入口只在 LLDP 也走 SNMP 时调用；helper 使用 4096 行上限且只支持 v1/v2c，SNMP 失败时没有对该域单独回退 CLI。应将 LAG 采集独立于 LLDP 传输方式，改为无行数上限和支持 v3 的完整 SNMP walk，SNMP 不完整时才回退 CLI/TextFSM。
- NSOT preview/catalog 仍把多项已有 SNMP 优先或待改造的采集标成 `cli`/`ssh`，需在实现后同步事实。
- 标准 MIB 的语义边界不同：BGP4-MIB 邻居状态不等同于完整 BGP RIB；普通 SNMP context 也不自动代表所有 VRF。

## 影响范围

- `backend/services/snmp_service.py`
- `backend/services/ip_locator_service.py`
- `backend/services/scheduler_service.py`
- `backend/services/interface_collection_service.py`（仅在保证接口/IP/交换属性数据完整时需要）
- `backend/services/vlan_discovery_service.py`
- `backend/services/nsot_collection_preview_service.py`
- `backend/services/collection_plan_service.py`
- 本计划及对应 walkthrough、handoff

## 实施步骤

1. **统一回退契约**：完整 SNMP walk 结果与不支持/权限/超时/部分列的失败状态可区分；多个列按索引集合校验，不设置应用层行数上限。只有能确认 MIB/表存在时才把有效空表作为成功空快照；不确定时走 CLI 兜底。回退按 ARP、接口状态、接口地址、VLAN、FDB、LLDP、默认路由、VRF 路由、各动态协议和 BGP RIB 分别判定。
2. **接口与 VLAN**：IF-MIB 采身份/状态/描述/MAC/MTU/速率；IP-MIB 采 IPv4/IPv6 地址及前缀并按 ifIndex 合并；Q-BRIDGE-MIB 采 VLAN、tagged/untagged PortList、PVID，按 bridge-port → ifIndex → ifName 映射。某个事实域完整时不得为其开 SSH；其他域缺失只运行其对应 CLI category。保证 SNMP 字段真实写入 CMDB/IPAM，不用空值擦除旧地址、VLAN 或描述。
3. **ARP/FDB/LLDP**：检查 NSOT 实际调用图；保留现有完整 IP-MIB ARP 与 Q-BRIDGE FDB 首采；LLDP 走完整 SNMP 快照优先，只有 SNMP 不支持/不完整时再走 SSH。每个域失败时不将部分 walk 写成完整快照；明确空表也要经过能力判定。
4. **路由**：默认表先完整采 IP-FORWARD-MIB；已知 VRF 先用 SNMP context/设备可用 VRF MIB 逐 context 采，只有相应 VRF 的 SNMP 不可用才对该 VRF CLI 兜底。SNMP 表失败后可使用已有 CLI VRF 发现补齐未知 VRF。失败 VRF 不应使其他已完整 VRF 被错误写成空表。
5. **邻居与 BGP RIB**：BGP、OSPFv2、OSPFv3、IS-IS、RIPv2 各自尝试相应 MIB；Cisco EIGRP 先试 CISCO-EIGRP-MIB，其他平台走 CLI。只有完整且字段映射通过的表才标记 SNMP 成功；若 helper 能确认表完整且确实为空，可作为成功空快照。协议未启用、MIB 不支持、空表无法确认完整或部分列失败时，回退该协议 CLI，避免把不可区分的空 walk 当成可清理快照。BGP 路由 RIB 核对 RFC 1657 BGP4-MIB：该表覆盖 IPv4 接收路径，但不能等价覆盖平台 CLI 所需的 IPv6、VRF 及厂商 weight 等字段；在现有接口要求完整路由视图时继续保留 CLI/TextFSM，而不把“BGP 邻居表”或普通转发表冒充为“完整 BGP 路由表”。
6. **拓扑 LAG 与入口元数据**：无论 LLDP 通过 SNMP 还是 SSH 完成，拓扑聚合关系都先完整读取 IEEE8023-LAG-MIB 的 member→aggregator ifIndex，并通过 IF-MIB 映射接口名；不完整/不支持时仅对该域回退 `eth_trunk` CLI/TextFSM。只有能确认设备没有聚合关系的完整 SNMP 空结果才作为空快照；不可确认、双源失败或 CLI 未匹配时保留旧关系。确保 `run_unified_nsot_sync` 及其他事实域遵守 SNMP 成功分支先于 SSH，并同步 preview/catalog 实际传输说明。
7. **持久化与核验**：一次完整成功才替换相应设备/域快照；不完整双源采集保留上次值；更新 plan、walkthrough 和 handoff。按仓库/用户约束只做静态解析和 `git diff --check`，不运行测试、构建或设备采集。

## 验证计划

- 按用户要求不运行测试或构建。
- 对每个 NSOT 网络事实域检查 SNMP 成功路径是否在任何 SSH 端口探测/Netmiko/platform action 前返回；检查完整列/索引、v1/v2c/v3凭据、接口映射、空表判定、局部 fallback 和数据库替换保护。
- 静态 Python AST 解析受影响模块，并执行 `git diff --check`；按现有用户/仓库要求不运行测试、构建或真实设备采集。

## 风险与回滚

- 标准 MIB 的设备实现、SNMP view、协议族及 context 支持不一致；需要区分“不支持/权限失败/完整空表”，只有已证明为空时才按空快照替换。
- 标准 IP-FORWARD-MIB 的普通默认 context 不代表所有 VRF；v3 context 命名、v2c community-indexing 与厂商 VRF MIB 不同，不能假定通用映射。
- Q-BRIDGE 的 PVID 和 tagged/untagged PortList 不等于厂商 CLI 的完整端口模式字段；只能写入可证明的事实，模式不确定时保留旧值或对该字段回退 CLI。
- BGP4-MIB 的 IPv4 peer/RIB 覆盖与 BGP4V2/厂商扩展不同；不具备 SNMP 等价字段的 AFI/SAFI/VRF 路由范围应明确回退，避免静默漏项。
- OSPFv2/v3 暂时映射到同一 `ospf` 存储键，数据库/UI 暂时不能区分协议版本；完整性判断仍须同时审查两个 MIB 表，不能一个版本成功就将另一个版本视为成功。
- 如发现数据语义或写库刷新范围异常，可分别回退路由、邻居、接口和 FDB 调用点；SNMP helper 本身不变更设备配置。

## Agent 分工

- 主 Agent：采集链路整合、路由/BGP RIB、catalog/preview、持久化语义、公共审查及计划/walkthrough/handoff。
- 接口 MIB worker：只负责 `snmp_service.py` 中 IP-MIB/Q-BRIDGE-MIB 接口地址和 VLAN helper，以及 `interface_collection_service.py` 的接口字段持久化集成；不改 scheduler。
- 动态邻居调度、路由/BGP VRF 范围与 preview/catalog 由主 Agent 修改；接口 MIB worker 不改 scheduler。

## 完成状态

- 原有 IP-MIB ARP、Q-BRIDGE FDB、IF-MIB 接口基础信息和 IP-FORWARD-MIB 默认路由路径继续作为主采集；未知/不完整数据仍保留 CLI/TextFSM 兜底。
- 普通路由改为按设备和 VRF 独立采集、独立替换：默认表和 SNMPv3 可用 context 先走 SNMP；不支持的 VRF 只回退该 VRF，失败不会阻止已成功 VRF 入库。
- BGP VRF 候选从对应设备接口/路由证据读取，不再将全局 VRF 列表发给所有设备；只有完整成功的设备/VRF 表才清理旧快照。
- 动态邻居回退按协议范围执行，并已调整 OSPFv2/v3 变体的独立成功/失败判断；统一 NSOT 不再硬编码禁用 EIGRP/RIP。新增 RIP2-MIB peer 表和 Cisco CISCO-EIGRP-MIB 邻居采集；不完整或无法确认完整性的空表按不确定处理并回退 CLI，helper 明确证明完整的空邻居表可安全更新为空快照。完整 BGP RIB 保留 CLI/TextFSM：RFC 1657 的 BGP4-MIB path-attribute 表提供 IPv4 接收路径，但不覆盖现有 CLI 所需的 IPv6、VRF 和厂商 weight 字段。
- LLDP 拓扑采集使用解析出的 SNMPv3 profile，不会因 v3 没有 community 字符串而跳过 SNMP。
- 活跃 MAC/FDB 端点采集经 `ip_locator_service._collect_full_mac_table_from_device` 使用 Q-BRIDGE-MIB 优先，完整性或映射失败才回退平台 CLI。
- 快照补充审查：SNMP/CLI 结果只有在解析状态明确且每条记录都成功归一化时才允许替换。ARP/FDB/路由和 BGP RIB 对当前无法证明的空表保留旧数据；路由邻居只接受 SNMP helper 明确声明完整的空邻居表。CLI/TextFSM 返回 `unmatched`、空记录或部分坏行时，不视作成功，不删除旧快照。
- MAC/FDB 快照现在按设备单独替换：仅完整成功设备清理并重写 `mac_table`，失败设备保留上次 MAC 记录。只要本轮有交换机 MAC 快照不完整，就暂停端点重新定位，避免用半份 FDB 把终端标记离线或迁移到错误端口。
- 拓扑 LAG 关系独立于 LLDP 的 SNMP/SSH 结果来源；完整读取 IEEE8023-LAG-MIB `dot3adAggPortAttachedAggID` 并用 IF-MIB `ifName`/`ifDescr` 映射成员和聚合 ifIndex。改用无行数上限的完整 walk，并支持 SNMPv3 profile。完整有成员结果写入；只有完整 IF-MIB 证明没有 LAG 时才用空快照清除；不支持、权限/超时/映射失败时对该域回退 CLI/TextFSM。CLI 仅接受明确 `matched` 的记录，两个来源都无有效结果时保留旧关系。成员和聚合状态缺失时保存为 `unknown`。
- ARP SNMP 归一化要求输入记录全部有效；CLI/TextFSM 仅消费 `matched` 记录，或在模板未匹配时使用已有原始输出兜底解析。无可解析行、解析失败或字段无法归一化均触发回退/保留旧缓存。
- 路由和 BGP 表成功状态要求存在非空、完整归一化的记录；空/未匹配 CLI 结果不会清除旧 VRF 快照。BGP 全量 RIB 继续 CLI/TextFSM 属于字段语义范围限制，不宣称其已改为 SNMP。
- LibreNMS 资料核对发现：通用路由模块在超过默认 1000 条限制时会跳过该次通用 MIB 采集，并非只保存前 1000 条；仓库已有通用 ISIS-MIB 邻居发现/轮询实现，不能再写成“未确认通用原生支持”。FDB 的 created/updated 时间和过期清理不能等同于完整的 MAC 迁移事件历史。
- 接口采集已接入 IF-MIB、IP-MIB、Q-BRIDGE-MIB 的独立完整性判断；完整域直接写入接口/IPAM，缺失域才请求对应 CLI category，失败不以空值清除上次快照。统一 NSOT 流程关闭旧的重复接口 CLI 路径，避免同一设备先后采两次接口。
- 接口字段边界：MAC/MTU 无专用 CLI fallback category，不完整时保留旧值；现有地址 fallback category 可能一并读取接口状态，但写库优先保留 IF-MIB 状态。`interfaces` 只能投影一个主地址，IP inventory 主键也无法表达同一 IP 在多个接口的重复配置；现有模型无带 tagged/untagged 属性的 VLAN 关联表，歧义 VLAN 不做推断。
- ARP 定时采集、按 IP 即时定位、MAC/FDB 端点采集和旧 IP inventory 地址辅助路径现在会接纳仅配置 SNMP 凭据的在线设备；角色过滤已提前到凭据分支之前，避免 SNMP-only 分支绕过角色范围。旧 IP inventory 辅助路径改为先读 IP-MIB。统一 NSOT 调用端跳过旧的重复设备 CLI 地址扫描，但在全量刷新时仍保留 CMDB `ip_addresses` 到 inventory 的登记投影。
