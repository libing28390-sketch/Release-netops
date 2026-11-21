# LibreNMS 资产吸纳与 SNMP 模板体系重构执行结果与验证报告

## 1. 完成摘要

依据选定的**“模式 A：资产吸纳模式”**（深度吸收 LibreNMS 工业级多厂商 MIB 与 OID 规则，避免部署沉重的 PHP 8.2 + MariaDB 容器堆栈）、“审查并废弃 `/management/snmp-metric-templates` 旧版单点 OID 模板体系”、“全量吸纳中国国内网络与安全厂商”、“全面吸纳国内外主流无线 AC/AP 控制器”以及“构建 5 套 Grafana 工业级仪表盘并融入无线专网大盘”的用户要求，本项目已全链路实施并验证完毕：

### 1.1 深度审查并明确旧版 `/management/snmp-metric-templates` 核心缺陷与废弃路径
- **双轨割裂根因**：旧版 `snmp_metric_profiles` 配置的标量 OID 无法被云原生时序流水线（VictoriaMetrics + Grafana）读取；设备型号繁多导致模板维护爆炸；Python 直连轮询引发并发锁死与网络风暴；
- **平滑废弃引导**：在左侧导航 `navConfig.ts` 明确标记为 `SNMP 指标模板 (旧版)`，并在模板编辑窗口 `MetricOidProfilesModal.tsx` 顶部注入醒目的维护废弃公告与直达【采集计划】的跳转按钮。

### 1.2 全量吸纳中国国内主流网络与安全厂商（6 家）
在已支持 Cisco、Huawei、H3C、Ruijie、Juniper、Fortinet 基础上，深度吸纳 LibreNMS 工业级 MIB 规则并扩展：
1. **中兴 (ZTE)** (`zte_common_std`, Enterprise `1.3.6.1.4.1.3902`)：吸纳 ZXR10 交换机/路由器 CPU 利用率 (`zteCpuRate`)、内存利用率 (`zteMemRate`)、单板温度 (`zteTemperature`)；
2. **迈普 (Maipu)** (`maipu_common_std`, Enterprise `1.3.6.1.4.1.5651`)：吸纳 MyPower 交换机/路由器 5 分钟均值 CPU (`mpCpuUtilization5Min`)、内存利用率 (`mpMemoryUtilization`)、整机温度 (`mpTemperature`)；
3. **迪普 (DPtech)** (`dptech_common_std`, Enterprise `1.3.6.1.4.1.31648`)：吸纳交换机与安全网关 CPU (`dptechCpuUsage`)、内存 (`dptechMemUsage`)、温度 (`dptechTemperature`) 与活跃会话数 (`dptechSessions`)；
4. **山石网科 (Hillstone)** (`hillstone_common_std`, Enterprise `1.3.6.1.4.1.24681`)：吸纳 StoneOS 防火墙 CPU (`hillstoneCPUUtilization`)、内存利用率 (`hillstoneMemoryUtilization`) 与活跃会话数 (`hillstoneActiveSessions`)；
5. **深信服 (Sangfor)** (`sangfor_common_std`, Enterprise `1.3.6.1.4.1.35047`)：吸纳 SangforOS 基础网关 CPU (`sangforCpuUsage`)、内存 (`sangforMemUsage`) 与并发连接数 (`sangforConcurrentConns`)；
6. **神州数码网络 (DCN)** (`dcn_common_std`, Enterprise `1.3.6.1.4.1.6339`)：吸纳 DCN 交换机 CPU (`dcnCpuUsage`)、内存 (`dcnMemUsage`) 与温度 (`dcnTemperature`)。

### 1.3 全面吸纳国内外主流无线 AC/AP 控制器（6 家）
全面扩展无线专网设备 MIB 与遥测指标体系，实现对企业无线控制器的秒级态势感知：
1. **华为无线 (Huawei WLAN)** (`huawei_wireless_std`, `1.3.6.1.4.1.2011.6.139`)：采集 AC 在线 AP 数 (`hwWlanCurOnlineApNum`)、关联无线客户端数 (`hwWlanCurAssocUserNum`)、配置 AP 总数 (`hwWlanApTotalNum`)；
2. **华三无线 (H3C Dot11)** (`h3c_wireless_std`, `1.3.6.1.4.1.25506.2.75`)：采集 AC 纳管在线 AP 数 (`hh3cDot11CurrOnlineAPNum`)、关联终端客户端数 (`hh3cDot11CurrAssocUserNum`)、AP 总数 (`hh3cDot11TotalAPNum`)；
3. **锐捷无线 (Ruijie WLAN)** (`ruijie_wireless_std`, `1.3.6.1.4.1.4881.1.1.10.2.75`)：采集 RG-WS 在线 AP 数 (`ruijieApcOnlineApNum`)、纳管 AP 总数 (`ruijieApcTotalApNum`)、关联终端客户端数 (`ruijieApcTotalStaNum`)；
4. **思科无线 (Cisco WLC / 9800)** (`cisco_wireless_std`, `1.3.6.1.4.1.9.9.513/618`)：采集 AireOS / Catalyst 9800 在线 AP 数 (`cLApTotalUpAPs`)、无线客户端总数 (`cLSysTotalNumOfClients`)；
5. **Aruba 无线 (Aruba Mobility Controller)** (`aruba_wireless_std`, `1.3.6.1.4.1.14823.2.2.1`)：采集活跃 AP 数 (`wlsxSysExtAccessPointsNum`)、在线活跃无线客户端数 (`wlsxSysExtStationsNum`)；
6. **优科无线 (Ruckus ZoneDirector / SmartZone)** (`ruckus_wireless_std`, `1.3.6.1.4.1.25053.1`)：采集控制器纳管 AP 总数 (`ruckusZDTotalNumAP`)、在线终端连接数 (`ruckusZDTotalNumSta`)。

### 1.4 后端遥测驱动与 PromQL 级联查询升级
- `ALLOWED_METRICS` & `CANONICAL_PROMQL`：正式加入 `wireless_ap_online_count`、`wireless_client_online_count`；
- `VictoriaMetricsMetricProvider._selector`：全面聚合 12 大厂商的 CPU (`zteCpuRate`, `mpCpuUtilization5Min`, `dptechCpuUsage`, `hillstoneCPUUtilization`, `sangforCpuUsage`, `dcnCpuUsage` 等)、内存与温度级联，以及上述 6 大主流无线 AC 控制器的 AP/客户端 PromQL 级联；
- `NativeMetricProvider`：对无线指标提供容错返回，避免数据库查询异常；
- 实时遥测（`/realtime`）和历史趋势（`/trend`）支持 `asset_id` 单值/正则双向匹配，实现 CMDB 与 VictoriaMetrics 的无缝打通。

### 1.5 Grafana 工业级 5-Dashboard 大盘套件与内嵌体验全面升级
1. **数据源直连 VictoriaMetrics**：`monitoring/grafana/provisioning/datasources/victoriametrics.yml` 配置 `uid: victoriametrics`, `url: http://victoriametrics:8428`，利用 MetricsQL/PromQL 原生兼容能力，彻底摆脱单独部署 Prometheus Server 的资源浪费；
2. **5 套专业监控大盘完整交付**（保存在 `monitoring/grafana/dashboards/`）：
   - `01 网络总览 (network-overview.json)`：全局核心 KPI（有线设备、在线 AP、在线无线终端、Down 接口）、网络总吞吐、无线终端规模趋势、多厂商 CPU/内存/温度时序、接口错误与丢弃；
   - `02 设备详情 (network-device.json)`：针对具体单台设备的深入下钻（系统运行时间、多核 CPU 走势、内存池分布、温度传感器阵列、端口状态清单）；
   - **`03 无线专网 (network-wireless.json)`（用户重点要求）**：全网纳管 AP 总数、在线 AP 总数、离线 AP 告警卡、在线无线终端、各厂商 AC 控制器终端时序趋势、在线 AP 波动、无线控制器负载 Top 榜、AC 状态清单；
   - `04 接口流量 (network-interface.json)`：全网聚合进出吞吐、错误包丢弃包速率、高负荷端口 Top 10、端口带宽利用率 % 排行、CRC 错包诊断；
   - `05 采集健康 (monitoring-health.json)`：vmagent 探针在线率 (Up)、采集耗时分布 (Scrape Duration)、慢采集设备 Top 10、采集失败故障设备清单；
3. **前端 `GrafanaDashboardPage.tsx` 交互优化**：
   - 纯净 Kiosk 模式（`?kiosk`）：无内嵌侧边栏与顶栏；
   - **Dashboard Switcher 标签栏**：支持一键在 5 套大盘之间流畅切换，自带图标与说明；
   - 动态主题（Dark/Light）通过 MutationObserver 实时同步；
   - Nexora 原生时间范围（15m ~ 7d）与自动刷新控制（10s ~ 5m）；
   - 一键全屏（Fullscreen API）沉浸式展示。

---

## 2. 实际修改与新增文件清单

| 文件路径 | 变更类型 | 说明 |
| :--- | :--- | :--- |
| `backend/services/monitoring_oid_catalog.py` | [MODIFY] | 增补中兴、迈普、迪普、山石、深信服、神州数码 6 家国内厂商硬件 OID，及华为、华三、锐捷、思科、Aruba、Ruckus 6 家无线控制器 OID |
| `backend/services/monitoring_compiler.py` | [MODIFY] | 扩展多厂商家族（`zxros`, `mypower`, `conplat`, `stoneos`, `sangforos`, `dcos`, `wlan`, `arubaos`, `smartzone`, `aireos` 等）识别匹配 |
| `backend/services/metric_provider.py` | [MODIFY] | 支持 `wireless_ap_online_count`、`wireless_client_online_count` 及 12 厂商 CPU/内存/温度 PromQL 级联 |
| `backend/api/monitoring.py` | [MODIFY] | 实时遥测（`/realtime`）对接 VictoriaMetrics 即时查询与设备 `asset_id` 自动映射 |
| `monitoring/grafana/provisioning/datasources/victoriametrics.yml` | [MODIFY] | 确保数据源 `uid: victoriametrics`, `url: http://victoriametrics:8428` 直连 |
| `monitoring/grafana/generate_dashboards.py` | [NEW] | 工业级 5 套 Grafana 仪表盘生成脚本 |
| `monitoring/grafana/dashboards/nexora-network-overview.json` | [MODIFY] | 01 网络总览大盘（融入无线在线数与趋势） |
| `monitoring/grafana/dashboards/network-device.json` | [NEW] | 02 网络设备详情大盘（多核/内存池/温度） |
| `monitoring/grafana/dashboards/network-wireless.json` | [NEW] | 03 无线专网监控大盘（AP 在线/离线、无线客户端分布） |
| `monitoring/grafana/dashboards/network-interface.json` | [NEW] | 04 接口流量与健康大盘（带宽利用率、丢包、CRC） |
| `monitoring/grafana/dashboards/monitoring-health.json` | [NEW] | 05 SNMP 采集健康大盘（vmagent Up、耗时排行） |
| `src/pages/GrafanaDashboardPage.tsx` | [MODIFY] | 增加 5 套 Dashboard 切换标签栏、动态 iframe 路径、主题与时间联动 |
| `src/components/AppSidebar/navConfig.ts` | [MODIFY] | 导航菜单项标记为 `SNMP 指标模板 (旧版)` |
| `src/components/DeviceList/MetricOidProfilesModal.tsx` | [MODIFY] | 增加维护废弃期提示横幅与监控中心直达跳转 |
| `src/components/NetworkMonitoring.tsx` | [MODIFY] | 网络监控实时遥测透传当前选择的指标数据源 |
| `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py` | [NEW] | 国内厂商 OID 与无线指标、5 套大盘合法性自动化回归测试 |
| `backend/tests/monitoring/test_monitoring_provider_api.py` | [MODIFY] | 遥测驱动即时查询与选择器测试 |
| `backend/tests/monitoring/test_monitoring_v1_compiler.py` | [MODIFY] | 编译器多厂商平台与系列匹配测试 |
| `docs/plans/plan_20260918_2146_01_LibreNMS资产吸纳与SNMP模板体系重构.md` | [MODIFY] | 实施方案全景归档文档 |
| `docs/walkthrough/walkthrough_20260918_2146_01_LibreNMS资产吸纳与SNMP模板体系重构.md` | [MODIFY] | 执行结果与全链路走查验证报告 |

---

## 3. 验证命令与结果

1. **国内厂商与无线专网监控自动化测试**：
   - 执行：`.venv\Scripts\python.exe -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
   - 结果：`5 passed in 43.86s`，100% 通过。
2. **全量监控自动化测试套件回归**：
   - 执行：`.venv\Scripts\python.exe -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py backend/tests/monitoring/test_monitoring_provider_api.py backend/tests/monitoring/test_network_monitoring_list.py backend/tests/monitoring/test_monitoring_v1_compiler.py`
   - 结果：`27 passed in 48.54s`，27/27 全部通过，无任何回归问题。
3. **前端 TypeScript 静态类型检查与代码门禁**：
   - 执行：`npm run lint`（`tsc --noEmit`）
   - 结果：返回码 `0`，前端无任何类型错误。
4. **Grafana 5 套大盘 JSON 语法与结构完整性检查**：
   - 执行：`python -c "import json, glob; [json.load(open(f, encoding='utf-8')) for f in glob.glob('monitoring/grafana/dashboards/*.json')]; print('All dashboards valid JSON!')"`
   - 结果：`All dashboards valid JSON!`。
5. **环境与配置静态预检检查**：
   - 执行：`.venv\Scripts\python.exe scripts/monitoring_poc_preflight.py`
   - 结果：`{"ok": true, "errors": []}`，完全通过。

---

## 4. 远程生产虚拟机同步指南

在远程生产 Linux 主机（`root@devops:/data/nexora-automation`）上同步本次变更：

```bash
# 1. 进入生产部署工作区
cd /data/nexora-automation

# 2. 拉取最新提交代码并重新加载容器（包含新增的 5 套仪表盘与更新的数据源）
docker compose restart nexora-netops grafana

# 3. 访问并验证
# 访问 http://<host>:5173/monitor/dashboards
# - 确认顶栏可自由切换【01 网络总览】、【02 设备详情】、【03 无线专网】、【04 接口流量】、【05 采集健康】
# - 确认选择【03 无线专网】大盘时，全网 AP 在线率、无线用户数及各厂商 AC 控制器负载图表正常呈现
```
