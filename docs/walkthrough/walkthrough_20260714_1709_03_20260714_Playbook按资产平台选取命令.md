# Playbook 按资产平台选取命令

## 结论

已有 Playbook 快捷方式执行时，命令来源应为场景定义中的 `platform_phases`，但选择键必须来自每一台设备资产记录的 `vendor/platform`。请求里的 `platform` 只用于界面预览、变更单校验和历史记录，不能作为所有目标设备的固定命令平台。

## 当前执行规则

1. 读取目标设备资产平台。
2. 精确匹配场景中的平台块，例如 `huawei_vrpv8`、`h3c_comware9`、`cisco_xe`。
3. 场景暂时只有厂商族定义时，才回退到同厂商兼容族：VRPv8 → VRP、Comware9 → Comware7、IOS-XE → IOS。
4. 已识别厂商找不到对应平台块时直接报告设备错误，不发送 Cisco 默认命令。
5. 预检查、执行、后检查、回滚、变更前快照和保存配置全部使用同一台设备解析出的平台。

## 与快速查询的区别

“路由表”等带有 `operationalCategory` 的快速查询由后端操作数据目录按资产平台解析命令；前端卡片上的 `cmds` 只用于展示/兜底，不作为该类查询的实际命令来源。Playbook 则使用场景自身的 `platform_phases`，同样按资产平台逐设备解析。

## 平台示例

| 资产平台 | 路由查询命令来源 |
| --- | --- |
| Huawei VRPv5 / `huawei_vrp` | `huawei_vrp` phase |
| Huawei VRPv8 / `huawei_vrpv8` | 精确 VRPv8 phase；没有时回退 `huawei_vrp` |
| H3C Comware5 / `hp_comware` | 精确 Comware5 phase；没有时回退 `h3c_comware` |
| H3C Comware7 / `h3c_comware` | `h3c_comware` phase |
| H3C Comware9 / `h3c_comware9` | 精确 Comware9 phase；没有时回退 `h3c_comware` |
| Cisco IOS-XE / `cisco_xe` | 精确 IOS-XE phase；没有时回退 `cisco_ios` |

官方 CLI 回显样例与 TextFSM 模板仍按厂商和平台独立维护，不修改 NTC 内置模板。
