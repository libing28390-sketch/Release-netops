# Nexora 自动拓扑场景模拟数据与测试方案

> 日期：2026-08-10  
> 范围：自动拓扑需求 T01-T63；重点执行 T48-T63 非标网络场景  
> 数据基线：`public/templates/asset_import_template.xlsx` 的“网络设备模板”工作表  
> 测试方式：资产数据按现有 Excel 模板导入；拓扑 Evidence/Relation 使用测试夹具注入，不连接真实设备、不写设备配置  
> 本文状态：核心修复已完成并通过自动化回归；真实设备采集兼容性仍需在测试网络验收

## 1. 测试目标

验证 Nexora 新拓扑引擎是否满足以下原则：

1. Role、Function、Site、Zone 只描述资产身份和语义，不硬编码设备层级。
2. LLDP/CDP 只能产生物理邻接事实，不直接决定上下游。
3. OSPF、ISIS、BGP、路由、STP 等证据不会误生成 PHYSICAL Edge。
4. 同一批资产可以形成 Physical、L2、L3、Site、OOB 等不同视图。
5. 支持双核心、双上联、多父节点、Peer、跨 Site、OOB、HA、IRF、Ring、无线控制等非树形关系。
6. Unknown 是正式状态；算法无法确认语义时不强制猜测。
7. Relation Override 与 Layout Override 分离，自动发现不能覆盖人工确认事实。
8. Edge、Evidence、Group、History 能够持久化并追踪变化。

本轮不测试公有云 VPC/VNet、Kubernetes、云资源发现和云原生 Overlay。

## 2. 资产导入模板基线

现有资产模板包含 5 个工作表：

- 填写说明
- 服务器模板
- 网络设备模板
- 参数可选值参考
- 下拉选项

“网络设备模板”共有 39 列。拓扑模拟重点使用以下字段：

| Excel 字段 | 内部字段 | 本方案用途 |
| --- | --- | --- |
| 主机名 | `hostname` | 作为可读设备身份和测试断言键 |
| 资产编号 | `asset_tag` | 保证每条模拟资产唯一 |
| 厂商 | `vendor` | 验证 Cisco、Huawei、H3C 多厂商契约 |
| 型号 | `model` | 提供资产上下文，不用于推断拓扑层级 |
| 平台 | `platform` | 决定命令目录、驱动和解析器 |
| 管理IP | `management_ip` | 设备唯一性与协议目标匹配 |
| 管理端口 | `management_port` | 固定为 22，仅作模板合法值 |
| 连接方式 | `connection_method` | 固定为 `ssh`，模拟测试不建立连接 |
| 状态 | `status` | 固定为 `active` |
| Role | `device_role` | 设备身份；不能直接决定 Rank |
| 设备分类 | `device_category` | `switch/router/firewall/wireless_controller/wireless_ap` |
| 录入来源 | `asset_origin` | 固定为 `new` |
| 站点 | `site_id` | 用于站点内拓扑和跨站点拓扑隔离 |
| 功能 | `function` | Internet Edge、Campus Core、OOB Management 等语义 |
| 区域 | `zone` | Internet、WAN、LAN、DMZ、OOB、Wireless |
| 标签代码 | `tag_codes` | 标记测试批次、厂商和场景 |
| 投产状态 | `lifecycle_status` | 使用 `staging`，避免测试数据直接成为生产资产 |

其余字段使用以下规则：

```text
序列号              每台唯一，格式 TOPO-20260810-xxx
机柜/U位/功耗        留空，避免触发机柜自动创建
SNMP社区名           留空，不在文档中保存敏感信息
普通/特权/Enable密码 留空
绑定凭据             留空；真实采集测试时另行绑定只读测试凭据
部门                 Topology-Lab
备注                 topology-scenario-fixture
投产状态             staging
录入来源             new
```

注意：资产模板只负责导入 DEVICE 节点。Internet、ISP、MPLS、Carrier 等 EXTERNAL 节点，以及 Evidence、Relation、Group 数据不应伪装成资产行。

## 3. 模拟资产数据

以下行应填写到原模板的“网络设备模板”工作表。表中使用模板支持的规范值；没有列出的字段按上一节默认值填写。

| 主机名 | 资产编号 | 序列号 | 厂商 | 型号 | 平台 | 管理IP | Role | 设备分类 | 站点 | 功能 | 区域 | 标签代码 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| edge-sw-bj-01 | TOPO-NET-001 | TOPO-20260810-001 | Cisco | C9300-24T | cisco_ios | 10.254.10.1 | access | switch | TOPO-BJ | Internet Edge | Internet | test.topology,vendor.cisco,scenario.t49 |
| fw-bj-01 | TOPO-NET-002 | TOPO-20260810-002 | Huawei | USG6600 | huawei_usg | 10.254.10.2 | firewall | firewall | TOPO-BJ | Internet Edge | WAN | test.topology,vendor.huawei,scenario.t52 |
| fw-bj-02 | TOPO-NET-003 | TOPO-20260810-003 | Huawei | USG6600 | huawei_usg | 10.254.10.3 | firewall | firewall | TOPO-BJ | Internet Edge | WAN | test.topology,vendor.huawei,scenario.t52 |
| core-bj-01 | TOPO-NET-004 | TOPO-20260810-004 | H3C | S6800 | h3c_comware | 10.254.10.4 | core | switch | TOPO-BJ | Campus Core | LAN | test.topology,vendor.h3c,scenario.t53 |
| core-bj-02 | TOPO-NET-005 | TOPO-20260810-005 | H3C | S6800 | h3c_comware | 10.254.10.5 | core | switch | TOPO-BJ | Campus Core | LAN | test.topology,vendor.h3c,scenario.t53 |
| agg-bj-01 | TOPO-NET-006 | TOPO-20260810-006 | Cisco | C9300-48P | cisco_xe | 10.254.10.6 | distribution | switch | TOPO-BJ | Business Aggregation | LAN | test.topology,vendor.cisco,scenario.t55 |
| agg-bj-02 | TOPO-NET-007 | TOPO-20260810-007 | Cisco | C9300-48P | cisco_xe | 10.254.10.7 | distribution | switch | TOPO-BJ | Business Aggregation | LAN | test.topology,vendor.cisco,scenario.t55 |
| access-bj-01 | TOPO-NET-008 | TOPO-20260810-008 | Huawei | S5735 | huawei_vrpv8 | 10.254.10.8 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,vendor.huawei,scenario.t54 |
| fw-dmz-bj-01 | TOPO-NET-009 | TOPO-20260810-009 | Fortinet | FortiGate-100F | fortinet | 10.254.10.9 | firewall | firewall | TOPO-BJ | DMZ Security | DMZ | test.topology,scenario.t50 |
| sw-dmz-bj-01 | TOPO-NET-010 | TOPO-20260810-010 | Cisco | C9200-24T | cisco_ios | 10.254.10.10 | access | switch | TOPO-BJ | Server Access | DMZ | test.topology,scenario.t50 |
| ring-sw-01 | TOPO-NET-011 | TOPO-20260810-011 | H3C | S5130 | h3c_comware | 10.254.10.11 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,scenario.t56 |
| ring-sw-02 | TOPO-NET-012 | TOPO-20260810-012 | H3C | S5130 | h3c_comware | 10.254.10.12 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,scenario.t56 |
| ring-sw-03 | TOPO-NET-013 | TOPO-20260810-013 | H3C | S5130 | h3c_comware | 10.254.10.13 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,scenario.t56 |
| ring-sw-04 | TOPO-NET-014 | TOPO-20260810-014 | H3C | S5130 | h3c_comware | 10.254.10.14 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,scenario.t56 |
| oob-sw-bj-01 | TOPO-NET-015 | TOPO-20260810-015 | Cisco | C9200-24T | cisco_ios | 10.254.10.15 | switch | switch | TOPO-BJ | OOB Management | OOB | test.topology,scenario.t60 |
| ac-bj-01 | TOPO-NET-016 | TOPO-20260810-016 | Huawei | AC6508 | huawei_vrpv8 | 10.254.10.16 | wireless_controller | wireless_controller | TOPO-BJ | Wireless Controller | Wireless | test.topology,scenario.t61 |
| ap-bj-01 | TOPO-NET-017 | TOPO-20260810-017 | Huawei | AirEngine-5762 | huawei_vrpv8 | 10.254.10.17 | wireless_ap | wireless_ap | TOPO-BJ | Terminal Access | Wireless | test.topology,scenario.t61 |
| r1-bj | TOPO-NET-018 | TOPO-20260810-018 | Huawei | AR6140 | huawei_vrpv8 | 10.254.10.18 | router | router | TOPO-BJ | WAN Edge | WAN | test.topology,scenario.t62 |
| transit-sw-01 | TOPO-NET-019 | TOPO-20260810-019 | Cisco | C9200-24T | cisco_ios | 10.254.10.19 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,scenario.t62 |
| transit-sw-02 | TOPO-NET-020 | TOPO-20260810-020 | Cisco | C9200-24T | cisco_ios | 10.254.10.20 | access | switch | TOPO-BJ | Terminal Access | LAN | test.topology,scenario.t62 |
| r2-bj | TOPO-NET-021 | TOPO-20260810-021 | H3C | MSR3600 | h3c_comware | 10.254.10.21 | router | router | TOPO-BJ | WAN Edge | WAN | test.topology,scenario.t62 |
| fw-sh-01 | TOPO-NET-022 | TOPO-20260810-022 | Huawei | USG6600 | huawei_usg | 10.254.20.2 | firewall | firewall | TOPO-SH | Site Interconnect | WAN | test.topology,scenario.t51 |
| core-sh-01 | TOPO-NET-023 | TOPO-20260810-023 | H3C | S6800 | h3c_comware | 10.254.20.4 | core | switch | TOPO-SH | Campus Core | LAN | test.topology,scenario.t51 |

### 3.1 EXTERNAL 与 GROUP 节点

这些节点由图引擎或测试夹具创建，不进入资产 Excel：

| node_id | node_type | display_name | 用途 |
| --- | --- | --- | --- |
| external:internet | EXTERNAL | Internet | T48-T52 外部网络入口 |
| external:isp-a | EXTERNAL | ISP-A | T52 多 Anchor |
| external:isp-b | EXTERNAL | ISP-B | T52 多 Anchor |
| external:mpls | EXTERNAL | MPLS | T51 跨站点关系 |
| group:ring-bj-01 | GROUP | BJ Ring 01 | T56 Ring Group |
| group:fw-ha-bj | GROUP | BJ Firewall HA | T57 HA Group |
| group:irf-bj | GROUP | BJ Core IRF | T58 IRF Group |
| group:gateway-ha-bj | GROUP | BJ Gateway HA | T59 VRRP/HSRP Group |

## 4. Evidence 测试数据契约

测试夹具统一使用以下结构。`source_node` 和 `target_node` 引用导入后设备 ID；实现测试时可先按 hostname 查询对应 ID。

```json
{
  "scenario_id": "T54",
  "source_node": "core-bj-01",
  "target_node": "access-bj-01",
  "source_interface": "Ten-GigabitEthernet1/0/49",
  "target_interface": "XGigabitEthernet1/0/49",
  "source_type": "lldp",
  "protocol": "lldp",
  "relation_type": "PHYSICAL",
  "direction": "undirected",
  "confidence": 0.95,
  "observed_at": "2026-08-10T08:00:00+08:00",
  "metadata": {
    "fixture": true,
    "read_only": true
  }
}
```

构造 Evidence 时遵守以下约束：

- LLDP/CDP 可以创建 PHYSICAL。
- OSPF、ISIS、BGP、Interface IP、Routing、ARP/MAC 不允许创建 PHYSICAL。
- 同一条双向 LLDP 使用互换后的设备和接口，必须归并为同一个规范化 Edge。
- Interface Description 只提供低权重语义证据。
- 人工确认使用 `source_type=manual`、`is_manual=1`、`manual_confirmed=1`。
- 测试时间固定，避免因为当前时间和 TTL 造成不稳定结果。

## 5. T48-T63 场景数据与模拟结论

状态说明：

- **可模拟通过**：当前服务函数能够表达并得到核心预期结果。
- **核心链路通过**：归一化、建图、持久化、视图或布局已经有自动化断言。
- **采集待联调**：引擎可以完整承载和展示，但仍需补充或验证厂商专用只读采集器。

| 场景 | 构造关系 | 核心断言 | 纯内存模拟结果 | 当前判断 |
| --- | --- | --- | --- | --- |
| T48 标准园区网 | `FW -> CORE -> AGG -> ACCESS`，全部 HIERARCHICAL | Rank 为 `[0,1,2,3]`；Role 修改后 Edge/Rank 不变 | `[0,1,2,3]` | 可模拟通过 |
| T49 防火墙上方有交换机 | `Internet -> edge-sw-bj-01 -> fw-bj-01 -> core-bj-01` | Access Role 的 Edge-SW 可以位于 Firewall 上方 | `[0,1,2,3]` | 可模拟通过 |
| T50 防火墙位于核心下游 | `core-bj-01 -> fw-dmz-bj-01 -> sw-dmz-bj-01` | Firewall Role 不会被强制移动到顶部 | `[0,1,2]` | 可模拟通过 |
| T51 防火墙用于 Site 互联 | `core-bj-01 -> fw-bj-01`；`fw-bj-01 -- MPLS -- fw-sh-01` | 生成 INTER_SITE；远端 Site 不继承本地纵向 Rank | BJ Rank `0/1`，SH 端 Rank `0` | 可模拟通过 |
| T52 双 ISP | `ISP-A -> FW01`、`ISP-B -> FW02`、`FW01/FW02 -> CORE` | 支持多个 Anchor；CORE 有两个父关系 | 识别 4 个边界/外部 Anchor，CORE Rank 2 | 可模拟通过 |
| T53 双核心 | `core-bj-01 == core-bj-02`，PEER | 两个 Core 同 Rank | 两者 Rank 均为 0 | 可模拟通过 |
| T54 接入双上联 | `CORE01 -> ACCESS01`、`CORE02 -> ACCESS01` | ACCESS 保留两条入边，不使用单 parent_id | ACCESS Rank 1，入边 2 | 可模拟通过 |
| T55 双汇聚 | `CORE01/02 -> AGG01/02`、`AGG01 == AGG02`、两个 AGG -> ACCESS | AGG 同 Rank；ACCESS 只增加一层 | Core 0、Agg 1、Access 2 | 可模拟通过 |
| T56 环网 | 四台 Ring SW 形成闭环，`group_type=RING` | 数据库保存环和 Group；布局为环形且稳定 | 双端成员去重完整；后端与前端均使用确定性环形布局 | 核心链路通过 |
| T57 Firewall HA | `FW01 == FW02`，HA_PEER，`group_id=fw-ha-bj` | 保留 HA_PEER 子类型；可折叠为 HA Group | HA_PEER 子类型、HA Group、Logical View 均保留 | 核心链路通过；采集待联调 |
| T58 IRF/Stack/CSS | `CORE01 == CORE02`，IRF，`group_id=irf-bj` | Physical View 显示成员；Logical View 显示 Group | IRF/STACK/CSS/VC 已进入 Physical、L2、Logical 视图，Group 成员可读取 | 核心链路通过；采集待联调 |
| T59 VRRP/HSRP | CORE01/02 共享 Gateway HA Group | VRRP_HSRP 不合并物理设备 | VRRP_HSRP 保持独立逻辑关系并排除主 Rank | 核心链路通过；采集待联调 |
| T60 OOB | `oob-sw-bj-01 -- CORE/AGG/ACCESS`，OOB | OOB Edge 不参与生产 Rank；OOB View 可单独读取 | OOB `rank_excluded=1`，生产 Rank 未被改变 | 可模拟通过 |
| T61 无线 | `Access-SW -- AP` 为 PHYSICAL；`AC == AP` 为 CONTROL | 同一 AP 同时存在两种 Relation，视图互不污染 | Physical 与 CONTROL 同时保留，CONTROL 可在 Logical View 读取 | 核心链路通过；CONTROL 采集待联调 |
| T62 L3 邻接穿越二层 | Physical：`R1-SW1-SW2-R2`；L3：`R1==R2` OSPF | Physical View 3 条物理边；L3 View 1 条逻辑边 | Physical=3，L3=1 | 可模拟通过 |
| T63 未知方向 | `PHYSICAL + direction=unknown` | 保留 Unknown Direction，不强制 Parent/Child | Direction 保持 `unknown`；反向观测仍归并为同一无向物理事实 | 核心链路通过 |

### 5.1 可执行夹具示例：T55 双汇聚

```json
{
  "scenario_id": "T55",
  "nodes": [
    {"id": "core-bj-01", "role": "core", "site_id": "TOPO-BJ"},
    {"id": "core-bj-02", "role": "core", "site_id": "TOPO-BJ"},
    {"id": "agg-bj-01", "role": "distribution", "site_id": "TOPO-BJ"},
    {"id": "agg-bj-02", "role": "distribution", "site_id": "TOPO-BJ"},
    {"id": "access-bj-01", "role": "access", "site_id": "TOPO-BJ"}
  ],
  "observations": [
    {"source_node": "core-bj-01", "target_node": "agg-bj-01", "source_type": "manual", "relation_type": "HIERARCHICAL", "direction": "directed", "confidence": 1.0},
    {"source_node": "core-bj-02", "target_node": "agg-bj-02", "source_type": "manual", "relation_type": "HIERARCHICAL", "direction": "directed", "confidence": 1.0},
    {"source_node": "agg-bj-01", "target_node": "agg-bj-02", "source_type": "manual", "relation_type": "PEER", "direction": "undirected", "confidence": 1.0},
    {"source_node": "agg-bj-01", "target_node": "access-bj-01", "source_type": "manual", "relation_type": "HIERARCHICAL", "direction": "directed", "confidence": 1.0},
    {"source_node": "agg-bj-02", "target_node": "access-bj-01", "source_type": "manual", "relation_type": "HIERARCHICAL", "direction": "directed", "confidence": 1.0}
  ],
  "expected": {
    "ranks": {
      "core-bj-01": 0,
      "core-bj-02": 0,
      "agg-bj-01": 1,
      "agg-bj-02": 1,
      "access-bj-01": 2
    },
    "access_parent_count": 2
  }
}
```

### 5.2 可执行夹具示例：T62 Physical/L3 隔离

```json
{
  "scenario_id": "T62",
  "observations": [
    {"source_node": "r1-bj", "target_node": "transit-sw-01", "source_type": "lldp", "relation_type": "PHYSICAL", "direction": "undirected", "confidence": 0.95},
    {"source_node": "transit-sw-01", "target_node": "transit-sw-02", "source_type": "lldp", "relation_type": "PHYSICAL", "direction": "undirected", "confidence": 0.95},
    {"source_node": "transit-sw-02", "target_node": "r2-bj", "source_type": "lldp", "relation_type": "PHYSICAL", "direction": "undirected", "confidence": 0.95},
    {"source_node": "r1-bj", "target_node": "r2-bj", "source_type": "ospf", "protocol": "ospf", "relation_type": "L3_NEIGHBOR", "direction": "undirected", "confidence": 0.75}
  ],
  "expected": {
    "physical_view_edges": 3,
    "l3_view_edges": 1,
    "physical_relation_types": ["PHYSICAL"],
    "l3_relation_types": ["L3_NEIGHBOR"]
  }
}
```

## 6. T01-T47 能力测试矩阵

| 需求范围 | 测试方法 | 关键断言 |
| --- | --- | --- |
| T01-T05 资产语义 | 使用同一组 Edge，只修改 Role/Function/Zone；分别按 TOPO-BJ、TOPO-SH 查询 | Role 改变不修改 Edge；Site 是一等属性；Zone 不直接固定 Rank |
| T06 Node 模型 | 构造 DEVICE、SITE、EXTERNAL、VIRTUAL、GROUP、UNKNOWN | Node 类型完整保留；非 DEVICE 不进入设备在线状态统计 |
| T07-T08 Edge/Relation | 对全部 Relation Type 做 schema 参数化测试 | source/target、接口、方向、状态、时间、两类 Confidence 均可读写 |
| T09-T11 Evidence/Confidence | 单向 LLDP、双向 LLDP、LLDP+CDP、LLDP+Description、多协议组合 | 证据归并稳定；存在可信度与语义可信度分别计算；顺序无关 |
| T12 LLDP | 输入双向 LLDP，并交换设备与端口顺序 | 只生成一个 PHYSICAL Edge，不产生 Parent/Child |
| T13 /30 /31 | 仅输入 Interface IP，再增加 LLDP | 仅 IP 时只有 L3；加入 LLDP 后同时存在 Physical 与 L3 |
| T14 ARP/MAC | 构造 MAC 学习路径和终端定位 | 不产生 Switch-to-Switch PHYSICAL，只产生 Endpoint/定位证据 |
| T15 Description | 输入 TO-CORE、TO-FW、PEER、HA、STACK、OOB 等描述 | 只能作为低权重语义证据，不能单独形成高可信 PHYSICAL |
| T16-T18 OSPF/ISIS/BGP | 使用 Cisco/Huawei/H3C 解析夹具 | OSPF/ISIS 为 L3_NEIGHBOR；eBGP 可为 WAN；均不得为 PHYSICAL |
| T19 Routing | 输入默认路由和普通 Next-Hop | 生成 LOGICAL/ROUTE_NEXT_HOP；默认路由可辅助 Anchor，但不能确认物理直连 |
| T20 Anchor | 同时提供 ISP-A、ISP-B、MPLS、人工 Anchor | 返回多个 anchors，不存在单 Root 假设 |
| T21 Rank | DAG、Peer、多父节点、有向环、无关孤立节点、Edge 乱序 | DAG 满足约束；Peer 同 Rank；Edge 顺序和孤立节点不能改变已有 Rank |
| T22 Layout | 双核心、双汇聚、交叉边、环网、Group、手工坐标 | 布局稳定、交叉减少；Ring 使用环形布局；人工坐标优先 |
| T23 Peer | Manual、Description、MLAG/vPC、协议邻居分别提供 Peer 证据 | PEER 保持同 Rank；低置信证据不能覆盖人工分类 |
| T24-T28 HA/Stack/Ring/STP | 构造 HA、IRF、VRRP、Ring、STP Forwarding/Blocking | Group 类型不混淆；VRRP 不合并设备；STP 状态保留并正确渲染 |
| T29-T31 OOB/Site/External | 构造两站点和独立 OOB 网络 | OOB、INTER_SITE 均不污染站点内部 Rank；External 不伪装成在线设备 |
| T32-T35 非标关系 | 运行防火墙 A-F、Branch、无线双关系、多父节点场景 | Firewall Role 不改变位置；Branch 不被插入主干；AP 可有两种关系 |
| T36 Tunnel | 写入 IPsec/GRE/VPN/TUNNEL | 数据库、API、历史均可承载；V1 不要求自动发现 |
| T37 Unknown | Unknown Role/Function/Relation/Direction/Site/External 全组合 | Unknown 不被自动改写成 Core/Access 或 directed/undirected |
| T38 Override | 先自动发现，再人工修改 Relation 和 Layout，再次自动发现 | Relation 人工确认保留；Layout 变化不修改 Relation |
| T39-T40 History | 连续执行新增、保持、消失、重新出现、关系变更 | Edge 不物理删除；first_seen 稳定；last_seen 更新；事件类型准确且无重复 |
| T41-T46 多视图 | 使用同一底层图分别读取 all/physical/l2/l3/site/oob | 各视图仅包含允许的 Relation；节点集合与边集合一致；互不污染 |
| T47 Pipeline | 从资产、协议记录、Evidence、Edge、Rank 到前端渲染做一次端到端测试 | 每阶段有明确输入输出；失败可定位；无静默吞错 |

## 7. 分层执行方案

### 7.1 第一层：纯函数单元测试

目标函数：

```text
normalize_role
normalize_node
normalize_observation
canonical_edge_key
detect_topology_anchors
calculate_dynamic_ranks
build_graph
layout_graph
```

优先覆盖：

- Edge/Observation 顺序随机化测试。
- 添加无关孤立节点后的不变性测试。
- 双向证据去重。
- Self-loop 过滤。
- 有向环和 SCC 测试。
- Unknown Direction 保留测试。
- Relation Type 全枚举参数化测试。

### 7.2 第二层：数据库集成测试

使用迁移后的隔离测试数据库，按事务回滚：

1. 导入资产节点。
2. 持久化 Edge 和 Evidence。
3. 再次持久化相同数据，验证幂等。
4. 删除一条输入证据，验证 Edge 变为 stale/inactive，而不是物理删除。
5. 对人工确认 Edge 再执行自动构建，验证人工 Relation 不被覆盖。
6. 检查 topology_history、topology_edge_history、topology_change_events。
7. 检查 tenant_id 隔离和跨租户访问拒绝。

### 7.3 第三层：API 契约测试

至少覆盖：

```text
GET  /api/topology/graph?view=physical
GET  /api/topology/graph?view=l2
GET  /api/topology/graph?view=l3
GET  /api/topology/graph?view=site
GET  /api/topology/graph?view=oob
GET  /api/topology/graph/history
GET  /api/topology/graph/edges/{edge_id}/evidence
POST /api/topology/graph/rebuild
```

断言：

- 未登录为 401、无权限为 403。
- tenant_id 由会话决定，不能通过查询参数越权。
- 视图 Relation 白名单准确。
- include_stale、limit、site_id 行为明确。
- 重建失败不产生半成品图。

### 7.4 第四层：前端场景验收

对每个场景保存一张基准截图或 DOM 快照，检查：

- SITE/GROUP/EXTERNAL/UNKNOWN 不被展示成在线设备。
- 站点设备数和链路数不重复累计。
- Peer 同层、双上联、多父节点显示正确。
- Physical/L2/L3/OOB 视图切换后不残留上一视图 Edge。
- STP Blocking/Discarding 使用区别于 Forwarding 的线型。
- Relation Confidence 与 Existence Confidence 分开展示。
- 手工拖拽只改变坐标，手工确认才改变关系。

### 7.5 第五层：多厂商采集夹具

每类协议至少准备 Cisco、Huawei、H3C 三套只读命令输出夹具：

| 能力 | Cisco | Huawei | H3C |
| --- | --- | --- | --- |
| LLDP | `show lldp neighbors detail` | `display lldp neighbor verbose` | `display lldp neighbor-information verbose` |
| OSPF | Cisco show 命令族 | Huawei display 命令族 | H3C display 命令族 |
| ISIS | Cisco show 命令族 | Huawei display 命令族 | H3C display 命令族 |
| BGP | Cisco show 命令族 | Huawei display 命令族 | H3C display 命令族 |
| STP | Cisco show 命令族 | Huawei display 命令族 | H3C display 命令族 |
| Stack/IRF | StackWise | CSS/iStack | IRF |

H3C TextFSM 必须使用 `hp_comware` 作为解析平台；接口比较必须使用共享接口规范化器。

### 7.6 第六层：规模与稳定性测试

建议生成以下数据规模：

| 规模 | 节点 | Edge | Evidence | 目标 |
| --- | ---: | ---: | ---: | --- |
| Small | 50 | 100 | 250 | 单元与 UI 日常回归 |
| Medium | 500 | 1,200 | 4,000 | API、数据库查询和布局基线 |
| Large | 2,000 | 5,000 | 20,000 | 分页、查询聚合和浏览器稳定性 |
| Stress | 5,000 | 15,000 | 60,000 | 只跑夜间性能测试 |

建议门槛：

- 2,000 节点 / 5,000 Edge 的图读取查询次数不超过 10 次。
- 同一输入重复构建，Edge ID、Rank、Group 和布局坐标保持稳定。
- 增加孤立节点不能改变原有连通分量的 Rank。
- 数据库构建失败必须整体回滚。
- 前端达到上限时进入聚合/分组模式，不直接绘制所有标签和 Evidence。

## 8. 自动化测试落点

```text
backend/tests/topology/test_topology_graph_completion.py
backend/tests/topology/test_topology_graph_service.py
backend/tests/topology/test_topology_protocol_service.py
backend/tests/database/test_m0115_topology_graph_completion.py
backend/tests/platform_registry/test_topology_discovery_performance.py
backend/tests/vendor_audit/test_topology_link_normalization.py
src/utils/topologyLayout.test.ts
```

建议命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/topology -q
npm run test:frontend -- --run src/utils/topologyLayout.test.ts
npm run lint
npm run build
```

## 9. 本轮模拟结论

本轮已完成 T48-T63 的核心引擎修复，并对高风险算法、数据读写和前端布局执行自动化验证：

- 后端拓扑专项：18 项通过。
- 数据库迁移、性能契约和厂商链路规范化：10 项通过。
- 前端布局：4 项通过。
- TypeScript：`tsc --noEmit` 通过。
- Python 编译检查：拓扑服务、拓扑 API、AI Natural Query 均通过。
- Vite 生产构建：通过。

本轮修复点：

1. 使用确定性的 SCC 压缩处理有向环，Edge 乱序或增加孤立节点不再改变已有 Rank。
2. `direction=unknown` 全链路保留，同时无向物理事实仍可做正反向证据归并。
3. `HA_PEER` 保留独立关系类型，不再降级成 `HA`。
4. Group 同时记录 Edge 两端成员并按 Group/Node 去重。
5. RING Group 在后端和前端均使用稳定环形布局。
6. Physical、L2、Logical、External 视图补齐 Stack/IRF/CSS/VC/HA/VRRP/CONTROL 等关系契约。
7. Evidence 数量改为单次聚合查询，避免逐 Edge 查询。
8. SITE/GROUP/EXTERNAL/UNKNOWN 作为图对象展示，不再伪装成在线设备。
9. Graph 读写接口增加认证和租户边界检查。

剩余工作不属于图引擎表达能力缺陷：HA、VRRP/HSRP、部分 Stack/IRF 和无线 CONTROL 的自动发现仍需按厂商准备只读命令输出夹具并做设备联调。在采集器产出标准 Evidence 后，现有建图、持久化、视图和布局链路可直接处理。

## 10. 执行约束

- 不把本方案中的管理 IP 当作真实设备地址。
- 不在文档、夹具或日志中保存真实密码、私钥、Enable Secret、SNMP Community。
- 自动化测试优先使用 mock driver 和厂商 CLI fixture。
- 如需真实设备验证，只允许执行 show/display 等只读命令，并使用专用只读凭据。
- 资产导入、图持久化和历史测试必须在隔离测试租户中执行。
- 测试完成后按测试租户或 `test.topology` 标签定向清理，不得使用全库删除。
