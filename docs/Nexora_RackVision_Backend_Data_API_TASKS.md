# Nexora RackVision 底层数据与接口专项开发清单

- 文档类型：后端、数据模型、迁移、接口和质量门禁专项清单
- 当前状态：代码收口与验收中（Rack/asset/health/topology 的认证与主要范围过滤、canonical placement、全量/授权范围数据质量审计、功率字段迁移、严格资产 DTO、资产核心审计、前端竞态保护已落地；5 个生产展示基线 GLB 已生成，4 个 Generic 条目已接入生产静态目录并完成本地浏览器 3D 冒烟；统一异常体系、生产回填和线上缓存验证仍未关闭）
- 基线日期：2026-09-07
- 适用页面：/cmdb/racks
- 关联产品任务：[Nexora_RackVision_Detailed_TASKS.md](D:/data/downloads/Nexora_RackVision_Detailed_TASKS.md)
- 关联资产目录：[Nexora_3D_Asset_Base_Catalog_v1.xlsx](D:/data/downloads/Nexora_3D_Asset_Base_Catalog_v1.xlsx)

## 文档使用说明

本文件是当前项目的开发任务清单，不是对附件内容的机械复制。附件中的产品目标、3D 资产要求和验收条件作为需求输入；本文件负责补齐进入 3D 建模前必须完成的底层数据、接口、权限、事务、迁移和测试工作。

执行原则：

- 先完成 M0 到 M6，再进入大批量 GLB 建模。
- 数据库迁移必须是增量、可重复、可审计的迁移。
- 不在应用启动过程中执行大批量数据回填。
- 不静默把未知高度、未知位置或 0U 设备改成 1U/front。
- 不让资产接口、机柜接口、导入脚本各自维护一套安装规则。
- 不直接删除历史字段；先兼容、双读/双写，再经过观察期后下线。
- 生产运行时以 PostgreSQL 为权威持久化后端；已有本地兼容分支不能作为生产迁移正确性的证据。
- 所有涉及密码、令牌、SNMP community、Vault 路径的响应和日志都必须经过脱敏。

## 本轮执行记录（2026-09-06）

已实现并通过隔离 PostgreSQL/前端回归验证的内容：

- `m0210_rackvision_canonical_placement`：机柜布局版本、安装方式/位置/状态、设备实例高度、资产位置投影、数据质量问题表及索引。
- `RackPlacementService`：安装、移动、更新、卸载、校验、资产投影同步、U 位/前后面/full-depth/0U/侧挂规则、锁和非空资产唯一性保护。
- `RackService` read model：兼容旧字段，同时提供 `placements`、`occupancy`、`data_quality`、`meta`；2D/3D/统计/导出共享布局来源。
- `rackvision_backfill.py`：默认 dry-run，`--apply` 显式提交，输出可审查报告；没有放进应用启动流程。
- Excel 目录工具：生成 YAML/JSON、manifest、summary、asset registry、SKU mapping，并提供 conflict-blocking 的 `device_types` 导入预览/应用脚本。
- 认证与范围：assets、health、topology、rack-assets 读取要求 Viewer，写入按 Operator/Administrator 分级；asset/health/topology 主要读模型已接入 site/tenant/device scope，自动化测试覆盖匿名访问、角色拒绝和跨租户读取。
- 敏感数据与探测：资产普通响应使用显式最小 DTO allowlist，密码/SNMP/Web Profile 只返回 set 标志；资产创建、更新、删除、批量导入和连通性验证通过脱敏审计事件关联 request_id；连通性验证已加入 IP/元数据/端口/超时/进程内并发/频率边界，并改为线程池执行阻塞网络调用。
- 拓扑补充读模型：graph 的分组、边缘证据和历史查询随授权设备范围过滤，避免从辅助接口绕过主图范围。

未标记为完成的内容仍需真实环境或进一步实现：资产读取/接管/凭据操作的全量审计、统一异常类型和 409/422/500/502 映射、批量导入的数据质量状态与文件摘要持久化、cursor 分页、Redis/多 worker 线上验证、剩余资产矩阵与 OEM 外观校准、线上 MIME/缓存头验证。批量导入的 `atomic=true` 全量回滚和 `detailed=true` 逐行失败结果、全量/授权范围质量审计和功率字段 reconciliation 已实现并有契约测试；完整后端回归剩余的独立失败来自 IPAM 临时表缺少 `ip_addresses.device_id`，不属于 RackVision。

## 一、改造目标和架构决策

### 1.1 目标

- 修复资产、健康、拓扑接口的认证和越权读取问题。
- 建立统一的机柜安装关系模型。
- 解决 physical_assets 和 rack_devices 双写导致的位置不一致。
- 支持 front、rear、full-depth、0U、side-mount 和 unknown。
- 将机柜容量、功率利用率等字段改为可验证的派生数据。
- 让 2D、3D、统计、导出和健康状态读取同一份布局读模型。
- 为后续 GLB registry 和 exact/family/vendor/global fallback 预留稳定字段。

### 1.2 第一阶段的表级决策

第一阶段不新建一个平行的 rack_placements 主表，而是把现有 rack_devices 逐步演进为逻辑上的 canonical placement 表。这样可以减少当前服务层和 SQL 查询的大范围重写。

如果未来出现“一个资产拥有多个机柜安装关系”或“一个设备拆成多个独立安装单元”的需求，再单独拆分 rack_placements；本阶段不提前引入这个复杂度。

目标关系：

    physical_assets
      负责资产身份、序列号、管理地址、生命周期和凭据关系
                  |
                  | asset_id，可为空
                  v
    rack_devices
      负责 rack_id、U 位、安装面、0U/侧挂和安装状态
                  |
                  +-- rack_id ------> racks
                  +-- device_type_id -> device_types

    2D、3D、统计、导出
      全部读取同一个 rack layout read model

### 1.3 权威来源

| 数据 | 权威来源 | 兼容字段 |
|---|---|---|
| 资产身份 | physical_assets | 无 |
| 设备型号模板 | device_types | 旧的 u_height、is_full_depth |
| 机柜安装位置 | rack_devices | physical_assets.rack、rack_unit、planned_start_u |
| 机柜物理参数 | racks | 旧的 power_capacity_w |
| 机柜类型模板 | rack_types | 机柜实例创建时复制的字段 |
| 3D 模型匹配 | 后续 asset model registry | model_key 兼容字段 |
| used_u、available_u、功率利用率 | read model / 汇总逻辑 | 旧表中同名字段只读兼容 |

## 二、目标数据模型

### 2.1 racks

保留和规范以下字段：

- site_id：站点关系，必须参与权限范围过滤。
- rack_code：稳定标识，新增或修复时优先使用，不使用名称作为唯一关系。
- name：展示名称，可以修改。
- rack_type_id：机柜类型外键。
- total_u：总 U，范围由业务规则限制。
- width_mm、depth_mm：物理尺寸。
- power_capacity_watts：唯一的标准功率容量字段。
- max_weight_kg：最大承重。
- mount_policy：front_only 或 front_rear。
- layout_revision：布局版本号，用于跨 worker 缓存失效。

以下字段改为派生或只读兼容：

- used_u
- available_u
- current_power_w
- power_utilization
- power_capacity_w

### 2.2 rack_types

机柜类型是创建机柜时使用的模板：

- 类型更新不自动修改已经存在的机柜。
- 如果要将新模板应用到已有机柜，必须提供显式的预览和确认流程。
- 应用模板前必须检查已有设备是否越界、冲突或超出容量。
- rack_type_id 需要真实外键；迁移前先处理孤儿类型。

### 2.3 device_types

保留：

- model
- vendor
- device_role
- power_watts

新增或规范：

- depth_class：full、half、unknown。
- width_mm、depth_mm、height_mm、weight_kg。
- dimension_status：confirmed、estimated、unknown、pending_verification。
- default_mount_kind：u_mount、zero_u、side_mount、unknown。
- model_family。
- catalog_key。

兼容处理：

- 保留 is_full_depth，但新代码使用 depth_class。
- 保留 u_height，但新规则不能用默认 1 覆盖未知尺寸。
- U 型设备必须有有效 U 高。
- 0U/side-mount 设备通过安装关系表达，不依赖标准 U 位。

### 2.4 rack_devices

现有字段继续保留：

- id
- name
- rack_id
- device_type_id
- asset_id
- serial_number
- status
- created_at
- updated_at

新增或调整：

- mount_kind：u_mount、zero_u、side_mount、floor、unknown。
- position：front、rear、full_depth、left_side、right_side、unknown。
- start_u：U 型设备必填；0U、side-mount、unknown 可以为空。
- height_u：安装实例的有效高度；为空时只能在规则允许的情况下从 device_type 继承。
- placement_status：confirmed、estimated、unknown、invalid。
- placement_source：manual、asset_import、legacy_rack_device、legacy_asset、discovery、migration。
- dimension_status：confirmed、estimated、unknown、pending_verification。
- location_note：侧挂位置、物理备注或人工核验说明。
- model_key：后续 3D registry 的解析键。

重要规则：

- 不能把 start_u 为空的设备隐式改成 U1。
- 不能把 unknown 高度隐式改成 1U。
- 同一非空 asset_id 最多只能对应一个 rack_devices。
- rack_devices 是安装位置权威来源。

### 2.5 physical_assets

继续负责：

- 资产标签、序列号、厂商、型号、主机名。
- 管理 IP、业务 IP、生命周期。
- site_id。
- 凭据关系和凭据状态。

新增兼容投影字段：

- rack_id。
- rack_position。
- rack_mount_kind。
- rack_location_status。

旧字段保留但降级为兼容投影：

- rack。
- rack_unit。
- planned_start_u。

新接口不直接写旧文本位置字段。所有位置变化先更新 rack_devices，再在同一个事务中更新 physical_assets 投影。

### 2.6 rack_data_quality_issues

建议新增数据质量问题表：

- id
- entity_type
- entity_id
- issue_code
- severity
- details_json
- status
- detected_at
- resolved_at
- resolved_by
- resolution_note

建议的 issue_code：

- RACK_NOT_FOUND
- RACK_NOT_UNIQUE
- RACK_TYPE_NOT_FOUND
- DEVICE_TYPE_NOT_FOUND
- ASSET_NOT_FOUND
- DUPLICATE_ASSET_INSTALLATION
- INVALID_POSITION
- U_OVERFLOW
- U_CONFLICT
- LEGACY_LOCATION_CONFLICT
- UNKNOWN_HEIGHT
- UNKNOWN_MOUNT
- POWER_FIELD_CONFLICT
- SITE_SCOPE_MISSING

## 三、安装位置规则

### 3.1 U 型设备

- mount_kind = u_mount。
- start_u 必须大于或等于 1。
- height_u 必须大于或等于 1。
- end_u = start_u + height_u - 1。
- end_u 不得超过机柜 total_u。
- 参与标准 U 位冲突检查。

### 3.2 front

front 设备与同一 U 范围内的 front 和 full_depth 设备冲突。

### 3.3 rear

rear 设备与同一 U 范围内的 rear 和 full_depth 设备冲突。

### 3.4 full_depth

full_depth 设备同时占用 front 和 rear 两个面，与任意同 U 范围的 front、rear、full_depth 设备冲突。

### 3.5 0U 和侧挂

- mount_kind = zero_u 或 side_mount。
- start_u 可以为空。
- 不参与普通 U 位占用计算。
- 必须有明确的 position 或 location_note。
- 必须检查同一侧的物理安装槽位冲突。
- 0U 设备仍然要出现在 2D、3D、统计和问题面板中。

### 3.6 unknown

- placement_status = unknown 或 invalid。
- 仍然返回给布局读模型。
- 不能进入正常 U 位可用性计算。
- 不能静默转换为 front、U1 或 1U。
- 3D 使用明确的 unknown/fallback 表达。

## 四、阶段清单

## M0：数据审计、接口盘点和契约冻结

目标：只读了解现状，不改变生产数据。

- [ ] RD-M0-001 备份和环境确认
  - 确认当前运行数据库类型、连接地址和备份方式。
  - 禁止在生产库上使用临时清库、重建库或不可逆脚本。
  - 记录当前迁移版本、应用版本、worker 数量和缓存配置。
  - 产出：数据库备份记录、环境基线记录。

- [x] RD-M0-002 表结构和查询依赖清单
  - 盘点 schema.py、backend/database/migrations、rack_service、assets API、health service、topology service 中所有涉及 racks、rack_types、device_types、rack_devices、physical_assets 的查询。
  - 盘点前端对现有字段的读取和写入。
  - 产出：字段依赖矩阵和待兼容字段列表。

- [x] RD-M0-003 机柜数据质量审计
  - `rack_data_quality_service.audit_all` 已支持全量或授权机柜范围审计，覆盖机柜/机柜类型/设备类型/机柜设备/物理资产引用、U 位越界与同面冲突、重复安装、非法位置、canonical placement 与 physical_assets 投影冲突，以及功率双字段冲突。
  - 审计不修改业务表，只以幂等问题记录写入 `rack_data_quality_issues`；`POST /api/rack-data-quality/audit` 支持按机柜或授权范围生成机器可读统计。
  - 产出：`racks_checked`、`rack_devices_checked`、`physical_assets_checked`、`issues_detected`、`by_code`、`by_entity_type` 和明细问题列表。

- [x] RD-M0-004 Excel 目录映射审计
  - 将 Excel 的厂商、型号、U 高、外形尺寸、框式设备、0U 设备映射到 device_types 和 rack_devices 目标字段。
  - 将“待核”转换为 pending_verification，不得转换成默认 1U。
  - 产出：目录映射表、未知尺寸清单、0U 清单。

- [x] RD-M0-005 API 路由和响应盘点
  - 记录资产、健康、拓扑、机柜布局、机柜设备和批量导入的认证状态。
  - 记录每个接口实际响应是否使用 success/data/message/error/meta。
  - 记录 HTTP 状态码和异常映射。
  - 产出：API 契约差异报告。

- [x] RD-M0-006 冻结数据契约
  - 创建或补充 docs/rack-data-contract.md。
  - 创建或补充 docs/rack-api-contract.md。
  - 冻结 mount_kind、position、placement_status、dimension_status、mount_policy 枚举。
  - 记录旧字段的读取、写入、弃用和移除计划。
  - 产出：评审通过的数据契约和兼容矩阵。

M0 完成标准：

- [ ] 所有历史数据都有数量统计。
- [ ] 所有位置冲突都有可定位的 entity_id。
- [ ] 未知尺寸和 0U 设备数量明确。
- [ ] 没有执行任何自动修复或破坏性回填。
- [ ] 2D、3D、资产、导入接口的字段来源已经确定。

## M1：认证、权限、敏感信息和异常契约

目标：先修复可以绕过页面登录直接读取数据的接口。

- [x] RD-M1-001 资产读取接口认证和范围（Viewer 门禁与 site/tenant 过滤已接入，并有跨范围回归）
  - 为 assets router 的列表、摘要、树、详情、Web Profile 查询增加 Viewer 认证。
  - 按 site 或 tenant 过滤数据。
  - 未登录必须返回 401。
  - 无权访问其他范围的数据不得通过改变 asset_id 绕过。

- [~] RD-M1-002 资产写接口权限（角色门禁和创建/更新/删除/导入/验证审计已接入；接管、凭据和 Web Profile 全量审计仍需补齐）
  - 创建、更新、导入、接管、凭据轮换至少要求 Operator。
  - 删除、批量凭据操作按项目角色要求 Administrator 或专门权限。
  - 所有写操作记录操作者、目标资产、结果和 request_id。

- [x] RD-M1-003 健康接口认证和范围（Viewer 门禁、Rack 解析与 site/tenant 过滤已接入）
  - device-health 的 overview、明细和报告路由增加 Viewer 认证。
  - 健康查询按授权 site/tenant 范围过滤。
  - 资产 IP、设备身份和告警信息不能匿名返回。

- [~] RD-M1-004 拓扑接口认证和范围（读/写角色门禁与主要 read model 范围已接入；线上分页/多 worker 门禁待补）
  - links、sites、generation-status 等读取路由增加 Viewer 认证。
  - discovery、生成、重建等操作要求 Operator。
  - 链路查询必须限制在授权站点、机柜或设备集合内。

- [x] RD-M1-005 资产 DTO 脱敏（兼容查询结果在 API 边界经过显式 allowlist；敏感字段只返回 set 标志并移除 Vault 路径）
  - 不直接返回 physical_assets 的完整数据库行。
  - 普通列表只返回资产展示和定位所需字段。
  - 凭据只返回 set/status 等布尔或枚举状态。
  - 禁止返回密码、SNMP community、Vault 路径和完整凭据对象。
  - 禁止把敏感字段写入日志。

- [x] RD-M1-006 连通性验证安全边界（授权资产、IP/元数据/保留地址、端口、超时、进程内并发和频率已实现；跨 worker 限流待部署）
  - 验证目标地址只能来自已授权资产，不能由未授权用户任意传入。
  - 拒绝环回、链路本地、云元数据和不允许的内网保留地址。
  - 限制端口、连接超时、并发数和调用频率。
  - 记录每次探测的操作者、资产、目标、端口和结果。

- [~] RD-M1-007 统一响应包装（health/layout/rack-assets 已稳定化；全路由仍在兼容期）
  - 健康接口统一返回 success、data、message、meta。
  - 布局接口、资产接口、拓扑接口统一错误格式。
  - 在 meta 中返回 schema_version 和 generated_at。
  - 对现有前端保持兼容，必要时先提供旧字段别名。

- [~] RD-M1-008 统一异常映射（Rack/placement 已有稳定 code 和 404/409/422 映射；全模块领域异常体系仍待收口）
  - NotFoundError 映射 404。
  - PermissionDeniedError 映射 403。
  - ValidationError 映射 422。
  - ConflictError 映射 409。
  - ExternalServiceError 映射 502。
  - 未预期异常记录服务端日志并返回 500。
  - 禁止使用 except (ValueError, Exception) 将所有错误伪装成 400。

M1 完成标准：

- [x] 未登录访问 assets、device-health、topology 的敏感路由全部返回 401。
- [~] Viewer、Operator、Administrator 权限矩阵已有资产核心自动化测试，凭据轮换和所有写入口仍待补齐。
- [x] 资产普通响应中不存在密码、SNMP community 和 Vault 路径。
- [x] 健康接口通过真实 HTTP 请求可以被 Rack 页面正确解析。
- [~] 内部 SQL/网络错误在稳定 API 路径不会泄漏，历史兼容路径仍待全量审计。

## M2：数据库增量迁移

目标：增加目标字段、索引和约束，保持老数据可读。

- [x] RD-M2-001 新增数据质量问题表
  - 创建 rack_data_quality_issues。
  - 增加 entity、issue_code、severity、status 索引。
  - 保证迁移可重复执行。

- [x] RD-M2-002 规范 racks 字段
  - 增加 layout_revision。
  - 增加或规范 mount_policy。
  - 确认 site_id、rack_code、rack_type_id 的关系。
  - 保留旧 power_capacity_w 作为兼容字段。
  - 明确 used_u、available_u、power_utilization 的只读/派生属性。

- [x] RD-M2-003 规范 device_types 字段
  - 增加 depth_class、dimension_status、几何尺寸、weight_kg、model_family、catalog_key。
  - 保留 is_full_depth 和 u_height 作为兼容字段。
  - 支持 unknown/pending_verification，不使用默认 1 覆盖未知尺寸。

- [x] RD-M2-004 演进 rack_devices
  - 增加 mount_kind、扩展 position、height_u、placement_status、placement_source、dimension_status、location_note、model_key。
  - 将 start_u 调整为允许对 zero_u、side_mount、unknown 为空。
  - PostgreSQL 使用事务化 DDL；如果保留现有 SQLite 兼容路径，SQLite 需要安全重建表并保留 ID、外键、索引和时间字段。
  - 新旧字段在迁移期间保持可读。

- [x] RD-M2-005 增加 physical_assets 位置投影
  - 增加 rack_id、rack_position、rack_mount_kind、rack_location_status。
  - 旧 rack、rack_unit、planned_start_u 保留为兼容投影。
  - 不把 physical_assets 的旧文本字段定义为新权威来源。

- [~] RD-M2-006 增加外键和索引（本轮完成位置索引与非空 asset_id 部分唯一索引；既有孤儿外键治理仍需生产数据审计）
  - rack_devices.rack_id → racks.id。
  - rack_devices.device_type_id → device_types.id。
  - rack_devices.asset_id 对应 physical_assets.id 时保持完整性。
  - rack_type_id 处理孤儿后增加外键。
  - 增加 rack_id、position、start_u、asset_id、device_type_id 查询索引。
  - 增加非空 asset_id 的唯一约束或唯一部分索引。

- [~] RD-M2-007 增加数据库约束（核心规则在 service 层；数据库 CHECK/历史脏数据约束仍需单独门禁）
  - 限制 rack 和 device type 的枚举值。
  - 限制 total_u、宽度、深度、功率和承重的非负范围。
  - U 型安装关系要求 start_u 和 height_u 合法。
  - 0U/side-mount/unknown 允许 start_u 为空，但必须满足 mount_kind 规则。
  - 对历史脏数据先审计、再验证约束，不让迁移无提示失败。

- [x] RD-M2-008 统一功率字段
  - `m0213_rackvision_power_reconciliation` 在升级时生成冲突证据，并以 `power_capacity_watts` 为权威值。
  - 当 watts 为空或为零时提升旧 `power_capacity_w`；无冲突行同步两个兼容字段。
  - 两个非零值冲突时保留原始值、写入 `POWER_FIELD_CONFLICT` 问题记录，再按 canonical watts 同步兼容列。
  - `rack_service` 和 racks API 的新写入已统一双列；不一致的显式输入会以稳定错误拒绝。

- [x] RD-M2-009 对齐新库和升级库
  - fresh schema 必须直接创建目标结构。
  - upgrade schema 必须通过编号迁移达到同样结构。
  - 迁移模块放在 backend/database/migrations，不把新结构继续堆进单体初始化逻辑。
  - 每个迁移具备幂等性和失败后可重试能力。

M2 完成标准：

- [ ] 新库和旧库升级后的目标字段一致。
- [x] PostgreSQL 迁移测试通过。
- [x] 迁移重复执行不会重复建表、重复索引或破坏数据。
- [x] 历史字段仍可供兼容读取。
- [ ] 唯一约束和外键建立前已经处理孤儿和重复数据。

## M3：历史数据回填和冲突隔离

目标：将旧数据转换为新模型，但不把不确定数据伪装成确定数据。

- [x] RD-M3-001 实现 dry-run 回填命令
  - 提供 rack-data-backfill --dry-run。
  - 输出将要新增、更新、跳过和隔离的记录数量。
  - dry-run 不得写入业务表。

- [x] RD-M3-002 回填已有有效 rack_devices
  - rack_id、device_type_id、start_u、position 均有效时保留原关系。
  - 设置 placement_source = legacy_rack_device。
  - 根据现有证据设置 confirmed 或 estimated，不无依据提高可信度。

- [x] RD-M3-003 回填资产文本位置
  - 仅当 rack_code 或名称可以唯一匹配时转换为 rack_id。
  - planned_start_u 合法时才转换为 start_u。
  - 名称匹配多个机柜时不自动选择。
  - 旧 rack_unit 不是数字时保留为 location_note。

- [x] RD-M3-004 隔离冲突数据
  - physical_assets 与 rack_devices 指向不同机柜时写入问题表。
  - 同一资产多个 rack_devices 时写入问题表。
  - U 位越界、U 位重叠、缺少 device_type 时写入问题表。
  - 不删除冲突记录，不覆盖原始位置。

- [x] RD-M3-005 回填未知和 0U 状态
  - Excel 中待核尺寸设置为 pending_verification 或 unknown。
  - 0U 垂直 PDU 等设备设置 zero_u/side_mount。
  - 无法判断安装面的设备设置 position = unknown。
  - 不将未知记录转换成 1U/front。

- [x] RD-M3-006 回填物理资产投影
  - 以 rack_devices 为权威来源回写 physical_assets 投影字段。
  - 更新 rack_id、rack_position、rack_mount_kind、rack_location_status。
  - 无有效安装关系的资产标记为 unplaced 或 unknown。

- [x] RD-M3-007 生成回填报告
  - 输出 confirmed、estimated、unknown、invalid 四类数量。
  - 输出 U 越界、重叠、重复资产、孤儿类型、位置歧义和功率冲突数量。
  - 支持按 issue_code、site_id、rack_id 导出。

- [!] RD-M3-008 评审后执行 apply（需要真实部署库备份、负责人审批和窗口）
  - 先完成备份。
  - 由负责人确认 dry-run 报告。
  - 使用 rack-data-backfill --apply 执行。
  - 记录 migration_run_id、操作者、开始/结束时间和结果。

M3 完成标准：

- [ ] 每条历史记录都有明确状态。
- [ ] 没有因为回填而删除原始资产或安装关系。
- [ ] 所有歧义数据可在页面或报告中定位。
- [ ] 回填后机柜列表、布局和资产详情的数量可对账。

## M4：统一机柜领域服务和事务

目标：所有安装、移动、卸载、资产绑定都走同一套业务规则。

- [x] RD-M4-001 建立 RackPlacementService
  - 提供 install、move、update、uninstall、validate、sync_asset_projection。
  - 资产 API、机柜 API、批量导入统一调用。
  - 不在多个路由中复制 U 位和资产唯一性规则。

- [~] RD-M4-002 重构事务边界（placement service 支持 commit=false；跨资产/Web Profile 全链路事务仍需收口）
  - API 或业务用例层负责开启和提交事务。
  - service 在嵌套业务流程中不得自行 commit。
  - 资产创建、rack_devices 创建、Web Profile、设备类型同步和审计在同一事务中完成。
  - 任一步失败必须整体回滚。

- [x] RD-M4-003 实现输入规范化
  - 统一处理空字符串、None、数字字符串和布尔字符串。
  - 严格解析 0、1、"0"、"1"、true、false。
  - 禁止使用 Boolean("0") 造成错误的 full-depth 判断。
  - 更新模型复用创建模型的名称、枚举、范围和位置校验。

- [x] RD-M4-004 实现 U 位和前后面约束
  - 实现 front/rear/full_depth 的占用规则。
  - 实现 rack mount_policy。
  - 实现 0U 和 side-mount 的独立位置规则。
  - validate-placement 和实际写入必须复用同一规则函数。

- [x] RD-M4-005 实现资产唯一安装
  - 同一个非空 asset_id 只能有一个有效 rack_devices。
  - PostgreSQL 使用机柜行锁和资产行锁。
  - 对无 physical_assets 行的旧资产 ID仍要有稳定的并发保护。
  - 数据库唯一约束作为最终保护，业务层返回可读的 409。

- [x] RD-M4-006 实现安装、移动和卸载
  - 安装时同时更新 rack_devices 和 physical_assets 投影。
  - 移动时同时更新 rack_id、position、start_u、height_u 和投影。
  - 资产关联从 A 改为 B 时同时处理旧资产和新资产。
  - 卸载时清理物理资产位置投影，或按明确策略返回 409。
  - rack_id 变化不能只更新 planned_start_u。

- [x] RD-M4-007 处理机柜缩容和设备类型变更
  - 修改 total_u 前检查所有已有设备。
  - 修改设备类型高度、深度类型或安装能力前检查所有引用关系。
  - 发现会破坏布局时返回 409 和受影响设备列表。
  - 设备类型模板更新不自动覆盖单个资产实际属性；核心受影响设备回归已通过。

- [~] RD-M4-008 修复机柜类型继承
  - 区分请求体未传字段和请求体显式传入默认值。
  - rack_type_id 存在时，未显式提供的字段从类型继承。
  - 已创建机柜不因类型更新而隐式改变。
  - 对宽度、深度、承重、功率和 mount_policy 做完整校验。

- [~] RD-M4-009 重构资产导入（资产批量接口已支持 atomic/detailed；独立质量问题汇总和文件摘要持久化仍待补）
  - `atomic=true` 失败时整批回滚。
  - `detailed=true` 返回逐行 created/skipped/failed 结果。
  - 创建和机柜绑定状态已返回；数据质量问题独立状态仍待补。
  - 同步失败会标记失败或触发整批回滚，不再只写日志后报告整行成功。

- [~] RD-M4-010 写入审计记录（资产核心写入/导入/验证已接入；安装、移动、卸载、资产绑定、类型变更和接管全量事件仍需补齐）
  - 已接入资产创建、更新、删除、批量导入和连通性验证，旧值/新值使用脱敏投影，操作者和 request_id 关联到同一事务。
  - 自动回填和人工修复仍需使用独立 source 并补充审计事件。

M4 完成标准：

- [~] 资产创建后续步骤失败时，资产、rack_devices 和投影全部回滚（placement service 已支持 commit=false；跨资产/Web Profile 用例仍待收口）。
- [~] 同一资产并发安装时一个成功、另一个返回 409（PostgreSQL 锁和唯一索引已实现，真实并发压测待执行）。
- [x] front/rear/full_depth/0U/side_mount/unknown 测试全部通过。
- [ ] 机柜缩容和类型高度修改不会产生新的越界数据。
- [~] 所有写入口使用同一个领域服务（机柜 rack-device 与资产批量导入已接入 canonical placement；安装/移动/卸载、类型变更和审计入口的全量统一仍待补齐）。

## M5：API 版本、布局读模型和兼容层

目标：对外形成稳定契约，给前端和后续 3D 使用。

- [x] RD-M5-001 统一布局响应（canonical placements/read model 已接入；保留旧字段兼容）
  - 保留 GET /api/racks/{rack_id}/layout。
  - 返回 rack、placements、occupancy、data_quality、meta。
  - placements 包含有效、未知和 invalid 记录。
  - 2D 和 3D 不再分别拼装设备列表。

- [x] RD-M5-002 增加安装关系接口（新版 placements 路由已暴露，旧 rack-devices 继续作为兼容别名）
  - POST /api/racks/{rack_id}/placements。
  - PATCH /api/rack-placements/{placement_id}。
  - DELETE /api/rack-placements/{placement_id}。
  - POST /api/racks/{rack_id}/validate-placement。
  - 现有 /api/rack-devices 路由暂时保留为兼容别名，但必须调用同一 service。

- [x] RD-M5-003 统一布局字段（位置、状态、模型解析字段及 stable asset/device/serial/hostname 已返回）
  - 明确 rack_id、asset_id、device_type_id、mount_kind、position、start_u、height_u。
  - 返回 placement_status、dimension_status、placement_source。
  - 返回 stable asset_id、network_device_id、serial_number、hostname。
  - 为后续 model_key、model_match_level 和 fallback_reason 留出字段。

- [x] RD-M5-004 修复健康接口契约（success/data/meta 与 health item 稳定身份字段已统一）
  - GET /api/device-health/overview 返回统一 success/data。
  - health item 返回 asset_id、network_device_id、serial_number、hostname。
  - 前端优先按稳定 ID匹配，hostname 只能作为带匹配置信度的 fallback。

- [x] RD-M5-005 修复资产位置接口（资产列表/详情返回来自 `rack_devices` 的批量 canonical `placement` DTO，并保留旧字段；ID/code 优先，历史名称歧义返回稳定 `RACK_NOT_UNIQUE`）
  - 新写入使用 placement 对象。
  - 旧 rack、rack_unit、planned_start_u 只做兼容转换。
  - `GET /api/assets` 和 `GET /api/assets/{asset_id}` 返回 `placement`；未安装资产明确返回 `null`。
  - placement DTO 同时经过 asset 与 rack 的 tenant/site 范围过滤，避免从资产接口泄露不可见机柜身份。
  - 名称匹配不唯一时返回明确的 `RACK_NOT_UNIQUE`（409）。
  - 资产详情从 rack_devices 生成当前安装位置。

- [~] RD-M5-006 修复拓扑范围（links/sites/graph/discovery/evidence/history 已按授权设备范围过滤；完整 cursor 分页和 legacy asset_id 补齐待收口）
  - topology links 支持 rack_id、site_id 和分页/游标。
  - 设备链路返回稳定设备 ID和资产 ID。
  - 未绑定资产的通用机柜项不强行制造拓扑关系。

- [x] RD-M5-007 修复机柜列表和校验接口（validate-placement 已接入；validate-u 保留兼容；无效 rack 设备查询返回 404）
  - validate-u 改为 validate-placement。
  - 支持 rack_id/rack_code，不把名称作为唯一查找条件。
  - 同时检查 front、rear、full_depth。
  - 无效 rack_id 的 devices 接口返回 404，而不是 200 空数组。

- [~] RD-M5-008 统一分页和导入响应
  - summary 返回 total、page、page_size、total_pages。
  - 目录导入已有冲突报告；正式资产批量接口的逐行失败/原子模式仍需补齐。
  - 所有接口的错误 code 可被前端稳定判断。

M5 完成标准：

- [x] 新旧接口可以在兼容周期内同时运行（旧接口已保留，新版 placements 路由已暴露并复用同一 service）。
- [x] layout 是 2D、3D、导出和统计的共同数据来源。
- [ ] 所有冲突返回 409，而不是 400 或内部异常文本。
- [~] 健康状态可以通过稳定 ID正确挂到机柜设备（Rack 页面兼容解析已完成，稳定 ID 字段补齐待办）。

## M6：缓存、版本和跨 worker 一致性

目标：避免布局写入后仍然读取旧数据。

- [x] RD-M6-001 增加布局版本
  - 每个 racks 维护 layout_revision。
  - 安装、移动、卸载、资产绑定和影响布局的设备类型变更时递增。
  - 版本更新和业务写入在同一个事务中完成。

- [~] RD-M6-002 修复缓存 key（layout 使用 rack_id+revision；授权范围和 summary 全局 revision 仍待接入）
  - layout key 包含 rack_id、layout_revision 和授权范围。
  - summary key 包含筛选条件、全局 revision 和授权范围。
  - 不缓存包含凭据或敏感资产明细的响应。

- [~] RD-M6-003 统一失效路径（主要机柜写接口已失效 rack_page；资产同步、导入和 topology 路径仍需统一）
  - 机柜写接口提交后失效 rack_page。
  - 资产同步创建、更新、移动、删除 rack_devices 后失效相关布局。
  - 批量导入成功后失效列表、摘要、统计和受影响机柜。
  - topology 变化后失效拓扑缓存。

- [~] RD-M6-004 处理多 worker（数据库 revision 可避免旧布局命中；Redis/线上多 worker 验证未完成）
  - 短期使用数据库 revision 避免另一 worker继续命中旧版本。
  - 中期评估 Redis 或其他共享缓存。
  - 明确本地进程缓存不能作为跨 worker 的一致性机制。

- [x] RD-M6-005 修复前端读请求竞态
  - layout、health、asset search 使用 AbortController 或序列号保护。
  - 缓存命中、取消请求、切换机柜时正确恢复 loading 状态。
  - 旧请求不能覆盖新机柜数据。

M6 完成标准：

- [~] 任意 worker 写入布局后，其他 worker 获取到新 revision（数据库 revision key 已接入；多 worker/共享缓存线上验证待执行）。
- [x] 机柜安装、移动和卸载后布局不会保持 10 秒以上的旧状态（写入递增 revision，layout cache key 随 revision 变化）。
- [ ] 快速切换机柜和快速搜索不会出现旧结果覆盖新结果。

## M7：前端兼容切换

目标：让当前 /cmdb/racks 页面消费新契约，不新增第二套推断逻辑。

- [x] RD-M7-001 切换 layout read model
  - RackElevation 和 RackScene 使用同一份 placements。
  - invalid/unknown 设备不从数组中删除。
  - 2D 和 3D 均显示数据质量状态。

- [~] RD-M7-002 修复 front/rear 安装（表单不再覆盖 position，full_depth 共用占用规则，unknown/invalid U 行不再占用 2D 可用 U；仍需浏览器人工回归）
  - 选择后视图 U 位后保留 rear。
  - 不得在选择资产时写死 position = front。
  - full_depth 设备在两侧视图中按占用规则表现。

- [~] RD-M7-003 支持无资产和 0U 安装（canonical 字段/UI 已支持；PDU/配线架/托盘等全场景验收待补）
  - 支持没有 asset_id 的通用机柜设备。
  - 支持 PDU、配线架、理线架、托盘、空白面板和传感器。
  - 0U/side-mount 使用独立安装位置，不要求标准 U 位。

- [~] RD-M7-004 修复折叠空位交互（折叠只作用于空白段；需浏览器拖拽验收）
  - collapseEmpty=true 时设备仍可点击、选中、拖动和打开详情。
  - 折叠只改变视觉空白，不改变设备交互能力。

- [~] RD-M7-005 修复资产选择器（前端本地过滤+后端唯一安装保护已接入；跨机柜返回状态与竞态仍需统一）
  - 过滤已安装在其他机柜的资产。
  - 后端返回资产安装状态，前端不单独猜测。
  - 旧查询请求不能覆盖新查询结果。

- [~] RD-M7-006 修复导入和导出（导出已跳过未知 U 的伪占位；英文模板与批量逐行结果仍待补）
  - 导出明确区分当前页和全部筛选结果。
  - 修复英文模板列数和示例值错位。
  - 非法数字、0、空值和待核值不能静默替换成默认值。

## M8：3D 接入前置和 GLB 交接

目标：数据底座通过验收后，才进入 3D 资产接入。

- [~] RD-M8-001 统一 3D 坐标和单位（规范、转换层和 Blender 生产脚本已完成；本机 Blender 5.2.1 已生成 5 个校验通过的 GLB，4 个 Generic 已登记为 `approved/glb`，真实 OEM 产品校准仍待补）
  - 明确后端 U 位、2D 坐标和 3D 坐标的转换层。
  - 将任务清单的 1U = 0.04445m 与现有程序化模型比例进行校准。
  - 不允许模型文件直接假设当前前端的旧坐标含义。

- [x] RD-M8-002 建立 model registry 接口
  - 支持 exact、family、vendor_generic、global_generic。
  - 每次解析返回 model_key、match_level、fallback_reason、version。
  - 解析失败不得返回 null，必须返回可见的 unknown/fallback。

- [x] RD-M8-003 3D 读取 unknown 和 invalid
  - 无效位置设备在 3D 中显示问题标记或 unknown 模型。
  - 不因无法计算正常坐标而从场景中静默消失。
  - 2D、3D 的设备数量和 placement_id 可对账。

- [~] RD-M8-004 修复 front/rear 3D 方向（GLB 转换层已定义，5 个资产已完成正面/背面/45° 浏览器冒烟；真实模型和线缆端点仍待验收）
  - rear 设备拉出方向为负 Z 或统一坐标系下的后方。
  - rear 线缆端点连接到后侧面。
  - full_depth 设备的连接面和占用范围正确。

- [~] RD-M8-005 支持非标准机柜几何参数（3D 设备深度/宽度和导轨已按 width_mm/depth_mm 缩放；本地浏览器已完成当前 600×1000mm 机柜 3D 冒烟，450mm 墙挂柜模板、真实 GLB 和现场校准仍待外部验收）
  - 450mm 墙挂柜、非标准宽度和深度不再在设备坐标或导轨位置上套用固定 19 英寸偏移。
  - 导轨、设备宽度和深度从 rack/device geometry 读取。

- [~] RD-M8-006 生产静态资源验证（Nginx/Docker 目录配置已完成，5 个 GLB 已复制到 `public/assets/3d` 且与 build 产物 SHA-256 一致，本地浏览器 3D 冒烟通过；线上 MIME、缓存头和 404 验证待执行）
  - Nginx 支持 glb、gltf、bin、ktx2、basis 等资源。
  - 验证 MIME、缓存头、压缩和 404 行为。
  - Blender 只作为离线资产生产工具，不进入生产运行时。

M8 启动条件：

- [ ] M1 到 M7 的阻断项已经关闭。
- [ ] 数据质量报告中所有未知/invalid 数量有明确展示策略。
- [ ] 2D、3D 共同布局接口和 placement_id 已稳定。
- [ ] GLB registry 的字段和 fallback 规则已经冻结。

## 五、接口契约样例

### 5.1 安装关系请求

    {
      "asset_id": "asset-001",
      "device_type_id": "device-type-001",
      "name": "switch-01",
      "mount_kind": "u_mount",
      "position": "front",
      "start_u": 30,
      "height_u": 1,
      "placement_status": "confirmed",
      "location_note": ""
    }

0U 设备示例：

    {
      "asset_id": "asset-pdu-001",
      "device_type_id": "device-type-pdu",
      "name": "vertical-pdu-01",
      "mount_kind": "zero_u",
      "position": "right_side",
      "start_u": null,
      "height_u": null,
      "placement_status": "confirmed",
      "location_note": "机柜右侧后部"
    }

未知设备示例：

    {
      "asset_id": "asset-unknown-001",
      "device_type_id": "device-type-unknown",
      "name": "unknown-device-01",
      "mount_kind": "unknown",
      "position": "unknown",
      "start_u": null,
      "height_u": null,
      "placement_status": "unknown",
      "location_note": "待现场核验"
    }

### 5.2 统一成功响应

    {
      "success": true,
      "data": {},
      "message": "",
      "meta": {
        "schema_version": "rack-v2",
        "generated_at": "2026-09-06T00:00:00Z"
      }
    }

### 5.3 统一失败响应

    {
      "success": false,
      "error": {
        "code": "RACK_U_CONFLICT",
        "message": "设备与已有设备发生 U 位冲突",
        "fields": {
          "start_u": "30",
          "position": "front"
        }
      },
      "request_id": "req-001"
    }

建议错误码：

- AUTH_REQUIRED
- PERMISSION_DENIED
- RACK_NOT_FOUND
- RACK_NOT_UNIQUE
- ASSET_NOT_FOUND
- ASSET_ALREADY_INSTALLED
- RACK_U_OVERFLOW
- RACK_U_CONFLICT
- POSITION_NOT_ALLOWED
- FULL_DEPTH_CONFLICT
- ZERO_U_POSITION_REQUIRED
- DEVICE_TYPE_IN_USE
- RACK_RESIZE_CONFLICT
- DATA_QUALITY_REVIEW_REQUIRED
- EXTERNAL_CONNECTIVITY_FAILED

## 六、测试清单

### 6.1 认证和安全

- [x] 未登录访问 assets 列表返回 401。
- [x] 未登录访问 health overview 返回 401。
- [x] 未登录访问 topology links 返回 401。
- [x] Viewer 无法创建、删除或轮换凭据（当前覆盖资产写入/删除；凭据轮换的完整矩阵仍待补）。
- [x] 跨 site/tenant 的 rack、asset、health、topology 请求不能读取数据（覆盖主要 read model；legacy 兼容路径继续审计）。
- [x] 普通资产响应不包含密码、SNMP community 和 Vault 路径。
- [x] 连通性验证不能探测未授权目标。

### 6.2 迁移和数据

- [x] PostgreSQL fresh schema 初始化。
- [x] PostgreSQL 从上一版本升级。
- [x] 迁移重复执行。
- [x] 迁移失败后回滚并重试。
- [x] rack_devices 新字段、外键和索引存在。
- [x] 重复 asset_id 在约束建立前能被报告。
- [x] 回填 dry-run 不修改业务表。
- [x] 回填 apply 后可按问题类型导出报告（真实部署库 apply 仍需审批）。

### 6.3 业务约束

- [x] front 与 front 冲突。
- [x] rear 与 rear 冲突。
- [x] front 与 rear 不冲突。
- [x] full_depth 与 front 冲突。
- [x] full_depth 与 rear 冲突。
- [x] 设备超出 total_u 被拒绝。
- [x] 0U 不占标准 U 位。
- [x] 0U 没有侧面位置时被拒绝。
- [x] unknown 不被转换成 1U。
- [x] 同一资产不能安装到两个机柜。
- [x] 机柜缩容前发现越界设备。
- [x] 修改设备类型高度前发现受影响设备。

### 6.4 事务和并发

- [~] 资产创建后 Web Profile 失败时整体回滚（主流程已使用同一连接，故障注入回归待补）。
- [~] 资产创建后 rack_devices 同步失败时整体回滚（主流程已使用同一连接，故障注入回归待补）。
- [x] 移动设备时 rack_id、position、start_u 和资产投影同时提交。
- [~] 并发安装同一资产时一个成功、一个返回 409（锁/唯一索引已实现，压测待执行）。
- [~] 并发安装同一 U 位时不会产生两个有效冲突记录（事务锁已实现，压测待执行）。
- [~] 多 worker 下写入后读到新 layout_revision（revision key 已实现，线上验证待执行）。

### 6.5 API 契约和回归

- [x] 真实 HTTP 请求验证 success/data/message/meta（健康 overview 已覆盖）。
- [~] 404、403、409、422 已有核心覆盖；500/502 及全模块错误矩阵待补。
- [x] 旧 /api/rack-devices 接口继续工作并走新 service。
- [x] layout 同时返回正常、unknown 和 invalid 设备。
- [x] health item 包含稳定资产/设备身份。
- [~] 批量导入逐行报告成功和失败（目录导入与资产批量接口已具备 `atomic=true` / `detailed=true`；独立数据质量状态和文件摘要持久化仍待补）。

### 6.6 前端联调

- [x] 后视图安装最终保存为 rear。
- [~] full_depth 在前后面显示和占用一致（后端和适配器通过，浏览器现场回归待补）。
- [~] 0U PDU 可以安装、显示和编辑（接口/适配器通过，浏览器现场回归待补）。
- [~] 折叠空位后设备仍可点击和移动（代码路径通过，浏览器现场回归待补）。
- [x] 快速切换机柜不会发生旧响应覆盖。
- [ ] 导出全部筛选结果时不丢分页。
- [x] unknown/invalid 设备在 2D、3D 中都有可见表达（3D 使用问题标记/兜底表达）。

## 七、上线和回滚策略

### 7.1 上线顺序

- [ ] 发布安全和响应契约修复。
- [ ] 发布只读审计脚本和报告。
- [ ] 执行数据库增量迁移。
- [ ] 执行回填 dry-run 并评审。
- [ ] 执行回填 apply。
- [ ] 开启 canonical placement 双读。
- [ ] 开启统一 service 双写或新写入路径。
- [ ] 切换 layout read model。
- [ ] 切换前端。
- [ ] 观察一个完整运行周期后再停止旧字段写入。

### 7.2 建议的功能开关

- [ ] rack_canonical_read_enabled
- [ ] rack_canonical_write_enabled
- [ ] rack_placement_v2_enabled
- [ ] rack_unknown_render_enabled
- [ ] rack_shared_cache_enabled

### 7.3 回滚原则

- [ ] 结构迁移只做 additive change，代码回滚时保留新增字段。
- [ ] 不提供未经验证的破坏性 down migration。
- [ ] 回填出现问题时优先停止新写路径并使用原始备份或前向修复。
- [ ] 回填前保存审计报告和备份校验值。
- [ ] 任何人工修复都记录原值、新值、原因和操作者。

## 八、交付物清单

- [x] docs/rackvision/architecture.md、current_architecture.md、NEXORA_3D_ASSET_SPEC_V1.md、model_mapping.md、frontend_integration.md、2d_3d_sync.md、blender_workflow.md、qa_checklist.md
- [ ] docs/rackvision/rack-data-contract.md、rack-api-contract.md、rack-data-quality-report.md（当前专项契约内容已在本清单和 architecture 文档中，独立拆分仍待补）
- [x] 编号数据库迁移模块
- [x] rack-data-backfill dry-run/apply/report 工具
- [x] RackPlacementService
- [ ] 统一错误类型和异常处理
- [x] 资产、健康、拓扑认证测试
- [x] 迁移、回填、事务、并发和 API 契约测试（已覆盖隔离 PostgreSQL 核心路径；真实部署和多 worker 仍待补）
- [~] 前后端联调记录（当前代码、适配器和 QA checklist 已记录；浏览器现场回归待执行）
- [~] 发布检查表和回滚说明（Nginx/Docker/Release 路径已更新，线上发布验证待执行）

## 九、最终完成定义

只有满足以下条件，底层数据和接口专项才算完成：

- [ ] 未登录无法读取资产、健康和拓扑数据。
- [ ] 资产普通接口不泄露凭据和不必要的敏感字段。
- [ ] 健康接口和 Rack 页面响应契约一致。
- [ ] rack_devices 成为唯一的机柜安装位置来源。
- [ ] physical_assets 位置字段成为事务内同步的投影。
- [ ] front、rear、full_depth、0U、side_mount、unknown 规则明确且有测试。
- [ ] 历史脏数据都有审计状态，没有被静默覆盖。
- [ ] 机柜缩容和设备类型变更不会制造新的越界或冲突。
- [ ] 安装、移动、卸载、资产绑定具备原子事务。
- [ ] 多 worker 场景下缓存不会长期返回旧布局。
- [ ] 2D、3D、统计和导出使用同一个布局读模型。
- [ ] unknown/invalid 设备在 2D 和 3D 中都可见。
- [ ] M1 到 M7 通过后，才允许进入大批量 GLB 建模和模型资产导入。
