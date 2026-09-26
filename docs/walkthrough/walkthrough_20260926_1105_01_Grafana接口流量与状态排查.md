# Grafana 九个看板全量核查与接口流量修复 Walkthrough

## 交付内容

修复本地 Grafana 看板生成源并重新生成 9 个看板 JSON；补充接口与无线看板回归断言；记录九个实时看板的页面数据和 Explore 查询结果。完整逐看板证据、根因和剩余事项见 [排查计划](../plans/plan_20260926_1105_01_Grafana接口流量与状态排查.md)。

## 确认的原因

- 设备下拉使用历史 ifOperStatus|up 序列上的 hostname，因此已移除设备的旧标签仍能进入下拉。刚重开 live 04 展开下拉，仍看到 23 个选项，包括 F1090-10、R10/R11/R12/R13/R14。新的 up 目标变量在 Explore 重复查询只返回当前 13 台 SNMP 主机且没有这些旧名称。仓库 Compose 中 Grafana 从 dashboards 只读挂载目录每 10 秒检查 provisioning；live 仍旧说明该实例未读到本地新文件或 provisioning 未成功。工作机没有 Docker 命令、本地服务端口或 live 容器日志，无法进一步区分。
- 04 的入/出流量查询在 group_left 右侧匹配到同一接口的多个元数据序列，VictoriaMetrics 返回 422。生成源将接口名和描述序列先按接口键聚合，修正后的流量查询重复验证能返回样本。
- 01 的旧关注条件将 ifOperStatus != 1 都计为异常。它是当前状态统计，不说明接口刚刚发生故障。生成源现在限定管理启用且运行状态明确为 DOWN，并说明空闲接口也可能出现。
- unclassified 是 CMDB 未给接口配置用途的分类值，不是健康状态。看板显示为“用途待确认”。
- 无线以及网络设备 CPU、内存、温度当前没有对应 VictoriaMetrics 样本；无线面板此前通过 or vector(0) 把缺样显示成零，本地生成源已移除无线零回退。静态代码显示厂商 assignment 会受平台/型号匹配、SNMP discovery 和 profile verification 门槛影响；因此缺样不等于设备不支持。具体运行目标/module assignment 尚无法读取。另发现 Grafana Cisco 温度 panel 未查询 exporter 已有的 entSensorValue，而原始值未经传感器类型/精度/单位规范化，暂不能直接加入摄氏度面板。
- 07 Linux 磁盘 Top10 和 D09 接口配置带宽表首次观察只见表头；重复打开同一时间范围后，D07 显示 3 个挂载点，D09 显示 R1/Et0/0 带宽 10 Mb/s。未复现持续缺数，首次未呈现的瞬时原因无法从只读页面确定。

## 九页复核简表

1. 01 网络总览：13 个目标、2 个站点、448 个接口；核对启用但运行 DOWN 的定义。
2. 02 网络设备：当前 R1 的 uptime 和端口状态可见；CPU/内存/温度源指标缺样。
3. 03 无线：无线指标族不存在，旧零值可能造成误读。
4. 04 接口流量与健康：实时流量类面板仍报 422；错误详情指出 SW6/Gi0/3/TO-R4 的 group_left 右侧出现一条带 CMDB 阈值/用途标签、一条不带这些标签的重复 ifName 序列。修正 join 在 Explore 返回数据。
5. 05 监控引擎健康：失败目标数为 0，失败列表为空符合当前健康状态。
6. 06 网络出口：旧设备选择为空；筛到 R1/Et0/0 后流量、利用率和质量统计均有数据。
7. 07 Linux：主机指标正常；磁盘 Top10 重复打开后显示 3 行。
8. 08 Windows：web-srv-02 的主要指标和表格均有数据。
9. 09 接口详情：R1/Et0/0 流量和质量数据正常；重复打开后带宽配置表显示 10 Mb/s。

## 无数据指标的采集链路追查

- D03 无线指标名与 catalog/exporter 定义匹配。最新迁移 m0243 将六家无线 variants 加入默认计划，但编译器在平台/型号不匹配，或缺少 discovery metrics 且 profile 未验证时会跳过 vendor-specific assignment。现场无样本不能单独证明没有控制器或设备不支持。
- D02 同样存在 vendor module assignment 门槛；仓库有厂商 OID 定义不代表运行时目标已经启用。提交的 SNMP target 文件为空模板，运行 target 来自 artifacts volume；工作机没有 Docker 命令或本地监控端口，无法读取 assignment、snapshot、manifest 或 scrape 错误。
- 现场只读核对顺序：设备 assignments → collector configs/snapshot 的 module 与目标 → latest metrics/VM 时序 → scrape 错误；目标在线且模块发布后仍无样本，再只读检查设备 OID 响应。

## 文件

- 生成逻辑：[generate_dashboards.py](../../monitoring/grafana/generate_dashboards.py)
- 回归测试：[test_domestic_and_wireless_monitoring.py](../../backend/tests/monitoring/test_domestic_and_wireless_monitoring.py)
- 生成物：monitoring/grafana/dashboards/ 中 9 份 Nexora JSON。

## 验证

- 定向测试：6 passed。
- Python 编译、生成器执行通过。
- 实时 Grafana 页面与 Explore 查询完成只读核查和重复查询。
- git diff --check 通过。
- 没有保存、发布或部署 live dashboard。需要先确认运行实例为何未采用本地新 JSON，再最终确认旧变量与 D04 页面已经更新。
