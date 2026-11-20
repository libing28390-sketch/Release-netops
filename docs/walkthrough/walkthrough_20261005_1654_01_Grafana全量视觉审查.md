# Grafana 全量视觉审查与设计建议

## 完成摘要与证据范围

- 使用已登录浏览器，逐一打开 Linux Docker 实例 `https://192.168.204.128/grafana/` 中的全部 12 个 Dashboard，查看实际首屏、表格和关键区域；告警页额外查看底部时长区域。
- 同时只读审查本地生成器与 12 个 JSON：共 224 个面板，其中 24 个是分区行、200 个是视觉面板。JSON 均可解析，生成器清单与文件集合一致，标题和 UID 对应，面板 ID 唯一，数据源 UID 均为 `victoriametrics`；网格没有重叠。
- 主 Agent 负责浏览器、线上指标查询、设计与最终集成；两个执行子 Agent 均使用用户指定的 `gpt-6-luna / max`，分别审查配置和无线采集链路，没有修改文件。
- 在线数值来自 2026-10-05 16:54–17:07（Asia/Shanghai）期间的不同采样快照；不是同一时刻的原子快照，数值随刷新变化。没有验证每一条历史曲线中的每个样本。
- 本地仓库是解释配置的证据，浏览器是当前部署表现的证据；没有读取 Linux 容器运行时文件，也没有假定本地文件就是部署版本。
- 本次已按后续授权修改看板生成源、12 份 JSON 和专项测试；没有修改采集规则或设备代码，也没有部署或执行真实设备操作。

## 终端数 0 / 缺失：确认事实与待验证原因

### 在线查询结果

在 Grafana Explore 中对 Victoriametrics 使用 Instant 查询，并用 Query Inspector 核对实际表达式与返回结果：

| 查询 | 结果 | 能说明什么 |
|---|---|---|
| `up{job="network_snmp",hostname="AC_11"}` | 1 条，值为 1 | AC_11 的 SNMP 目标采集在线；不能证明无线专用 OID 已采集 |
| `hh3cDot11CurrAssocUserNum{job="network_snmp",hostname="AC_11"}` | 0 条，No data | 01 网络总览依赖的 H3C 原始终端指标当前缺失 |
| `nexora_wireless_sensor_value{job="platform_hardware_inventory",hostname="AC_11",sensor_class="clients"}` | 7 条，均为 0；其中一条 `measured_entity_type="wireless_controller"` | 硬件采集链路实际导出了控制器终端数 0；不是把空值强制补零 |

AC_11 的标签包括 H3C、h3c_comware、wireless_controller、WH-DC-01。SNMP 实例是设备地址；硬件指标的 `instance` 是 `netops:8003`，它是采集服务地址，不应展示为设备管理 IP。

**浏览时 01 显示的是“暂无采集数据”；03 显示的是 0。** 用户此前见到的 0 无法由本次快照还原，但两页当前统计口径确实不同：

- 01：汇总 `job="network_snmp"` 下厂商原始控制器指标，包含 H3C 的 `hh3cDot11CurrAssocUserNum`。没有硬件指标回退，也没有 `or vector(0)`。
- 03：先使用厂商原始指标，再按控制器身份回退到平台控制器指标或 SSID 客户端统计，使用 `unless on(site_name,vendor,role,hostname)` 避免重复计数，最后汇总。
- 因而“SNMP 在线 + 总览无线指标缺失 + 专网页 0”可以同时成立。AP 在线表示 AP 与控制器的关联状态，不等于有手机、电脑等终端关联。
- 本次没有读取设备 CLI 或执行设备侧 SNMP GET，不能断言设备真实终端数就是 0，也不能把缺失指标解释成真实 0。

相关查询与缺失值配置：

- [总览查询生成逻辑](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:791)
- [无线专网回退逻辑](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:1772)
- [缺失值与 Stat helper](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:239)

### 上游缺失指标的候选原因

这里的候选尚未在 Linux 运行时验证，不能当成已确认根因：

1. **AC_11 没有启用或没有成功编译无线采集模块。** 编译器按显式采集计划选择模块，对没有发现证据的厂商模块会跳过；基础 IF-MIB 采集成功不意味着无线模块存在。应核对实际生效的目标计划、模块绑定与采集日志。
2. **运行时仍使用旧无线 OID 绑定。** 本地 OID 目录和硬件探测使用 H3C 控制器客户端 OID `1.3.6.1.4.1.25506.2.75.1.1.3.6`（标量实例 `.0`）；bootstrap `snmp.yml` 中同名指标仍绑定到 `.1.1.2`。仓库已有 m0269 修正迁移，但 Docker 使用编译后的共享运行时配置，必须检查数据库迁移状态和实际加载配置，不能仅凭 bootstrap 文件定论。
3. **设备侧该 OID 不支持、没有读权限，或返回结果不能解析。** 需要设备侧读数与采集错误证据确认；本次未验证。

证据入口：

- [H3C 无线 OID 目录](D:/netops/netsops-main/backend/services/monitoring_oid_catalog.py:656)
- [控制器硬件探测](D:/netops/netsops-main/backend/services/snmp_hardware_probe_service.py:1946)
- [bootstrap 中的指标绑定](D:/netops/netsops-main/monitoring/snmp-exporter/snmp.yml:1167)
- [m0269 OID 修正迁移](D:/netops/netsops-main/backend/database/migrations/m0269_correct_h3c_wireless_oid_bindings.py:1)
- [采集模块编译](D:/netops/netsops-main/backend/services/monitoring_compiler.py:797)
- [Docker 运行时配置卷](D:/netops/netsops-main/docker-compose.yml:181)

### 建议修正顺序

先验证生效模块、OID 和设备读数，再让 01 与 03 共用同一控制器客户端查询 helper，统一身份、来源优先级和新鲜度判定。展示“数值 + 采集来源 + 更新时间/覆盖情况”；真实 0、指标缺失、不支持、过期应是不同状态。不能直接给缺失值补 0，也不能简单汇总 AP/射频客户端数代替控制器总数，以免重复计量。

## 推荐配色、字体和布局规范

### 深海蓝：日常运维主方案

| 用途 | 颜色 | 规则 |
|---|---|---|
| 页面背景 | `#0B1220` | 深蓝灰，减少长时间观看的刺眼感 |
| 面板背景 | `#121D2F` | 与页面形成轻微层次；不用全屏发光渐变 |
| 分隔 / 边框 | `#26364D` | 低对比细线，形成秩序 |
| 主文字 / 普通数值 | `#E6EDF7` | 设备数量、站点数量、容量默认中性 |
| 次级文字 | `#A4B3C9` | 单位、时间、上下文仍需可读 |
| 入向 / 信息 | `#49B5FF` | 所有看板固定蓝色 |
| 出向 / 健康 | `#2AD4A7` | 固定薄荷绿；普通数量不用大面积绿底 |
| 错误 / 高风险 | `#FF985C` | 错误曲线或主要告警；0 条错误的 Stat 使用中性 |
| 丢弃 / critical / 已确认故障 | `#FF5D73` | 珊瑚红只强调需要行动的异常 |
| 预警 / warning | `#F5C451` | 未达严重阈值的风险；待核验接口用提示而非故障定性 |
| 未采集 / 未知 / 管理停用 | `#9AA8B8` | 冷灰 + 明确文案；避免与健康混淆 |

紫色 `#B18CFF` 可用于无线业务类别或第二组对比曲线，但不作为通用健康色。颜色必须伴随文字、状态标签或线型，不能只依赖颜色传达状态。暗色和面板背景属于 Grafana 用户主题设置，Dashboard JSON 不负责强制全局主题。

当前生成器按蓝/绿/橙/红固定入向、出向、错误和丢弃，并在健康、预警、严重及未知状态中使用绿/金/珊瑚红/冷灰；含多设备或动态硬件名称的系列保留 Grafana 分类调色，以便相互区分。

### 推荐尺度

- 桌面主标题约 24px，面板标题 14–16px，表格正文 12–14px，主要 Stat 32–40px；大屏关键 Stat 48–64px。时长采用“10天 01:59”或分行，避免超大数字撑破卡片。
- 间距 12–16px，面板低对比细边框，圆角约 6–8px；不用每个卡片都加彩色边框、投影和发光。
- 当前规模最多一行 4–6 个紧凑 KPI。第一屏回答：哪里异常、影响什么、数据是否可信；第二层回答原因和趋势；第三层放硬件、接口与诊断明细。
- Grafana 24 格：4 个核心 KPI 各 6 格；关键异常列表 14–16 格，覆盖/健康摘要 8–10 格；两张趋势图各 12 格。不要将 14–17 列表格挤进 8 格宽。
- 趋势线宽约 2px，填充透明度约 5–12%；保留少量持续有意义的系列，通常 5–10 条。两条曲线优先使用底部紧凑图例；长名称通过表格或下钻查看。
- 总览表格只留站点/设备、接口或部件、当前值/状态、必要阈值、下钻入口，通常 5–7 列。资产 ID、规则版本、内部索引、空白 AP 元数据不占默认视野。
- 图表的错误/丢弃曲线始终使用固定语义色；当前 0 值不意味着 Stat 需要红色。资源阈值按角色或现有策略设置，不给所有设备套同一阈值。

Grafana 的标准字段 override、线条/填充、图例、单位、阈值和网格布局可以完成大部分调整。预览中的自定义侧栏、精确背景色和圆角属于应用外壳设计；要像素一致，需要 Nexora 页面外壳或主题配合，不能承诺仅修改 Dashboard JSON 即实现。

参考官方设置：[Time series 配置](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/time-series/)、[字段 overrides](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/configure-overrides/)。仅使用现有生成器已具备的基础能力，不依赖最新版新增特性。仓库固定 Grafana 12.1.0；本次未核实在线运行版本。

## 12 个 Dashboard 的逐页审查

| Dashboard / 视觉面板数 | 浏览器观察与配置证据 | 推荐布局与表现 |
|---|---|---|
| **01 网络总览 / 17** | 15 台纳管、15 在线、2 站点、507 接口；无线终端暂无采集数据。24h 变动且仍 Down 从 393 刷新到 391。三张硬件 Top10 表很窄，内存表露出 `netops:8003` 和很多空 AP 元数据。异常接口在底部。 | 核心 KPI → 关键链路异常/采集缺口 → 观测接口聚合趋势/硬件热点 → 明细。缩减硬件表字段并放宽。接口求和不能称去重后的“全网业务流量”。391/393 不直接等于相同数量的业务故障；结合用途与关键链路判断。 |
| **02 网络设备详情 / 28** | 设备身份表占一整行；“CPU 超出 10 条部件数”0 仍是巨大红色 Stat。温度约 24 条曲线，电源约 156 条，出现未展开模板名称与统一 80mW。风扇缺失；光功率出现 `100 mdBm`。 | 页首压缩成设备身份和状态，再放当前异常/采集覆盖。CPU/内存/温度同排，硬件细节折叠分区。超量 0 中性，大于 0 才强调。按部件选择并限序列，核对电源单位/传感器身份；光功率固定 dBm 精度和合适显示。 |
| **03 无线专网 / 13** | AP 2 台，后续快照 1 在线/1 idle；终端 0。两个不同 AP 状态条都铺满各自宽度，无法表示构成。AP 表露出 rule_version 等内部字段，排名数值在右侧；平台地址被称管理 IP。 | 控制器/AP 健康、终端数量、射频质量分层。AP 状态使用共同刻度或状态表，不用独立满格条。AP 表 5–7 列，明确 AP 地址与控制器地址；减少仅 2 条数据时的大片空表。加入设备/AP 下钻。 |
| **04 接口流量与健康 / 17** | 全选时流量图约 266 条系列，图例占大量宽度。容量、当前/峰值/P95 和阈值上下文存在宽表与重复身份。错误 0 红色、丢弃 0 黄色。 | 全网视图以关键链路异常和 Top-N 表为主；趋势只画选中设备、接口或 Top5–10。容量/当前/P95 一接口一行，关键值靠前，剔除不相关虚拟接口并显示实际范围。 |
| **05 SNMP 采集健康 / 8** | 15 在线、0 失败、平均约 1.34s、最大约 3.03s。失败表为空仍写“暂无采集数据”；“耗时分布”实际上是时间曲线。慢目标的秒单位缺失。 | 失败目标先于趋势，Top 慢采集目标并列辅助定位。已确认有目标且失败数为 0 时显示“当前无失败目标”；没有目标才显示未采集。修正单位与图名，少量曲线或分位数替代全量叠加。 |
| **06 互联网出口与 WAN / 14** | 浏览器自动选择 AC_11 的 Gi1/0/0，描述 TO-HOST-NEXORA，速率均 0；该选择不能证明它是 WAN。JSON 并未硬编码 AC_11。 | 显式选择已绑定的出口接口，空选择提示先选线路；页首展示线路身份、容量和方向。流量/利用率两图，质量和 Top-N 下方。未确认角色的内部口不能自动代表出口。 |
| **07 Linux 服务器 / 14** | CPU 约 60.9%、内存 34.9%。上线时长与文件句柄等占同等醒目位置。磁盘表值 75.6 没有 %；出现重复根挂载/bind mount。多主机均值可能掩盖热点。 | 页首主机风险与 CPU/内存/磁盘余量，uptime 做身份补充。磁盘表按真正文件系统语义去重，过滤不相关挂载，修正百分比。多主机使用最差值/Top-N，读写和入出方向固定色。 |
| **08 Windows 服务器 / 11** | CPU 约 61.6%；物理内存、RDP 缺失仍占大块绿/紫色。磁盘剩余显示 16.4、18.7 等但无 %。服务表列出很多普通服务。 | 未采集项压缩为灰色能力/覆盖提示。低剩余空间前置，阈值方向与使用率相反。按业务定义关键服务范围，异常服务优先，状态名称可读；主机网络图限制网卡系列。 |
| **09 接口详情 / 19** | 默认接口速率均 0；错误和丢弃 0 使用异常色。容量/阈值表宽，部分身份重复；局部曲线重复名称。配置 y34–41 留空。 | 页首接口身份、Admin/Oper、速率、利用率和质量。流量与利用率 12+12，PPS/错误下方，DOM 再下钻；填补空白。保留 3–7 的 IF-MIB 精确枚举，不能全映射为 UNKNOWN。 |
| **10 监控平台健康 / 20** | 同一快照“在线 6、失败 3、总数 6”，即时明细却全部 UP。Stat 使用 range + lastNotNull，表格 instant。6 条 0/1 状态曲线填充杂乱；容器指标缺失。 | 当前状态统一 instant 或新鲜度判断，当前失败服务前置。状态矩阵/时间线替代大量填充曲线；Remote Write、存储、容器分组。采集器 UP 不等于每类业务指标都可用。 |
| **11 WAN 拨测 / 21** | 1h 可用率约 69.8%、24h 75.7%；ICMP 0%，DNS/HTTPS/TCP 约 99.8/98.8/99.8%。ICMP RTT/丢包/抖动缺失，很多巨大蓝色空卡。 | 首屏 1h/24h 对照 + 协议可用率表，异常协议和采集覆盖前置。缺失质量指标压缩显示，按配置 SLO 着色。当前探测没有线路 source-IP 绑定，不能据此宣称某条 WAN 线路 SLA。 |
| **12 告警处置与通知 / 18** | 未关闭 111，其中 major 110、warning 1；通知队列失败 127、成功 930、待处理 0。失败曲线绿色、成功橙色；最长/P95 未关闭时长约 10 天，文字在卡片内溢出。 | 按严重度固定色，失败红/橙、成功绿、待处理蓝/灰。首屏开放告警与老化 Top-N、通知失败渠道；MTTA/MTTR 和历史趋势次级。长时长紧凑格式；无样本、无异常和未采集分开。滚动 24h 统计明确标注。 |

## 跨看板的准确性问题

1. **当前值与历史值混用。** Stat helper 默认 range 查询 + `lastNotNull`，如果最新样本缺失或“失败数为 0”的表达式返回空序列，可能保留旧非零值。当前在线/失败/Down/开放告警宜 instant 或有新鲜度约束；历史趋势保留 range。平台健康的冲突是线上可见证据，具体每个 Stat 应逐项确认。
2. **管理 IP 误命名。** 公共转换将 `instance` 一概改名为管理 IP。硬件 exporter 的 `instance=netops:8003` 应显示“采集目标”，或者与资产身份连接使用实际设备管理地址。
3. **单位 override 没有命中。** 表 helper 默认匹配“数值”，Linux/Windows 磁盘表先改为“磁盘使用率”/“剩余空间 (%)”但没有传同名 `value_col_name`；SNMP 最慢目标表也类似。修正字段 matcher，同时保留数值类型和正确排序。
4. **状态枚举丢失。** `ifOperStatus` 的 3–7 被归为 UNKNOWN；应保留 testing、unknown、dormant、notPresent、lowerLayerDown，结合 admin 状态区分管理停用和故障。
5. **指标名称需要说明范围。** 全接口 rate 求和可重复计量同一业务路径；24h 滚动计数曲线不能被解释为按事件时间切分的每日数量；系统级拨测不能替代线路级 SLA。

配置入口：[Stat helper](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:239)、[表格字段转换](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:384)、[表格单位 matcher](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:469)、[Linux 表](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:2638)、[Windows 表](D:/netops/netsops-main/monitoring/grafana/generate_dashboards.py:2720)。

### 本次已落地的配置调整

- 入向/出向/错误/丢弃统一使用蓝/绿/橙/红，预警用黄，未知和普通 Stat 用中性灰；告警按 critical/major/warning/minor 分别红/橙/黄/灰，0 值不再统一着红色。
- 抽出控制器客户端总数查询 helper，01 与 03 共用同一按设备身份去重的 controller→SSID 回退；趋势和 Stat 复用表达式。无序列仍显示“暂无采集数据”，实际采样值 0 保持 0。
- `instance` 显示为“采集目标”，避免把 exporter 地址误标为设备管理地址。
- 修正 Linux/Windows 磁盘百分比与 SNMP 慢目标耗时表格的 unit override 字段匹配。
- Stat KPI 改为 instant query，避免 range query + lastNotNull 在当前源序列消失后继续显示窗口内旧样本。
- 接口趋势图例改在底部；接口详情看板 y34–41 的布局留白收紧。
- 生成器在写入前检查 12 个 Dashboard 清单、UID、panel ID 唯一性及网格碰撞。

这些仓库变更不会自动写入已部署的 Docker Grafana；需通过 Dashboard provisioning 或导入后才会在线生效。

## 本地审查记录与实际面板配置

- 本计划：`docs/plans/plan_20261005_1654_01_Grafana全量视觉审查.md`。
- 本审查记录：`docs/walkthrough/walkthrough_20261005_1654_01_Grafana全量视觉审查.md`。
- 首轮产生过一个独立 HTML 视觉概念稿；它不对应 Grafana panel JSON，也不是本次实际改版结果。根据用户澄清，后续交付只以生成器和 Grafana JSON 为准，不再展示该概念稿作为结果。
- 实际修改入口是 `monitoring/grafana/generate_dashboards.py`，并重新生成 `monitoring/grafana/dashboards/nexora-*.json` 共 12 份。

### 第二轮：Grafana 面板实际改版

- 所有 Dashboard 的首排 Stat/Gauge 摘要卡统一为 4 个 Grafana 网格单位高；纯数值 Stat 默认关闭面积 sparkline，避免 instant query 卡片显示空白装饰图。
- 12 份 Dashboard 均具备清晰 Row 分组。缺少分组的告警、SNMP、出口 WAN、Linux、Windows、平台健康与拨测页已加入章节标题；设备详情和无线页补上首屏摘要分组。
- Windows“非运行关键服务”表与网络趋势并排前移，连续 Down 的 WAN 计数和最长时长从页面底部移至拨测趋势前；告警效率 KPI 等宽，避免 3 格窄卡。
- Overview、无线与接口诊断的低序列趋势图例移至底部，释放窄图绘图区；SNMP 曲线标题改为趋势语义。平台 endpoint up/down 趋势改成阶梯线，避免连续插值暗示中间状态。
- 无线 AP KPI 的无数据文案统一为“暂无采集数据”；设备详情明确硬件渲染错误数为全局指标，不随设备变量变化。
- 将语义色更新为高对比 Nexora 配色：入向亮蓝、出向薄荷绿、错误橙、丢弃珊瑚红、预警金色、未知冷灰、组播紫色；健康与告警继续按状态/严重度上色，普通 KPI 保持中性。未通过 JSON 设置 Grafana 全局主题或页面外壳。
- `insert_section_rows` 现在会避开当前 Dashboard 已用 panel ID；生成器在写入前仍验证 UID、panel ID 唯一和网格不重叠。

## 验证、未执行项与统一交接

- 两个 Luna 子 Agent 的只读检查完成，结果已集成在本记录。Dashboard 执行者完成 12 份 JSON 重新生成，主 Agent 重新运行生成器并复核结果。
- 12 个 JSON 的解析、清单/标题/UID、唯一 panel ID 和网格检查通过；90 个 Stat 面板使用 instant query。范围为本地当前仓库。
- 12 个线上 Dashboard 的首屏和关键区域实际浏览完成；无线 3 条 Instant 查询已经通过 Query Inspector 核对结果。
- 设计预览使用技能自带 `scripts/render.py` 包装，并在浏览器检查桌面和窄屏布局、两方案切换、无线口径展开；页面脚本语法检查通过。
- `.venv\Scripts\python.exe -m py_compile monitoring/grafana/generate_dashboards.py` 通过；`.venv\Scripts\python.exe monitoring/grafana/generate_dashboards.py` 成功重建全部 12 个 JSON。
- `.venv\Scripts\python.exe -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py backend/tests/monitoring/test_monitoring_v1_deployment_contract.py -q`：本轮 19 passed。包含全部 12 份 builder 的摘要卡高度、Stat instant/无 sparkline、Row 分组、状态阶梯线、异常前移和网格碰撞检查。
- `git diff --check` 通过。没有运行无关 TypeScript build、设备集成或全量业务回归；更改限于 Dashboard 配置及契约测试。
- 未检查容器运行时无线模块、数据库迁移应用状态、实际 OID 读数：现有访问证据来自浏览器，尚未建立 Linux/设备侧只读会话。下一阶段由主 Agent 核对这些证据，再决定修改；没有发现需要本次立即变更生产的授权。
- 已完成：语义色、Stat 即时查询、无线查询合同、章节分组、KPI 高度、窄面板图例、告警/Down 异常优先级及服务异常布局调整。尚未在部署实例中回归新 JSON。
- 尚未确认原始客户端 OID 缺失原因，仍需只读验证运行时模块绑定、迁移版本和设备侧 OID 读数。
- 修复记录以不含现场地址、设备名或遥测快照的摘要提交；本 walkthrough 保留在本地供用户审阅。
- 已推送提交 `e4b3c2572d3b502323b836df92d525af7ed95623`（`fix: align Grafana dashboard semantics`），推送后 `origin/main` 与本地 HEAD 一致。
- 本轮代码已提交并推送：`b3620d0ed2b625d727b5b1de0b74e5ed47044121`（`feat: improve Grafana dashboard hierarchy`）；核对后 `origin/main` 与本地 HEAD 一致。Linux 上的 Grafana 没有收到写入或部署。开发机没有 Docker 命令，故本轮没有本地 Grafana 容器渲染验证。
- 配色已提交并推送：`e5886532`（`feat: refine Grafana semantic palette`）；19 项定向测试通过，12 份 JSON 的比较确认只有颜色值变化。Linux 上的 Grafana 仍未收到部署。
- 协作已完成，没有仍在编辑的共享业务文件。用户原有未跟踪 build/dist 目录保持原状。
