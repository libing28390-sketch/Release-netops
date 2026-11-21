# LibreNMS 硬件 MIB 来源与进度交接

更新时间：2026-09-29
用途：继续完成 Nexora 网络设备硬件监控（含光模块）与 Grafana 设备详情适配。本文是当前工作树的静态盘点，不代表实机或部署验收。

## 1. 目标与边界

- 以资产系统网络设备厂商目录中的 26 家厂商为适配范围，以 LibreNMS 为规则来源。
- 本轮只调整硬件、环境传感器和光模块采集；既有公共接口 OID / 接口采集保持原样。
- MIB 和规则应随项目本地保存。SNMP 运行时从项目代码和数据库中的本地导入结果采集，不需要连接 LibreNMS 或下载 MIB。
- 当前机器没有 Docker 和真实设备验证环境。按用户要求，本轮不做 Docker、真实设备、Grafana 运行验收；结论只基于代码和 pinned LibreNMS 源文件。

## 2. 上游来源和本地文件

### 固定版本

- 上游仓库：`https://github.com/librenms/librenms`
- pinned commit：`6c26b4fe4a40f7b392c19c36a44257212736e38c`
- commit 日期：2026-09-29
- 本地说明：`backend/vendor/librenms/README.md`
- 精确文件来源、上游相对路径、SHA-256：`backend/vendor/librenms/source-manifest.json`
- 该快照包含 136 个 OS detection YAML、122 个 OS discovery YAML、217 个精选 MIB 文件（约 33.1 MiB）。它是硬件轮询所需的精选集合，不是 LibreNMS 全仓库或全量 MIB 镜像。

### 本地目录结构

| 内容 | 本地路径 | 用途 |
|---|---|---|
| OS 自动识别 | `backend/vendor/librenms/resources/definitions/os_detection/` | 由 sysObjectID、sysDescr 等识别 LibreNMS OS key，再映射业务厂商/平台 |
| OS 硬件规则 | `backend/vendor/librenms/resources/definitions/os_discovery/` | CPU、内存、温度、电压、风扇、状态、光功率等结构化定义，含 OID、索引、单位、比例、过滤和转换函数 |
| 厂商 MIB | `backend/vendor/librenms/mibs/<vendor>/_upstream/...` | YAML 符号 OID 解析和源码审计；具体模块路径及 SHA 见 manifest |
| 标准 MIB | `backend/vendor/librenms/mibs/standard/_upstream/` | `ENTITY-MIB`、`ENTITY-SENSOR-MIB`、`IF-MIB` 等通用设备来源 |
| 同步/导入代码 | `backend/services/librenms_mib_service.py`、`backend/services/librenms_rule_service.py`、`backend/scripts/sync_librenms_mibs.py` | 从本地快照导入 MIB 和 OS 规则；同步脚本默认提供联网同步选项，离线使用需 `--no-fetch` |

采集运行时读取 `backend/vendor/librenms` 本地快照和已导入的 MIB/规则数据；`backend/vendor/librenms/README.md` 明确说明运行时不从 GitHub 获取数据。manifest 记录有 1 个上游规则引用在选定快照中找不到对应 MIB：`FROGFOOT-RESOURCES-MIB`（被 UniFi 规则引用），需要继续评估该规则的符号 OID 是否能可靠解析。

### 标准 MIB 清单

当前捆绑 8 个标准模块：`ENTITY-MIB`、`IF-MIB`、`ENTITY-SENSOR-MIB`、`POWER-ETHERNET-MIB`、`BRIDGE-MIB`、`IP-FORWARD-MIB`、`IPV6-MIB`、`LLDP-MIB`。硬件通用探测主要用到 `ENTITY-MIB`、`ENTITY-SENSOR-MIB` 和 HOST-RESOURCES 的标准数字 OID；接口公共采集链不在本次范围。

## 3. 26 家网络设备厂商来源矩阵

“MIB 数”是 manifest 中按业务厂商归类的精选文件数，不表示每个模块都已被 Nexora 采集器消费。硬件规则状态表示 pinned OS discovery YAML 中是否存在结构化硬件定义；即使为“有”，某个 OS key 的函数、过滤或实体关联仍可能未移植。

| 资产厂商 | LibreNMS OS profile | 本地厂商 MIB 数 | 硬件相关 MIB 示例 | OS discovery 硬件定义 / 当前适配情况 |
|---|---:|---:|---|---|
| Cisco | 有 | 29 | `CISCO-ENTITY-FRU-CONTROL-MIB`、`CERENT-ENVMON-MIB`、UCS CPU/Memory MIB | 有；通用 ENTITY-SENSOR 已接入硬件清单；IOS-XR watts→dBm 转换在标准 ENTITY-SENSOR 探测/轮询计划中；接口映射只在明确匹配时输出 `ifIndex` |
| Huawei | 有 | 18 | `HUAWEI-ENTITY-EXTENT-MIB`、`HUAWEI-POWER-MIB`、`HUAWEI-STORAGE-HARDWARE-MIB`、OPTIX MIB | 有；pinned `vrp.yaml` 明确含 `.32/.33` lane Rx/Tx 列、除数 100、状态/哨兵过滤及 `uw_to_dbm`；本地 allowlist 实现 uW→dBm；无设备样本验算 |
| H3C | 有 | 4 | `HH3C-ENTITY-EXT-MIB`、`HH3C-TRANSCEIVER-INFO-MIB` | 有；Comware 光模块有专门接入新硬件清单的适配，按 pinned PHP 规则实现诊断存在、端口 admin-up、传感器列和比例 |
| Arista | 有 | 0 | 无厂商 MIB 收录；可用标准 ENTITY-SENSOR | 无结构化 OS 硬件定义；旧 collector 有 ENTITY-SENSOR DOM 分支，当前来源/过滤范围需继续审计 |
| Juniper | 有 | 11 | `JUNIPER-IFOPTICS-MIB`、`JUNIPER-DOM-MIB`、`JUNIPER-VIRTUALCHASSIS-MIB` | 有；pinned `junos.yaml` 含 DOM classic `.5/.7`、module lane `.6/.8` 和 IFOPTICS Rx/Tx 定义，比例均按 YAML；实际表索引与 IF-MIB 对应仍需设备核验 |
| Ruijie | 有 | 9 | `RUIJIE-FIBER-MIB`、`FS-FIBER-MIB`、Ruijie/FS Memory、Process MIB | 有；pinned `ruijie.yaml` 的 RX/TX 分别为 `.76/.81`、除数 100，跳过 DDM 不支持状态及 RX `-10000` 哨兵；温度零值过滤保留在同一规则引擎 |
| ZTE | 有 | 3 | `ZXR10-MIB`、`ZTE-AN-CHASSIS-MIB`、`ZTE-AN-ENVMON-MIB` | 有；pinned `zxr10.yaml` 只有 CPU 与内存定义，没有光模块 YAML；新入口只接受设备实际上报的标准 ENTITY-SENSOR 光功率，不再运行旧项目专用 ZTE OID 分支 |
| Raisecom | 有 | 11 | `RAISECOM-OPTICAL-TRANSCEIVER-MIB`、`ROSMGMT-OPTICAL-TRANSCEIVER-MIB`、FAN/POWER/MEMORY MIB | 有；新入口使用 pinned OS 规则和本地 MIB；旧 collector 的 ROS/legacy OID 特例已移除，未声称每个 Raisecom OS key 都含光模块定义 |
| Maipu | 有 | 1 | `MPIOS-MIB` | 有；目前依赖结构化规则/通用解析，厂商专用硬件语义尚未逐条核完 |
| DPtech | 无 | 0 | 无上游厂商 MIB 收录 | 无；只应走已确认的标准 MIB 或有证据的本地目录，不能仅凭本地旧 OID catalog 宣称 LibreNMS 兼容 |
| DCN | 有 | 1 | `DCN-MIB` | 有；规则可进入通用路径，本地专用 OID catalog 的上游来源仍需区分和审计 |
| FiberHome | 有 | 7 | `WRI-CPU-MIB`、`WRI-MEMORY-MIB`、`WRI-POWER-MIB`、`WRI-TEMPERATURE-MIB`、`WRI-VOLTAGE-MIB`、`FAN-MIB` | 有；依赖 LibreNMS 结构化规则和通用 MIB 引擎，逐个 OS key 的转换/过滤尚未全部核完 |
| Nokia | 有 | 20 | `TROPIC-OPTICALPORT-MIB`、`TROPIC-PSD-MIB`、`TROPIC-FAN-MIB`、`TIMETRA-CHASSIS-MIB` | 有；Nokia 1830 `.4/.5` /10 与 admin-up 的旧光模块逻辑已对到 LibreNMS；Nokia 其他 OS key 不等于 1830 已覆盖 |
| Aruba | 有 | 16 | `ARUBAWIRED-PM-MIB`、`ARUBAWIRED-TEMPSENSOR-MIB`、`ARUBAWIRED-POWERSUPPLY-MIB` | 有；AOS-CX 光功率/lane 由 pinned YAML、本地 MIB 和统一硬件探测器采集；其他 Aruba OS key 按各自规则能力状态报告 |
| Extreme Networks | 有 | 8 | `S5-CHASSIS-MIB`、`ENTERASYS-RESOURCE-UTILIZATION-MIB`、`EXTREME-SYSTEM-MIB` | 有；规则引擎覆盖但需核 OS key 及不支持的 PHP/条件语义 |
| Ruckus | 有 | 3 | `RUCKUS-ZD-SYSTEM-MIB`、`RUCKUS-UNLEASHED-SYSTEM-MIB`、`RUCKUS-SYSTEM-MIB` | 有；通用 YAML/标准传感器路径，型号级适配未完成 |
| MikroTik | 有 | 1 | `MIKROTIK-MIB` | 有；通用 YAML/标准传感器路径，型号级适配未完成 |
| Ubiquiti | 有 | 9 | `UBNT-EdgeMAX-MIB`、`UBNT-UFIBER-MIB`、`UI-AF60-MIB` | 有；UniFi `unifi` 内存规则引用的 `FROGFOOT-RESOURCES-MIB` 不在 pinned bundle，两个相关内存 OID 明确 unsupported；其它 OS key 按规则/标准 MIB 能力状态报告 |
| D-Link | 有 | 4 | `DLINKSW-DDM-MIB`、`DLINKSW-ENTITY-EXT-MIB`、`EQUIPMENT-MIB` | 有；有 DDM/硬件 MIB 和结构化规则，具体 DDM 转换/索引路径待核 |
| TP-Link | 有 | 8 | `TPLINK-DDMSTATUS-MIB`、RX/TX/温度/电压/偏置电流 threshold MIB | 有；有 DDM 相关 MIB/规则，具体读取与 threshold 展示仍待核 |
| Dell | 有 | 12 | `DELL-NETWORKING-CHASSIS-MIB`、`DELLEMC-OS10-CHASSIS-MIB` | 有；需区分网络 OS 与 iDRAC/存储类 MIB 规则，不以文件存在作为已采集 |
| Brocade | 有 | 6 | `SW-MIB`、`FOUNDRY-SN-AGENT-MIB`、`FOUNDRY-SN-STACKING-MIB` | 有；依赖通用规则/传感器语义，型号级适配未完成 |
| Ciena | 有 | 14 | `CIENA-WS-XCVR-MIB`、`CIENA-CES-PORT-XCVR-MIB`、`WWP-LEOS-PORT-XCVR-MIB`、`NORTEL-OPTICAL-PM-MIB` | 有；有多套平台和光模块 MIB，不能把一家厂商等同一套 OID；逐 OS key 适配未完成 |
| Alcatel-Lucent Enterprise | 有 | 10 | `A4400-CPU-MIB`、`ALCATEL-IND1-CHASSIS-MIB`、`ALCATEL-IND1-HEALTH-MIB` | 有；通用规则和标准传感器路径，型号级覆盖需继续审计 |
| Allied Telesis | 有 | 4 | `AT-ENVMONv2-MIB`、`AT-PLUGGABLE-DIAGNOSTICS-MIB` | 有；通用规则可用，光模块/环境规则逐项适配未完成 |
| Edgecore | 有（OcNOS 以 `ocnos` 识别） | 0 | 无 Edgecore scope MIB 收录 | 无结构化 OS 硬件定义；当前走标准 MIB/上游 profile 识别，OcNOS 与业务厂商映射需保留证据 |

上述 MIB 文件的完整 217 项模块名、manifest bundle 路径、LibreNMS 原始路径及 SHA-256 以 `backend/vendor/librenms/source-manifest.json` 为准。表中示例是硬件相关代表项，不是全量清单。

## 4. 当前采集链路和任务进度

### 已有实现

1. **本地来源包**：已固定 LibreNMS commit，将选定 OS identity/discovery YAML 和 217 个 MIB 文件放入项目；文件 SHA 和 upstream 路径记录在 manifest。
2. **规则导入/解释**：`librenms_rule_service.py` 保留 OS key、来源 commit/path、结构化硬件定义和诊断；已支持一部分 OID、索引、skip 条件、状态映射和 user_func。遇到 PHP-only 或未实现语义时保留“不支持/部分”状态，不应伪报成功。
3. **统一硬件清单**：`snmp_hardware_probe_service.py` 探测标准 HOST-RESOURCES/ENTITY-SENSOR 和 LibreNMS YAML 定义，保留 SNMP 表索引、来源、换算与轮询计划；`snmp_hardware_inventory_service.py` 管理规范化样本和 exporter。
4. **Comware 补充适配**：H3C 专用 PHP 逻辑通过 `_probe_h3c_comware_transceivers` 并入新硬件清单，覆盖 DDM 诊断存在、IF-MIB admin-up、RX/TX/温度/电压/电流及阈值比例。它只表示这组规则有代码适配，不代表所有 H3C CPU/内存/板卡都完整。
5. **Grafana 路径**：`/hardware-metrics` 暴露 `nexora_hw_*` 指标，dashboard generator 和 `nexora-network-device.json` 已使用规范化 CPU、内存、温度、风扇、部件状态、光功率、质量/能力状态指标；设备页面已加入单设备 Grafana 深链。
6. **光模块查询入口**：旧 `collect_optical_snmp()` 及其按品牌 OID 分支已删除。设备运维数据和平台 `get_transceivers` 动作只调用 `snmp_librenms_optical_service.py`，复用身份解析、标准 MIB 与本地 LibreNMS 硬件探测，再投影成兼容记录。光模块投影仅在存在显式接口映射时输出 `ifIndex`，不把 `entPhysicalIndex` 冒充接口索引。Cisco IOS-XR watts→dBm 转换已并入标准 ENTITY-SENSOR 硬件探测；ArubaOS-CX lane 与 H3C Comware 走本地规则/已审查适配。

### 统一后的光模块路径

- 后台发现将标准 ENTITY-SENSOR 与 LibreNMS OS discovery YAML 结果写入硬件清单；后台轮询通过 `poll_hardware_inventory()` 更新样本，Grafana 导出 `nexora_hw_*`。
- 手动设备运维数据和平台 `get_transceivers` 动作由 `snmp_librenms_optical_service.py` 调用同一设备发现/硬件探测入口，再把光模块传感器投影为原有 API 记录字段。
- ArubaOS-CX lane 规则由 pinned `arubaos-cx.yaml` 和本地 MIB 驱动；H3C Comware 继续用已接入清单的 LibreNMS 对齐适配；Cisco IOS-XR watts→dBm 转换现在进入标准硬件探测结果和轮询计划。
- 这统一了规则来源和采集实现，但每个 OS key 的 YAML 函数、过滤、实体关联仍以 capability 状态为准。没有实机验证前，不能报告厂商覆盖已完整验收。

### 光模块来源审计状态

| OS/profile | 新路径使用的来源 | 新路径状态/已知限制 |
|---|---|---|
| H3C Comware | pinned LibreNMS Comware PHP 规则和 `HH3C-TRANSCEIVER-INFO-MIB` | 新清单适配保留诊断列、admin-up、换算和索引；未做设备验证 |
| Cisco / IOS-XR | 标准 ENTITY-SENSOR 与 pinned Cisco sensor 规则 | IOS-XR watts→dBm 已进入发现和轮询计划；只有明确的 ENTITY/IF-MIB 关联才输出接口索引 |
| Huawei VRP | pinned `vrp.yaml` 与本地 Huawei MIB | `.32/.33` lane 列、除数 100、正/非正哨兵过滤和 `uw_to_dbm` 已在源码及 allowlist 中逐项对应；设备端物理实体/接口映射未验证 |
| Juniper | pinned `junos.yaml` 与本地 Juniper MIB | classic DOM、module lane 和 IFOPTICS Rx/Tx 三组来源已核对；全部用 YAML 索引/比例，具体型号表索引仍需设备确认 |
| Ruijie | pinned `ruijie.yaml` 与本地 Ruijie MIB | `.76/.81`、除数 100、DDM 状态、RX `-10000` 哨兵和温度 0 过滤已核对；上游 TX 规则的哨兵条件也读取 RX 列，按原 YAML 保留 |
| Raisecom ROS/legacy | pinned OS discovery YAML 与本地 Optical Transceiver MIB | 新路径仅执行可解析且支持的 YAML 定义；索引与状态语义需要型号数据确认 |
| Arista | 标准 ENTITY-SENSOR 与 pinned OS discovery 规则 | 只使用类型/状态及名称可判定的标准光功率；不再用旧描述猜测品牌私有 DOM 指标 |
| Nokia 1830 | pinned Nokia OS discovery YAML 与本地 TROPIC MIB | 新入口按 OS 规则读取；旧专用 `.4/.5` 硬编码列已移除，是否有数据取决于具体 OS YAML |
| ZTE | pinned `zxr10.yaml` 与本地 ZTE MIB | `zxr10.yaml` 没有 transceiver 定义；只使用设备实际报告的标准 ENTITY-SENSOR 光功率，不保留旧 ZTE 私有分支 |
| ArubaOS-CX | pinned `arubaos-cx.yaml` 与 `ARUBAWIRED-PM-MIB` | lane 索引和规则换算由同一 LibreNMS 硬件探测器处理；接口索引未知时保留实体/索引信息，不伪造 `ifIndex` |

旧 collector 代码及其专用光模块 adapter 已删除，旧入口的全部调用点已迁移至 LibreNMS 服务；历史文档仍可能记载当时的实现，不作为当前运行路径。新入口只使用标准 MIB、pinned LibreNMS 规则和明确保留在硬件探测器中的来源适配；不保证旧分支覆盖过的每家设备都有相同结果。静态源码层面没有厂商可被报告为“已完整实现并实机验收”。

## 5. 继续工作的顺序

1. **统一光模块链路**：两个 API 消费点都调用 LibreNMS 规则/标准 MIB 探测；增加了不把 `entPhysicalIndex` 投影为 `ifIndex` 的约束。采集换算按 `poll_plan` 使用规则；具体接口/lane 映射仍依赖设备数据，未做设备验证。
2. **明确光模块规则来源**：已按 pinned YAML/MIB 核对 Huawei `.32/.33` 与 `uw_to_dbm`、Juniper DOM/lane/IFOPTICS、Ruijie `.76/.81` 和 sentinel、ZTE `zxr10.yaml` 无 transceiver 定义；Ruijie TX YAML 使用 RX 哨兵列，当前按源文件保留。详见第 4 节。
3. **生成 OS 能力矩阵**：[`librenms-hardware-profile-capability-matrix.md`](librenms-hardware-profile-capability-matrix.md) 列出全部 136 个 detection profile、122 个 discovery YAML 的定义数、OID 来源类别、函数/过滤兼容、状态/阈值、端口标记和静态 poll 候选。矩阵不把 MIB 模块存在等同于符号解析或实机采集成功。
4. **处理缺失 MIB 引用**：已确认 UniFi `unifi` memory rule 的 `total`/`free` 均引用缺失的 `FROGFOOT-RESOURCES-MIB`；bundle 不含该模块，探测器将其 definition/capability 标为 unsupported，不编造替代 OID。本轮未扩大精选 MIB 包含范围。
5. **坚持范围边界**：只改硬件/光模块；公共接口 OID 和接口采集流程不在改动范围。

## 6. 工作范围与验证边界

- 新增/修改集中在 MIB 快照/规则导入、硬件 inventory/probe/poll、Grafana hardware metrics/dashboard、H3C/Aruba/Cisco/Raisecom 光模块规则等路径。工作树里还存在与本任务无关的既有改动；继续时不要清理或覆盖。
- 本轮新增/核对：旧 `snmp_optical_service.py`、按品牌光模块 adapter、旧 API 测试引用已清除，调用点已迁移到本地 LibreNMS 光模块投影服务；Cisco IOS-XR 转换并入标准 ENTITY-SENSOR 探测/轮询计划。
- LibreNMS optical service、运维入口、平台动作、规则、硬件 probe/inventory、Grafana metrics 与 monitoring compiler 聚焦测试：70 passed；MIB sparse source refresh 检查：1 passed。`npm run lint` (`tsc --noEmit`)、MIB manifest SHA、dashboard JSON、Python 编译和 `git diff --check` 通过。
- 未运行 Docker、SNMP 设备或 Grafana/VictoriaMetrics 环境验证。
- 用户已授权在代码检查通过后直接 push；本文件记录实现范围与验证边界，不追踪 Git 提交状态。
