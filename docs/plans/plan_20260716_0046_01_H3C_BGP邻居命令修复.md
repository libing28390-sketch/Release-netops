# H3C BGP 邻居查询命令修复计划

## 目标

将 Comware 7/9 的 BGP 邻居查询统一为设备实际支持的 `display bgp peer ipv4 unicast`，同时兼容设备回显中的缩写 `dis bgp peer ipv4 un`。

## 实施项

1. 更新 `h3c_comware`、`h3c_comware9` 的操作数据命令目录。
2. 更新自动化任务页面的 H3C BGP 快捷查询命令。
3. 更新 H3C 内置 playbook、巡检项和 BGP 状态指标的命令定义。
4. 将完整命令和缩写命令归一化到现有 `display bgp peer ipv4` TextFSM 模板，避免重复维护模板。
5. 保留 `hp_comware` Comware 5 的旧命令 `display bgp peer`。

## 验收标准

- Comware 7/9 实际发送 `display bgp peer ipv4 unicast`。
- `dis bgp peer ipv4 un` 和完整命令均能复用现有解析模板。
- Cisco、Huawei、Comware 5 命令不被改变。
