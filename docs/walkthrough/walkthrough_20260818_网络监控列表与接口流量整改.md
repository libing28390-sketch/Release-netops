# 网络监控列表与接口流量整改

## 本次调整

- 网络监控左侧设备列表改为服务端搜索、区域/状态筛选和分页，每次只返回 30 台，不再把完整设备清单交给浏览器渲染。
- 采集健康与数据新鲜度卡片压缩为更紧凑的网格，提升状态文字对比度，并在中文界面显示“成功、失败、未配置”等中文状态。
- 接口实时表只返回并展示当前状态为 UP 的接口；汇总流量和实时趋势快照同步按 UP 接口计算。
- 采集器继续使用配对的 64 位 HC 计数器，必要时回退到配对的 32 位 IF-MIB 计数器，并排除 `InLoopBack`、`Register-Tunnel` 等虚拟接口。
- 页面将 `ifInErrors + ifOutErrors` 明确标为“错误包”，提示它不是厂商专用 CRC/FCS 计数；当前没有伪造 CRC 数值。

## CRC 与流量口径

`ifInErrors`/`ifOutErrors` 是 IF-MIB 定义的通用入/出方向错误报文计数，不等同于 CRC/FCS。实际 CRC 需要对应厂商和芯片的专用 MIB 或 CLI 字段，后续应按型号模板验证后再接入。

接口速率使用两次有效 SNMP Counter 采样的实际时间差计算，并检查计数器位宽、设备重启、回绕和物理速率上限；首个采样或异常采样不会生成虚假速率。

## 验证

- `.venv/Scripts/python.exe -m pytest backend/tests/monitoring/test_network_monitoring_list.py backend/tests/monitoring/test_device_health_dimensions.py backend/tests/snmp/test_snmp_metric_semantics.py backend/tests/snmp/test_snmp_walk_api.py -q`
  - 44 passed
- `npm run lint`
  - passed（TypeScript noEmit）
- `npm run build`
  - passed（Vite production build）
