# 网络监控与站点拓扑整改执行记录

- 开始时间：2026-07-16（Asia/Shanghai）
- 执行分支：`codex/monitoring-topology-remediation`
- 基线提交：`6553161`
- 基线状态：从 `main` 创建分支时工作树干净；后续保留用户已有未跟踪文件。
- 当前范围：SNMP/LLDP 采集、监控状态、拓扑发现、站点分组、前端监控与拓扑页面。

## 一、目标与验收口径

1. 设备凭据统一从 Vault/凭据表解析，设备 API 不再返回 SNMP community 明文。
2. 采集结果必须能区分 `success`、`failed`、`not_configured`、`stale` 和 `unsupported`，并保留最近成功、失败连续次数、覆盖率和错误码。
3. LLDP/CDP 拓扑发现必须支持按全量、站点、设备范围运行；任务可查询进度、逐设备结果、取消和最终汇总。
4. 链路重建必须串行化；真实链路、未匹配邻居、推断链路和过期链路分别表达，禁止把空数据画成在线链路。
5. 拓扑以 `site_id` 为主键分组，站点筛选、站点卡片、链路 API 和画布使用同一套标识。
6. 监控页面要展示采集健康、数据新鲜度、趋势采样策略、SNMP 未配置提示和错误态；图表不得因容器尺寸为负数产生运行时告警。

## 二、已执行改造

### 1. 凭据与采集状态（已完成）

- `backend/services/vault_service.py`：统一解析 `snmp_community`，支持 Vault、凭据表和迁移期旧字段回退。
- `backend/api/devices.py`：设备响应脱敏；新增/更新时只把 SNMP community 写入加密凭据存储，设备表字段清空；SNMP 测试不回显 community。
- `backend/services/background_monitor_service.py`：采集前解析凭据，无 community 时标记 `not_configured`，记录 reachability、SNMP metrics、device info、interfaces 四类 collector 状态。
- `backend/services/collection_status_service.py`：提供采集状态 upsert、失败连续次数、覆盖率、最近成功时间、stale 动态计算和元数据脱敏。
- `backend/api/monitoring.py`：新增 `/api/monitoring/collection-status` 与设备级采集状态接口；网络趋势查询改为跨 SQLite/PostgreSQL 的统一 1 分钟查询并在应用层降采样。

### 2. 迁移与数据契约（已完成）

- `backend/database/migrations/m0010_monitoring_topology_hardening.py`：新增 `device_collection_status`；拓扑运行增加 `site_id`、scope、取消标记；观测增加来源站点、匹配方式、匹配状态、候选证据；链路增加来源/目标站点字段和索引。
- `backend/database/schema.py`：同步新鲜数据库建表和字段，避免“迁移后 schema 与 fresh install 不一致”。
- 迁移保留旧 community 数据的加密回填能力；如果依赖表或加密环境不可用则保留原值并让部署日志显式失败，不做静默丢弃。

### 3. 拓扑发现与站点模型（已完成）

- `backend/services/topology_service.py`：平台标准化覆盖 Cisco/Huawei/H3C/Ruijie；不再把未知平台静默当 Cisco；LLDP/CDP 目标匹配采用 IP、机箱序列号、系统名、前缀打分，近似并列时标记 ambiguous 并保存候选。
- 拓扑重建增加进程级锁；新链路默认 `unknown`，只有真实采集状态才能更新为在线/离线，避免虚假的绿色链路。
- 发现任务按设备逐个更新进度和结果，支持取消；批量任务只在设备采集结束后重建一次链路，定时任务采用并发采集、单次重建。
- `backend/api/topology.py`：新增范围参数、站点筛选、站点摘要和取消接口；链路接口支持 `site_id`、`include_stale`。
- `src/components/TopologyGraph.tsx`、`src/hooks/useTopologyVisibleDevices.ts`：站点分组改用 `site_id`，保留推断链路样式但不再根据空链路自动制造中心节点和虚假连接。

### 4. 前端监控与拓扑（已完成）

- `src/components/NetworkMonitoring.tsx`：增加采集健康、覆盖率、最近成功、失败次数、数据新鲜度和趋势错误态；轮询每 30 秒，趋势约每 60 秒刷新；保留上一次有效数据防止瞬时接口错误导致界面闪空。
- `src/pages/TopologyPage.tsx`、`src/hooks/useTopology.ts`、`src/contexts/TopologyContext.tsx`：增加站点卡片、站点筛选、后台发现进度、逐设备结果、取消操作和错误提示。
- `src/App.tsx`、`src/components/AppMainContent.tsx`：移除全局重复拉取拓扑链路，改由拓扑 hook 统一负责，避免请求竞态和状态覆盖。

## 三、剩余阶段执行结果

### P0：上线前门禁（代码与预发验证已完成）

- m0010/m0011 已加入迁移链；fresh PostgreSQL 启动已通过，旧安装路径由迁移补字段和索引。
- Cisco/Huawei/H3C 平台契约和 LLDP/CDP 命令 fixture 已通过；真实设备三站点采集仍需在目标设备网络可达、已登录环境执行。
- `not_configured`、失败连续次数、恢复归零、诊断缺 SNMP 凭据均由专项测试覆盖。
- 完整后端、前端 lint/build 已通过。

### P1：任务可靠性与证据（已完成）

- `m0011_topology_run_leases` 增加幂等键、租约 owner/expiry、心跳、最大重试、超时和设备级 attempt_count；任务 claim 使用条件更新，重复 worker 不会重复执行。
- discovery run 设备明细支持分页；新增证据接口按 run、状态、limit/offset 返回 LLDP/CDP 证据，原始 payload 有边界且仅认证访问。
- 后端统一应用 30 分钟链路 TTL，`include_stale=false` 和站点摘要使用同一有效状态计算。
- 原始趋势降采样已在上一阶段完成；时序聚合表作为大规模部署的后续容量优化项保留。

### P2：体验与运营增强（已完成）

- 拓扑画布现支持角色、链路状态、LLDP/CDP 协议、站点和设备状态筛选；站点卡片承担故障域入口。
- 监控详情新增 DNS/TCP/UDP 161/凭据配置诊断和“诊断采集链路”按钮；诊断不回显秘密。
- 新增迁移幂等、拓扑匹配、TTL、采集诊断和三厂商命令契约测试；浏览器业务页仍受目标地址和登录态限制。

### P3：工程治理（本轮已完成基础治理）

- 新增 `site_identity_service.py`，监控状态使用 canonical site name；拓扑和监控主键继续以 `site_id` 为准。
- 新增 `resolve_collector_credentials`，SSH/SNMP 采集方不再自行拼装凭据；当前 wire driver 明确为 SNMPv2c，未伪装支持 SNMPv3。
- 生产构建通过；主入口 bundle 仍大于 500 kB，属于后续独立的 code-splitting 优化，不阻断本次功能交付。

## 四、进度日志

- 2026-07-16：完成仓库基线核查，确认基线提交 `6553161`，创建分支 `codex/monitoring-topology-remediation`。
- 2026-07-16：完成凭据解析、设备响应脱敏、SNMP 测试和后台采集状态改造。
- 2026-07-16：完成 m0010 迁移与 fresh schema 同步，增加采集状态表和拓扑证据字段。
- 2026-07-16：完成拓扑平台标准化、目标匹配证据、串行重建、按站点 discovery scope、取消和批量单次重建。
- 2026-07-16：完成监控页面采集健康/新鲜度/趋势降采样，以及拓扑页面站点卡片/任务进度/取消交互。
- 2026-07-16：专项测试 8/8 通过；前端 lint 通过；生产构建通过。
- 2026-07-16：发现并修复 Playbook 平台解析的 Huawei 变体回归：保留 `huawei_vrpv8` 精确键，同时在无专用阶段时安全回退到 `huawei_vrp`。
- 2026-07-16：修复后完整后端测试 196 通过、25 个 subtests 通过。
- 2026-07-16：浏览器回归已启动本地前后端服务；目标 `192.168.42.1:5150` 在当前浏览器网络上下文拒绝连接，本地 `127.0.0.1:5150` 可打开登录页；未使用未授权凭据绕过登录，业务页回归需在已登录环境执行。
- 2026-07-16：本地 API 烟测通过：`/api/health/resources`、`/api/monitoring/collection-status`、`/api/topology/sites` 均返回 200，接口能返回采集状态和站点摘要。
- 2026-07-16：完成 m0011 任务租约、幂等、重试、证据分页和链路 TTL；修复 fresh PostgreSQL 初始化时索引早于字段的问题。
- 2026-07-16：完成采集链路诊断、拓扑链路状态/协议筛选和 collector credential/site identity 契约治理。
- 2026-07-16：全量回归最终为 200 passed、25 subtests passed；专项测试最终为 12 passed。
- 2026-07-16：清理拓扑服务遗留死代码，重新完成 compileall、主入口导入、专项测试和差异检查。
- 2026-07-16：现场浏览器回归：`192.168.42.1:5150` 已可达且 admin 会话有效；网络监控、站点拓扑、站点筛选、链路状态筛选和 LLDP/CDP 筛选可用。发现线上后端 OpenAPI 未包含诊断 POST 路由，诊断按钮返回 405；发现线上前端仍缓存旧 bundle，刷新发现仍报 `crypto.randomUUID is not a function`。源码已补充 UUID 降级生成并完成 lint/build，待服务加载最新前后端后复测。
- 2026-07-16：根据现场截图完成监控中心、网络监控、网络拓扑三页视觉整改：统一运维画布色板与间距、收敛高饱和告警色、强化状态左边条、降低卡片堆叠感；拓扑画布改为深色网络地图，分层带与链路状态使用高对比语义色，节点标签和缩放工具统一为地图控件风格。前端 `npm run lint` 与 `npm run build` 均通过，线上浏览器需重新加载最新 bundle 后复核最终视觉效果。
- 2026-07-16：根据二次现场反馈继续优化监控中心驾驶舱：增加 1720px 宽屏内容边界，状态卡改为按 P1/P2/P3/正常呈现语义底色与大字号指标，告警横幅改为深色事件带，健康分布增加健康率主指标，减少页面在宽屏下的信息摊薄。重启 Vite 后浏览器回归确认新结构已生效；`npm run lint` 与 `npm run build` 均通过。
- 2026-07-16：修复拓扑节点图标在 155% 缩放下的低清问题：移除 D3 SVG 内的外部 `<image>` 图标，改为在主 SVG 中直接绘制交换机、路由器和防火墙矢量图形，并为拓扑 SVG 增加几何精度渲染；拓扑 PNG 导出提升为至少 3x 像素比并启用缓存刷新。拓扑 DOM 回归确认无外部 image 节点、矢量 glyph 正常生成；lint/build 均通过。

## 五、验证结果

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| Python 语法/模块导入 | 通过 | `compileall backend`；`import main` 成功 |
| 专项后端测试 | 通过 | `12 passed` |
| 完整后端测试 | 通过 | `200 passed, 25 subtests passed` |
| TypeScript/lint | 通过 | `npm run lint` |
| 生产构建 | 通过（有告警） | `npm run build`；存在既有大 chunk >500 kB 提示 |
| 浏览器页面 | 受环境限制 | 本地登录页可达；目标 IP 当前 `ERR_CONNECTION_REFUSED`，业务页需登录态 |
| API 烟测 | 通过 | health、collection-status、topology/sites 均返回 200 |
| 敏感字段审计 | 通过（本模块） | 设备 API 响应清空 `snmp_community`，采集状态元数据过滤 secret 标记 |

## 六、交付状态

### 2026-07-16 拓扑拖拽体验补强

- 按网络管理平台常见的 camera/scene 交互模型拆分手势：空白区域负责平移，节点负责排布，滚轮负责缩放；节点手势不再被 SVG zoom 抢占。
- 节点拖拽使用当前 SVG 世界坐标，并保留鼠标抓取偏移，避免节点在按下瞬间跳动；拖拽中降低连线与端口标签干扰，使用 grab/grabbing 光标和操作提示。
- 仅在实际移动且拖拽结束后持久化布局，并抑制拖动结束产生的误点击，避免频繁写入和误打开设备详情。
- 已在本地拓扑页完成真实交互回归：节点拖动坐标发生变化，空白区平移改变 zoom transform，页面控制台无错误；测试布局已通过 RESET 恢复。

剩余代码阶段已全部完成并通过自动化质量门禁。发布前唯一未能在当前环境闭环的是三厂商/三站点真实设备采集：目标 `192.168.42.1:5150` 当前拒绝连接，且没有可用的已登录业务态；接入真实设备网络后按本文 P0 清单做只读验收即可。
- 2026-07-16：核对 PostgreSQL 设备角色来源：`devices.role` 与 `physical_assets.device_role` 当前三台设备均为 `switch`；`interfaces.switchport_mode` 为 `access` 仅表示接口二层模式，不是拓扑设备角色。资产管理弹窗已补充“拓扑角色”编辑项，后端已有同步逻辑；拓扑布局增加 `roleBuckets` 校验，避免旧坐标把设备错误留在 ACCESS 分层。交换机节点改为 Cisco 风格蓝色 L3 多层交换机内联矢量符号（蓝色设备体、红色三层路由核心、白色方向标记），不再依赖低清外部位图。

### 2026-07-16 拓扑交互增强全量完成

- 新增框选模式与 Shift+空白框选，兼容 mouse/pointer 双事件通道，并支持跨越 Navigator/footer 的窗口级拖拽收尾。
- 新增多选节点、Control/Meta 追加选择、多节点保持相对位置联动拖动、清除选择和选中态高亮。
- 新增网格吸附开关、自动布局、布局保存、撤销/恢复按钮及 Ctrl/Cmd+Z、Ctrl/Cmd+Y 快捷键。
- 新增 Space+拖动平移、拖拽中连线降噪、抓取偏移、边界约束和拖拽结束后批量持久化。
- 本轮验证覆盖：自动布局、网格开关、单节点拖动、多选联动拖动、框选 2 个节点、撤销恢复、清除选择；`npm run lint`、`npm run build` 均通过，浏览器控制台无错误。生产构建仍保留既有大 chunk >500 kB 提示，不影响本次功能交付。
- 2026-07-16：建立 `src/assets/topology/devices/` 资源目录，拓扑交换机节点改为读取 `cisco-switch-l3-master.svg`，画布统一渲染为 48×48 CSS 像素；PNG 多尺寸资源保留给导出/缩略图等非主画布场景，浏览器验证已生成 3 个 SVG image 节点且无错误。
- 2026-07-16：按设备分类整理图标目录：`switches/`、`routers/`、`firewalls/`、`servers/`、`wireless/`、`generic/`；拓扑代码已从分类目录加载交换机、路由器和防火墙 SVG，新增分类图标只需放入对应目录并更新资源表。
