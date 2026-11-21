# SNMP 优先 NSOT 采集与 LibreNMS 事实核对

## 本轮结果

- 追加修正：ARP sweep、即时 IP 定位、MAC/FDB 端点采集和 IP inventory 辅助采集已允许 SNMP-only 在线设备；角色筛选先于凭据分支执行。旧 IP inventory 设备地址 helper 也改为 IP-MIB 优先。统一 NSOT 跳过 endpoint collector 中重复的旧设备 CLI 地址扫描，全量任务仍执行 CMDB IPAM 登记导入，避免丢掉这项旧行为。
- 新增完整的 SNMP 表采集与完整性校验：Q-BRIDGE FDB、IP-FORWARD-MIB IPv4/IPv6 路由，以及 BGP4、OSPFv2、OSPFv3、ISIS 邻居。SNMP 凭据支持 v1/v2c/v3；核心表按完整 walk 读取，不设行数上限。字段缺失、索引不一致、值无法解析或端口映射不完整时，调用方保留 CLI/TextFSM 回退。
- MAC/FDB 的活动端点定位路径先采 Q-BRIDGE-MIB，失败时回到现有平台/CLI采集。该表有 created/updated 时间戳和过期清理，但不会保存完整 MAC 迁移事件序列。
- 默认路由表先采 IP-FORWARD-MIB。已知非默认 VRF 仍由现有按 VRF 的 CLI 命令补采，因为默认 SNMP context 不代表所有 VRF；SNMP 默认表失败时保留原来的 CLI VRF 探测路径。若非默认 VRF 补采失败，不用不完整结果覆盖旧设备快照。
- 动态路由邻居逐协议先采 SNMP。BGP、OSPFv2/v3、IS-IS、RIPv2 使用对应 MIB；Cisco EIGRP 使用 CISCO-EIGRP-MIB。统一 NSOT 不再禁用 EIGRP/RIP；只在策略启用或现有路由证据提升时采集，MIB 完整且有记录时不为对应协议打开 CLI；只有采集失败、结果不完整或空表完整性无法确认时才回退该协议。标准 RIPv2 peer 表是可选组，因此空表仍保守回退。EIGRP 仅在归一化为 Cisco 平台时访问其私有 MIB，其他平台直接使用 CLI。BGP local AS 和标准 MIB 可读到的 established time 映射到已有字段。为兼容现有存储/UI，OSPFv2 与 OSPFv3 暂都归入 `ospf` 协议键，数据库暂时不能区分协议族。
- 接口采集现由 IF-MIB、IP-MIB、Q-BRIDGE-MIB 分别读取状态/描述/速率/MAC/MTU、IPv4/IPv6 地址、VLAN 与端口成员关系；IP 按 ifIndex 合并，VLAN 按 bridge-port → ifIndex 映射。每域完整后独立写入，缺失域才发起对应 CLI category，失败保留旧快照。统一 NSOT 流程关闭旧 `sync_topology_and_interfaces_job` 中的重复接口 SSH/CLI 阶段，之后由 `collect_interface_status_for_online_devices` 单次完成接口采集；完整 SNMP 域不再打开 SSH。
- 拓扑 LAG 父子关系现在独立于 LLDP 的 SNMP/SSH 来源：完整 walk `dot3adAggPortAttachedAggID`，以 IF-MIB `ifName`/`ifDescr` 映射聚合口和成员口；取消原有 4096 行上限、支持 SNMPv3，并将该 helper 的整表超时提高到 30 秒。完整 SNMP 结果直接写入；不完整/不支持时该事实域单独回退 `eth_trunk` CLI/TextFSM。完整 IF-MIB 能证明无 LAG 时可以清理旧关系；MIB 不可用/部分映射或 CLI 未匹配时保留旧关系。状态缺失记为 `unknown`。
- 完整 BGP RIB 继续用 CLI/TextFSM。RFC 1657 BGP4-MIB 提供 IPv4 接收路径及 AS_PATH、NEXT_HOP、LOCAL_PREF、MED、ORIGIN、BEST 等属性，但该范围不能完整覆盖设备 CLI 中的 IPv6、VRF 和厂商 weight 字段，因此当前整体 RIB 仍以 CLI 保证范围完整；SNMP peer collector 只提供邻居状态，不能代替 RIB。
- 接口剩余边界：接口状态/地址 fallback 共用现有 `interfaces` category，地址缺失时 CLI 可能同时读取接口状态，但合并仍保留 IF-MIB 状态。MAC/MTU 当前没有专用 CLI category，SNMP 不完整时保留旧值。现有数据模型对接口只保留一个主 IP、IP inventory 的 IP 是全局主键，且没有完整 tagged/untagged 关系表；重复 IP 与歧义 VLAN 不作猜测。
- `poll_endpoints_job` 仍只从缓存构建投影；其 `return` 之后的旧设备采集逻辑不可达。本轮没有把这条死代码说成新增的活动采集流程。
- 追加快照保护审查：ARP SNMP 行必须全部归一化；CLI/TextFSM 只有 `matched` 且行完整，或原始输出兜底确实解析出记录，才可作为成功。解析空/未匹配/坏行现在计为失败并触发回退，避免将空结果上报为健康采集。
- MAC/FDB 改为按设备快照处理：成功设备事务性删除并替换旧行，失败设备保留上次数据；只要任一目标交换机本轮采集失败，就不按不完整 FDB 重算或停用终端位置。路由表、BGP RIB 和动态邻居的 CLI fallback 也要求非空、完整归一化记录；不匹配或不完整时保留上次快照。当前不能证明的空路由、ARP、FDB、BGP CLI 表不会作为空快照清理旧记录；SNMP 动态邻居 helper 明确确认无邻居时仍可作为成功空快照。

## LibreNMS 附件核对

| 附件说法 | 核对结果 | 更准确的表述 |
| --- | --- | --- |
| FDB 可采 VLAN/端口并保存历史 | 大体准确 | LibreNMS 映射 FDB、VLAN 和 bridge port/ifIndex，并保存创建/更新时间和当前记录；旧行会清理，端口变更更新同一记录，不等于完整迁移事件轨迹。 |
| IPv4/IPv6 路由默认最多 1000 条并有历史 | 基本准确，需限定 | 通用 MIB 分支默认上限为 1000、可配置；超限时抛出 `TooManyRoutes` 并记录跳过，不会截取前 1000 条。之前的路由记录会保留供历史查看并由 daily 清理；这是发现周期的快照历史，不是实时轮询。OS 专用 `RouteDiscovery` 可绕过通用分支。 |
| BGP 状态/远端 AS/计数/建立时间/错误 | 大体准确；前缀数需拆开说 | `/api/v0/bgp` 的 peer 记录包含状态、remote AS、UPDATE/消息计数、建立时间和部分错误字段；前缀计数在独立的 `/api/v0/routing/bgp/cbgp` 数据中按 AFI/SAFI 提供，不是基础 peer 记录的通用字段，具体可用字段取决于设备 MIB/实现。Session Up/Down/Flap 事件按轮询观察到的状态或建立时间变化产生，不能保证捕获两轮之间又恢复的短暂抖动。 |
| OSPFv2 和 OSPFv3 可采邻居 | 准确，模块阶段需区分 | OSPFv2 在 `Ospf` poller 中走 `OSPF-MIB::ospfNbrTable`，OSPFv3 在 discovery/poller 中走 `OSPFV3-MIB::ospfv3NbrTable`。两者都会同步当前模型并清掉未返回的邻居；当前邻居表不是事件历史。 |
| IS-IS 未确认通用原生支持 | 不准确/过时 | LibreNMS 有通用 `ISIS-MIB` discovery/polling；设备实现不一，仍可能需要厂商适配。 |
| FDB 查询 API | 准确 | 官方 Switching API 提供 FDB 列表、按 MAC 查询和带设备/接口可读名称的 detail 接口；这些 API 读取 LibreNMS 已采集的数据，不代表调用 API 时会实时向设备采集。 |
| SNMP 支持等同于任意设备都能读到 | 不成立 | OID 实现、协议是否启用、SNMP view/权限和 VRF/context 都会影响结果；需在目标型号与系统版本上实测。 |
| PostgreSQL/时序库存储规划 | 设计建议 | 这部分是 Nexora 的架构建议，不是 LibreNMS 功能事实，需要按页面、查询和保留需求自行评估。 |

另外，文档中的 `discovery-protocols` 指 LLDP/CDP/FDP 邻居发现及 OSPF/OSPFv3 自动发现；它不等于 OSPF 邻居表采集模块。通用 ISIS-MIB 邻居发现/轮询由独立模块实现。

## 主要变更文件

- `backend/services/snmp_service.py`：完整 FDB、路由和 BGP/OSPF/IS-IS/RIPv2/Cisco EIGRP 邻居采集 helper。
- `backend/services/topology_service.py`：LAG 采集独立于 LLDP 成功协议；按域执行 SNMP 优先和 CLI/TextFSM 回退，并保留旧快照保护。
- `backend/services/topology_snmp_aggregation_service.py`：LAG 改用无上限完整 walk，支持 SNMPv3 profile 和更长整表超时。
- `backend/services/ip_locator_service.py`：默认路由的 SNMP 优先路径及已知 VRF 保底逻辑；活动 FDB 路径使用 SNMP 优先。
- `backend/services/interface_collection_service.py`：接口 IF-MIB/IP-MIB/Q-BRIDGE-MIB 采集、逐域完整性、快照保护和 CLI 回退。
- `backend/services/scheduler_service.py`：关闭统一 NSOT 流程中的旧重复接口收集；动态邻居按协议 SNMP 优先与局部 CLI 回退；保存 BGP local AS/established time。
- `backend/services/collection_plan_service.py`、`backend/services/nsot_collection_preview_service.py`：采集范围、RIP/EIGRP 操作项和传输描述。
- `handoff.md`：记录行为、边界和历史状态更新。

## 静态验证

- Python AST 解析通过：`snmp_service.py`、`interface_collection_service.py`、`ip_locator_service.py`、`scheduler_service.py`、`collection_plan_service.py`、`nsot_collection_preview_service.py`、`topology_service.py`，包括本次快照保护变更。
- `git diff --check` 通过；Git 仅提示个别工作区文件的 LF/CRLF 转换警告。
- 按用户既有要求，未运行测试或构建；未连接设备做 SNMP/SSH 验证，未部署或推送。

## 参考来源

- [LibreNMS Discovery Support](https://docs.librenms.org/Support/Discovery%20Support/)
- [LibreNMS Poller Support](https://docs.librenms.org/Support/Poller%20Support/), [Switching API](https://docs.librenms.org/API/Switching/), [Routing API](https://docs.librenms.org/API/Routing/)
- [LibreNMS Routes module](https://github.com/librenms/librenms/blob/master/LibreNMS/Modules/Routes.php)
- [LibreNMS ARP table module](https://github.com/librenms/librenms/blob/master/LibreNMS/Modules/ArpTable.php)
- [LibreNMS FDB synchronization](https://github.com/librenms/librenms/blob/master/includes/discovery/fdb-table.inc.php)
- [LibreNMS BGP peer polling](https://github.com/librenms/librenms/blob/master/includes/polling/bgp-peers.inc.php)
- [LibreNMS OSPFv2 module](https://github.com/librenms/librenms/blob/master/LibreNMS/Modules/Ospf.php), [OSPFv3 module](https://github.com/librenms/librenms/blob/master/LibreNMS/Modules/Ospfv3.php), [IS-IS module](https://github.com/librenms/librenms/blob/master/LibreNMS/Modules/Isis.php)
- [RFC 1657 BGP4-MIB](https://www.rfc-editor.org/rfc/rfc1657.html), [RFC 1724 RIPv2-MIB](https://www.rfc-editor.org/rfc/rfc1724.html), [Cisco EIGRP MIB neighbor table](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_eigrp/configuration/15-e/ire-15-e-book/eigrp-mib.html), [RFC 4750 OSPFv2-MIB](https://www.rfc-editor.org/info/rfc4750/), [RFC 5643 OSPFv3-MIB](https://www.rfc-editor.org/rfc/rfc5643.html), [RFC 4444 ISIS-MIB](https://www.rfc-editor.org/info/rfc4444/)
