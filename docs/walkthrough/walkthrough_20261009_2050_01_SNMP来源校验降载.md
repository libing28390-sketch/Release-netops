# SNMP 来源校验降载走查

## 完成摘要

定位到持续高 CPU 的一个直接原因：LibreNMS 硬件轮询循环每 10 秒运行一次，逐条读取传感器并重复验证相同来源证明。验证过程反复解析并检查 vendor bundle 路径。当前数据约 3,896 个传感器行，部署早期记录约 602 个活动传感器，规则清单扩大放大了重复工作。

采样文件由 `py-spy` 临时写入服务器 `/tmp`，采样后删除；未改容器、配置或设备。连续 30 秒观察 CPU 仍约 100–140%。60 秒采样期间同时发生配置备份/API 请求，视为额外负载；这些请求结束后 CPU 仍高。高负载栈确认包含 `_load_active_sensors`、`is_trusted_hardware_sensor`、`_entry_is_verified` 和 `Path.resolve`。

已在本地代码中为每台设备一次传感器加载增加 provenance 去重。同一来源只做一次完整可信验证；不同来源继续分别验证，拒绝结果也只在本次设备加载中复用。SNMP 周期、规则内容、校验逻辑和输出没有改变。

## 修改文件

- `backend/services/snmp_hardware_poller_service.py`：按完整 provenance key 缓存当前设备加载中的信任判定。
- `backend/services/librenms_source_policy.py`：公开现有 provenance key helper，供轮询器复用。
- `backend/tests/monitoring/test_snmp_hardware_poller_service.py`：覆盖相同/不同来源、拒绝结果、禁用传感器及旧版本传感器。

## 验证

- 定向测试：`27 passed`。
- 扩展回归：`72 passed in 92.42s`，覆盖轮询器、来源策略、无线规则/适配器和 Grafana 指标导出。
- `git diff --check`：通过；仅报告 Git 将 LF 转换 CRLF 的提示。
- Ruff 未安装在项目 `.venv`，未运行。

## 深化核对

- 用户提供的 15 分钟 Grafana 图显示 `nexora-netops` 持续约 95–117%（图表标尺为单核 100%），其他容器大多低于 8%。这与生产 `py-spy` 中硬件轮询器的来源校验热点一致，说明负载集中在应用 CPU；本次不判断 SNMP 返回值是否符合真实设备。
- `/hardware-metrics` 每分钟导出约 3,902 条传感器记录，响应约 9.35 MB，处理耗时约 1.2–3.3 秒，属于额外的周期性负载，无法单独解释持续 15 分钟的高 CPU。
- 当前 3,902 条活动记录分布在 15 台有传感器的设备上，共 31 个设备内 provenance 校验键。旧逻辑每 10 秒轮询会对每条记录重复执行来源校验，约 23,412 次/分钟；本地改动后约 186 次/分钟，按调用次数估算下降约 99.2%。所有传感器行仍会独立保留和采样。
- 本轮复跑定向测试：`27 passed in 58.06s`；`git diff --check` 通过。

## 未执行与剩余风险

- 改动尚未部署到生产，因此尚未验证生产 CPU 回落。部署后应继续比对容器 CPU、传感器采样成功率/更新时间，以及 `/hardware-metrics` 的处理耗时。
- 此次为每设备、每次 sensor load 的临时复用，不跨设备或跨采样周期持久缓存；来源证明仍会在每个采集周期重新验证一次，保持验证刷新行为。
- 未修改部署镜像、Docker Compose、数据库或设备状态。
