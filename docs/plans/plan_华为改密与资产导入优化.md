# 实施计划 - 华为改密交互与资产导入模板优化

## 1. 华为 VRP8 自身改密失败问题分析与优化

* **问题分析**：
  1. **交互式校验限制**：在华为 VRP8 设备（例如 AGG-SW2）上，当使用管理员账号（`admin01`）登录并对该账号自身进行口令上收（takeover）或密码修改时，设备 AAA 模块会强制触发交互式安全校验，并提示 `Please enter old password:`。由于 Netmiko 默认的 `send_config_set` 仅适用于批量无交互命令下发，在此提示处未输入旧密码，导致随后下发的所有指令与登录验证失败。
  2. **Candidate 配置状态下的提示符丢失 `>`**：在 VRP8 设备上进行修改操作后，密码处于暂存区，设备提示符由于未提交而变为 `[*agg-sw2-aaa]` 或 `[*agg-sw2]`（即最前方多出了 `*`，且**不再以 `>` 结尾**）。Netmiko 驱动在退出配置模式 `exit_config_mode()` 时，其内部硬编码了等待 `>` 匹配的逻辑，这导致 Netmiko 因检测不到 `>` 而直接抛出超时异常 `Pattern not detected: '>' in output`。
* **解决方案**：
  * 对 `NetmikoDriver.send_config` 增加定制化的交互与状态回扫处理：
    1. 改用逐行下发形式，在捕获到 `old password` 提示后，自动发送当前会话的登录密码（即旧密码），完成交互验证。
    2. 执行完所有命令后，动态获取设备当前 prompt 状态。如果还在 `aaa` 子视图中（提示符包含 `-aaa`），主动下发 `quit` 退出到系统视图。
    3. 检查提示符是否以 `*` 开头（表示有未提交的 candidate 修改）。如果是，主动发送 `commit` 提交指令。这能令提示符状态重置，恢复以 `>` 结尾的常规视图，从而保证 `exit_config_mode()` 能顺利退出并正常匹配。对于没有 candidate 特性的 VRP5 设备，提示符不以 `*` 开头，会自动跳过 `commit` 这一步，避免了执行不支持的命令发生报错，实现了完美的双版本兼容。

---

## 2. 华为全量平台补全与 `Unsupported device_type` 问题范围自查

* **自查结论**：
  * **受影响范围**：不仅仅是配置备份，如果底层资产在数据库中配置了非标准的平台名称（如 `comware` 或 `华为vrp`、`huawei_vrpv8` 等），除配置备份外，全局数据采集、脚本执行、拓扑链路扫描、SNMP 自动发现等功能凡是使用到 `NetmikoDriver` 驱动或 scrapli 驱动的场景都会由于无法识别底层 Netmiko `device_type` 而报错崩溃。
  * **解决方案**：我们在 [netmiko_driver.py](file:///d:/netops/netsops-main/backend/drivers/netmiko_driver.py) 内部的 `_map_platform`、[operational_data_service.py](file:///d:/netops/netsops-main/backend/services/operational_data_service.py) 和 [topology_service.py](file:///d:/netops/netsops-main/backend/services/topology_service.py) 中，对 `huawei_vrpv8` 进行了全局注册和别名转换（统一映射到 `huawei` 连接器），同时也在前端组件中增加了 `Huawei VRPv8` 的下拉选项。

---

## 3. 资产管理页面设备导入模板防错优化

* **问题分析**：
  * 用户在使用资产导入 Excel 时，由于手动输入“厂商”、“平台”或“设备分类”的文本不符合系统标准，导致导入失败。
  * 纯前端依赖 `xlsx` 库的社区版（社区版 SheetJS）无法在导出 Excel 时完美支持设置原生 Excel Dropdown 单元格数据有效性校验（`<dataValidations>` 在写出时会被忽略）。
* **解决方案**：
  * 采用双重防错机制：
    1. **模板增加规范工作表**：在导出的 `资产导入模板.xlsx` 中新增第三张 Sheet 页面 `参数可选值参考` (Option Reference)，明确罗列出全量支持的 厂商、平台标识（如 `cisco_ios`、`huawei_vrpv8` 等）以及设备分类标识，并提供中英文说明，指导用户复制填充。
    2. **导入强校验与转换**：用户上传 Excel 后，前端导入解析模块自动对厂商、平台、设备分类字段做规范转换与容错映射。
