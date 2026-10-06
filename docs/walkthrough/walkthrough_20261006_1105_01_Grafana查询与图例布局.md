# Grafana 查询与图例布局执行记录

## 完成摘要
- 修复 01 总览与 03 无线看板共用的在线客户端查询。controller/SSID 聚合各多一个右括号，inventory 表达式展开两次后最终多四个右括号；实际 VM 解析器复现旧查询的 422 `unparsed data left`。
- 保留客户端总数的既有来源优先级：controller 总数 → SSID 合计 → legacy SNMP；真实 0 不触发回退，完全缺失保持无数据。
- 无线面板统一为 `SSID 客户端 Top 20`。按同一设备和 SSID 优先取 controller SSID，缺失时汇总具有非空 SSID 名称的 BSS，避免同名双来源重复。BSS 面板保留 AP/Radio/WLAN 粒度，去掉 Huawei/H3C 的额外硬编码过滤。
- 02 设备详情的 CPU、内存、温度、风扇、功率、光功率六个趋势面板改为 bottom/list 图例，去掉 Last/Max/Mean 三列。保留完整传感器系列名、悬浮对比、下方当前读数明细和原有曲线数据。
- 生成前验证所有查询的分组/字符串闭合，全部 12 份预检通过后才写文件，避免错误查询或部分生成产物进入 provisioning。

## 实际文件
- `monitoring/grafana/generate_dashboards.py`：两个无线 helper、六个图例选项、SSID/BSS 文案、查询闭合校验与写前全量预检。
- `monitoring/grafana/dashboard_presentation_v2.json`：SSID 面板和 row 的统一标题。
- `monitoring/grafana/dashboards/nexora-network-overview.json`
- `monitoring/grafana/dashboards/nexora-network-device.json`
- `monitoring/grafana/dashboards/nexora-network-wireless.json`
- `backend/tests/monitoring/test_grafana_queries.py`：新增无数据库依赖的语法/展示/预检回归。
- `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`：更新旧标题和厂商硬过滤断言，补充 SSID/BSS 回退契约。

## 数据契约与展示依据
- Huawei 的控制器 SSID 来源由 `snmp_hardware_probe_service.py` 输出 `wireless_ssid`；H3C 在 `wireless_bss` 行携带 SSID；Huawei 的 BSS 行可能没有 SSID。统一列表过滤空 SSID，不能将两类源直接相加。
- 设备/SSID 匹配仍使用原有 `site_name,vendor,role,hostname`，SSID 明细再加 `ssid`。本轮不改 exporter、数据库或网络设备配置。
- 对照 Grafana 12.1.0 的 [VizLayout 源码](https://github.com/grafana/grafana/blob/v12.1.0/packages/grafana-ui/src/components/VizLayout/VizLayout.tsx)：底部图例默认最多占可视区域高度 35%，超出内容滚动；右侧图例默认可占宽度 60%。本轮使用该版本已有的 list/bottom 选项，没有依赖新版 legend limit/overflow 功能。
- 没有新增视觉告警阈值。保留 datasource UID、Dashboard UID、Panel IDs、单位、变量、transformations 和 Data Links。

## 验证命令与结果
1. `.venv/Scripts/python.exe monitoring/grafana/generate_dashboards.py`
   - 12 份 JSON 全部成功生成；12 UID / 253 panels 的唯一性、布局和查询闭合校验通过。
2. `.venv/Scripts/python.exe -m py_compile monitoring/grafana/generate_dashboards.py backend/tests/monitoring/test_grafana_queries.py`
   - 通过。
3. `.venv/Scripts/python.exe -m pytest --noconftest -q backend/tests/monitoring/test_grafana_queries.py backend/tests/monitoring/test_grafana_v2_presentation.py backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
   - **66 passed in 0.86s**。`--noconftest` 避免加载会初始化 app DB 的 backend 全局 fixture；三份测试仅检查查询、展示、指标契约，不触及持久化。
   - 首轮有一个 SSID description 超过现有 60 字符上限的失败，缩短文案后通过，没有放宽断言。
4. `.venv/Scripts/python.exe C:/Users/NINGMEI/AppData/Local/Temp/nexora-grafana-validation-20261006/validate_vm_queries.py`
   - 使用官方 release 的 **VictoriaMetrics v1.103.0** Windows 二进制，与 Compose pin 一致。临时存储、仅监听 127.0.0.1:58428，退出时终止子进程；确认剩余 listener 为 0。
   - 旧 helper 查询 **422 可复现**；新完整 catalog **262 条 target 查询全部接受**。
   - 五组结果断言覆盖：controller/SSID/legacy 回退，真实 0 保留，全部缺失返回空，同 SSID controller 与 BSS 重叠去重，多 AP BSS 汇总，空/缺失 SSID 排除，按同设备不同 SSID 独立回退。
   - 临时 fixture 导入后的查询显式关闭缓存，样本时间置于两分钟前；初始测试空结果来自 fixture 可见性/缓存时序，处理后通过，并未改业务查询。详细脚本与 `validation-result.json` 保留在上述临时目录。
5. 对全部 12 份生成 JSON 与 HEAD 做字段白名单比较。
   - 仅 **13 个 panel** 的授权字段变化；另 **9 个 dashboard 完全未变化**。三份看板的变量、ID、datasource、transformations、链接和单位均保持；设备详情查询未变化。
6. `git diff --check -- monitoring/grafana backend/tests/monitoring/test_grafana_queries.py backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
   - 通过。Git 仅提示项目 CRLF 转换策略，没有空白错误。
7. `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`
   - **0 violations / PASS**。

## 浏览器核对与部署包
- 浏览器打开用户已登录的远端 `https://192.168.204.128`：确认 01/03 客户端总数和趋势的 Panel status 错误，02 右侧三列图例挤压图形。
- 远端设备详情 JSON Model 当前 version 为 14，与本地生成 version 30 存在差异。没有把本地整份看板覆盖保存到远端；临时 Make editable 与保存预览已取消并丢弃，回到只读看板。
- 包：`artifacts/grafana-dashboard-update-20261006_1105.zip`，71,174 字节，包含三份受影响 JSON、两份作者源和应用说明；ZIP CRC 校验通过。
- SHA256：`DAA0E250966551D22B59303B1BFCF25CACCFD2839A7E171D428B184A0B1DE1F5`。
- Compose 从 Linux 主机项目目录 bind-mount dashboard JSON，repo provider 的扫描间隔为 10 秒。把更新包同步到实际挂载的项目目录后，可通过文件 provisioning 自动加载；通常无需重建 app/Grafana 镜像。若远端目录或 provider 与仓库配置不同，以其实际配置为准。

## 未执行验证与剩余边界
- 没有访问 Linux 主机 shell、更新远端挂载文件、提交 Git、推送或部署生产服务。远端仍运行旧 JSON；本地包是可同步的成品。
- 没有在更新后的远端 Grafana 做曲线渲染验收；已验证 JSON 配置、Grafana 12.1.0 选项与本地 VM 执行结果。未运行无关前端 build 和全 backend 回归。
- 无真实 SSID/BSS 设备采集时仍显示无数据，去掉厂商过滤不会生成缺失指标。
- 既有四个设备标签可能合并同标签但不同资产/租户；legacy 多来源也依赖采集侧互斥。本轮保留身份和总数口径，作为后续专题审查边界。
- 回滚时恢复备份的两份作者源和三份 JSON；其他九份看板及用户已有 YunShan/开发端口/skill 修改均已保留。

## Agent 分工结果
- `grafana_query_audit`：只读定位右括号错误、controller/SSID/legacy 优先级、Huawei/H3C SSID/BSS 数据标签与既有身份边界。
- `grafana_validation_audit`：仅新增聚焦测试文件，确认无 DB 的测试运行方式和官方 VM Windows release 支持；没有执行公共验证。
- 主 Agent：作者源、旧测试更新、生成产物、真实 VM fixture 验证、全 catalog diff 审查、浏览器核对、部署包与归档；公共验证只在集成后执行。
