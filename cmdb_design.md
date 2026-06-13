# 企业级网络运维平台 CMDB 与网络基础架构模型设计

本设计方案旨在为商业化网络运维平台提供符合生产级企业网络运维架构的数据模型和技术实现架构，对标 Cisco DNA Center, Cisco Catalyst Center, NetBrain, SolarWinds NPM, NetBox, Infoblox 等行业解决方案。

---

## 第一部分：CMDB 数据模型设计

企业级 CMDB 是整个网络运维平台的核心配置元数据中心。模型包含物理站点、物理机柜、设备实体与物理/逻辑接口的多级关联体系。

### 1. 实体定义

#### 1.1 tenants (租户表)
支持多租户 SaaS 隔离架构。
* **id**: UUID, 主键
* **name**: 租户名称
* **description**: 租户描述

#### 1.2 roles (角色表)
* **id**: UUID, 主键
* **role_name**: 角色名称
* **description**: 角色描述

#### 1.3 users (用户表)
* **id**: UUID, 主键
* **username**: 用户名
* **password_hash**: 密码哈希值
* **email**: 邮箱地址
* **role_id**: 外键, 关联 `roles.id`
* **tenant_id**: 外键, 关联 `tenants.id`
* **is_active**: 是否激活

#### 1.4 sites (站点表)
存储企业物理或逻辑地域信息，作为资产边界的最高级容器。
* **id**: UUID, 主键
* **site_code**: 唯一站点编码, 索引
* **site_name**: 站点名称
* **country**: 国家
* **city**: 城市
* **timezone**: 时区
* **address**: 详细地址
* **status**: 站点状态
* **tenant_id**: 外键, 关联 `tenants.id`

#### 1.5 racks (机柜表)
存储站点内部机房的机柜空间容量信息。
* **id**: UUID, 主键
* **site_id**: 外键, 关联 `sites.id`
* **rack_code**: 机柜编码, 索引
* **rack_name**: 机柜名称
* **total_u**: 总 U 位数
* **available_u**: 可用 U 位数

#### 1.6 device_types (设备型号表)
* **id**: UUID, 主键
* **vendor**: 厂商
* **model**: 设备型号
* **part_number**: 配件编号/型号编码
* **u_height**: 所占 U 高度

#### 1.7 devices (设备表)
整合了资产生命周期与网络监控管理属性的设备表。
* **id**: UUID, 主键
* **hostname**: 设备主机名, 唯一, 索引
* **mgmt_ip**: 管理 IP 地址, 索引
* **asset_tag**: 资产标签
* **device_type_id**: 外键, 关联 `device_types.id`
* **platform**: 操作系统平台名称类型（如 ios-xe, nx-os, junos, comware）
* **vendor**: 厂商
* **model**: 设备型号
* **serial_number**: 序列号, 唯一, 索引
* **site_id**: 外键, 关联 `sites.id`
* **rack_id**: 外键, 关联 `racks.id`
* **os_version**: 操作系统软件版本
* **firmware_version**: 固件/引导版本
* **lifecycle_status**: 生命周期状态（如 production, staging, decommissioned）
* **purchase_date**: 购买日期
* **warranty_expire**: 保修过期日期
* **owner_team**: 负责团队名称
* **criticality**: 资产关键级别（P1, P2, P3）
* **monitoring_enabled**: 是否启用 SNMP/Telemetry 监控
* **config_backup_enabled**: 是否启用配置自动备份
* **last_discovered**: 最后一次被自动发现的时间
* **credential_id**: 外键, 关联凭据中心 `credentials.id`
* **tenant_id**: 外键, 关联 `tenants.id`

#### 1.8 interfaces (接口表)
物理接口与逻辑接口元数据。
* **id**: UUID, 主键
* **device_id**: 外键, 关联 `devices.id`, 级联删除
* **interface_name**: 接口名称, 索引
* **description**: 接口描述
* **admin_status**: 管理状态（up/down）
* **oper_status**: 运行状态（up/down/testing/unknown）
* **mac_address**: MAC 地址, 索引
* **mtu**: MTU 值
* **speed**: 物理速率（bps）
* **interface_type**: 接口类型（physical, subinterface, vlan, loopback, port-channel, tunnel, vtep）
* **duplex**: 双工模式（full, half, auto）
* **bandwidth**: 接口带宽（bps）
* **parent_interface_id**: 外键, 关联自身 `interfaces.id`
* **channel_group**: 聚合组 ID
* **vrf_id**: 外键, 关联 `vrfs.id`
* **switchport_mode**: 交换模式（access, trunk, routed）
* **access_vlan**: Access 接入 VLAN ID
* **native_vlan**: Trunk 本地 VLAN ID
* **allowed_vlans**: Trunk 允许通过的 VLAN 范围定义
* **ip_enabled**: 接口是否启用 IP 配置
* **last_flapped**: 接口最后一次状态变更震荡时间

---

## 第二部分：IPAM 地址管理模型

IPAM（IP Address Management）负责管理企业网络中的网段（Prefix）与 IP 地址池分配，支持复杂的网络地址类型。

### 1. 实体定义

#### 1.1 vrfs (VRF表)
* **id**: UUID, 主键
* **vrf_name**: VRF 名称, 唯一, 索引
* **rd**: Route Distinguisher (如 65000:1)
* **description**: 描述
* **tenant_id**: 外键, 关联 `tenants.id`

#### 1.2 vlans (VLAN表)
* **id**: UUID, 主键
* **vlan_id**: VLAN ID 范围 (1-4094)
* **name**: VLAN 名称
* **site_id**: 外键, 关联 `sites.id`
* **status**: VLAN 状态
* **tenant_id**: 外键, 关联 `tenants.id`

#### 1.3 prefixes (网段表)
存储 CIDR 网段信息，支持父子网段层级嵌套。
* **id**: UUID, 主键
* **prefix**: CIDR 网段（如 `10.0.0.0/8`, `10.1.0.0/16`）, 索引
* **vrf_id**: 外键, 关联 `vrfs.id`
* **vlan_id**: 外键, 关联 `vlans.id`
* **site_id**: 外键, 关联 `sites.id`
* **tenant_id**: 外键, 关联 `tenants.id`
* **status**: 状态（如: container, active, reserved）

#### 1.4 ip_addresses (IP地址表)
存储具体 IP 地址的分配状态与接口映射关系。
* **id**: UUID, 主键
* **ip_address**: IP 地址（IP/Mask 格式）, 索引
* **prefix_id**: 外键, 关联 `prefixes.id`
* **vrf_id**: 外键, 关联 `vrfs.id`
* **device_id**: 外键, 关联 `devices.id`
* **interface_id**: 外键, 关联 `interfaces.id`
* **status**: 状态（如: active, reserved, vip, anycast, dhcp）
* **last_seen**: 最后活跃时间

### 2. 特殊 IP 类型管理机制

* **Loopback IP**: 
  在 `ip_addresses` 表中注册，`status` 标记为 `active`。通过 `interface_id` 关联至 `interfaces` 表中类型为 `loopback` 的虚拟接口。由于 Loopback 没有硬件地址，其 MAC 映射为空。
* **VIP (Virtual IP)**: 
  在 `ip_addresses` 表中注册，`status` 标记为 `vip`。此 VIP 会同时绑定到集群中多台物理设备的虚拟接口（如 HSRP/VRRP 组）。通过 `arp_table` 将该 VIP 解析为虚拟 MAC（如 `00:00:5E:00:01:XX`）。
* **Anycast IP**: 
  在 `ip_addresses` 表中注册，`status` 标记为 `anycast`。在数据库中支持该 IP 绑定到多台不同设备的物理/逻辑接口上，通过动态路由协议（OSPF/BGP）在各站点宣告相同的 Anycast IP。
* **Secondary IP**: 
  单一 `interfaces` 实体可对应多个 `ip_addresses` 实体。在 `ip_addresses` 中通过外键 `interface_id` 实现一对多关联，从而在主接口上配置多个次要 IP 地址。
* **Floating IP**: 
  在 `ip_addresses` 表中注册，`status` 标记为 `floating`。在云网联动或 NAT 场景下，建立专属映射表，将外部 Floating IP 与特定内部私网 IP 地址进行动态映射关联。

---

## 第三部分：拓扑关系模型

拓扑模型定义设备接口之间的互联状态，支持通过网络邻居协议自动发现并生成多层拓扑。

### 1. 实体定义

#### 1.1 topology_links (链路表)
存储两端接口之间的逻辑或物理互联关系。
* **local_device_id**: 外键, 关联 `devices.id`
* **local_interface_id**: 外键, 关联 `interfaces.id`
* **remote_device_id**: 外键, 关联 `devices.id`
* **remote_interface_id**: 外键, 关联 `interfaces.id`
* **protocol**: 发现协议（LLDP, CDP, Static）
* **last_seen**: 最后发现时间
* **主键**: (`local_interface_id`, `remote_interface_id`)

### 2. 拓扑生成机制

* **二层拓扑 (L2 Topology)**:
  通过读取并计算 `neighbor_table` 中 LLDP/CDP 的邻居数据与各设备的 `mac_table` 生成。如果交换机 A 接口 1 学习到交换机 B 接口 2 的 MAC 地址，且 LLDP 邻居关系匹配，则在 `topology_links` 中记录该物理链路。
* **三层拓扑 (L3 Topology)**:
  分析各设备的 `route_table` 及 `ip_addresses`。提取属于同一网段（Prefix）的接口 IP 并建立逻辑对等关系，同时结合 BGP 和 OSPF 协议邻居表构建路由器、防火墙、VRF 之间的三层路由拓扑。
* **路径图生成 (Path Trace)**:
  自源 IP 节点开始，查询 `route_table` 确定下一跳 IP 与出接口，通过 `arp_table` 和 `mac_table` 定位下一跳设备的出入接口，依次迭代直到目的 IP 节点，最后将所经物理与逻辑跳点渲染为可视化网络拓扑路径图。

---

## 第四部分：Endpoint Tracker

Endpoint Tracker 用于追踪接入交换机边缘端口的终端动态。

### 1. 实体定义

#### 1.1 network_endpoints (终端表)
记录终端设备接入网络的位置与属性信息。
* **id**: UUID, 主键
* **ip_address**: 终端 IP 地址, 索引
* **mac_address**: 终端 MAC 地址, 唯一, 索引
* **vlan_id**: 外键, 关联 `vlans.id`
* **device_id**: 外键, 关联 `devices.id`（接入交换机）
* **interface_id**: 外键, 关联 `interfaces.id`（接入端口）
* **endpoint_type**: 终端类型（PC, Server, VM, Printer, Phone, IoT）
* **host_name**: 终端主机名
* **operating_system**: 终端操作系统
* **first_seen**: 首次发现时间
* **last_seen**: 最后发现时间
* **confidence_score**: 置信度得分 (0-100)

#### 1.2 endpoint_history (终端迁移历史表)
记录终端物理接口及网络绑定的变动历史。
* **id**: UUID, 主键
* **ip_address**: 历史 IP 地址
* **mac_address**: 历史 MAC 地址, 索引
* **from_device_id**: 移出设备外键, 关联 `devices.id`
* **from_interface_id**: 移出端口外键, 关联 `interfaces.id`
* **to_device_id**: 移入设备外键, 关联 `devices.id`
* **to_interface_id**: 移入端口外键, 关联 `interfaces.id`
* **vlan_id**: VLAN ID
* **event_time**: 事件记录时间
* **event_type**: 变化类型（如 online, offline, move）

### 2. 实现机制

* 平台分布式 Agent 监听网络核心及汇聚设备的 Syslog 信息（如 MAC 移动告警）与 SNMP Trap。
* 联动 RADIUS 认证服务器（如 Cisco ISE / 802.1X 认证记账报文），实时捕获终端的上线、下线与 IP/MAC 绑定变更。
* 结合 DHCP Snooping 绑定表，自动更新 `network_endpoints`。若终端变更接入端口，系统更新该表并将旧记录归档至 `endpoint_history`。
* 通过集成主动扫描（ICMP / Nmap）和被动流量指纹分析（DHCP Fingerprint, MAC OUI），推断终端的操作系统与设备类型，生成置信度评分。

---

## 第五部分：Credential Vault 设计

凭据中心用于集中管理网络设备访问控制信息，保障系统凭据存储的安全。

### 1. 实体定义

#### 1.1 credentials (凭据表)
* **id**: UUID, 主键
* **credential_name**: 凭据配置名称, 唯一, 索引
* **credential_type**: 凭据类型（如: ssh_password, ssh_key, snmpv2, snmpv3, api_token）
* **username**: 用户名
* **encrypted_password**: 加密的用户密码 (AES-256-GCM 加密存储)
* **enable_password**: 加密的特权模式密码 (AES-256-GCM 加密存储)
* **private_key**: 加密的 SSH 私钥 (AES-256-GCM 加密存储)
* **snmp_community**: 加密的 SNMP 团体名 (AES-256-GCM 加密存储)

### 2. 安全要求

* 严禁将明文密码或加密密码字段直接存放在 `devices` 表中。
* 所有的设备实体必须通过 `credential_id` 关联 `credentials` 表以引用对应访问凭据。
* 所有敏感数据列（密码、私钥、团体名）必须在写入前通过应用层使用 AES-256-GCM 算法加密，且加解密密钥需通过硬件安全模块（HSM）或系统环境变量独立隔离保管。

---

## 第六部分：Route Intelligence

路由智能分析模型用于保存、解析和跟踪设备控制平面路由选择路径。

### 1. 实体定义

#### 1.1 route_table (路由表)
* **id**: UUID, 主键
* **device_id**: 外键, 关联 `devices.id`, 级联删除
* **vrf_name**: VRF 名称, 索引
* **destination**: 目的 CIDR 网段, 索引
* **next_hop**: 下一跳 IP 地址
* **outgoing_interface**: 出接口名称
* **protocol**: 路由协议
* **metric**: 度量值
* **preference**: 协议优先级（Administrative Distance）
* **active**: 是否为当前活动路由（选路优选）
* **last_updated**: 数据同步时间
* **route_source**: 路由来源细分（static, connected, ospf, bgp）
* **age**: 路由条目持续时间
* **tag**: 路由标记
* **as_path**: BGP 自治系统路径属性
* **community**: BGP 团体属性
* **origin**: BGP 起源属性
* **local_pref**: BGP 本地优先级
* **med**: BGP 多出口鉴别值 (MED)

#### 1.2 arp_table (ARP表)
* **id**: UUID, 主键
* **device_id**: 外键, 关联 `devices.id`, 级联删除
* **ip_address**: IP 地址, 索引
* **mac_address**: MAC 地址, 索引
* **interface_name**: 接口名称
* **vlan_id**: VLAN ID
* **last_updated**: 数据同步时间

#### 1.3 mac_table (MAC地址表)
* **id**: UUID, 主键
* **device_id**: 外键, 关联 `devices.id`, 级联删除
* **mac_address**: MAC 地址, 索引
* **interface_name**: 出接口名称
* **vlan_id**: 所在 VLAN ID, 索引
* **entry_type**: 学习类型（dynamic, static）
* **last_updated**: 数据同步时间

#### 1.4 neighbor_table (协议邻居表)
* **id**: UUID, 主键
* **device_id**: 外键, 关联 `devices.id`, 级联删除
* **local_interface**: 本地接口名称
* **neighbor_hostname**: 邻居主机名, 索引
* **neighbor_interface**: 邻居接口名称
* **neighbor_ip**: 邻居 IP 地址
* **protocol**: 邻居协议类型（lldp, cdp, bgp, ospf）
* **last_updated**: 数据同步时间

### 2. 路由智能算法实现机制

* **路由递归 (Route Recursion)**:
  若优选路由的 `next_hop` 并非直连网段，路由智能分析引擎会迭代检索 `route_table` 中目的网段包含该 `next_hop` 的活动路由，直到匹配至出接口为直连物理接口的底层物理路由为止。
* **Loopback 定位**:
  当目的地址为 Loopback IP 时，引擎在 `ip_addresses` 表中查找匹配项，确认对应的虚拟接口类型后直接返回归属设备的 ID，跳过物理拓扑二层寻址阶段。
* **BGP Next-Hop 递归**:
  针对 IBGP 路由所宣告的 Next-Hop（通常为 Peer 设备的 Loopback IP），利用三层 IGP（OSPF/IS-IS/静态路由）表项进行递归查询，计算出到达该 IBGP Peer 的实际物理出接口和真实物理下一跳。
* **OSPF 路径追踪**:
  分析设备的 OSPF 邻居关系与路由表度量值，计算该跳点在特定 OSPF Area 内的路径成本（Cost），并根据 SPF 算法还原三层转发跳步。
* **ECMP (等价多路径) 识别**:
  当查询 `route_table` 时，若同一目的前缀 `destination` 存在多条活动状态（`active = true`）、协议优先级与度量值完全相同的路由表项，路径诊断引擎将标记该路径为 ECMP，并将追踪路径分叉显示。
* **路由环路检测**:
  路径分析引擎在迭代递归检索过程中建立遍历路径队列。如果计算得出的转发跳步路径中，在未到达目的地前，重复访问了相同的设备主键 ID，则立即触发路由环路告警，终止计算并在报告中标记环路节点。

---

## 第七部分：Smart Trace 重构

路径智能追踪（Smart Trace）将网络故障定位过程模块化，采用高效非侵入式的诊断策略。

### 1. 故障排查阶段顺序

1. **CMDB定位 (CMDB Localization)**: 
   首先定位源和目的 IP 在系统 CMDB 中的属性。查询设备管理接口、Loopback 或 VIP。
2. **Endpoint定位 (Endpoint Localization)**: 
   针对物理终端、服务器或虚拟机，通过 `network_endpoints` 缓存表直接抓取其所连接的接入层交换机及具体端口。
3. **路由递归 (Routing Recursion)**: 
   依据所经三层路由器的 `route_table` 进行递归计算，解析下一跳与物理出接口。
4. **L2定位 (L2 Localization)**: 
   跨越三层网关时，结合 `arp_table` 和交换机的 `mac_table` 定位数据包在局域网段内穿过的物理交换路径。
5. **策略分析 (Policy Analysis)**: 
   读取设备的 ACL、安全策略规则和 NAT 转换表，校验诊断数据流是否会被安全策略过滤或阻断。
6. **Overlay分析 (Overlay Analysis)**: 
   在 VXLAN EVPN、MPLS 或 SD-WAN 网络场景下，解析隧道封装协议头部（如 VNI/VTEP），并将其关联至 Underlay 传输路径。
7. **TCP验证 (TCP Verification)**: 
   若指定了端口和协议，智能 Agent 将模拟发起 TCP 握手包或服务可用性侦测，校验端到端四层通断性。
8. **AI根因分析 (AI Root Cause Analysis)**: 
   引入诊断算法，结合历史端口丢包率、CPU/内存瓶颈及近期路由协议震荡日志，推导导致网络劣化的根因。
9. **智能报告生成 (Smart Report Generation)**: 
   自动输出包含可视化拓扑图、详细诊断跳点、阻断策略条目以及修复建议的结构化报告。

### 2. 采集性能保障原则

* **避开全网实时 SSH 扫描**: 路径排障引擎默认优先从平台 CMDB 及同步生成的路由表（`route_table`）、ARP表（`arp_table`）以及 MAC地址表（`mac_table`）缓存数据中进行路径计算。
* **只有缓存未命中时**: 即通过本地缓存无法递归得到下一跳的出接口或端口对端链路时，才调用指定 Agent 针对相关单台设备触发实时的 CLI 交互、NetConf 协议或 SNMP 状态抓取，从而避免网络风暴并降低设备 CPU 开销。

---

## 第八部分：数据库设计

### 1. tenants
* **表名**: tenants
* **字段名与数据类型**:
  * `id` UUID
  * `name` VARCHAR(100)
  * `description` TEXT
* **主键**: `id`
* **索引**: 无
* **约束**: `id` NOT NULL, `name` NOT NULL

### 2. roles
* **表名**: roles
* **字段名与数据类型**:
  * `id` UUID
  * `role_name` VARCHAR(50)
  * `description` TEXT
* **主键**: `id`
* **索引**: 无
* **约束**: `id` NOT NULL, `role_name` NOT NULL

### 3. users
* **表名**: users
* **字段名与数据类型**:
  * `id` UUID
  * `username` VARCHAR(50)
  * `password_hash` VARCHAR(255)
  * `email` VARCHAR(100)
  * `role_id` UUID
  * `tenant_id` UUID
  * `is_active` BOOLEAN
* **主键**: `id`
* **索引**: `idx_users_username` (username) UNIQUE, `idx_users_email` (email) UNIQUE
* **约束**: `id` NOT NULL, `username` NOT NULL, `password_hash` NOT NULL, `email` NOT NULL, `role_id` NOT NULL REFERENCES roles(id), `tenant_id` NOT NULL REFERENCES tenants(id), `is_active` NOT NULL

### 4. sites
* **表名**: sites
* **字段名与数据类型**:
  * `id` UUID
  * `site_code` VARCHAR(50)
  * `site_name` VARCHAR(100)
  * `country` VARCHAR(100)
  * `city` VARCHAR(100)
  * `timezone` VARCHAR(50)
  * `address` TEXT
  * `status` VARCHAR(20)
  * `tenant_id` UUID
* **主键**: `id`
* **索引**: `idx_sites_code` (site_code) UNIQUE
* **约束**: `id` NOT NULL, `site_code` NOT NULL, `site_name` NOT NULL, `timezone` NOT NULL, `status` NOT NULL, `tenant_id` NOT NULL REFERENCES tenants(id)

### 5. racks
* **表名**: racks
* **字段名与数据类型**:
  * `id` UUID
  * `site_id` UUID
  * `rack_code` VARCHAR(50)
  * `rack_name` VARCHAR(100)
  * `total_u` INTEGER
  * `available_u` INTEGER
* **主键**: `id`
* **索引**: `idx_racks_site_id` (site_id)
* **约束**: `id` NOT NULL, `site_id` NOT NULL REFERENCES sites(id) ON DELETE CASCADE, `rack_code` NOT NULL, `rack_name` NOT NULL, UNIQUE (`site_id`, `rack_code`)

### 6. device_types
* **表名**: device_types
* **字段名与数据类型**:
  * `id` UUID
  * `vendor` VARCHAR(50)
  * `model` VARCHAR(100)
  * `part_number` VARCHAR(100)
  * `u_height` INTEGER
* **主键**: `id`
* **索引**: `idx_devtypes_vendor_model` (vendor, model) UNIQUE
* **约束**: `id` NOT NULL, `vendor` NOT NULL, `model` NOT NULL, `u_height` NOT NULL

### 7. devices
* **表名**: devices
* **字段名与数据类型**:
  * `id` UUID
  * `hostname` VARCHAR(100)
  * `mgmt_ip` INET
  * `asset_tag` VARCHAR(100)
  * `device_type_id` UUID
  * `platform` VARCHAR(50)
  * `vendor` VARCHAR(50)
  * `model` VARCHAR(100)
  * `serial_number` VARCHAR(100)
  * `site_id` UUID
  * `rack_id` UUID
  * `os_version` VARCHAR(100)
  * `firmware_version` VARCHAR(100)
  * `lifecycle_status` VARCHAR(20)
  * `purchase_date` DATE
  * `warranty_expire` DATE
  * `owner_team` VARCHAR(100)
  * `criticality` VARCHAR(10)
  * `monitoring_enabled` BOOLEAN
  * `config_backup_enabled` BOOLEAN
  * `last_discovered` TIMESTAMPTZ
  * `credential_id` UUID
  * `tenant_id` UUID
* **主键**: `id`
* **索引**: `idx_devices_hostname` (hostname) UNIQUE, `idx_devices_serial` (serial_number) UNIQUE, `idx_devices_mgmt_ip` (mgmt_ip)
* **约束**: `id` NOT NULL, `hostname` NOT NULL, `mgmt_ip` NOT NULL, `device_type_id` NOT NULL REFERENCES device_types(id), `site_id` NOT NULL REFERENCES sites(id), `rack_id` REFERENCES racks(id) ON DELETE SET NULL, `credential_id` REFERENCES credentials(id) ON DELETE SET NULL, `tenant_id` NOT NULL REFERENCES tenants(id)

### 8. interfaces
* **表名**: interfaces
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `interface_name` VARCHAR(100)
  * `description` TEXT
  * `admin_status` VARCHAR(10)
  * `oper_status` VARCHAR(10)
  * `mac_address` MACADDR
  * `mtu` INTEGER
  * `speed` BIGINT
  * `interface_type` VARCHAR(30)
  * `duplex` VARCHAR(10)
  * `bandwidth` BIGINT
  * `parent_interface_id` UUID
  * `channel_group` INTEGER
  * `vrf_id` UUID
  * `switchport_mode` VARCHAR(20)
  * `access_vlan` INTEGER
  * `native_vlan` INTEGER
  * `allowed_vlans` VARCHAR(255)
  * `ip_enabled` BOOLEAN
  * `last_flapped` TIMESTAMPTZ
* **主键**: `id`
* **索引**: `idx_interfaces_device_id` (device_id), `idx_interfaces_mac` (mac_address)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `interface_name` NOT NULL, `admin_status` NOT NULL, `oper_status` NOT NULL, `parent_interface_id` REFERENCES interfaces(id) ON DELETE SET NULL, `vrf_id` REFERENCES vrfs(id) ON DELETE SET NULL, UNIQUE (`device_id`, `interface_name`)

### 9. vrfs
* **表名**: vrfs
* **字段名与数据类型**:
  * `id` UUID
  * `vrf_name` VARCHAR(100)
  * `rd` VARCHAR(50)
  * `description` TEXT
  * `tenant_id` UUID
* **主键**: `id`
* **索引**: `idx_vrfs_name` (vrf_name) UNIQUE
* **约束**: `id` NOT NULL, `vrf_name` NOT NULL, `tenant_id` NOT NULL REFERENCES tenants(id) ON DELETE CASCADE

### 10. vlans
* **表名**: vlans
* **字段名与数据类型**:
  * `id` UUID
  * `vlan_id` INTEGER
  * `name` VARCHAR(100)
  * `site_id` UUID
  * `status` VARCHAR(20)
  * `tenant_id` UUID
* **主键**: `id`
* **索引**: `idx_vlans_site_vlan` (site_id, vlan_id)
* **约束**: `id` NOT NULL, `vlan_id` NOT NULL CHECK (vlan_id >= 1 AND vlan_id <= 4094), `name` NOT NULL, `site_id` REFERENCES sites(id) ON DELETE CASCADE, `status` NOT NULL, `tenant_id` NOT NULL REFERENCES tenants(id) ON DELETE CASCADE

### 11. prefixes
* **表名**: prefixes
* **字段名与数据类型**:
  * `id` UUID
  * `prefix` CIDR
  * `vrf_id` UUID
  * `vlan_id` UUID
  * `site_id` UUID
  * `tenant_id` UUID
  * `status` VARCHAR(20)
* **主键**: `id`
* **索引**: `idx_prefixes_prefix` (prefix), `idx_prefixes_tenant` (tenant_id)
* **约束**: `id` NOT NULL, `prefix` NOT NULL, `vrf_id` REFERENCES vrfs(id) ON DELETE SET NULL, `vlan_id` REFERENCES vlans(id) ON DELETE SET NULL, `site_id` REFERENCES sites(id) ON DELETE SET NULL, `tenant_id` NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, `status` NOT NULL

### 12. ip_addresses
* **表名**: ip_addresses
* **字段名与数据类型**:
  * `id` UUID
  * `ip_address` INET
  * `prefix_id` UUID
  * `vrf_id` UUID
  * `device_id` UUID
  * `interface_id` UUID
  * `status` VARCHAR(20)
  * `last_seen` TIMESTAMPTZ
* **主键**: `id`
* **索引**: `idx_ips_address` (ip_address), `idx_ips_device_interface` (device_id, interface_id)
* **约束**: `id` NOT NULL, `ip_address` NOT NULL, `prefix_id` REFERENCES prefixes(id) ON DELETE SET NULL, `vrf_id` REFERENCES vrfs(id) ON DELETE SET NULL, `device_id` REFERENCES devices(id) ON DELETE SET NULL, `interface_id` REFERENCES interfaces(id) ON DELETE SET NULL, `status` NOT NULL

### 13. topology_links
* **表名**: topology_links
* **字段名与数据类型**:
  * `local_device_id` UUID
  * `local_interface_id` UUID
  * `remote_device_id` UUID
  * `remote_interface_id` UUID
  * `protocol` VARCHAR(20)
  * `last_seen` TIMESTAMPTZ
* **主键**: (`local_interface_id`, `remote_interface_id`)
* **索引**: `idx_topo_local_device` (local_device_id), `idx_topo_remote_device` (remote_device_id)
* **约束**: `local_device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `local_interface_id` NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE, `remote_device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `remote_interface_id` NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE, `protocol` NOT NULL, `last_seen` NOT NULL

### 14. network_endpoints
* **表名**: network_endpoints
* **字段名与数据类型**:
  * `id` UUID
  * `ip_address` INET
  * `mac_address` MACADDR
  * `vlan_id` UUID
  * `device_id` UUID
  * `interface_id` UUID
  * `endpoint_type` VARCHAR(20)
  * `host_name` VARCHAR(100)
  * `operating_system` VARCHAR(100)
  * `first_seen` TIMESTAMPTZ
  * `last_seen` TIMESTAMPTZ
  * `confidence_score` NUMERIC(5,2)
* **主键**: `id`
* **索引**: `idx_endpoints_mac` (mac_address) UNIQUE, `idx_endpoints_ip` (ip_address), `idx_endpoints_device_port` (device_id, interface_id)
* **约束**: `id` NOT NULL, `mac_address` NOT NULL, `vlan_id` REFERENCES vlans(id) ON DELETE SET NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `interface_id` NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE, `first_seen` NOT NULL, `last_seen` NOT NULL, `confidence_score` NOT NULL

### 15. endpoint_history
* **表名**: endpoint_history
* **字段名与数据类型**:
  * `id` UUID
  * `ip_address` INET
  * `mac_address` MACADDR
  * `from_device_id` UUID
  * `from_interface_id` UUID
  * `to_device_id` UUID
  * `to_interface_id` UUID
  * `vlan_id` UUID
  * `event_time` TIMESTAMPTZ
  * `event_type` VARCHAR(20)
* **主键**: `id`
* **索引**: `idx_endp_hist_mac` (mac_address), `idx_endp_hist_time` (event_time)
* **约束**: `id` NOT NULL, `mac_address` NOT NULL, `from_device_id` REFERENCES devices(id) ON DELETE SET NULL, `from_interface_id` REFERENCES interfaces(id) ON DELETE SET NULL, `to_device_id` REFERENCES devices(id) ON DELETE SET NULL, `to_interface_id` REFERENCES interfaces(id) ON DELETE SET NULL, `vlan_id` REFERENCES vlans(id) ON DELETE SET NULL, `event_time` NOT NULL, `event_type` NOT NULL

### 16. credentials
* **表名**: credentials
* **字段名与数据类型**:
  * `id` UUID
  * `credential_name` VARCHAR(100)
  * `credential_type` VARCHAR(30)
  * `username` VARCHAR(100)
  * `encrypted_password` TEXT
  * `enable_password` TEXT
  * `private_key` TEXT
  * `snmp_community` TEXT
* **主键**: `id`
* **索引**: `idx_credentials_name` (credential_name) UNIQUE
* **约束**: `id` NOT NULL, `credential_name` NOT NULL, `credential_type` NOT NULL

### 17. route_table
* **表名**: route_table
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `vrf_name` VARCHAR(100)
  * `destination` CIDR
  * `next_hop` INET
  * `outgoing_interface` VARCHAR(100)
  * `protocol` VARCHAR(50)
  * `metric` INTEGER
  * `preference` INTEGER
  * `active` BOOLEAN
  * `last_updated` TIMESTAMPTZ
  * `route_source` VARCHAR(20)
  * `age` INTEGER
  * `tag` INTEGER
  * `as_path` VARCHAR(255)
  * `community` VARCHAR(255)
  * `origin` VARCHAR(20)
  * `local_pref` INTEGER
  * `med` INTEGER
* **主键**: `id`
* **索引**: `idx_routes_device_vrf` (device_id, vrf_name), `idx_routes_destination` (destination)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `destination` NOT NULL, `active` NOT NULL, `last_updated` NOT NULL

### 18. arp_table
* **表名**: arp_table
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `ip_address` INET
  * `mac_address` MACADDR
  * `interface_name` VARCHAR(100)
  * `vlan_id` INTEGER
  * `last_updated` TIMESTAMPTZ
* **主键**: `id`
* **索引**: `idx_arp_device_ip` (device_id, ip_address), `idx_arp_mac` (mac_address)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `ip_address` NOT NULL, `mac_address` NOT NULL, `last_updated` NOT NULL

### 19. mac_table
* **表名**: mac_table
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `mac_address` MACADDR
  * `interface_name` VARCHAR(100)
  * `vlan_id` INTEGER
  * `entry_type` VARCHAR(20)
  * `last_updated` TIMESTAMPTZ
* **主键**: `id`
* **索引**: `idx_mac_device_vlan` (device_id, vlan_id), `idx_mac_address` (mac_address)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `mac_address` NOT NULL, `interface_name` NOT NULL, `vlan_id` NOT NULL, `entry_type` NOT NULL, `last_updated` NOT NULL

### 20. neighbor_table
* **表名**: neighbor_table
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `local_interface` VARCHAR(100)
  * `neighbor_hostname` VARCHAR(100)
  * `neighbor_interface` VARCHAR(100)
  * `neighbor_ip` INET
  * `protocol` VARCHAR(20)
  * `last_updated` TIMESTAMPTZ
* **主键**: `id`
* **索引**: `idx_neighbors_device` (device_id), `idx_neighbors_name` (neighbor_hostname)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `local_interface` NOT NULL, `neighbor_hostname` NOT NULL, `neighbor_interface` NOT NULL, `protocol` NOT NULL, `last_updated` NOT NULL

### 21. config_backups
* **表名**: config_backups
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `config_type` VARCHAR(20)
  * `backup_time` TIMESTAMPTZ
  * `file_path` VARCHAR(255)
  * `config_hash` VARCHAR(64)
* **主键**: `id`
* **索引**: `idx_cfg_backup_device` (device_id), `idx_cfg_backup_time` (backup_time)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `config_type` NOT NULL, `backup_time` NOT NULL, `file_path` NOT NULL, `config_hash` NOT NULL

### 22. alarms
* **表名**: alarms
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `severity` VARCHAR(20)
  * `source` VARCHAR(20)
  * `alarm_type` VARCHAR(50)
  * `alarm_time` TIMESTAMPTZ
  * `clear_time` TIMESTAMPTZ
  * `status` VARCHAR(20)
* **主键**: `id`
* **索引**: `idx_alarms_device` (device_id), `idx_alarms_status` (status)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `severity` NOT NULL, `source` NOT NULL, `alarm_type` NOT NULL, `alarm_time` NOT NULL, `status` NOT NULL

### 23. performance_metrics
* **表名**: performance_metrics
* **字段名与数据类型**:
  * `id` UUID
  * `device_id` UUID
  * `metric_name` VARCHAR(50)
  * `metric_value` NUMERIC
  * `timestamp` TIMESTAMPTZ
* **主键**: `id`
* **索引**: `idx_perf_device_metric` (device_id, metric_name), `idx_perf_timestamp` (timestamp)
* **约束**: `id` NOT NULL, `device_id` NOT NULL REFERENCES devices(id) ON DELETE CASCADE, `metric_name` NOT NULL, `metric_value` NOT NULL, `timestamp` NOT NULL

### 24. events
* **表名**: events
* **字段名与数据类型**:
  * `event_id` UUID
  * `event_type` VARCHAR(50)
  * `event_source` VARCHAR(50)
  * `event_time` TIMESTAMPTZ
  * `payload` JSONB
* **主键**: `event_id`
* **索引**: `idx_events_type_time` (event_type, event_time)
* **约束**: `event_id` NOT NULL, `event_type` NOT NULL, `event_source` NOT NULL, `event_time` NOT NULL

### 25. discovery_jobs
* **表名**: discovery_jobs
* **字段名与数据类型**:
  * `id` UUID
  * `job_type` VARCHAR(20)
  * `target` VARCHAR(100)
  * `status` VARCHAR(20)
  * `start_time` TIMESTAMPTZ
  * `finish_time` TIMESTAMPTZ
  * `result` JSONB
* **主键**: `id`
* **索引**: `idx_disc_status` (status)
* **约束**: `id` NOT NULL, `job_type` NOT NULL, `target` NOT NULL, `status` NOT NULL, `start_time` NOT NULL
