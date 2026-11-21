# 华为 YunShan 平台链路与 LibreNMS 支持核查

## 完成范围

资产导入及编辑、网络设备新增/编辑/平台绑定、厂商过滤与显示、驱动边界、平台注册和 TextFSM 目录支持独立 `huawei_yunshan`。YunShan SSH 使用已有 Huawei transport，parser/catalog 保留 YunShan 身份。不会自动重绑既有 VRP 设备。

接收 `yunshan`、`yunshanos`、`yunshan_os`、`YunShan OS`、`Huawei YunShan OS`、`huawei_yunshan_os` 和中英文显示名。明确 YunShan OS 标识优先于同时存在的 Huawei Versatile Routing Platform Software 标题。

## 实际修改文件

- 后端规范化/API：`backend/core/platform_utils.py`、`backend/api/assets.py`、`backend/api/devices.py`、`backend/services/config_vendor_platform_service.py`。
- 后端运行和目录：`backend/services/operational_data_service.py`、`backend/services/platform_registry_service.py`、`backend/services/platform_identification_service.py`、`backend/core/textfsm.py`。
- 驱动：`backend/drivers/netmiko_driver.py`、`backend/drivers/scrapli_driver.py`、`backend/engine/drivers/netmiko_driver.py`。
- 定向注册：`backend/database/migrations/m0275_huawei_yunshan_platform.py`；新增回归在 `backend/tests/database/test_m0275_huawei_yunshan_platform.py`、`backend/tests/platform_registry/test_huawei_yunshan_platform.py`、`backend/tests/vendor_audit/test_huawei_yunshan_textfsm.py`。
- 六个模板：`data/textfsm_templates/huawei_yunshan_display_{version,interface_brief,ip_interface_brief,lldp_neighbor_brief,arp,mac_address}.textfsm`。运行时实际目录是项目根目录 `data/textfsm_templates`，沿用现有目录解析。
- 导入模板：`public/templates/asset_import_template.xlsx`，通过项目 API 的 `_build_asset_import_template([])` 再生成，保留样式/其他厂商列表，华为与全部网络平台命名范围各有一个 YunShan 项，不带真实 SNMP 凭据。
- 前端：`src/pages/AssetManagement/constants.ts`、`src/pages/AssetManagement/index.tsx`、`src/pages/AssetManagement/components/AssetModal.tsx`、`src/components/DeviceFormModal.tsx`、`src/hooks/useDeviceFormActions.ts`、`src/pages/textfsmPlatformCatalog.ts`、`src/pages/{InventoryDevicesTab,InspectionItemsTab,PlatformSettingsTab}.tsx`、`src/pages/AutomationExecute/constants.ts`、`src/pages/AutomationExecute/helpers.ts`、`src/pages/AutomationExecute/index.tsx`、`src/types.ts`、`src/utils/{platformVendor,configBackupCommands}.ts`、`src/components/{DeviceDetailModal,ServerMonitoring}.tsx`、`src/components/PasswordRotationPanel.export.ts`、`src/App.tsx` 及下列聚焦测试。
- 开发启动端口收尾：`scripts/dev-internal.mjs`、`scripts/dev-backend.mjs`、`package.json`、`vite.config.ts`。

## 关键实现

迁移 275 只建立 YunShan 系统 Profile、release、6 个 system parser/version/action binding 和明确 OS 识别规则。重复执行不会产生重复目录项；不触碰同名租户自定义 Profile/template，保留既有共享动作定义。不删除历史平台、设备或资产。

仅发布有对应解析模板的六个只读动作。不把 VRP 的 CPU、路由、配置场景等未经本次验证的动作自动挂到 YunShan；缺失模板不跨 OS 回退。IP 接口的地址与前缀长度分别输出，LLDP/ARP/MAC 字段经现有 normalizer 接入动作消费者。

华为官方示例同时有 YunShan OS `1.24.0.1` 与产品软件 `V600R025C00`。两者并非 VRP V5/V8 或 Comware V5/V7 的代际编号。新版本模板目录暂为 `common`；`VERSION` 与 `PRODUCT_VERSION` 保留在结构化解析结果，未新增 CMDB 版本列。后续应按确定的型号/软件回显差异拆语法，不能仅凭 V600/V300 推断 OS 或兼容性。

Windows excluded TCP 范围 5256–5355 包含旧开发默认端口 5310。Windows 开发默认值统一为 15310，Linux 仍为 5310，`BACKEND_PORT` 和 `VITE_API_TARGET` 仍可覆盖；前端继续 5400。

## LibreNMS 证据与支持边界

检查日期：2026-10-06。上游 master 当时为 `08241cf197188049e2fdf161d5b0298cce870caa`；项目内置固定来源为 `6c26b4fe4a40f7b392c19c36a44257212736e38c`（2026-09-29）。两份 YunShan detection/discovery YAML 与当日上游内容一致。

| 项目 | 核查结果 |
| --- | --- |
| OS 识别 | 独立 `os: yunshan`，Huawei group，sysObjectID 前缀 `.1.3.6.1.4.1.2011.2.23` |
| 身份 | 型号/产品版本正则及硬件、序列号 OID 定义 |
| CPU | HUAWEI-ENTITY-EXTENT-MIB CPU usage，带运行状态/阈值过滤 |
| 传感器 | temperature、count、runtime、dbm、voltage、current、power、percent、state 定义；具体可用项依型号/MIB |
| 上游样本 | S5735-L-V2 / V600R022C01SPC500，以及 S6700 / V600R024C00SPC100；包含端口、CPU、实体和传感器等模块 |
| 内存 | YunShan YAML 无 mempools。上游 OS 基类可尝试 HOST-RESOURCES/UCD 通用内存发现，需设备提供对应 MIB；两个 YunShan 样本未含 mempools。NetOps 内置适配范围没有这些 PHP 通用内存回退，暂不承诺 YunShan 内存池采集 |
| 本地导入 | `parse_rules()` 报告 identity/hardware 均 supported、diagnostics 为空；这表示规则语法可解释，不代表所有硬件 OID 经实机验证 |
| 平台持久化 | 上游键 `yunshan` 留在 SNMP discovery 快照/provenance，不写 `devices.platform` 或 `physical_assets.platform`；CLI/资产绑定规范化为 `huawei_yunshan` |

相关本地链路：`librenms_rule_service.py` → `snmp_discovery_service.py` → `snmp_hardware_probe_service.py`。未扩大 VRP 通用 OID variant 的平台范围；独立 YunShan 走它自己的规则定义。

## 验证

- 前端聚焦：7 个测试文件 / 39 项通过；后续别名与类型修正分别复查受影响文件，均通过。
- `NODE_OPTIONS=--max-old-space-size=8192 npm run lint`：通过。首次默认约 4GB 堆 OOM；复查发现并修正新增测试的 Testing Library 选项类型错误。
- `node node_modules/vite/bin/vite.js build --outDir C:/Users/NINGMEI/AppData/Local/Temp/nexora-yunshan-build-20261006`：通过，4329 modules，约 87 秒；原有 dist/用户构建产物保留。
- `node --check` 两个开发启动器；Vite 配置加载检查默认值、BACKEND_PORT 覆盖、VITE_API_TARGET 覆盖及四个代理：通过。
- 6 模板各 2 个脱敏合成语法样本、10 个 parser/transport 别名、6 个动作消费者字段：通过纯函数检查。
- `scripts/validate_postgresql_only.py --list`：0 violations，通过。移除了与策略扫描冲突的新增非 PG 调用测试，持久化验证使用真实隔离 PostgreSQL。
- 后端兼容集成：12 个文件 / 204 项通过，326.26 秒。最终 YunShan 复查：3 个文件 / 56 项通过，211.10 秒，包含最后的前缀字段和迁移保护调整。两轮用例有重叠，不将两项数量相加作为独立用例数。每轮使用先新建的 `nexora_pytest_*` 空源库，pytest 的源库 init 和 case clones 均只触及测试库；两轮源库已在 finally 强制清理。
- `npm run dev:internal` 默认启动：通过，后台运行于工具会话 99487。后端 `http://127.0.0.1:15310/api/health`、Vite 代理 `http://127.0.0.1:5400/api/health` 均 200 / healthy / database connected，前端根页面 200 且含 app root。本机应用目录已加载 migration 275，系统 Profile 的 transport/parser 为 `huawei_vrp` / `huawei_yunshan`，发布动作数量为 6。初次健康请求在启动/冷加载阶段超时，就绪后直接及代理检查均通过。

前端原聚焦命令（后续只重跑改动文件）：

```powershell
npm run test:frontend -- --run src/pages/AssetManagement/constants.test.ts src/pages/textfsmPlatformCatalog.test.ts src/components/DeviceFormModal.test.tsx src/components/PlatformProfileSelector.test.tsx src/pages/AutomationExecute/helpers.test.ts src/utils/platformVendor.test.ts src/utils/configBackupCommands.test.ts
```

后端命令经上述专用临时 PostgreSQL 源库启动器执行；没有对开发应用数据库直接运行 pytest：

```text
.venv/Scripts/python.exe -m pytest -q backend/tests/platform_registry/test_huawei_yunshan_platform.py backend/tests/database/test_m0275_huawei_yunshan_platform.py backend/tests/vendor_audit/test_huawei_yunshan_textfsm.py backend/tests/vendor_audit/test_netmiko_driver_security.py backend/tests/vendor_audit/test_platform_parser_boundary.py backend/tests/vendor_audit/test_textfsm_platform_catalog.py backend/tests/vendor_audit/test_textfsm_platform_action_resolution.py backend/tests/vendor_audit/test_h3c_textfsm_contract.py backend/tests/platform_registry/test_device_platform_binding.py backend/tests/platform_registry/test_platform_identification.py backend/tests/configuration/test_asset_import_template.py backend/tests/snmp/test_librenms_rule_service.py
.venv/Scripts/python.exe -m pytest -q backend/tests/platform_registry/test_huawei_yunshan_platform.py backend/tests/database/test_m0275_huawei_yunshan_platform.py backend/tests/vendor_audit/test_huawei_yunshan_textfsm.py
```

## 未验证项与后续

未进行真实 YunShan 设备验证或主动连接测试，没有设备型号和完整真实回显；模板样本是脱敏合成的代表性输出，不冒充实机或官方完整原文。`common` 不承诺所有软件版本/型号兼容。后续提供实际型号、OS/产品版本与脱敏输出后，按差异扩充模板和 SNMP 内存定义。

没有执行正式发布全量回归、Git 提交/推送、发布或真实设备配置变更。回滚不删除已有绑定的 Profile；若停止使用新平台，应先在应用里按权限解除绑定。用户既有 Grafana skill 修改与构建产物保持原样。

## 资料

- [华为 CloudEngine 6820H 官方产品资料](https://e.huawei.com/marketingcloud/pep/asset/20000001/Material/0cc108d837714cc2a26c554531f69b9e/M3T1A590N1074728076490014760/%E5%8D%8E%E4%B8%BACloudEngine%206820H%E6%95%B0%E6%8D%AE%E4%B8%AD%E5%BF%83%E4%BA%A4%E6%8D%A2%E6%9C%BA%E8%AF%A6%E7%89%88%E5%BD%A9%E9%A1%B5.pdf)
- [华为 S16700 V600R025C00 官方 LLDP 命令参考](https://support.huawei.cn/enterprise/en/doc/EDOC1100515417/556971e0/lldp-configuration-commands)
- [LibreNMS YunShan 识别定义](https://github.com/librenms/librenms/blob/master/resources/definitions/os_detection/yunshan.yaml)
- [LibreNMS YunShan 采集定义](https://github.com/librenms/librenms/blob/master/resources/definitions/os_discovery/yunshan.yaml)
- [LibreNMS YunShan S5735-V2 样本](https://github.com/librenms/librenms/blob/master/tests/data/yunshan_s5735-v2.json)、[S6700 样本](https://github.com/librenms/librenms/blob/master/tests/data/yunshan.json)
- [LibreNMS OS 基类通用内存发现](https://github.com/librenms/librenms/blob/master/LibreNMS/OS.php)
