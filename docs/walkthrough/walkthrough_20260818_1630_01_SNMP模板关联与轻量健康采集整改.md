# SNMP 模板关联与轻量健康采集整改

## 目标

- 设备健康采集统一经过 `snmp_metric_profile_service` 的厂商 + 型号精确匹配。
- 健康轮询只采集 CPU、内存、温度、风扇、电源，以及接口名称和运行状态。
- 设备列表、设备详情和 SNMP 测试结果明确显示模板关联、验证状态、来源和采集模式。

## 实现结果

### 后端

- `backend/services/snmp_metric_profile_service.py`
  - 保留未验证/验证失败模板的匹配元数据，但只有已验证定义进入有效采集配置。
  - 新增健康指标白名单 `cpu / memory / temperature / fan / power_supply`。
  - 新增 `resolve_health_metric_profiles()` 和 `annotate_devices_with_snmp_profile()`，所有设备健康关联信息由同一解析器产生。
- `backend/services/snmp_service.py`
  - 新增 `collect_interface_health()`，仅执行 ifName（必要时 ifDescr）和 ifOperStatus 的 Bulk Walk，不读取接口计数器、错误、丢弃、带宽等字段。
- `backend/services/background_monitor_service.py`
  - 后台 SNMP 健康采集改用健康解析结果和轻量接口采集。
  - `snmp_metrics`、`snmp_interfaces` 状态记录包含 `collection_mode=health_only`、模板来源和指标来源。
- `backend/api/devices.py`、`backend/api/device_health.py`
  - 设备列表、设备健康详情和 SNMP 测试结果返回 `snmp_metric_profile` / 模板关联元数据。
  - 不返回 SNMP community 等敏感凭据。
  - 新增按当前指标模板执行的只读 `/platform-registry/snmp-hardware-test`，直接返回 CPU、内存、温度、风扇、电源等指标结果，不返回整棵 WALK OID 列表。
  - `/devices/{id}/snmp-test` 成功后同步返回默认健康五项，并复用同一批结果写回设备 CPU、内存、温度、风扇、电源字段；避免只显示“SNMP 连通成功”而看不到硬件值。
  - H3C 温度 `65535` 作为不支持/哨兵值处理；风扇、电源状态按 `HH3C-ENTITY-EXT-MIB` 错误状态和 `ENTITY-MIB` 实体类型关联判断。

### 前端

- 设备展开行和设备详情弹窗显示：关联模板、来源、验证状态、健康指标范围。
- SNMP 测试结果显示模板关联及 `health_only` 采集模式。
- SNMP 模板编辑器中的实时测试直接展示每项硬件指标的值、单位和健康状态；OID 仅在单项“查看采集定义”中展开。
- SNMP 连通测试弹窗展示硬件健康采集卡片；设备列表 CPU/MEM 字段由同一次健康采集结果回填。
- 未配置精确型号模板时明确显示“内置默认/未配置”，不会把厂商内置采集伪装成已应用的型号模板。

## 模板生效规则

1. 单台设备 CPU/内存覆盖优先。
2. 已验证的精确厂商 + 型号模板补充对应健康指标和接口 OID。
3. 未验证/失败模板只显示关联状态，不参与有效采集。
4. 没有可执行模板定义时使用厂商内置健康采集，并在设备页面标明 `builtin_default`。

因此，官方预置项不会因“看起来相似”而自动套用到其他型号；要让某个型号显示为“型号模板/已验证”，需要在 SNMP 模板页面保存并验证该厂商 + 型号的定义。

## 验证

- `.venv/Scripts/python.exe -m pytest backend/tests/snmp/test_snmp_metric_semantics.py backend/tests/snmp/test_snmp_walk_api.py -q`
  - 29 passed
- `npm run lint`
  - passed（TypeScript noEmit）
- `npm run build`
  - passed（Vite production build）
- `MetricOidProfilesModal.test.tsx` 的 4 个旧用例仍查找 `New`，而当前按钮名称为 `New Profile`；该组件未被本次改动修改。`MetricRowItem.test.tsx` 通过。
- `.venv/Scripts/python.exe -m pytest backend/tests -q`
  - 1705 passed，2 skipped，6 failed，76 errors
  - 失败/错误来自 PostgreSQL-only 平台注册测试未配置 PostgreSQL，以及知识库、PAM、拓扑等既有模块的独立夹具/契约问题；本次 SNMP 聚焦测试通过。
