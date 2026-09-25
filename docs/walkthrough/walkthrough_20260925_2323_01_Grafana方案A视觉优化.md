# Grafana 方案 A 视觉优化（实施记录）

## 结果

按方案 A 完成 8 个既有看板的视觉统一，并新增 `09 接口详情` 下钻页。所有接口状态表均将 `1` 显示为绿色 `Up`、`2` 显示为红色 `down`；`0`、`3–7`、空值和 NaN 显示为灰色 `UNKNOWN`，不呈现原始状态数字。

`01 网络总览` 使用摘要、趋势、热点和异常分区；设备与接口表提供详情下钻。`04` 聚焦接口利用率、容量、链路质量和稳定性，补入 Current/24h Peak/24h P95、入/出利用率 Top20、错误/丢弃百分比、入向/出向/单播/组播/广播 PPS、24h/7d Flap 和 Last Change。

## 视觉与交互

- 入方向蓝色、出方向绿色、错误橙色、丢弃红色、广播黄色、组播紫色、PPS 青色；普通 Stat 使用中性蓝色，异常阈值仍使用黄/橙/红。
- 时序图统一为 2px 线宽、10% 填充、关闭点标记，右侧表格图例显示 Last、Max、Mean。
- 表格启用筛选、分页和短行高；利用率表使用 Gauge，状态列使用彩色文字。空值统一为“数据暂不可用”。
- `01` 异常接口表区分“当前无异常”和状态数据不可用；总览不堆叠接口级分析。
- `04` 保留利用率排行并移除重复的流量 TopN，容量表将百分比和带宽拆列并标明单位。
- 详情页 Data Link 会传递站点、厂商、设备角色、设备、接口角色、接口名和当前时间范围。

## 采集与 CMDB profile

- `interfaces` 增加接口角色与 warning/high/critical 百分比阈值，默认 `unclassified` 和 `60/75/90`；迁移版本为 252。
- CMDB 接口 API 提供 Operator 权限的监控 profile 更新，前端展示角色/阈值并校验严格递增区间。
- CMDB 接口列表和 profile 更新沿用 asset 资源的租户/站点授权范围；没有持久化 skeleton 主键的 IP 库合成行不显示编辑按钮。
- Monitoring V1 编译从 CMDB 读取 profile，并在 vmagent metric relabel 阶段按 asset 与 `ifName` 匹配，为接口指标加上接口角色和阈值标签；未配置的接口使用默认值。
- SNMP IF-MIB catalog、fallback exporter 和静态 exporter module 补充高容量包计数器及 `ifLastChange`；迁移 253 只在非空内置配置中追加缺失的 `ifLastChange`，保留运维人员对已有 OID/metrics 的编辑，并按最终 JSON 重算 hash；空配置仍完整 seed。
- 04 的多接口 Gauge 继续使用平台默认阈值；详情页的单接口面板用该接口阈值计算 `NORMAL/WARNING/HIGH/CRITICAL` 状态，容量表同时展示每接口阈值。
- Last Change 年龄通过同设备 `sysUpTime` 计算；标准采集基线同时启用 interface/system 模块，interface-only 的自定义计划可能没有该值。

## 文件范围

- `monitoring/grafana/generate_dashboards.py` 与 9 个生成 JSON（新增 `nexora-interface-detail.json`）。
- `backend/services/monitoring_compiler.py`、`backend/api/monitoring_v1.py`、`backend/services/monitoring_oid_catalog.py`、`monitoring/snmp-exporter/snmp.yml`。
- `backend/database/schema.py`、m0252/m0253、`backend/services/cmdb_service.py`、`backend/api/cmdb.py`、`src/pages/CmdbManagementTab.tsx`。
- 对应计划文档及 `handoff.md`。

## 验证与限制

- `.venv\Scripts\python.exe -m py_compile`：生成器、监控编译器、Monitoring V1 API、OID catalog 与两条迁移通过。
- `.venv\Scripts\python.exe monitoring\grafana\generate_dashboards.py`：成功生成 9 份 JSON。
- 一次性静态结构检查通过：全部 JSON 可解析、面板 ID 唯一、datasource UID 正确、接口状态映射完整、详情页变量/链接和关键 P1/P2 面板存在；面板网格无重叠。04 与详情页 PPS 图现在包含入向/出向方向总速率及单播/组播/广播分类。
- SNMP exporter YAML 解析与 `ifLastChange` OID/索引/lookup 检查通过；vmagent profile relabel 配置静态检查通过。
- 并行只读审查发现的 `ifAlias` selector 不匹配已改为设备级 selector；CMDB tenant/site scope 和合成库存行可编辑条件也已补齐。
- `git diff --check` 通过。迁移 PostgreSQL 回归检查和跨租户快照读取检查在本轮聚焦验证中执行；未应用数据库迁移，未部署线上 Grafana，也未连接真实设备。
- PPS 图使用已采集的 Counter64 `ifHC*Pkts`。不支持/未暴露这些计数器的接口会显示无数据；IF-MIB 旧式 non-unicast 计数无法可靠拆分为组播与广播，因此不伪造分类回退。结构检查不能代替 Grafana 12.1.0 的页面渲染和实际 PromQL 结果验收。`ifLastChange` 由 SNMP TimeTicks 与 `sysUpTime` 推算；Flap 计数受采样间隔限制。
