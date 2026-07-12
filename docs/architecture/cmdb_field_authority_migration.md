# CMDB 字段权威边界与迁移路径

## 结论

“CMDB 的构建依赖设备 + interface”这个判断是对的，但还不完整。

更适合中大型企业网络运维平台的模型应是四层：

```text
physical_assets  ->  devices  ->  interfaces  ->  ip_addresses
物理资产层           设备运维层      接口层            地址层
```

其中：

- `devices + interfaces` 是网络 CMDB 的主骨架。
- `physical_assets` 是资产、采购、机柜、生命周期和物理归属的权威来源。
- `ip_addresses` 是 IPAM 地址分配、占用、归属和 VRF/Prefix 关系的权威来源。
- 拓扑链路应优先绑定 `interfaces.id`，端口名称字符串只作为导入、展示和兼容字段。

## 当前项目现状

### 已具备的基础

1. `devices` 表已经承载设备运维对象：
   - `id`
   - `hostname`
   - `ip_address`
   - `platform`
   - `status`
   - `role`
   - `site`
   - `asset_id`
   - `site_id`
   - `credential_id`

2. `interfaces` 表已经承载接口对象：
   - `id`
   - `device_id`
   - `interface_name`
   - `description`
   - `admin_status`
   - `oper_status`
   - `mac_address`
   - `vrf_id`
   - `switchport_mode`
   - `access_vlan`

3. `ip_addresses` 表已经开始承载 IPAM 地址对象：
   - `id`
   - `address`
   - `ip_address`
   - `prefix_id`
   - `vrf_id`
   - `device_id`
   - `interface_name`
   - `interface_id`

4. `topology_links` 已经开始承载接口级拓扑：
   - `source_device_id`
   - `source_interface_id`
   - `source_port`
   - `target_device_id`
   - `target_interface_id`
   - `target_port`

5. `physical_assets` 已经承载资产与机房相关字段：
   - `asset_tag`
   - `serial_number`
   - `vendor`
   - `model`
   - `datacenter`
   - `rack`
   - `rack_unit`
   - `management_ip`
   - `business_ip`
   - `purchase_date`
   - `warranty_expiry`

### 当前主要问题

| 问题 | 当前表现 | 风险 |
|---|---|---|
| 站点重复 | `devices.site` 与 `devices.site_id` 并存 | 名称变更后设备归属漂移 |
| 管理 IP 重复 | `devices.ip_address` 与 `physical_assets.management_ip` 并存 | 巡检、资产和 IPAM 显示不一致 |
| 硬件字段重复 | `devices.vendor/model/sn` 与 `physical_assets.vendor/model/serial_number` 并存 | SN/型号来源不清 |
| 凭据字段重复 | `devices`、`physical_assets`、`credentials` 都有账号字段 | 安全边界不清，密码轮换困难 |
| 接口引用过渡态 | `ip_addresses.interface_name` 与 `interface_id` 并存 | 端口改名后 IP 归属可能断裂 |
| 拓扑引用过渡态 | `topology_links.source_port` 与 `source_interface_id` 并存 | 链路无法稳定落到接口主键 |

## 字段权威边界

### 总体原则

1. 能用稳定 ID 的地方，不再以名称字符串作为权威。
2. 业务层只能有一个权威写入点，其他表可保留兼容镜像，但必须标记为 legacy。
3. 删除 legacy 字段前必须经历：
   - 回填
   - 双写
   - 读路径切换
   - 校验
   - 只读冻结
   - 删除或废弃
4. 对外 API 可以继续返回旧字段，但内部服务应优先使用新权威字段。

### 权威字段矩阵

| 语义 | 权威表/字段 | 兼容字段 | 迁移策略 |
|---|---|---|---|
| 设备身份 | `devices.id` | 无 | 已是权威 |
| 设备名称 | `devices.hostname` | `physical_assets.hostname` | 资产层可展示镜像，写入以 `devices.hostname` 为准 |
| 管理 IP | `devices.ip_address` + `ip_addresses` 绑定 | `physical_assets.management_ip` | 过渡期双写，最终以 `ip_addresses` 的管理地址角色为准 |
| 物理资产身份 | `physical_assets.id` | `devices.asset_id` 引用 | `devices.asset_id` 只做外键引用 |
| 资产标签 | `physical_assets.asset_tag` | `devices.asset_tag` | 资产层权威，设备层废弃镜像 |
| 序列号 | `physical_assets.serial_number` | `devices.sn`、`devices.serial_number` | 资产层权威，设备层仅展示镜像 |
| 厂商/型号 | `physical_assets.vendor/model` 或 `device_types` | `devices.vendor/model` | 中期以资产层权威，长期收敛到 `device_types` |
| 设备平台/驱动 | `devices.platform` | `physical_assets.platform` | 设备层权威 |
| 设备角色 | `devices.role` | `physical_assets.device_role` | 设备层权威，资产层只保留资产分类 |
| 站点 | `devices.site_id` -> `sites.id` | `devices.site` | `site_id` 权威，`site` 只做展示缓存 |
| 机柜位置 | `physical_assets.rack/rack_unit/u_height/planned_start_u` | `devices.rack_id` | 资产/机柜层权威 |
| 接口身份 | `interfaces.id` | `device_id + interface_name` | `interfaces.id` 权威，复合键保留唯一约束 |
| 接口名称 | `interfaces.interface_name` | `ip_addresses.interface_name`、`topology_links.source_port` | 接口层权威，其他表保留快照 |
| 接口状态 | `interfaces.admin_status/oper_status` | 指标/巡检表状态 | 接口层保存最近状态，时序表保存历史 |
| IP 地址 | `ip_addresses.id/address/ip_address/prefix_id` | legacy `ip_inventory` | IPAM 权威 |
| IP 绑定接口 | `ip_addresses.interface_id` | `ip_addresses.interface_name` | `interface_id` 权威，`interface_name` 为展示快照 |
| 拓扑链路端点 | `topology_links.source_interface_id/target_interface_id` | `source_port/target_port` | interface_id 权威，端口字符串为发现证据 |
| 凭据材料 | `credentials` | `devices.*password`、`physical_assets.*password` | `credentials` 权威，legacy 字段只做临时回退 |
| 凭据用途 | 后续新增绑定关系 | `credentials.username` | 应新增账号用途/绑定模型 |

## 推荐目标模型

### 设备层

`devices` 应回答：

- 这是什么网络设备？
- 如何连接它？
- 当前运维状态是什么？
- 它属于哪个站点？
- 它关联哪个物理资产？

建议权威字段：

- `id`
- `hostname`
- `ip_address`：过渡期管理 IP。
- `platform`
- `status`
- `role`
- `site_id`
- `asset_id`
- `credential_id`：过渡期单凭据引用。
- `lifecycle_status`
- `last_discovered`

不建议长期作为权威：

- `site`
- `asset_tag`
- `serial_number`
- `vendor/model`
- `username/password/normal_password/admin_password`

### 接口层

`interfaces` 应回答：

- 某台设备有哪些接口？
- 接口的管理状态、运行状态、MAC、速率、VRF、VLAN 是什么？
- IP 和链路绑定在哪个稳定接口 ID 上？

建议权威字段：

- `id`
- `device_id`
- `interface_name`
- `admin_status`
- `oper_status`
- `mac_address`
- `speed`
- `bandwidth`
- `interface_type`
- `parent_interface_id`
- `vrf_id`
- `switchport_mode`
- `access_vlan`
- `native_vlan`
- `allowed_vlans`

接口唯一性继续使用：

```text
UNIQUE(device_id, interface_name)
```

但跨表引用应优先使用：

```text
interfaces.id
```

### IPAM 地址层

`ip_addresses` 应回答：

- 这个地址属于哪个 prefix/VRF/site/tenant？
- 当前是否被占用？
- 被哪个设备、哪个接口使用？
- 是管理地址、Loopback、Transit、业务地址还是保留地址？

建议长期增加或规范字段：

- `role` 或标准化现有 `device_type`
  - `management`
  - `loopback`
  - `transit`
  - `service`
  - `reserved`
- `assignment_source`
  - `manual`
  - `discovery`
  - `import`
  - `dhcp`
- `confidence`
- `last_seen`

绑定关系权威：

```text
ip_addresses.interface_id -> interfaces.id
ip_addresses.device_id -> devices.id
ip_addresses.prefix_id -> prefixes.id
ip_addresses.vrf_id -> vrfs.id
```

### 资产层

`physical_assets` 应回答：

- 这个物理资产是什么？
- SN、资产标签、厂商型号是什么？
- 在哪个机房/机柜/U 位？
- 采购、质保、生命周期和归属是什么？

建议权威字段：

- `id`
- `asset_type`
- `asset_tag`
- `serial_number`
- `vendor`
- `model`
- `datacenter`
- `rack`
- `rack_unit`
- `u_height`
- `planned_start_u`
- `purchase_date`
- `warranty_expiry`
- `department`
- `lifecycle_status`
- `power_watts`

不建议长期作为权威：

- `username/password/admin_password`
- `management_ip`
- `business_ip`
- `device_role`
- `platform`

这些字段可以在过渡期保留，但应逐步转为展示快照或迁移到设备/IPAM/凭据模型。

## 两条关键迁移路径

### 1. `site` -> `site_id`

当前已有迁移逻辑根据 `devices.site` 创建/匹配 `sites`，并回填 `devices.site_id`。后续应分阶段执行：

#### 阶段 A：兼容读取

所有读取逻辑使用：

```text
site_display = sites.site_name/site_code by devices.site_id
fallback devices.site
```

#### 阶段 B：写入收敛

新建/编辑设备时：

- 必须写入 `site_id`。
- `site` 仅作为展示缓存同步写入站点名称。

#### 阶段 C：校验

增加数据质量检查：

- `devices.site_id` 为空的数量。
- `devices.site` 与 `sites.site_name` 不一致的数量。
- 指向不存在 `sites.id` 的设备数量。

#### 阶段 D：冻结 legacy

前端不再编辑 `site` 字符串，只允许选择 `site_id`。

#### 阶段 E：废弃 legacy

当 API 消费方都切换后：

- `devices.site` 标记为 deprecated。
- 长期可删除或只保留为 denormalized display cache。

### 2. `interface_name` -> `interface_id`

当前 `ip_addresses` 和 `topology_links` 已经有 `interface_id` 字段，但仍依赖端口名称字符串。后续应分阶段执行：

#### 阶段 A：统一接口名称规范化

沉淀一个公共 normalize 函数，不要在 migration、topology、IPAM 各处散落实现。

建议输出：

```text
raw_name
normalized_name
display_name
```

#### 阶段 B：回填 `interface_id`

对 `ip_addresses`：

```text
device_id + normalized(interface_name) -> interfaces.id
```

对 `topology_links`：

```text
source_device_id + normalized(source_port/source_port_normalized) -> source_interface_id
target_device_id + normalized(target_port/target_port_normalized) -> target_interface_id
```

#### 阶段 C：写路径收敛

所有新采集数据入库时：

1. 先 upsert `interfaces`。
2. 再写 `ip_addresses.interface_id` 或 `topology_links.*_interface_id`。
3. 同步保留 `interface_name/source_port` 作为发现证据和展示快照。

#### 阶段 D：数据质量检查

必须定期检查：

- 有 `device_id + interface_name` 但无 `interface_id` 的 IP 地址。
- 有 `source_port/target_port` 但无法匹配接口 ID 的链路。
- 同设备下接口名称归一化冲突。

#### 阶段 E：接口 ID 成为 API 主路径

前端和 API 使用：

```text
/api/cmdb/interfaces/{interface_id}
/api/ipam/addresses?interface_id=...
/api/topology/links?interface_id=...
```

端口名称只作为展示字段，不作为业务主键。

## 推荐后续任务拆分

### CMDB-002A：字段权威只读审计接口

新增只读接口：

```text
GET /api/cmdb/data-quality/field-authority
```

输出：

- 设备总数。
- `site_id` 为空数量。
- `site` 与 `site_id` 不一致数量。
- `ip_addresses.interface_id` 缺失数量。
- `topology_links.source_interface_id/target_interface_id` 缺失数量。
- 资产与设备管理 IP 不一致数量。

### CMDB-002B：站点写路径收敛

目标：

- 设备创建/编辑统一使用 `site_id`。
- `site` 只做兼容展示缓存。
- 前端设备表单改为站点选择器。

### CMDB-002C：接口归一化公共模块

目标：

- 抽出统一接口名称 normalize 函数。
- migration、拓扑发现、IPAM 地址绑定都调用同一个实现。

### CMDB-002D：IPAM 地址绑定接口 ID 回填

目标：

- 回填 `ip_addresses.interface_id`。
- 新增审计报表和失败明细。
- 不删除 `interface_name`。

### CMDB-002E：拓扑链路接口 ID 回填

目标：

- 回填 `topology_links.source_interface_id/target_interface_id`。
- 新增低置信度和未匹配链路列表。

### CMDB-002F：凭据模型二阶段设计

目标：

- 从单个 `devices.credential_id` 过渡到设备-凭据用途绑定。
- 支持：
  - 普通登录账号
  - 管理员账号
  - Enable 密码
  - SNMP RO/RW
  - API Token

## 企业级适用性判断

当前项目方向是合理的，已经有成为中大型企业网络运维平台的基础：

- 有设备表。
- 有接口表。
- 有 IPAM 地址表。
- 有拓扑链路表。
- 有资产表。
- 有凭据中心。

但要适用于中大型企业，必须继续完成以下收敛：

1. ID 权威化：站点、接口、地址、链路都用稳定 ID。
2. 字段去重：每个语义只有一个权威写入点。
3. 数据质量报表：迁移前先知道脏数据在哪里。
4. 兼容期双写：避免一次性破坏历史数据和现有页面。
5. 删除前冻结：legacy 字段不再被前端编辑后，才考虑删除。

## 不建议现在立即做的事

1. 不建议马上删除 `devices.site`、`ip_addresses.interface_name`、`topology_links.source_port`。
2. 不建议马上把所有 credential legacy 字段清空。
3. 不建议直接强制 `site_id/interface_id` 非空。
4. 不建议在没有数据质量审计接口前做批量 destructive migration。

这些都应该放在审计、回填、验证之后。
