# TextFSM 与平台动作的直接匹配链路

## 目标

设备完成 SNMP、CLI 或人工平台确认后，设备的 Profile 即为后续命令和解析的唯一平台依据。TextFSM 不再要求先注册、发布、审核或绑定到 Release；模板保存后即可使用。

## 运行时解析顺序

1. 读取设备绑定的具体 Profile。华三 V5、V7、V9 都使用 Netmiko `hp_comware`，但分别选择 `h3c_comware_v5`、`h3c_comware_v7`、`h3c_comware_v9` 解析命名空间。
2. 从当前已发布 Release 读取 action 的实际命令。系统不会根据模板名称猜命令，也不会把一个版本的命令静默替换成另一个版本。
3. 使用“具体平台 + 规范化后的实际命令”精确查找 TextFSM。具体版本没有模板时，只允许回退到明确命名为通用的无版本模板；不会跨到其他版本。
4. 解析成功返回结构化记录；没有匹配模板返回 `parse_status=unmatched` 并保留原始回显；设备明确返回命令错误时返回 `parse_status=device_error`，提示检查 Profile 中的实际命令。

## 模板创建

模板页按“厂商 → 平台 → 版本”选择文件命名空间。Action 关联是可选元数据：选择 Action 会自动带出该平台当前命令，但命令仍可编辑；保存不依赖测试解析。关联信息写入模板注释，独立模板和没有 Action 的模板仍可正常解析。

Action 名称使用统一的短名称，例如“接口状态”“ARP表”“Eth-Trunk/链路聚合”“BFD会话”“NTP同步”“日志概览”“系统运行时间”。

## 兼容性

旧的 `/automation/textfsm-registry` 地址保留为兼容入口并跳转到 `/automation/textfsm`，避免旧书签失效；独立的注册表页面和前端导航入口不再作为用户流程的一部分。旧的 TextFSM 版本 API 已移除，遗留数据库字段仅因非破坏性迁移暂留，运行时不再读取或依赖它们。
