# H3C Comware 7 自动化解析修复计划

## 问题范围

自动化任务页面执行 H3C Comware 7 的 `display transceiver interface`、`display version`、`display environment` 和 `display power` 时，现有 TextFSM 模板与真实设备输出格式不一致，导致记录被覆盖、字段拆成多条记录或完全无法结构化。

## 实施项

1. 光模块：以 `Vendor Name` 作为每个接口块的结束标志，支持缺少 `Ordering Name` 和 `Transfer Distance(km)`，保证每个接口独立生成一条记录。
2. 版本信息：兼容 `H3C Comware Software, Version ...`，取消在 uptime 行提前落记录，等完整信息结束或进入 Slot 区域后再落一条记录。
3. 环境信息：同时支持旧版键值格式和新版温度传感器表格格式，按传感器逐行输出温度及阈值。
4. 电源信息：同时支持旧版 `Power 1/State/Type` 格式和 `Device Info on Slot` 表格格式。
5. 对 `hp_comware` 与 `h3c_comware` 两个平台键同步修复，避免平台归一化路径不同导致行为不一致。
6. 为用户提供的真实输出增加回归测试，覆盖记录数、接口、版本、温度和电源状态字段。

## 验收标准

- 三个光模块接口返回三条记录，不再只保留最后一个接口。
- `display version` 返回一条完整设备记录，包含软件版本、设备型号、运行时间和重启原因。
- `display environment` 返回六条传感器记录，温度为 30、33、37、39、42、44。
- `display power` 返回两个电源记录，状态均为 Normal。
- 既有 Comware 5、Comware 7 和其他厂商回归测试不受影响。
