# 资产设备 SNMP 采集开关

## 实现结果

- 在 `devices` 表新增 `snmp_collection_enabled BOOLEAN NOT NULL DEFAULT TRUE`，迁移版本为 `m0296`。旧设备和未填写字段的新导入设备都按开启处理；不在 `physical_assets` 再存一份，避免两个状态副本漂移。
- 资产新建/编辑表单增加 SNMP 开关，默认开启；编辑时读取当前值，复制资产时继承。资产批量导入不增加 Excel 列，导入设备仍默认开启。
- 资产列表和详情 API 返回设备开关；只改开关也会写入 `devices`、记录资产修改审计，并触发监控目标同步。
- 开关关闭时，Nexora 不再为该设备生成 vmagent/SNMP exporter 目标，也不再运行 SNMP 硬件轮询、SNMP 在线探测、接口/地址、ARP/MAC、路由邻居和拓扑 SNMP 采集。已有 CLI 回退仍然保留，在线状态继续走 ICMP/管理端口检测。
- 关闭开关不会删除凭据、设备、采集计划、历史观测或缓存；重新开启后，后续周期采集恢复。

## 外部系统边界

已在独立 LibreNMS 实例注册的设备仍由该实例按其自身配置轮询。本开关控制 Nexora 发起的自动 SNMP 采集，并阻止开关关闭后的自动 LibreNMS 纳管；它不会改写外部 LibreNMS 已有设备的启用状态。

## 验证

- PostgreSQL 回归：`python -m pytest -q backend/tests/monitoring/test_monitoring_v1_compiler.py backend/tests/monitoring/test_snmp_collection_policy_service.py backend/tests/monitoring/test_snmp_hardware_poller_service.py backend/tests/monitoring/test_background_monitor_snmp_alerts.py backend/tests/rackvision/test_asset_save_contract.py backend/tests/rackvision/test_asset_import_contract.py backend/tests/database/test_m0296_device_snmp_collection_switch.py backend/tests/vendor_audit/test_ip_locator_arp_contract.py` — 123 passed。
- 最终在线探测/禁用状态回归：`python -m pytest -q backend/tests/monitoring/test_background_monitor_snmp_alerts.py backend/tests/monitoring/test_snmp_collection_policy_service.py` — 20 passed。
- PostgreSQL-only policy：`python scripts/validate_postgresql_only.py` — 通过，0 项违规。
- 本机开发 PostgreSQL：只读确认 `schema_migrations` 含版本 `296/device_snmp_collection_switch`，且 `devices.snmp_collection_enabled` 列已存在。
- TypeScript：`npm run lint` — 通过。
- Vite isolated build：`.\node_modules\.bin\vite.cmd build --outDir "$env:TEMP\nexora-snmp-toggle-check-20261025-a936f1d" --emptyOutDir` — 构建通过，4,347 个模块。
- 本机开发服务启动后，`/assets/network-devices` 与 `/api/health` 均返回 200；电脑使用工具一直返回 `Transport closed`，因此未能完成登录态下的表单交互检查。停止了本次启动的本机服务。
- 本机未安装 SNMP exporter，跳过运行时配置发布检查；目标过滤逻辑由 compiler 单测覆盖。此环境限制不计入代码验收失败。

## 已知边界与回滚

- 当前开关控制 Nexora 自动发起的 SNMP 请求。独立 LibreNMS 中已经启用的设备需要在 LibreNMS 自行停用。
- 回滚代码时可保留 `snmp_collection_enabled` 列和现有值；移除新增判定后旧设备仍按默认开启行为运行。不开启破坏性数据回退。
