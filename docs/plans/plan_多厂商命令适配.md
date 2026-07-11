# 多厂商命令适配与连接回退逻辑优化实施计划

目前系统在处理多厂商（Cisco, Huawei, H3C, Juniper, Arista, Ruijie 等）的命令下发和快速查询时，存在部分硬编码混淆（例如将华三与华为归为一类，导致华三下发华为特有的不支持指令报错；连接未知厂商时硬编码强制回退为思科等）。本计划旨在全面解决这些问题，保证各厂商使用其标准的、最精确的命令和连接配置。

## User Review Required

> [!IMPORTANT]
> 1. **连接回退逻辑修改**：当遇到未在 `mapping`/`PLATFORM_DEVICE_TYPE_MAP` 中显式定义的厂商时，系统将不再直接强制重置为 `cisco_ios`，而是优先将用户填写的 `platform` 直接作为 Netmiko 的 `device_type` 传入，仅在 `platform` 为空时才回退至 `cisco_ios`。这允许用户直接添加并连接任何 Netmiko 原生支持的厂商。
> 2. **前端与后端命令的统一**：快速查询结果上方的“执行命令”将不再使用前端单设备估算的静态字符串，而是使用后端连接设备后实际执行的命令（后端已经按各厂商在 `COMMAND_CATALOG` 里的动态映射执行了最精确的指令）。

## Proposed Changes

---

### Backend Components

#### [MODIFY] [netmiko_driver.py](file:///d:/netops/netsops-main/backend/engine/drivers/netmiko_driver.py)
* 优化 `_map_device_type` 方法，对于不在硬编码列表中的厂商，如果传入的 `platform` 非空，优先返回 `platform` 作为 Netmiko 的 `device_type` 连接驱动名，仅在为空时才以 `cisco_ios` 进行最后的兼容性回退。

#### [MODIFY] [operational_data_service.py](file:///d:/netops/netsops-main/backend/services/operational_data_service.py)
* 优化 `_build_connection_params`，对 `device_type` 采用同样的优先采用 `platform`、空值时兜底 `cisco_ios` 逻辑。
* 确保 `COMMAND_CATALOG` 中对已定义平台（如 `h3c_comware`、`huawei_vrp`、`cisco_ios`/`cisco_nxos`、`juniper_junos` 等）的命令精准无误。

---

### Frontend Components

#### [MODIFY] [index.tsx](file:///d:/netops/netsops-main/src/pages/AutomationExecute/index.tsx)
* 在前端的“自动化执行控制台”页面，细化 `platform` 判定：将 `isHuawei`（华为）与 `isH3c`（华三）拆分，独立检测 `isCisco`, `isNxos`, `isHuawei`, `isH3c`, `isJuniper`, `isArista`, `isRuijie`。
* 重新编写 `queryPresets` 数组中各操作项的 `cmds` 参数，为每个厂商分配最精确的设备专用命令（例如华三的光模块状态使用 `display transceiver interface`，日志概览使用 `display logbuffer`，避免报错）。

#### [MODIFY] [useAutomation.ts](file:///d:/netops/netsops-main/src/hooks/useAutomation.ts)
* 优化 `runQuickQuery` 逻辑：当从后端返回快速查询结果后，从返回 of `res.data.categories[0].commands` 字段提取实际由后端执行的命令，并用它来更新 `quickQueryCommands` 状态。这样前端终端视图上显示的执行指令即可百分百准确反映后端对各个厂商真实下发的命令。

## Verification Plan

### Automated Tests
* 运行现有的自动化测试用例，确保修改不影响现有的配置校验和自动化引擎测试：
  `pytest backend/tests/`

### Manual Verification
* 选择不同厂商 of 设备（Cisco、Huawei、H3C 等）执行快捷查询，检查终端上方输出的命令是否完全适配各自厂商的专用命令格式，并且没有语法报错。
