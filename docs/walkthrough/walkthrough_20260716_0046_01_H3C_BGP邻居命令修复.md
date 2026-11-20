# H3C BGP 邻居命令修复验收记录

## 修改结果

- `h3c_comware`、`h3c_comware9` 命令目录改为 `display bgp peer ipv4 unicast`。
- 自动化任务 BGP 快捷查询同步改为完整命令。
- 巡检、指标和内置 playbook 同步更新。
- 解析层兼容 `dis bgp peer ipv4 un`、`dis bgp peer ipv4 unicast` 和旧模板键。
- `hp_comware` 仍保留 `display bgp peer`，避免影响 Comware 5。

## 验证结果

- H3C/Cisco 厂商专项测试：87 passed。
- 后端编译检查：通过。
- `git diff --check`：无内容错误。
