# Nexora RackVision 主任务开发清单

- 文档类型：RackVision 完整实施主清单
- 当前状态：代码收口与验收中（P0 认证/范围/严格 DTO/核心资产审计/探测边界、P1 数据模型/目录/前端联调已落地；5 个生产展示基线 GLB 已生成并通过离线校验，4 个 Generic 条目已接入 `public/assets/3d` 并在浏览器 3D 页面完成冒烟验证；完整资产覆盖、OEM 校准和线上发布验收仍待外部条件）
- 基线日期：2026-09-07
- 适用页面：/cmdb/racks
- 产品需求来源：[Nexora_RackVision_Detailed_TASKS.md](D:/data/downloads/Nexora_RackVision_Detailed_TASKS.md)
- 资产目录来源：[Nexora_3D_Asset_Base_Catalog_v1.xlsx](D:/data/downloads/Nexora_3D_Asset_Base_Catalog_v1.xlsx)
- 底层专项清单：[Nexora_RackVision_Backend_Data_API_TASKS.md](D:/netops/netsops-main/docs/Nexora_RackVision_Backend_Data_API_TASKS.md)

## 一、清单说明

本文件将原始产品/3D/GLB/Blender/拓扑任务，与当前项目审查后补充的底层数据、接口、安全、迁移、事务、缓存、前端联调和质量门禁任务合并为一份执行清单。

附件中的任务文档是需求输入。本文件是当前项目的实施计划，所有任务都需要结合现有代码、数据库和部署方式执行，不能把附件中的路径或示例直接当成当前项目已经存在的结构。

### 1.4 本轮实现状态（2026-09-06）

已落地并通过当前隔离 PostgreSQL/前端测试的范围：

- P0：现状基线、资产/健康/拓扑路由认证与 site/tenant 范围、健康稳定 envelope、资产严格 DTO 与敏感字段脱敏、资产核心写入/导入/验证审计、连通性探测边界、GLB 静态资源发布配置。
- P1：`m0210` canonical placement 与 `m0213` 功率字段 reconciliation 迁移、`RackPlacementService`、数据质量审计与回填 CLI、0U/侧挂/落地/unknown 语义、布局 read model、2D/3D 共享适配、机柜缩容/类型高度变更保护、拓扑读取范围过滤。
- 目录：Excel 五个工作表的只读解析、120 条网络设备/59 条机柜配套/34 条线缆/30 条优先级记录导出、71 条待核尺寸保留、88 个可复用 registry 条目、120 条 exact SKU 映射、dry-run-first `device_types` 导入工具。
- 3D：坐标/单位/命名规范、Blender headless 生产基线流水线、resolver 的 exact/family/vendor/global fallback、无 GLB 时的程序化兜底和待确认标记；5 个 GLB 已生成并通过场景/结构校验，4 个 Generic registry 条目已切换为 `approved/glb`，本地浏览器正面/背面/45° 3D 冒烟通过。

仍未关闭的外部/发布门禁：真实 Blender 构建机生成并人工验收 GLB、官方尺寸/端口证据补齐、真实部署库回填审批、Nginx 线上 MIME/缓存头验证、多 worker/性能基准和拓扑线缆增强。

### 1.1 全局执行规则

- [ ] 不跳过 P0/P1 基础任务直接进入大批量 GLB 建模。
- [ ] 不重写无关 Nexora 功能。
- [ ] 先读现有路由、页面、service、schema、迁移和测试，再修改代码。
- [ ] 生产运行时以 PostgreSQL 为权威持久化后端。
- [ ] 数据库迁移必须可重复、可审计，并兼容已有真实数据。
- [ ] 大批量数据回填不得放在应用启动流程中。
- [ ] 不静默把未知高度、未知尺寸、未知位置或 0U 设备改成 1U/front。
- [ ] 2D、3D、统计、导出和健康信息使用同一份布局读模型。
- [ ] 3D 第一版本保持只读，不新增独立的 3D 位置保存接口。
- [ ] 不凭图片比例推断官方产品尺寸。
- [ ] 不把 120 个精确型号直接制作成 120 个独立高精度 GLB。
- [ ] 所有密码、Token、SNMP community、Vault 路径和原始凭据都不得出现在普通响应或日志中。
- [ ] 每完成一个有意义的任务，都要补充测试和任务状态。
- [ ] 偏离本清单的地方必须记录原因、影响和替代方案。

### 1.2 状态和优先级

| 标记 | 含义 |
|---|---|
| [ ] | 未开始 |
| [~] | 进行中 |
| [x] | 已完成并通过验收 |
| [!] | 被阻塞，需要外部输入或数据 |
| P0 | 安全或数据一致性阻断，上线前必须关闭 |
| P1 | 核心功能或可靠性问题，进入主版本前关闭 |
| P2 | 优化、增强或后续体验任务 |

### 1.3 总体依赖

    P0 现状、安全和数据审计
      ↓
    P1 数据模型、迁移、回填、事务和 API 契约
      ↓
    P2 2D/3D 共用布局读模型和前端联调
      ↓
    P3 3D 规范、资产目录、GLB registry 和 Blender 流程
      ↓
    P4 Viewer、拓扑、线缆、性能和发布
      ↓
    P5 总体验收

## 二、P0：仓库发现、运行安全和现状基线

前置：无。  
目标：确认当前项目真实结构，记录问题，不做无关重构。

### 2.1 代码和部署发现

- [x] RV-P0-001 检查仓库树和工作区状态，保留用户已有未提交修改。
- [x] RV-P0-002 确认前端根目录、React 入口、Vite 配置和生产构建命令。
- [x] RV-P0-003 确认 FastAPI 后端入口、API router 注册方式和数据库连接方式。
- [x] RV-P0-004 确认当前机柜页面入口、路由、导航和权限链路。
- [x] RV-P0-005 确认 2D 机柜数据结构、布局接口和前端状态管理方式。
- [x] RV-P0-006 确认设备库存、physical_assets、devices、device_types、rack_devices 等表的关系。
- [x] RV-P0-007 确认 assets、health、topology、racks 各接口的实际响应格式。
- [x] RV-P0-008 确认静态资源路径、Nginx、Docker、Ubuntu 部署和前端 dist 发布方式。
- [x] RV-P0-009 确认测试框架、共享 PostgreSQL 测试 fixture 和质量门禁命令。
- [x] RV-P0-010 将现状写入 docs/rackvision/current_architecture.md。

### 2.2 现有问题登记

- [x] RV-P0-011 登记 assets router 缺少强制认证的问题。
- [x] RV-P0-012 登记 device-health 路由缺少认证和响应格式不一致的问题。
- [x] RV-P0-013 登记 topology 读取路由缺少强制认证的问题。
- [x] RV-P0-014 登记 rack_devices 与 physical_assets 双位置来源问题。
- [x] RV-P0-015 登记 front/rear/full-depth/0U/unknown 数据语义缺失问题。
- [x] RV-P0-016 登记并收口 power_capacity_w 与 power_capacity_watts 重复问题。
- [~] RV-P0-017 登记进程内缓存和多 worker 失效不一致问题。
- [~] RV-P0-018 登记并开始收口异常被统一转成 400 以及内部错误泄漏问题。
- [x] RV-P0-019 登记现有 2D/3D 坐标和单位转换差异。
- [x] RV-P0-020 登记 Nginx 尚未覆盖 GLB/GLTF/BIN/KTX2/Basis 的问题。

### 2.3 P0 门禁

- [x] 当前架构文档已提交。
- [ ] 所有相关代码路径和数据库查询有依赖矩阵。
- [ ] 未修改无关功能。
- [ ] 数据库、接口和部署的真实现状已有证据。

## 三、P0：认证、权限、敏感数据和 API 基础契约

前置：RV-P0-003、RV-P0-007。  
目标：先关闭匿名资产、健康和拓扑访问，再继续数据改造。

### 3.1 资产接口安全

- [x] RV-P0-101 为 assets 列表、摘要、树和详情路由增加 Viewer 认证。
- [x] RV-P0-102 为资产创建、更新、导入和接管增加 Operator 权限。
- [x] RV-P0-103 为资产删除、凭据轮换和批量敏感操作设置 Administrator 或专门权限。
- [x] RV-P0-104 对资产接口增加 site/tenant 范围过滤。
- [x] RV-P0-105 保留兼容查询但在 API 边界使用显式资产 DTO allowlist，敏感列不会因 schema 扩展自动进入响应。
- [x] RV-P0-106 资产列表和详情只返回稳定 CMDB/UI 字段；密码、SNMP community 等只保留 set 标志和空值兼容字段。
- [x] RV-P0-107 凭据只返回 set/status 等布尔或枚举状态。
- [x] RV-P0-108 禁止普通接口返回密码、SNMP community、Vault 路径和完整 Web Profile 凭据。
- [x] RV-P0-109 资产连通性验证只能针对授权资产自身地址。
- [x] RV-P0-110 拒绝环回、链路本地、云元数据和未授权保留地址。
- [~] RV-P0-111 已限制端口、超时、进程内并发和频率；跨 worker 共享限流仍待部署能力。
- [~] RV-P0-112 资产创建、更新、删除、批量导入和连通性验证已写入同事务脱敏审计；读取、接管、凭据/Web Profile 全链路审计仍待补齐。

涉及基线：

- backend/api/assets.py
- backend/core/rbac.py
- backend/main.py

### 3.2 健康接口安全和契约

- [x] RV-P0-121 为 device-health overview、明细和报告路由增加 Viewer 认证。
- [x] RV-P0-122 对健康数据增加 site/tenant 范围过滤。
- [x] RV-P0-123 将健康接口统一为 success、data、message、meta 响应。
- [x] RV-P0-124 健康条目返回 asset_id、network_device_id、serial_number、hostname。
- [x] RV-P0-125 前端按稳定 ID匹配，hostname 只能作为有置信度的 fallback。
- [x] RV-P0-126 修复 Rack 页面 fetchJson 与健康接口原始响应不一致的问题。

涉及基线：

- backend/api/device_health.py
- backend/services/device_health_service.py
- src/pages/RackManagement/index.tsx

### 3.3 拓扑接口安全和范围

- [x] RV-P0-131 为 topology links、sites、generation-status 读取路由增加 Viewer 认证。
- [x] RV-P0-132 为拓扑发现、生成和重建操作增加 Operator 权限。
- [x] RV-P0-133 拓扑读取按 site_id、rack_id、tenant 范围过滤。
- [~] RV-P0-134 主拓扑/健康/机柜读模型已返回稳定 device_id 和端口状态，拓扑 legacy 链路的 asset_id 补齐仍待收口。
- [~] RV-P0-135 已将 links/graph 结果上限提高并返回 truncated，discovery 明细支持 limit/offset；完整 cursor 分页仍待收口。

涉及基线：

- backend/api/topology.py
- src/pages/RackManagement/Rack3D/index.tsx

### 3.4 异常和错误响应

- [~] RV-P0-141 RackVision placement 已有领域错误类型，完整六类领域异常体系仍待统一。
- [~] RV-P0-142 Rack/placement 路径已映射 404/409/422，跨模块 403/502/500 统一映射仍待收口。
- [~] RV-P0-143 RackVision 新路径已减少全量吞错，历史 topology/asset 兼容路径仍有局部兼容吞错。
- [~] RV-P0-144 稳定 API 路径已隐藏 SQL/路径/traceback/网络原始错误，完整全路由审计仍待完成。
- [~] RV-P0-145 稳定错误响应已有 code/message/request_id 基础，fields/details 全面统一仍待收口。
- [~] RV-P0-146 请求日志已有 request_id 且审计服务具备脱敏，资产全量事件接入仍待完成。

### 3.5 P0 验收

- [x] 未登录访问资产列表返回 401。
- [x] 未登录访问健康概览返回 401。
- [x] 未登录访问拓扑链路返回 401。
- [x] Viewer 不能执行资产写入、删除或凭据操作。
- [x] 普通资产响应没有密码、SNMP community 和 Vault 路径。
- [x] 健康接口真实 HTTP 请求可以被 Rack 页面解析（当前回归覆盖统一 envelope 和 Rack 兼容解析）。
- [x] 连通性验证不能被用作任意内网探测（IP/元数据/端口/超时/并发/频率边界已加入，跨 worker 限流仍属部署门禁）。

## 四、P1：资产目录导入和规范化

前置：RV-P0-004、RV-P0-006。  
输入：[Nexora_3D_Asset_Base_Catalog_v1.xlsx](D:/data/downloads/Nexora_3D_Asset_Base_Catalog_v1.xlsx)。  
目标：保留源数据，生成机器可读、可追溯、不会静默猜测尺寸的目录。

### 4.1 工作簿处理

- [x] RV-P1-001 读取 00_说明与统计。
- [x] RV-P1-002 读取 01_网络设备清单。
- [x] RV-P1-003 读取 02_机柜与配套设备。
- [x] RV-P1-004 读取 03_线缆与光模块。
- [x] RV-P1-005 读取 04_建模优先级。
- [x] RV-P1-006 保留原始 Excel，不覆盖或改写源文件。
- [x] RV-P1-007 导出规范化机器数据。
- [x] RV-P1-008 创建 assets/catalog/network_devices.yaml。
- [x] RV-P1-009 创建 assets/catalog/rack_assets.yaml。
- [x] RV-P1-010 创建 assets/catalog/cables_optics.yaml。
- [x] RV-P1-011 保留原始来源 URL、来源标题和来源版本。
- [x] RV-P1-012 将 TBD、待核和空值保留为 unknown/pending_verification。
- [x] RV-P1-013 禁止通过图片比例或默认值静默推断缺失尺寸。
- [x] RV-P1-014 同时生成 JSON 机器接口、manifest、summary 和可审查 YAML 输出。
- [x] RV-P1-015 提供 dry-run-first 的 device_types 目录导入，冲突时整批阻断。

### 4.2 标准字段

- [x] RV-P1-021 规范 vendor。
- [x] RV-P1-022 规范 family。
- [x] RV-P1-023 规范 exact_model。
- [x] RV-P1-024 规范 device_type。
- [x] RV-P1-025 规范 deployment_domain。
- [x] RV-P1-026 规范 role。
- [x] RV-P1-027 规范 height_u。
- [x] RV-P1-028 规范 width_mm、depth_mm、height_mm。
- [x] RV-P1-029 规范 port_layout、port_count 和 port_media_type（可从源字段解析的值已结构化；缺失值保留 unknown/null）。
- [~] RV-P1-030 规范 uplink、management、console、PSU、fan 信息（字段和解析入口已预留；原 Excel 未提供的型号级证据仍待补）。
- [x] RV-P1-031 规范 asset_priority。
- [x] RV-P1-032 增加 dimension_status。
- [x] RV-P1-033 增加 data_confidence。

建议 vendor 值：

    huawei
    h3c
    ruijie
    zte
    maipu
    dptech
    generic

建议 device_type 值：

    switch
    router
    firewall
    server
    storage
    ups
    battery
    pdu
    patch_panel
    odf
    cable_manager
    kvm
    tray
    blank_panel
    sensor
    other

建议 data_confidence 值：

    verified_official
    verified_manual
    visual_only
    tbd

### 4.3 目录质量门禁

- [x] vendor、family、exact_model 不因大小写或空格产生重复。
- [x] 每条设备有唯一 catalog_key。
- [x] 高度、尺寸、深度类型均有来源或明确 unknown。
- [x] Excel 中 0U 设备被标记为 zero_u/side_mount。
- [~] 框式设备不被强行归入普通 1U（目录保留 unknown/pending；需要逐型号现场/官方证据复核）。
- [x] 71/120 条存在待核或不完整尺寸的数据有单独清单。
- [x] 120 条网络设备的建议 GLB 模板已映射，但不直接代表已有模型文件。

## 五、P1：厂商研究和证据收集

前置：RV-P1-001 到 RV-P1-033。  
目标：优先使用官方资料，形成可追溯建模依据。

### 5.1 厂商覆盖

Huawei：

- [ ] RV-P1-101 至少收集 10 个园区模型。
- [ ] RV-P1-102 至少收集 10 个数据中心模型。

H3C：

- [ ] RV-P1-111 至少收集 10 个园区模型。
- [ ] RV-P1-112 至少收集 10 个数据中心模型。

Ruijie：

- [ ] RV-P1-121 至少收集 10 个园区模型。
- [ ] RV-P1-122 至少收集 10 个数据中心模型。

ZTE：

- [ ] RV-P1-131 至少收集 10 个园区模型。
- [ ] RV-P1-132 至少收集 10 个数据中心模型。

Maipu：

- [ ] RV-P1-141 至少收集 10 个园区模型。
- [ ] RV-P1-142 至少收集 10 个数据中心模型。

DPtech：

- [ ] RV-P1-151 至少收集 10 个园区模型。
- [ ] RV-P1-152 至少收集 10 个数据中心模型。

### 5.2 每个型号的证据

- [ ] RV-P1-161 记录 exact product model。
- [ ] RV-P1-162 记录 product family。
- [ ] RV-P1-163 记录 marketing status，如资料可见。
- [ ] RV-P1-164 记录园区/数据中心分类。
- [ ] RV-P1-165 记录 Access、Aggregation、Core、ToR、Leaf、Spine 等角色。
- [ ] RV-P1-166 记录 U 高。
- [ ] RV-P1-167 记录宽度、深度、高度。
- [ ] RV-P1-168 记录前面板资料。
- [ ] RV-P1-169 记录后面板资料，如可获得。
- [ ] RV-P1-170 记录端口数量和类型。
- [ ] RV-P1-171 记录上联端口。
- [ ] RV-P1-172 记录 Console 和 Management 端口位置。
- [ ] RV-P1-173 记录电源位置。
- [ ] RV-P1-174 记录风扇位置。
- [ ] RV-P1-175 记录风向提示。
- [ ] RV-P1-176 记录厂商 Logo、LED 位置。
- [ ] RV-P1-177 记录 source URL。
- [ ] RV-P1-178 记录来源文档标题。
- [ ] RV-P1-179 记录来源日期或版本。

### 5.3 研究规则

- [ ] RV-P1-181 优先使用官方厂商资料。
- [ ] RV-P1-182 保留每个字段的来源引用。
- [ ] RV-P1-183 未获授权时不把受版权保护的营销图片复制进项目。
- [ ] RV-P1-184 允许只保存来源 URL 并人工使用原资料作为建模参考。
- [ ] RV-P1-185 官方尺寸缺失时标记 unknown，不从图片比例推导。
- [ ] RV-P1-186 冲突资料进入人工复核清单。
- [ ] RV-P1-187 输出 docs/rackvision/research/vendor_asset_research.md。

## 六、P1：产品族聚类和模型数量控制

前置：第五阶段研究完成或明确标记为待核。  
目标：根据可见外形和物理特征复用模型，避免 120 个 SKU 变成 120 个详细 GLB。

### 6.1 型号映射

- [x] RV-P1-201 为每个 exact SKU 判断是否使用 exact asset（生成 120 条 SKU mapping；是否有 GLB 由 registry status 决定）。
- [x] RV-P1-202 为每个 exact SKU 判断是否使用 family asset。
- [x] RV-P1-203 为每个 exact SKU 判断是否使用 vendor generic。
- [x] RV-P1-204 为每个 exact SKU 判断是否使用 global generic。
- [x] RV-P1-205 创建 assets/catalog/model_mapping.yaml。
- [x] RV-P1-206 每条映射记录匹配原因和数据置信度。
- [x] RV-P1-207 映射不能改变 CMDB 的设备身份。

### 6.2 物理特征聚类

- [~] RV-P1-211 按 chassis height 聚类（目录已按高度/未知状态分组，逐型号外形聚类待研究证据）。
- [~] RV-P1-212 按 chassis depth 聚类（已保留 depth_class；官方深度缺失项仍待核）。
- [~] RV-P1-213 按 front panel layout 聚类（当前以 family/catalog_key 作为可审查映射，详细面板证据待补）。
- [x] RV-P1-214 按端口数量和类型聚类（已解析可见端口数/介质；缺失值不猜测）。
- [~] RV-P1-215 按 PSU/fan layout 聚类（字段已预留，源资料不足的型号待补）。
- [~] RV-P1-216 按 front/rear orientation 聚类（安装面由 placement 单独表达，产品级 orientation 证据待补）。
- [x] RV-P1-217 只有可见外形有实质差异时才创建新 GLB（当前采用 family/vendor/global fallback，未按 SKU 批量建模）。

### 6.3 模型数量目标

- [ ] RV-P1-221 网络 exact/family GLB 目标约 25–35 个。
- [ ] RV-P1-222 机柜和配套 GLB 目标约 20–25 个。
- [ ] RV-P1-223 连接器和光模块 prefab 目标约 10–15 个。
- [ ] RV-P1-224 总可复用基础资产目标约 55–75 个。
- [ ] RV-P1-225 将模型数量视为目标而不是硬上限。

## 七、P0/P1：底层数据模型、迁移和历史数据

前置：RV-P0-006、RV-P0-015、RV-P1-001。  
目标：建立可靠的机柜安装关系和可审计的历史数据迁移。

### 7.1 权威来源

- [x] RV-P1-301 明确 physical_assets 负责资产身份、序列号、管理地址、生命周期和凭据关系。
- [x] RV-P1-302 明确 device_types 负责厂商/型号模板。
- [x] RV-P1-303 将 rack_devices 演进为机柜安装位置权威来源。
- [x] RV-P1-304 将 physical_assets.rack、rack_unit、planned_start_u 降级为兼容投影。
- [x] RV-P1-305 将机柜容量和功率利用率改为派生数据。
- [x] RV-P1-306 不在第一阶段引入平行的 rack_placements 主表，避免重复写入；未来有多安装关系需求时再拆分。

### 7.2 racks 和 rack_types

- [ ] RV-P1-311 统一 site_id、rack_code、name 和 rack_type_id 的关系。
- [x] RV-P1-312 增加 layout_revision。
- [x] RV-P1-313 增加 mount_policy：front_only 或 front_rear。
- [ ] RV-P1-314 统一 total_u、width_mm、depth_mm、max_weight_kg。
- [x] RV-P1-315 以 power_capacity_watts 为唯一权威功率字段。
- [x] RV-P1-316 保留 power_capacity_w 作为兼容别名，不再作为新写入字段。
- [x] RV-P1-317 used_u、available_u、current_power_w、power_utilization 不再作为普通接口可写字段。
- [ ] RV-P1-318 rack_type_id 处理孤儿后增加真实外键。
- [x] RV-P1-319 机柜类型更新不自动修改现有机柜。
- [ ] RV-P1-320 提供显式的机柜类型预览和应用流程。

### 7.3 device_types

- [x] RV-P1-331 增加 depth_class：full、half、unknown。
- [x] RV-P1-332 增加 width_mm、depth_mm、height_mm、weight_kg。
- [x] RV-P1-333 增加 dimension_status：confirmed、estimated、unknown、pending_verification。
- [x] RV-P1-334 增加 default_mount_kind：u_mount、zero_u、side_mount、unknown。
- [x] RV-P1-335 增加 model_family 和 catalog_key。
- [x] RV-P1-336 保留 is_full_depth 作为兼容字段。
- [x] RV-P1-337 保留 u_height 作为兼容字段，但未知值不能回退到 1（前端只使用边界渲染占位，不对外宣称为 1U）。
- [x] RV-P1-338 区分设备类型模板和单台资产实际尺寸。

### 7.4 rack_devices

- [x] RV-P1-341 增加 mount_kind。
- [x] RV-P1-342 扩展 position 为 front、rear、full_depth、left_side、right_side、unknown。
- [x] RV-P1-343 允许 zero_u、side_mount、unknown 的 start_u 为空。
- [x] RV-P1-344 增加实例 height_u。
- [x] RV-P1-345 增加 placement_status：confirmed、estimated、unknown、invalid。
- [x] RV-P1-346 增加 placement_source。
- [x] RV-P1-347 增加 dimension_status。
- [x] RV-P1-348 增加 location_note。
- [x] RV-P1-349 增加 model_key，为后续 GLB registry 预留。
- [x] RV-P1-350 同一非空 asset_id 最多对应一个有效安装关系。
- [x] RV-P1-351 为 rack_id、position、start_u、asset_id、device_type_id 增加实际查询索引。
- [x] RV-P1-352 PostgreSQL 修改约束时使用事务化 DDL。
- [~] RV-P1-353 如果保留现有本地兼容路径，安全处理 start_u 非空约束变更，保留原 ID、外键、索引和时间字段（PostgreSQL 已完成；旧 SQLite 表重建仍待专项验证）。

### 7.5 physical_assets

- [x] RV-P1-361 增加 rack_id 投影字段。
- [x] RV-P1-362 增加 rack_position 投影字段。
- [x] RV-P1-363 增加 rack_mount_kind 投影字段。
- [x] RV-P1-364 增加 rack_location_status 投影字段。
- [x] RV-P1-365 新接口不直接写旧的 rack、rack_unit、planned_start_u 文本位置。
- [x] RV-P1-366 所有位置变化在同一事务内回写投影。

### 7.6 数据质量问题表

- [x] RV-P1-371 创建 rack_data_quality_issues。
- [x] RV-P1-372 增加 entity_type、entity_id、issue_code、severity、details_json。
- [x] RV-P1-373 增加 status、detected_at、resolved_at、resolved_by、resolution_note。
- [x] RV-P1-374 为实体、问题类型和状态建立索引。
- [x] RV-P1-375 定义 RACK_NOT_FOUND、RACK_NOT_UNIQUE、DEVICE_TYPE_NOT_FOUND、ASSET_NOT_FOUND。
- [x] RV-P1-376 定义 DUPLICATE_ASSET_INSTALLATION、INVALID_POSITION、U_OVERFLOW、U_CONFLICT。
- [x] RV-P1-377 定义 LEGACY_LOCATION_CONFLICT、UNKNOWN_HEIGHT、UNKNOWN_MOUNT、POWER_FIELD_CONFLICT。

### 7.7 迁移和 fresh schema

- [x] RV-P1-381 新增编号迁移模块，不继续堆积单体初始化逻辑。
- [x] RV-P1-382 迁移可重复执行，失败后可重试。
- [x] RV-P1-383 fresh schema 直接创建目标字段。
- [x] RV-P1-384 upgrade schema 通过迁移达到同样结构。
- [ ] RV-P1-385 迁移前处理 rack_type 孤儿、asset 重复和位置脏数据。
- [x] RV-P1-386 建立非空 asset_id 的唯一约束或部分唯一索引。
- [x] RV-P1-387 功率字段迁移前生成冲突报告（m0213 升级时保留原值和冲突明细）。
- [x] RV-P1-388 watts 非零时优先使用 power_capacity_watts；否则使用旧 power_capacity_w。
- [x] RV-P1-389 功率冲突记录到 rack_data_quality_issues。

涉及基线：

- backend/database/schema.py
- backend/database/migrations/
- backend/schemas/schemas.py

## 八、P1：历史数据回填和冲突隔离

前置：第七阶段迁移完成。  
目标：转换旧数据，但不把不确定数据伪装成确定数据。

- [x] RV-P1-401 实现 rack-data-backfill --dry-run。
- [x] RV-P1-402 实现 rack-data-backfill --apply。
- [x] RV-P1-403 实现 rack-data-backfill --report。
- [x] RV-P1-404 dry-run 不写入业务表。
- [x] RV-P1-405 有效 rack_devices 保留为 legacy_rack_device 来源。
- [x] RV-P1-406 仅在机柜文本位置唯一匹配时回填 rack_id。
- [x] RV-P1-407 仅在 planned_start_u 合法时回填 start_u。
- [x] RV-P1-408 名称匹配多个机柜时进入待复核，不自动选择。
- [x] RV-P1-409 非数字 rack_unit 保留为 location_note。
- [x] RV-P1-410 physical_assets 和 rack_devices 位置冲突进入问题表。
- [x] RV-P1-411 同一资产多个 rack_devices 进入问题表。
- [x] RV-P1-412 U 位越界、重叠、缺少 device_type 进入问题表。
- [x] RV-P1-413 待核尺寸标记 pending_verification 或 unknown。
- [x] RV-P1-414 0U PDU 标记 zero_u/side_mount。
- [x] RV-P1-415 无法判断安装面的位置标记 unknown。
- [x] RV-P1-416 以 rack_devices 为权威回写 physical_assets 投影。
- [x] RV-P1-417 无有效安装关系的资产标记 unplaced 或 unknown。
- [x] RV-P1-418 输出 confirmed、estimated、unknown、invalid 数量。
- [x] RV-P1-419 输出 U 越界、U 冲突、重复资产、孤儿类型和功率冲突数量。
- [ ] RV-P1-420 回填前完成备份并保存校验值。
- [ ] RV-P1-421 apply 必须经过 dry-run 报告评审。

回填完成标准：

- [ ] 每条历史记录都有 confirmed、estimated、unknown 或 invalid 状态。
- [ ] 回填不删除原始资产或安装关系。
- [ ] 所有歧义数据可定位到 entity_id。
- [ ] 回填后机柜、资产和安装关系数量可以对账。

## 九、P0/P1：统一机柜领域服务、安装规则和事务

前置：第七、八阶段。  
目标：所有安装、移动、卸载、资产绑定和导入统一走一套规则。

### 9.1 RackPlacementService

- [x] RV-P1-501 建立 RackPlacementService。
- [x] RV-P1-502 提供 install、move、update、uninstall、validate、sync_asset_projection。
- [~] RV-P1-503 资产 API、机柜 API、导入脚本统一调用该 service（资产/机柜同步与批量导入已接入 canonical placement；安装/移动/卸载及跨资产失败回滚的全量收口仍待完成）。
- [x] RV-P1-504 service 不复制多套 U 位和资产唯一性规则。

### 9.2 安装位置规则

- [x] RV-P1-511 U 型设备要求 mount_kind=u_mount。
- [x] RV-P1-512 U 型设备要求 start_u 大于或等于 1。
- [x] RV-P1-513 U 型设备要求有效 height_u。
- [x] RV-P1-514 end_u 不得超过 total_u。
- [x] RV-P1-515 front 与 front/full_depth 冲突。
- [x] RV-P1-516 rear 与 rear/full_depth 冲突。
- [x] RV-P1-517 full_depth 同时占用 front 和 rear。
- [x] RV-P1-518 zero_u 和 side_mount 不参与标准 U 位占用。
- [x] RV-P1-519 zero_u 和 side_mount 必须有侧面/后面位置或明确备注。
- [x] RV-P1-520 unknown 不参加正常容量计算，但必须返回读模型。
- [x] RV-P1-521 rack mount_policy 在 service 层真正生效。
- [x] RV-P1-522 validate-placement 与实际写入复用同一规则函数。

### 9.3 事务和锁

- [~] RV-P1-531 API/业务用例层负责事务边界（canonical service 支持 commit=false；全链路用例仍待收口）。
- [x] RV-P1-532 service 在嵌套业务流程中不得自行 commit（提供 commit=false 路径）。
- [~] RV-P1-533 资产创建、rack_devices 创建、Web Profile、审计和投影在同一事务内完成（核心资产创建/更新/导入路径已并入；接管后台任务和全量 Web Profile/凭据链路仍需继续盘点）。
- [~] RV-P1-534 任一步失败时整体回滚（canonical placement 和 `atomic=true` 批量导入已覆盖；跨资产后台接管用例仍待补）。
- [x] RV-P1-535 PostgreSQL 使用机柜行锁和资产行锁。
- [x] RV-P1-536 对没有 physical_assets 行的旧 asset_id 也提供稳定并发保护（使用事务级 advisory lock）。
- [x] RV-P1-537 使用数据库唯一约束作为资产重复安装的最终保护。

### 9.4 安装、移动、卸载

- [x] RV-P1-541 安装时同时创建 rack_devices 和 physical_assets 投影。
- [x] RV-P1-542 移动时同时更新 rack_id、position、start_u、height_u 和投影。
- [x] RV-P1-543 asset_id 从 A 改为 B 时同时处理旧资产和新资产。
- [x] RV-P1-544 卸载时清理物理资产位置投影，或返回明确 409。
- [x] RV-P1-545 rack_id 变化不能只更新 planned_start_u。
- [x] RV-P1-546 资产删除时先通过 canonical placement 显式卸载并清理投影，再删除资产。

### 9.5 类型和机柜变化

- [x] RV-P1-551 修改 total_u 前检查所有已有设备。
- [~] RV-P1-552 修改宽度、深度和 mount_policy 前已有字段/版本保护，安装关系影响检查仍需扩大。
- [x] RV-P1-553 修改设备类型高度、深度和尺寸前检查所有引用关系中的继承高度。
- [x] RV-P1-554 发生影响时返回 409 和受影响设备列表。
- [x] RV-P1-555 资产更新不能隐式覆盖共享 device_type 模板。
- [x] RV-P1-556 区分请求未传字段和显式传入默认值。
- [ ] RV-P1-557 rack_type_id 存在时，未显式提供的字段才从模板继承。
- [ ] RV-P1-558 rack_type 更新不自动修改既有机柜。

### 9.6 批量导入

- [x] RV-P1-561 支持 `atomic=true` 的全量回滚模式（资产批量接口已提供整批回滚）。
- [x] RV-P1-562 支持逐行结果模式（`detailed=true` 返回 created/skipped/failed 逐行结果）。
- [~] RV-P1-563 返回资产创建、机柜绑定和数据质量三种状态（创建/绑定/失败状态已返回；独立数据质量状态和质量问题汇总仍待补）。
- [x] RV-P1-564 同步失败不能只写日志后报告整行成功。
- [~] RV-P1-565 记录导入批次、操作者、文件摘要和每行错误（batch_id、操作者、request_id 和逐行错误已接入；文件摘要持久化仍待补）。

涉及基线：

- backend/services/rack_service.py
- backend/api/assets.py
- backend/api/racks.py
- backend/schemas/schemas.py

## 十、P1：API 版本、布局读模型和兼容层

前置：第九阶段。  
目标：给当前 2D、未来 3D、统计、导出和健康联动提供稳定接口。

### 10.1 布局接口

- [x] RV-P1-601 保留 GET /api/racks/{rack_id}/layout。
- [x] RV-P1-602 返回 rack、placements、occupancy、data_quality 和 meta。
- [x] RV-P1-603 placements 同时包含正常、unknown 和 invalid 记录。
- [x] RV-P1-604 返回 rack_id、asset_id、device_type_id、mount_kind、position、start_u、height_u。
- [x] RV-P1-605 返回 placement_status、dimension_status、placement_source。
- [x] RV-P1-606 返回 asset_id、network_device_id、serial_number、hostname。
- [x] RV-P1-607 为 model_key、match_level、fallback_reason、version 留出字段。

### 10.2 安装关系 API

- [x] RV-P1-611 增加 POST /api/racks/{rack_id}/placements。
- [x] RV-P1-612 增加 PATCH /api/rack-placements/{placement_id}。
- [x] RV-P1-613 增加 DELETE /api/rack-placements/{placement_id}。
- [x] RV-P1-614 增加 POST /api/racks/{rack_id}/validate-placement。
- [x] RV-P1-615 现有 /api/rack-devices 路由作为兼容别名。
- [x] RV-P1-616 兼容别名必须调用新 service。
- [x] RV-P1-617 validate-placement 和写入接口共享同一业务规则（validate-u 作为兼容入口保留）。

### 10.3 资产、健康和拓扑 API

- [x] RV-P1-621 资产新写入使用 placement 对象（创建、更新和批量导入均调用 canonical placement service；批量导入支持 atomic/detailed 失败策略）。
- [x] RV-P1-622 旧 rack、rack_unit、planned_start_u 仅做兼容转换。
- [x] RV-P1-623 机柜 code/id 已优先使用，历史名称兼容查找的不唯一返回 `RACK_NOT_UNIQUE`（409）。
- [x] RV-P1-624 资产列表/详情从 rack_devices 生成稳定 canonical placement DTO；未安装资产返回 null，同时保留旧位置字段兼容。
- [x] RV-P1-625 健康 overview 统一返回 success/data/message/meta。
- [~] RV-P1-626 topology links 支持 rack_id、site_id 和 limit/truncated；完整分页/游标仍待收口。
- [ ] RV-P1-627 未绑定通用机柜项不强行制造拓扑关系。

### 10.4 状态码和错误码

- [x] RV-P1-631 RACK_NOT_FOUND。
- [x] RV-P1-632 RACK_NOT_UNIQUE。
- [x] RV-P1-633 ASSET_NOT_FOUND（canonical placement 对非空 asset_id 强制校验物理资产存在）。
- [x] RV-P1-634 ASSET_ALREADY_INSTALLED。
- [x] RV-P1-635 RACK_U_OVERFLOW。
- [x] RV-P1-636 RACK_U_CONFLICT。
- [x] RV-P1-637 POSITION_NOT_ALLOWED。
- [x] RV-P1-638 FULL_DEPTH_CONFLICT。
- [x] RV-P1-639 ZERO_U_POSITION_REQUIRED。
- [x] RV-P1-640 DEVICE_TYPE_IN_USE。
- [x] RV-P1-641 RACK_RESIZE_CONFLICT。
- [ ] RV-P1-642 DATA_QUALITY_REVIEW_REQUIRED。
- [ ] RV-P1-643 EXTERNAL_CONNECTIVITY_FAILED。
- [x] RV-P1-644 无效 rack_id 的 devices 接口返回 404，而不是 200 空数组。

## 十一、P1：缓存、版本和跨 worker 一致性

前置：第十阶段。  
目标：写入后所有 worker 都能快速识别布局变化。

- [x] RV-P1-701 每个 racks 维护 layout_revision。
- [x] RV-P1-702 安装、移动、卸载、资产绑定和影响布局的类型变更递增 revision。
- [x] RV-P1-703 revision 更新和业务写入处于同一事务。
- [x] RV-P1-704 layout 缓存 key 包含 rack_id、layout_revision 和授权范围。
- [ ] RV-P1-705 summary 缓存 key 包含筛选条件、全局 revision 和授权范围。
- [ ] RV-P1-706 不缓存含凭据或敏感资产明细的响应。
- [~] RV-P1-707 所有机柜写接口提交后失效 rack_page（主要 racks/rack-devices 写入口已接入；类型/资产兼容路径仍待全量盘点）。
- [~] RV-P1-708 资产同步导致 rack_devices 变化时由 canonical 写入递增 revision；资产全链路缓存失效仍待统一。
- [ ] RV-P1-709 批量导入后失效列表、摘要、统计和受影响机柜。
- [ ] RV-P1-710 topology 变化后失效拓扑缓存。
- [!] RV-P1-711 评估 Redis 或其他共享缓存（需结合真实部署拓扑和运维配置决定）。
- [x] RV-P1-712 明确进程内 TTL 缓存不能作为多 worker 一致性机制。

## 十二、P1：前端 2D 兼容切换

前置：第十、十一阶段。  
目标：当前 /cmdb/racks 页面切换到 canonical placement，不在前端重新猜测数据。

- [x] RV-P1-801 RackElevation 和 RackScene 使用同一份 placements。
- [x] RV-P1-802 invalid/unknown 设备不从布局数组中删除。
- [x] RV-P1-803 后视图选择 U 位后保存为 rear。
- [x] RV-P1-804 删除选择资产后写死 position=front 的逻辑。
- [~] RV-P1-805 full_depth 在前后面视图中按同一占用规则表现（后端和读模型已统一，浏览器现场回归待补）。
- [x] RV-P1-806 支持无 asset_id 的通用机柜设备。
- [~] RV-P1-807 支持 PDU、配线架、理线架、托盘、空白面板和传感器（通用 mount_kind/device_type 已支持，逐类验收待补）。
- [x] RV-P1-808 支持 0U/side-mount 独立位置。
- [~] RV-P1-809 collapseEmpty=true 时设备仍可点击、选中、拖动和打开详情（空白折叠与设备保留逻辑已实现，浏览器回归待补）。
- [~] RV-P1-810 资产选择器排除安装在其他机柜的资产（前端过滤和后端唯一性保护已实现，跨机柜响应状态待统一）。
- [x] RV-P1-811 layout、health、asset search 增加请求取消或序列号保护。
- [x] RV-P1-812 缓存命中、取消请求和切换机柜时正确恢复 loading 状态。
- [ ] RV-P1-813 导出明确区分当前页和全部筛选结果。
- [ ] RV-P1-814 修复英文导入模板列数和示例值错位。
- [x] RV-P1-815 非法数字、0、空值和待核值不能静默替换成默认值（未知标准 U 仅保留渲染边界占位，并在 UI 标注待确认）。
- [x] RV-P1-816 严格解析 0、1、"0"、"1"、true、false。

## 十三、P1：3D 资产规范

前置：目录归一化、模型聚类和底层布局契约完成。  
输出：docs/rackvision/NEXORA_3D_ASSET_SPEC_V1.md。

### 13.1 单位和坐标

- [x] RV-P1-901 使用 Metric。
- [x] RV-P1-902 Blender unit = meter。
- [x] RV-P1-903 统一 1U = 0.04445 m。
- [x] RV-P1-904 明确 X=left/right。
- [x] RV-P1-905 明确 Y=front/back。
- [x] RV-P1-906 明确 Z=vertical。
- [x] RV-P1-907 明确正面方向和导出朝向。
- [x] RV-P1-908 定义设备 origin：X 为机箱中心，Y 为插入参考面，Z 为设备底部。
- [~] RV-P1-909 定义机柜 origin（设备坐标和前端转换已固定；机柜级 origin 仍需结合真实 GLB/场景验收冻结）。
- [x] RV-P1-910 建立现有前端坐标到 Blender 坐标的显式转换层。

### 13.2 几何和命名

- [x] RV-P1-921 官方尺寸优先。
- [x] RV-P1-922 缺少尺寸时显示 unknown，不任意缩放。
- [x] RV-P1-923 定义 BODY、FRONT_PANEL、REAR_PANEL、LOGO_VENDOR、LCD_MAIN。
- [x] RV-P1-924 定义 LED_POWER、LED_SYSTEM、LED_ALARM。
- [x] RV-P1-925 定义 PSU_01、PSU_02、FAN_01、FAN_02。
- [x] RV-P1-926 端口按需要命名 PORT_GE_01、PORT_SFP_01、PORT_QSFP_01、PORT_MGMT_01、PORT_CONSOLE_01。
- [x] RV-P1-927 定义 MAT_CHASSIS、MAT_FRONT_PANEL、MAT_PORT、MAT_GLASS、MAT_LED、MAT_LABEL、MAT_LOGO。

### 13.3 纹理、面数和 LOD

- [ ] RV-P1-931 通用设备纹理控制在 512–1024 px。
- [ ] RV-P1-932 详细前面板纹理最高约 2048 px。
- [ ] RV-P1-933 避免 4K/8K 纹理用于普通机柜视图。
- [ ] RV-P1-934 通用 1U 设备控制在约 10k triangles 内。
- [ ] RV-P1-935 family model 控制在约 30k triangles 内。
- [ ] RV-P1-936 重点精细模型控制在约 50k triangles 内。
- [ ] RV-P1-937 不逐个建模通风孔。
- [ ] RV-P1-938 定义 LOD0 bounding/generic block。
- [ ] RV-P1-939 定义 LOD1 simplified rack view。
- [ ] RV-P1-940 定义 LOD2 normal product view。
- [ ] RV-P1-941 定义可选 LOD3 close-up。

### 13.4 导出

- [x] RV-P1-951 运行时格式统一为 GLB。
- [x] RV-P1-952 源文件格式保留为 BLEND。
- [!] RV-P1-953 所有模型通过 GLB validation（首批 5 个 GLB 已通过结构和场景校验，其中 4 个 Generic 已登记为 `approved/glb` 并进入生产静态目录；registry 其余模型仍需分批构建和人工验收）。
- [~] RV-P1-954 记录模型版本、来源和变更说明（首批 5 个模型已有输入 spec、BLEND、build/public GLB、SHA-256 和 registry 路径；全量 manifest/变更记录仍待补齐）。

## 十四、P1：资产目录、仓库结构和 Blender 主模板

前置：第十三阶段。  
目标：建立可批量生产和审查的离线资产工作区。

### 14.1 目录结构

- [x] RV-P1-1001 创建或适配 assets/catalog。
- [x] RV-P1-1002 创建或适配 assets/source/blender。
- [x] RV-P1-1003 创建或适配 assets/source/textures。
- [x] RV-P1-1004 创建或适配 assets/source/references。
- [x] RV-P1-1005 创建或适配 assets/build/glb。
- [x] RV-P1-1006 创建或适配 assets/thumbnails。
- [x] RV-P1-1007 将运行时文件发布到当前项目真实的 public/assets/3d 位置。
- [x] RV-P1-1008 创建 tools/blender。
- [x] RV-P1-1009 创建 docs/rackvision。
- [ ] RV-P1-1010 避免复制多份大型二进制资产。

### 14.2 机柜模板

- [ ] RV-P1-1021 42U enclosed rack。
- [ ] RV-P1-1022 47U enclosed rack。
- [ ] RV-P1-1023 可选 open-frame rack。
- [ ] RV-P1-1024 front/rear rails。
- [ ] RV-P1-1025 U markers。
- [ ] RV-P1-1026 必要的 side panels。
- [ ] RV-P1-1027 可选 front/rear doors。
- [ ] RV-P1-1028 450mm 墙挂式或非标准机柜模板。

### 14.3 通用网络设备

- [x] RV-P1-1031 1U 24-port copper switch（生产展示基线 GLB 已生成、校验并登记为 `approved/glb`）。
- [x] RV-P1-1032 1U 48-port copper switch（生产展示基线 GLB 已生成、校验并登记为 `approved/glb`）。
- [x] RV-P1-1033 1U SFP/SFP+ switch（生产展示基线 GLB 已生成、校验并登记为 `approved/glb`）。
- [x] RV-P1-1034 1U high-speed data-center switch（生产展示基线 GLB 已生成、校验并登记为 `approved/glb`）。
- [ ] RV-P1-1035 2U modular switch/router。
- [ ] RV-P1-1036 generic 1U firewall。
- [ ] RV-P1-1037 generic 2U firewall。

### 14.4 服务器和存储

- [ ] RV-P1-1041 1U server。
- [ ] RV-P1-1042 2U server。
- [ ] RV-P1-1043 4U server/storage chassis。

### 14.5 电源设备

- [ ] RV-P1-1051 1U UPS。
- [ ] RV-P1-1052 2U UPS。
- [ ] RV-P1-1053 2U battery pack。
- [ ] RV-P1-1054 0U vertical PDU。
- [ ] RV-P1-1055 1U horizontal PDU。
- [ ] RV-P1-1056 smart PDU variant。
- [ ] RV-P1-1057 ATS/STS generic variant。

### 14.6 配线和支撑设备

- [ ] RV-P1-1061 24-port RJ45 patch panel。
- [ ] RV-P1-1062 48-port RJ45 patch panel。
- [ ] RV-P1-1063 LC fiber panel。
- [ ] RV-P1-1064 MPO panel。
- [ ] RV-P1-1065 1U cable manager。
- [ ] RV-P1-1066 vertical cable manager。
- [ ] RV-P1-1067 brush panel。
- [ ] RV-P1-1068 1U blank。
- [ ] RV-P1-1069 2U blank。

## 十五、P1：Blender Python 自动化

前置：主模板和资产规范完成。  
目标：批量模型生成、导出、校验和缩略图不依赖逐个手工操作。

### 15.1 工具

- [x] RV-P1-1101 创建 tools/blender/generate_device.py。
- [x] RV-P1-1102 创建 tools/blender/export_glb.py。
- [x] RV-P1-1103 创建 tools/blender/validate_scene.py。
- [x] RV-P1-1104 创建 tools/blender/render_thumbnail.py。
- [x] RV-P1-1105 创建 tools/blender/batch_build.py。

### 15.2 生成能力

- [ ] RV-P1-1111 输入使用 YAML 或 JSON。
- [ ] RV-P1-1112 创建或重置场景。
- [ ] RV-P1-1113 设置 metric units。
- [ ] RV-P1-1114 构造基础 chassis。
- [ ] RV-P1-1115 赋予宽度、深度、高度。
- [ ] RV-P1-1116 生成 front panel。
- [ ] RV-P1-1117 放置标准端口块。
- [ ] RV-P1-1118 生成 PSU/fan placeholders。
- [ ] RV-P1-1119 添加标准对象名。
- [ ] RV-P1-1120 添加基础材质。
- [ ] RV-P1-1121 绑定批准的纹理。
- [ ] RV-P1-1122 设置 origin。
- [ ] RV-P1-1123 应用 transforms。
- [ ] RV-P1-1124 导出 GLB。
- [ ] RV-P1-1125 生成缩略图。
- [ ] RV-P1-1126 报告校验错误并返回非零状态。

### 15.3 Headless build

- [ ] RV-P1-1131 支持 Blender background/headless 模式。
- [ ] RV-P1-1132 支持单模型构建。
- [ ] RV-P1-1133 支持批量构建。
- [ ] RV-P1-1134 支持失败模型单独重试。
- [ ] RV-P1-1135 构建输出包含 GLB、缩略图、元数据和日志。

## 十六、P1：GLB 元数据、Registry 和 Resolver

前置：目录规范、模型映射和 Blender 导出流程完成。  
目标：任何设备都有可解释的模型结果，不返回无意义的 null。

### 16.1 Registry

- [x] RV-P1-1201 创建 assets/catalog/asset_registry.yaml 或等效数据库表。
- [x] RV-P1-1202 每个资产有唯一 asset_key。
- [x] RV-P1-1203 记录 vendor。
- [x] RV-P1-1204 记录 family。
- [x] RV-P1-1205 记录 exact_models。
- [x] RV-P1-1206 记录 device_type。
- [x] RV-P1-1207 记录 deployment_domain。
- [x] RV-P1-1208 记录 height_u、width_mm、depth_mm、height_mm。
- [x] RV-P1-1209 记录 front_orientation。
- [x] RV-P1-1210 记录 lod。
- [x] RV-P1-1211 记录 glb_path 和 thumbnail_path。
- [x] RV-P1-1212 记录 source_blend。
- [x] RV-P1-1213 记录 source_refs。
- [x] RV-P1-1214 记录 data_confidence。
- [x] RV-P1-1215 记录 version。
- [x] RV-P1-1216 记录 status：draft、review、approved、deprecated。
- [ ] RV-P1-1217 记录 geometry_status、dimension_status 和 QA 结果。

### 16.2 Resolver

- [x] RV-P1-1221 实现 exact model 匹配。
- [x] RV-P1-1222 实现 family 匹配。
- [x] RV-P1-1223 实现 vendor generic by form factor。
- [x] RV-P1-1224 实现 global generic by type/form factor。
- [x] RV-P1-1225 解析结果返回 match_level。
- [x] RV-P1-1226 解析结果返回 fallback_reason。
- [x] RV-P1-1227 解析结果返回 registry version。
- [x] RV-P1-1228 有合理通用模型时不得返回 null。
- [x] RV-P1-1229 无合理模型时返回可见 unknown asset。
- [ ] RV-P1-1230 记录 fallback level 和命中日志。
- [x] RV-P1-1231 Resolver 不改变 CMDB device identity。
- [x] RV-P1-1232 精确资产、产品族资产和通用资产都有单元测试。

解析示例：

    H3C S6850-56HF
      -> h3c_s6850_family.glb

    Unknown H3C 48-port 1U switch
      -> h3c_switch_1u_48p.glb

    Unknown vendor 48-port 1U switch
      -> generic_switch_1u_48p.glb

## 十七、P1：React 3D Viewer

前置：布局读模型、GLB registry、坐标规范完成。  
目标：只读显示一个机柜及其设备，不新增独立位置写入。

### 17.1 组件结构

- [x] RV-P1-1301 明确 Rack3DPage。
- [x] RV-P1-1302 明确 RackScene。
- [ ] RV-P1-1303 明确 Camera。
- [ ] RV-P1-1304 明确 Lighting。
- [ ] RV-P1-1305 明确 Environment。
- [ ] RV-P1-1306 明确 Controls。
- [x] RV-P1-1307 明确 RackModel。
- [x] RV-P1-1308 明确 RackDevice。
- [ ] RV-P1-1309 明确 DeviceModel。
- [ ] RV-P1-1310 明确 CableLayer。
- [ ] RV-P1-1311 明确 DeviceInfoPanel。

### 17.2 基础能力

- [x] RV-P1-1321 加载一个机柜 GLB 或当前 procedural rack fallback。
- [x] RV-P1-1322 从现有统一布局 API读取设备位置。
- [x] RV-P1-1323 调用 Resolver 选择模型。
- [x] RV-P1-1324 根据 start_u 放置设备。
- [x] RV-P1-1325 尊重 height_u。
- [x] RV-P1-1326 支持 front/rear/full_depth。
- [ ] RV-P1-1327 支持 orbit。
- [ ] RV-P1-1328 支持 zoom。
- [ ] RV-P1-1329 按需要支持 pan。
- [ ] RV-P1-1330 支持 hover highlight。
- [ ] RV-P1-1331 支持点击选择设备。
- [ ] RV-P1-1332 显示基本设备详情。
- [ ] RV-P1-1333 支持 focus selected device。
- [ ] RV-P1-1334 支持 reset camera。
- [x] RV-P1-1335 unknown/invalid 设备在 3D 中仍然可见。
- [ ] RV-P1-1336 模型加载失败时不影响其他设备。

### 17.3 首版明确不做

- [ ] RV-P1-1341 不做 3D drag-and-drop placement。
- [ ] RV-P1-1342 不做 3D U 位编辑。
- [ ] RV-P1-1343 不做重复的 3D save API。
- [ ] RV-P1-1344 不建独立 3D topology database。
- [ ] RV-P1-1345 不做物理碰撞编辑器。
- [ ] RV-P1-1346 不做物理仿真。

### 17.4 现有 3D Bug 修复

- [ ] RV-P1-1351 rear 设备拉出方向与坐标系一致，不能穿过机柜前面。
- [ ] RV-P1-1352 rear 线缆端点连接后侧面。
- [ ] RV-P1-1353 full_depth 设备的连接面和占用范围正确。
- [ ] RV-P1-1354 固定 19 英寸导轨不能套用到 450mm 墙挂柜。
- [x] RV-P1-1355 严格解析 is_full_depth 的 0、1、"0"、"1"。
- [x] RV-P1-1356 未知高度不能由前端静默改为 1U。
- [ ] RV-P1-1357 procedural fallback 不能把不同深度设备全部显示为同一深度。

## 十八、P1：2D/3D 同步和配套设备

前置：统一布局读模型和 Viewer 完成。  
目标：2D 是位置写入口，3D 是只读投影。

### 18.1 数据流

    2D Rack Editor
          ↓ save
    Rack Placement API / DB
          ↓ read
    3D Rack Viewer

- [x] RV-P1-1401 2D 保存后只写统一安装关系。
- [x] RV-P1-1402 3D 只读同一份 rack/device placement。
- [x] RV-P1-1403 不创建单独的 3D 位置表。
- [x] RV-P1-1404 使用 rack_id。
- [x] RV-P1-1405 使用 placement_id 或 rack_device_id。
- [x] RV-P1-1406 使用 asset_id。
- [x] RV-P1-1407 使用 device_model、device_type、start_u、height_u、orientation。
- [ ] RV-P1-1408 可选显示 vendor、serial、hostname、management_ip。

### 18.2 同步验收

- [ ] RV-P1-1411 打开 Rack A 的 2D 编辑器。
- [ ] RV-P1-1412 将设备从 U38 移动到 U30。
- [ ] RV-P1-1413 保存。
- [ ] RV-P1-1414 打开或刷新 3D。
- [ ] RV-P1-1415 设备显示在 U30。
- [ ] RV-P1-1416 不需要独立 3D 保存。
- [ ] RV-P1-1417 刷新后位置不丢失。

### 18.3 配套设备

- [ ] RV-P1-1421 支持 PDU。
- [ ] RV-P1-1422 支持 patch panel。
- [ ] RV-P1-1423 支持 ODF。
- [ ] RV-P1-1424 支持 cable manager。
- [ ] RV-P1-1425 支持 UPS。
- [ ] RV-P1-1426 支持 battery。
- [ ] RV-P1-1427 支持 server。
- [ ] RV-P1-1428 支持 storage。
- [ ] RV-P1-1429 支持 KVM。
- [ ] RV-P1-1430 支持 tray。
- [ ] RV-P1-1431 支持 blank panel。
- [x] RV-P1-1432 0U vertical PDU 使用侧面/后面位置，不消耗普通 U。
- [x] RV-P1-1433 没有 CMDB 资产的配套设备仍可作为 generic rack item。

## 十九、P2：线缆、端口和拓扑显示

前置：拓扑 API 有认证和稳定设备 ID；Viewer 已能渲染设备。  
目标：不为每条线缆制作 GLB，使用运行时曲线。

### 19.1 连接器 prefab

- [ ] RV-P2-1501 RJ45。
- [ ] RV-P2-1502 LC。
- [ ] RV-P2-1503 MPO。
- [ ] RV-P2-1504 SFP/SFP+/SFP28。
- [ ] RV-P2-1505 QSFP+/QSFP28/QSFP56/QSFP-DD/QSFP112。
- [ ] RV-P2-1506 OSFP。

### 19.2 运行时线缆

- [ ] RV-P2-1511 线缆输入使用 endpoint_a.position。
- [ ] RV-P2-1512 线缆输入使用 endpoint_b.position。
- [ ] RV-P2-1513 线缆输入包含 cable_type。
- [ ] RV-P2-1514 使用 Three.js curves 生成线缆主体。
- [ ] RV-P2-1515 支持 Cat6。
- [ ] RV-P2-1516 支持 Fiber LC。
- [ ] RV-P2-1517 支持 MPO。
- [ ] RV-P2-1518 支持 DAC。
- [ ] RV-P2-1519 支持 AOC。
- [ ] RV-P2-1520 支持 Power。
- [ ] RV-P2-1521 根据 front/rear 选择正确端点。
- [ ] RV-P2-1522 端口缺失时显示连接关系 fallback，而不是崩溃。
- [ ] RV-P2-1523 首版线缆显示可以作为可选功能，不阻塞基础机柜交付。

## 二十、P2：性能和大数据量

前置：基础 Viewer 可用。  
目标：单机柜可用，逐步支持多机柜场景。

- [ ] RV-P2-1601 只懒加载选中的机柜资产。
- [ ] RV-P2-1602 实现 GLTF/GLB 缓存。
- [ ] RV-P2-1603 复用共享材质。
- [ ] RV-P2-1604 对重复通用模型评估 instancing。
- [ ] RV-P2-1605 开启或验证 frustum culling。
- [ ] RV-P2-1606 使用 LOD。
- [ ] RV-P2-1607 评估 Draco/mesh compression。
- [ ] RV-P2-1608 按需要使用 KTX2。
- [ ] RV-P2-1609 降低纹理分辨率。
- [ ] RV-P2-1610 避免隐藏内部几何体。
- [ ] RV-P2-1611 基准测试 42U 机柜和 20–35 个安装对象。
- [ ] RV-P2-1612 基准测试典型工作站浏览器。
- [ ] RV-P2-1613 基准测试多机柜 LOD0/LOD1。
- [ ] RV-P2-1614 记录首次加载、切换机柜、旋转、缩放和内存指标。

## 二十一、P1/P2：QA、测试和质量门禁

前置：对应阶段代码完成。  
要求：后端和数据库持久化测试使用共享隔离 PostgreSQL fixture；不以 SQLite 行为作为 PostgreSQL 迁移正确性的证据。

### 21.1 后端和安全

- [x] RV-P1-1701 assets 未登录返回 401。
- [x] RV-P1-1702 health 未登录返回 401。
- [x] RV-P1-1703 topology 未登录返回 401。
- [x] RV-P1-1704 Viewer 写操作返回 403。
- [x] RV-P1-1705 跨 site/tenant 读取被拒绝。
- [x] RV-P1-1706 敏感字段不会出现在普通响应。
- [x] RV-P1-1707 连通性验证目标限制有效。
- [~] RV-P1-1708 Rack/placement 的 404、409、422 已覆盖；全模块 400、403、500、502 矩阵仍待补齐。
- [~] RV-P1-1709 请求 request_id 已进入统一日志/错误响应基础设施，资产审计事件关联仍待补齐。

### 21.2 迁移和数据

- [x] RV-P1-1711 PostgreSQL fresh schema 初始化。
- [~] RV-P1-1712 从上一版本升级（迁移为增量/幂等，真实上一版本数据库升级仍待窗口验证）。
- [x] RV-P1-1713 迁移重复执行。
- [~] RV-P1-1714 迁移失败后可以重试（模块设计支持重试，故障注入验收仍待补）。
- [x] RV-P1-1715 rack_devices 新字段、外键和索引存在。
- [x] RV-P1-1716 旧字段仍可兼容读取。
- [x] RV-P1-1717 dry-run 回填不修改业务表。
- [x] RV-P1-1718 apply 回填可生成报告。
- [x] RV-P1-1719 回填不删除原始数据。

### 21.3 业务约束

- [x] RV-P1-1721 front 与 front U 位冲突。
- [x] RV-P1-1722 rear 与 rear U 位冲突。
- [x] RV-P1-1723 front 与 rear 可以并存。
- [x] RV-P1-1724 full_depth 与 front 冲突。
- [x] RV-P1-1725 full_depth 与 rear 冲突。
- [x] RV-P1-1726 full_depth 与 full_depth 冲突。
- [x] RV-P1-1727 设备超出 total_u 被拒绝。
- [x] RV-P1-1728 0U 不占标准 U。
- [x] RV-P1-1729 0U 没有侧面位置时被拒绝。
- [x] RV-P1-1730 unknown 不被转换成 1U。
- [x] RV-P1-1731 同一资产不能安装两次。
- [x] RV-P1-1732 机柜缩容前发现越界设备。
- [x] RV-P1-1733 修改设备类型高度前发现受影响设备。

### 21.4 事务和并发

- [ ] RV-P1-1741 资产创建后 Web Profile 失败时整体回滚。
- [ ] RV-P1-1742 资产创建后 rack_devices 同步失败时整体回滚。
- [ ] RV-P1-1743 移动设备时 rack_id、position、start_u 和资产投影同时提交。
- [ ] RV-P1-1744 并发安装同一资产时一个成功、一个 409。
- [ ] RV-P1-1745 并发安装同一 U 位时不会产生两个有效冲突记录。
- [ ] RV-P1-1746 多 worker 能识别新 layout_revision。

### 21.5 API 契约和前端

- [x] RV-P1-1751 通过真实 HTTP 请求验证 success/data/message/meta。
- [x] RV-P1-1752 layout 同时返回正常、unknown 和 invalid 设备。
- [x] RV-P1-1753 health item 包含稳定资产/设备身份。
- [x] RV-P1-1754 批量导入逐行报告成功和失败（资产批量接口已提供 `atomic=true` 全量回滚和 `detailed=true` 逐行结果；独立数据质量状态与文件摘要持久化另列待办）。
- [x] RV-P1-1755 后视图安装保存为 rear。
- [~] RV-P1-1756 full_depth 前后面显示和占用一致（后端/适配器已测，浏览器现场回归待补）。
- [~] RV-P1-1757 0U PDU 可以安装、显示和编辑（通用能力和接口已测，浏览器现场回归待补）。
- [~] RV-P1-1758 折叠空位后设备仍可点击和移动（请求/适配器已测，浏览器现场回归待补）。
- [x] RV-P1-1759 快速切换机柜不会发生旧响应覆盖。
- [ ] RV-P1-1760 导出全部筛选结果时不丢分页。

### 21.6 Resolver 和 Blender

- [x] RV-P1-1771 exact match test。
- [x] RV-P1-1772 family fallback test。
- [x] RV-P1-1773 vendor fallback test。
- [x] RV-P1-1774 global generic fallback test。
- [x] RV-P1-1775 unknown type test。
- [x] RV-P1-1776 fallback rendering test。
- [x] RV-P1-1777 missing asset error boundary。
- [x] RV-P1-1778 validation script 对非法资产返回非零。
- [ ] RV-P1-1779 batch exporter 能处理多个资产。
- [ ] RV-P1-1780 输出 GLB 文件存在。
- [ ] RV-P1-1781 尺寸在容差范围内。
- [ ] RV-P1-1782 缩略图生成成功。

### 21.7 几何 QA

- [ ] RV-P1-1791 metric dimensions 有效。
- [ ] RV-P1-1792 U 高正确。
- [ ] RV-P1-1793 正面方向正确。
- [ ] RV-P1-1794 origin 正确。
- [ ] RV-P1-1795 transforms 已应用。
- [ ] RV-P1-1796 没有非预期 scale。
- [ ] RV-P1-1797 没有缺失纹理。
- [ ] RV-P1-1798 没有极端面数。
- [ ] RV-P1-1799 没有隐藏重复几何。
- [ ] RV-P1-1800 GLB 能正确导入。

### 21.8 元数据和 Viewer QA

- [x] RV-P1-1811 asset key 唯一。
- [x] RV-P1-1812 source references 存在。
- [x] RV-P1-1813 exact/family mapping 有效。
- [x] RV-P1-1814 status 有效。
- [x] RV-P1-1815 没有静默猜测尺寸。
- [x] RV-P1-1816 unknown model fallback 正常。
- [ ] RV-P1-1817 重复模型加载效率可接受。
- [ ] RV-P1-1818 U 计算正确。
- [ ] RV-P1-1819 1U、2U、4U 对齐。
- [ ] RV-P1-1820 点击选择识别正确设备。
- [ ] RV-P1-1821 2D 位置更新能出现在 3D。

## 二十二、P1：初始建模优先级

前置：资产规范、族聚类和 Registry 完成。  
原则：先做基础可复用模型，再做厂商族，最后做少量精确展示模型。

### 22.1 M0 Foundation

- [ ] RV-P1-1901 42U rack。
- [ ] RV-P1-1902 Generic 1U 24-port switch。
- [ ] RV-P1-1903 Generic 1U 48-port switch。
- [ ] RV-P1-1904 Generic 1U DC switch。
- [ ] RV-P1-1905 Generic server 1U。
- [ ] RV-P1-1906 Generic server 2U。
- [ ] RV-P1-1907 Generic UPS 2U。
- [ ] RV-P1-1908 0U PDU。
- [ ] RV-P1-1909 patch panel。
- [ ] RV-P1-1910 cable manager。

### 22.2 M1 Vendor families

- [ ] RV-P1-1921 H3C S5130 family。
- [ ] RV-P1-1922 H3C S6850 family。
- [ ] RV-P1-1923 Huawei S5700/S5755 family。
- [ ] RV-P1-1924 Huawei CloudEngine CE6800 family。
- [ ] RV-P1-1925 Ruijie S57xx/S61xx campus family。
- [ ] RV-P1-1926 Ruijie S69xx DC family。
- [ ] RV-P1-1927 ZTE 59xx campus family。
- [ ] RV-P1-1928 ZTE 5960/DC family。
- [ ] RV-P1-1929 Maipu NSS58xx campus family。
- [ ] RV-P1-1930 Maipu NSS59xx DC family。
- [ ] RV-P1-1931 DPtech LSW36xx campus family。
- [ ] RV-P1-1932 DPtech LSW66xx DC family。

### 22.3 M2 Power/rack ecosystem

- [ ] RV-P1-1941 KEBOS representative UPS。
- [ ] RV-P1-1942 KEBOS battery pack。
- [ ] RV-P1-1943 smart PDU。
- [ ] RV-P1-1944 LC ODF。
- [ ] RV-P1-1945 MPO panel。
- [ ] RV-P1-1946 KVM。
- [ ] RV-P1-1947 storage appliance。

### 22.4 M3 Exact showcase assets

- [ ] RV-P1-1951 仅为展示设备制作 exact high-detail 模型。
- [ ] RV-P1-1952 优先用户高频使用型号。
- [ ] RV-P1-1953 优先客户指定设备。
- [ ] RV-P1-1954 优先核心和数据中心设备。
- [ ] RV-P1-1955 优先 KEBOS 品牌设备。

## 二十三、P1/P2：部署、静态资源和发布

前置：Viewer、模型资源和测试完成。

- [x] RV-P1-2001 确认 GLB/GLTF/BIN/KTX2/Basis 的实际发布目录。
- [x] RV-P1-2002 Nginx 支持上述扩展名。
- [ ] RV-P1-2003 验证 MIME 类型。
- [ ] RV-P1-2004 验证缓存头。
- [ ] RV-P1-2005 验证 gzip/brotli 或等效压缩策略。
- [ ] RV-P1-2006 验证资源版本和 cache busting。
- [ ] RV-P1-2007 构建后检查所有 registry 引用文件存在。
- [ ] RV-P1-2008 资源 404 有可定位日志。
- [ ] RV-P1-2009 多 worker 下布局 revision 和缓存行为正确。
- [x] RV-P1-2010 前端生产 build 通过（本轮 `npm run lint`、目标测试和 `npm run build` 均通过）。
- [ ] RV-P1-2011 不在生产服务器运行 Blender。
- [ ] RV-P1-2012 记录 Ubuntu、Nginx、前端 dist 和模型资源的回滚步骤。
- [ ] RV-P1-2013 发布前保留数据库备份和回填报告。
- [ ] RV-P1-2014 发布顺序为后端兼容层、数据库迁移、回填、读模型、前端、3D 资源。
- [ ] RV-P1-2015 代码回滚时保留 additive schema，数据问题采用前向修复。

## 二十四、P1/P2：文档和运维交付

### 24.1 必须创建的文档

- [x] RV-P1-2101 docs/rackvision/architecture.md。
- [x] RV-P1-2102 docs/rackvision/current_architecture.md。
- [x] RV-P1-2103 docs/rackvision/NEXORA_3D_ASSET_SPEC_V1.md。
- [ ] RV-P1-2104 docs/rackvision/asset_research_method.md。
- [x] RV-P1-2105 docs/rackvision/blender_workflow.md。
- [x] RV-P1-2106 docs/rackvision/model_mapping.md。
- [x] RV-P1-2107 docs/rackvision/frontend_integration.md。
- [x] RV-P1-2108 docs/rackvision/2d_3d_sync.md。
- [ ] RV-P1-2109 docs/rackvision/performance.md。
- [x] RV-P1-2110 docs/rackvision/qa_checklist.md。
- [ ] RV-P1-2111 docs/rackvision/troubleshooting.md。
- [ ] RV-P1-2112 docs/rackvision/rack-data-contract.md。
- [ ] RV-P1-2113 docs/rackvision/rack-api-contract.md。
- [ ] RV-P1-2114 docs/rackvision/rack-data-quality-report.md。

### 24.2 AI/开发协作规则

- [ ] RV-P1-2121 开发前读取本文件和 AGENTS.md。
- [ ] RV-P1-2122 先检查现有实现再改代码。
- [ ] RV-P1-2123 保持小的、可审查的提交或补丁。
- [ ] RV-P1-2124 不发明官方产品尺寸。
- [ ] RV-P1-2125 不在没有族分析时批量生产精确模型。
- [ ] RV-P1-2126 保留来源 URL 和置信度。
- [ ] RV-P1-2127 优先使用 Blender Python 自动化。
- [ ] RV-P1-2128 早期 3D 保持只读。
- [ ] RV-P1-2129 复用现有 Nexora API 和数据结构。
- [ ] RV-P1-2130 每个有意义的改动运行相关测试。
- [ ] RV-P1-2131 完成任务后更新本清单状态。
- [ ] RV-P1-2132 记录偏离本清单的原因。

## 二十五、最终验收场景

### 25.1 业务流程

- [ ] RV-P1-2201 用户打开 Nexora 2D 机柜编辑器。
- [ ] RV-P1-2202 机柜中包含厂商交换机。
- [ ] RV-P1-2203 机柜中包含 family/generic 交换机。
- [ ] RV-P1-2204 机柜中包含服务器。
- [ ] RV-P1-2205 机柜中包含配线架。
- [ ] RV-P1-2206 机柜中包含 PDU。
- [ ] RV-P1-2207 机柜中包含 UPS。
- [ ] RV-P1-2208 用户将一个设备从 U38 改到 U30。
- [ ] RV-P1-2209 保存 2D。
- [ ] RV-P1-2210 打开 3D Viewer。
- [ ] RV-P1-2211 3D 显示正确机柜。
- [ ] RV-P1-2212 3D 显示正确设备位置。
- [ ] RV-P1-2213 3D 显示正确设备高度。
- [ ] RV-P1-2214 3D 使用最佳 exact/family/vendor/generic 模型。
- [ ] RV-P1-2215 未知模型仍然可见。
- [ ] RV-P1-2216 0U 设备仍然可见且不错误占用 U。
- [ ] RV-P1-2217 rear/full_depth 设备方向和占用正确。
- [ ] RV-P1-2218 不需要独立 3D placement save。
- [ ] RV-P1-2219 浏览器仍保持响应。

### 25.2 生产安全

- [ ] RV-P1-2221 生产服务器没有 Blender 进程。
- [ ] RV-P1-2222 未登录不能读取资产、健康和拓扑数据。
- [ ] RV-P1-2223 普通用户不能读取凭据。
- [ ] RV-P1-2224 跨 site/tenant 访问被拒绝。
- [ ] RV-P1-2225 资产、安装关系和投影不会出现部分提交。
- [ ] RV-P1-2226 迁移和回填有备份、报告和恢复方案。

## 二十六、阶段完成门禁

### Gate 0：现状和安全

- [~] RV-GATE-0-001 P0 认证问题关闭（认证、site/tenant、脱敏和探测边界代码已完成，资产审计和跨 worker 限流仍待关闭）。
- [~] RV-GATE-0-002 API 契约和异常格式稳定（health/layout/rack-assets 与 RackVision 错误映射已稳定，统一异常体系仍待补）。
- [~] RV-GATE-0-003 当前架构和数据质量报告完成（架构、质量接口和回填报告骨架已完成，真实库审计待执行）。

### Gate 1：数据底座

- [x] RV-GATE-1-001 数据迁移在 PostgreSQL 通过。
- [~] RV-GATE-1-002 回填 dry-run 和 apply 通过（dry-run/apply 工具已验证；真实库 apply 需备份、审批和窗口）。
- [~] RV-GATE-1-003 资产、机柜设备和投影事务一致（canonical placement 核心已通过；跨资产/Web Profile 事务仍待收口）。
- [x] RV-GATE-1-004 front/rear/full_depth/0U/unknown 规则有测试。

### Gate 2：统一读模型

- [x] RV-GATE-2-001 layout read model 已稳定（RackVision 回归覆盖布局契约）。
- [x] RV-GATE-2-002 2D 和 3D 使用同一份 placements。
- [~] RV-GATE-2-003 缓存 revision 和多 worker 行为通过（revision key 已验证，多 worker/共享缓存待线上验证）。
- [~] RV-GATE-2-004 前端关键交互回归通过（目标测试已通过，浏览器现场拖拽/3D GLB 仍待验收）。

### Gate 3：3D 资产

- [x] RV-GATE-3-001 资产规范完成。
- [x] RV-GATE-3-002 产品族映射完成（120 条 exact SKU 映射；首批 5 个生产展示基线 GLB 已生成，未覆盖的 SKU 仍按 fallback 规则处理）。
- [x] RV-GATE-3-003 Registry 和 Resolver 完成。
- [!] RV-GATE-3-004 M0 Foundation 模型通过 QA（5 个选定 GLB 已通过 Blender 场景/GLB 结构校验并完成本地浏览器 3D 冒烟；机柜模板、真实产品外观/端口证据和人工几何签署仍待完成）。
- [x] RV-GATE-3-005 不存在 null 模型结果或不可见 unknown 设备（无 GLB 时使用程序化 fallback/问题标记）。

### Gate 4：发布

- [~] RV-GATE-4-001 Blender 离线流水线通过（本机 Blender 5.2.1 已生成并校验 5 个选定 GLB，源 BLEND 与 build/public 文件保留；完整 M0 资产矩阵仍待构建）。
- [~] RV-GATE-4-002 GLB、静态资源和 Nginx 验证通过（5 个 GLB 已同步到 `public/assets/3d` 且与 build 产物 SHA-256 一致；本地浏览器 3D 正面/背面/45° 冒烟通过，线上 MIME/缓存、404 和真实部署仍待验证）。
- [~] RV-GATE-4-003 后端 RackVision focused pytest 通过（扩展 focused suite 61 passed，另有生命周期/MFA/控制表 35 passed、导入/安全/事务 23 passed、placement API 4 passed；上一轮完整 `backend/tests` 为 2304 passed/2 failed，其中批量导入失败已修复，剩余 1 个独立 IPAM 临时表兼容失败）。
- [x] RV-GATE-4-004 前端 `npm run lint` 和 `npm run build` 通过（本轮最终代码收口后已重跑）。
- [~] RV-GATE-4-005 生产发布、监控和回滚说明完成（发布路径已更新，线上发布说明和回滚演练待补）。
- [ ] RV-GATE-4-006 最终验收场景全部通过。

## 二十七、当前执行建议

当前已经完成第一轮中可在隔离环境落地的代码和目录任务，后续按以下顺序收口：

- [x] 已完成：认证基础门禁、canonical placement、迁移、数据质量接口、dry-run 回填、Excel 目录、registry/resolver、2D/3D 共享 read model。
- [~] 进行中：统一异常码、全量资产审计、跨资产事务收口、批量导入数据质量/文件摘要、拓扑稳定 asset_id、cursor 分页和 summary 缓存。
- [!] 外部条件：真实部署库备份/审批后执行 apply；剩余资产的 Blender 生成和人工验收；线上 MIME/缓存头、404、多 worker、性能和生产浏览器验收。
- [ ] 暂不启动：120 个 SKU 的大批量精确建模，直到 Gate 0–2 的阻断项和 GLB 生产条件满足。
