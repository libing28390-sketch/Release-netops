# IPAM 批量用途与设备自动关联

## 完成摘要

已完成 IPAM 前缀批量用途修改、网关候选自动匹配、IP 地址页 CIDR 来源说明，以及对账页空结果语义修正。

用户询问的 `/ipam/reconciliation` 与接口采集的关系是：**接口 CLI 快照不参与本页对账**。本页未登记端点和建档信息不一致以当前 `network_endpoints` 活动端点对比 `ip_addresses`；长期未发现检查使用 `network_endpoints.last_seen` 历史观测。CLI 接口观察存于 CMDB 快照表，仅作为单独来源计数显示，不会被并入对账 findings。

初次只读抽样时，对账输入为 0 条已分配 IPAM 地址、0 条窗口内活动端点；成功接口快照中有 55 条 IP 观察。该时点页面列表为空是因为没有两侧可比输入，并不代表对账通过；计数可能随采集变化。

## 实际修改

- `backend/api/ipam.py`、`backend/schemas/schemas.py`、`backend/services/ipam_service.py`：新增批量网络用途更新和只读网关候选接口；对账摘要增加来源计数；缓存新鲜度依据 15 分钟内活动端点，新增 `latest_active_endpoint_seen` 并保留原 `latest_endpoint_seen`。
- `src/pages/IPVlan/PrefixManagementTab.tsx`：常驻工具栏与批量上下文操作分离；批量改用途沿用人工分类保护字段；网关只在唯一证据时自动匹配，点对点多端点不猜选。
- `src/pages/IPVlan/IPAddressTab.tsx`：IPAM 登记 CIDR 与设备报告 CIDR 同列分源显示，不将观察网络伪装为 IPAM 登记网段。
- `src/pages/IPVlan/IPReconciliationTab.tsx`、`src/pages/IPVlan/ipReconciliationPresentation.ts`：显示两侧可比输入与被排除的接口快照计数；空结果区分无输入、缓存过期、搜索/分页为空、未归属端点以及当前分类确无差异。未归属端点存在时，三个明细页签均说明结果不完整。
- 测试覆盖：批量更新与网关候选、IPAM/CMDB 地址来源、对账数据来源及空态文案。
- 未增加数据库迁移；没有修改监控代码或解析模板。

## 验证

- `npm run test:frontend -- --run src/pages/IPVlan/prefixManagementSelection.test.ts src/pages/IPVlan/prefixGatewayBinding.test.ts src/pages/IPVlan/prefixClassificationFilters.test.ts src/pages/IPVlan/ipReconciliationPresentation.test.ts src/pages/IPVlan/ipamExport.test.ts src/pages/IPVlan/ipAddressTablePresentation.test.ts`：6 个测试文件、31 项通过。
- `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_prefix_batch_and_gateway_candidates.py backend/tests/ipam/test_ipam_reconciliation_source_counts.py`：9 项 PostgreSQL 隔离测试通过（批量/网关 7 项、来源计数 2 项）。
- `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/ipam/test_ipam_inventory_scope.py backend/tests/ipam/test_ipam_reconciliation_source_counts.py`：19 项 PostgreSQL 隔离测试通过；包含 inactive 记录最近但 active 观测已过期时缓存应判为过期的回归。
- `.venv/Scripts/python.exe -m py_compile backend/api/ipam.py backend/schemas/schemas.py backend/services/ipam_service.py backend/tests/ipam/test_prefix_batch_and_gateway_candidates.py backend/tests/ipam/test_ipam_reconciliation_source_counts.py backend/tests/ipam/test_ipam_inventory_scope.py`：通过。
- `python scripts/validate_postgresql_only.py`：0 项违规，通过。
- `npm run lint`：通过。
- `node --max-old-space-size=4096 node_modules/vite/bin/vite.js build --outDir C:\Users\NINGMEI\AppData\Local\Temp\nexora-ipam-reconciliation-final-20261028`：生产构建通过，输出位于临时目录。
- `git diff --check`：通过。

## 运行时与未验证项

- `192.168.56.1:5400` 初始拒绝连接。按用户此前授权的本机恢复方式启动了隐藏开发监督器；本机 `127.0.0.1:5400/ipam/reconciliation` 返回 HTTP 200，`127.0.0.1:15310/api/health` 返回 healthy，数据库 connected。
- CUA 浏览器自动化通道连续两次返回 transport closed，因此未取得页面 DOM、截图或登录态下的交互证据；HTTP 健康和源码/单测不等同于浏览器验收。
- 服务启动会按现有逻辑初始化后台调度任务。本次未手动触发 IPAM 采集、设备配置操作或监控代码变更；本地后台已有只读采集日志属于服务启动后的既有调度行为。
- 未推送、未提交、未部署到其他环境。

## 风险与回滚

- 批量用途更新在 PostgreSQL 单事务中执行，范围校验或任一记录失败会整体回滚；成功只写一条汇总审计事件。
- 自动网关绑定只接受唯一接口证据；歧义时保留未绑定状态。CLI 观察不写回 IPAM 前缀/地址台账。
- 回滚可通过反向代码变更恢复旧 UI 和服务查询；本次没有数据库结构或真实业务数据变更。

## 追加：对账页面说明简化

- 用途统一为“核对已登记 IP 与网络发现 IP，找出漏登记、信息不一致和长期未发现的地址”。
- 移除独立缓存状态横幅、15 分钟窗口、最近活动观测时间、接口快照数量及数据库表名说明。只显示已登记 IP 和近期发现 IP 两个数量。
- 简化无输入、发现数据过期及归属待确认文案；仍保留原有判定条件，数据不足时不会显示核对正常。
- 本次只调整页面展示与文案，未调整后端对账、监控或解析逻辑。
- 聚焦前端回归 8 项通过；TypeScript 检查通过。浏览器自动化通道此前不可用，尚无本轮视觉验收证据。

- 来源标签补充明确为“IPAM 已登记 IP”和“近期发现 IP（ARP/MAC）”。登记来源为手动分配、接口生成及对账登记；发现来源为端点跟踪/定位保存的 ARP/MAC 端点记录。

## 追加只读审查：终端 PC 发现口径

- 发现记录来自网关 ARP 的 IP/MAC 与交换机 MAC 接口定位，不是完整 PC 资产清单；睡眠、离线或未留下 ARP 记录的 PC 可能不可见，发现记录也包含服务器等非 PC 地址。
- 确认 `endpoint_tracker_service.py` 读取缓存 ARP/MAC 后，以本次计算时间重写 `network_endpoints.last_seen`；`scheduler_service.poll_endpoints_job` 可只重算缓存而不访问设备。因此对账的 15 分钟新鲜度不能充分证明近期实际采集成功。
- tracker 在存在输出时先将全部端点设为 inactive，再写入此次输出；未将采集成功范围作为停用边界，存在不完整证据影响活动状态的风险。
- 本轮仅做只读审查并记录，未修改端点采集/调度相关代码；以上问题仍待明确范围后修正。页面简化的 TypeScript 检查已通过。

## 完整只读复审：IPAM 对账的数据和时效

用途：比较 IPAM 计划/登记地址与网络发现记录，产生未登记、字段不一致、历史长期未发现三类核查项。它不是 PC 资产总量统计、在线监控或自动地址回收器。页面刷新仅重新查询 PostgreSQL 计算结果，不启动设备采集；登记、校准（主机名/MAC）、释放是人工确认的写操作。

来源与字段：IPAM `ip_addresses` 来自手动分配、从接口生成、对账登记；网络侧为 `network_endpoints`。ARP 从三层网关取得 IP/MAC；交换机 FDB/MAC 表提供 MAC/VLAN/端口，LLDP/拓扑用于避开上联口；站点由关联设备/资产推断，厂商由 MAC OUI 推断，置信度由规则赋值。当前主 ARP、FDB 采集函数均为 SNMP 优先、失败或结果不可用后回退平台 CLI。CMDB 接口 CLI 快照不参与对账。ARP 记录代表设备邻居表中的观察，不证明 PC 此刻在线。

实际时效（2026-10-28只读源码与配置核对）：
- 当前环境 ARP sweep 周期 600 秒，ARP 缓存 TTL 1200 秒；按批次与失败退避执行，不保证每设备每10分钟成功。
- `main.py` 未注册独立5分钟终端/FDB采集，实际 NSOT 数据库计划为 `0 2 * * *`、enabled=1、approved；执行统一 ARP→端点/MAC→其余网络事实工作流，另支持手动触发。采集目录5m与旧函数注释不能作为当前运行频率依据。
- 对账写死当前窗口15分钟、长期未发现阈值7天；后者只处理有历史匹配的 active/allocated IPAM 地址，并排除 Loopback/VIP 等。从未发现的登记地址不会进入7天列表。
- 当前只读计数：ip_addresses=0、arp_table=90、mac_table=0、network_endpoints=0、成功接口快照IP观察=55。三个对账分类为0是缺少比较输入，不是采集范围完整且无问题。

确认的问题：
1. 端点每日投影与15分钟对账窗口不匹配。ARP独立更新不会自动更新端点投影，大部分时间可能缺少当前比较记录。
2. tracker读旧缓存后将last_seen重写为本次计算时间，无法区分设备观察时间和投影时间；周期重算会让历史记录假新鲜，影响15分钟及7天判定。
3. 主端点collector在MAC失败或空结果时提前退出，ARP-only降级分支在该情况下不可达；即使已有ARP IP，也可能没有任何对账输入。当前90/0/0数据与此条件一致，但不据计数推定某次任务确切失败原因。
4. 旧tracker将关联交换机hostname写入终端hostname，并写死Linux；不能作为PC主机名/操作系统。页面主机名校准可将错误旁证写入台账。
5. 旧tracker全局inactive后重写当前结果，没有完整采集代次/成功范围作为停用边界。主collector有MAC部分失败保护，应与旧tracker区别看待。
6. 任意一个新活动端点可使总体cache_fresh为true，并不证明全部站点/设备采集成功；两侧数量非0也不能证明覆盖完整。
7. IPAM未登记/空字段、从未发现、采集失败和真实长期缺席没有完全独立的结果口径；手动释放按钮虽需确认，但底层时间证据仍不足以证明地址安全可回收。

建议边界：保留IPAM登记为台账基准；ARP是否见到IP与MAC能否定位分开；保留原始observed_at与投影updated_at及每设备成功采集代次；按采集范围/失败情况判定结果完整性；基于有效采集次数与可配置持续时长产生“待核查”，不把未发现当空闲。实际修正涉及共享采集链路，需继续遵守用户禁止修改监控代码的约束，不在本次只读审查中直接改动。

验证性质：仅源码追踪与SELECT；未运行新测试、设备命令、配置变更或数据库写入。

补充身份审计：`network_endpoints.ip` 为全表唯一键（schema.py:1372），tracker在内存按IP去重（endpoint_tracker_service.py:173），多个写入路径按ON CONFLICT(ip)更新归属。跨站点/VRF同IP证据会覆盖，tracker还可能保留旧VRF。对账虽按tenant/VRF/IP解析，但无法恢复已经在上游丢失的记录。应在后续方案中定义租户/地址空间或VRF/站点的身份规则，再决定数据结构迁移，不能只修改对账查询。

优先级：P1处理实际采集与投影时间、范围覆盖、ARP-only可见性及错误主机名校准；P1梳理跨VRF/站点身份键；P2完善从未发现/采集不可用/持续未发现分类与可配置阈值。上一轮页面空态和自动化测试通过只证明对应展示与已覆盖路径，不证明以上业务语义正确。
