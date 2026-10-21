# 采集器自动同步不能恢复丢失的运行配置

## 症状与边界
保留数据库但运行配置丢失/损坏时，周期自动同步可能持续跳过发布；手动发布重新落盘后状态才变化。该路径已通过本地故障注入验证，另一台不可访问部署的现场原因仍未确认。

## 原因
compile 的 checksum 相同分支只用数据库 APPLIED 判断 already_applied，自动同步据此跳过发布。源产物文件本身遗失时仍返回旧路径。自动同步也会把个别发布失败汇总为 SUCCESS。

## 修正
- 校验源产物内容、checksum、版本和 collector；源产物不可用则重新编译新版本。
- 校验 current/runtime 及 current_version 标记；损坏则自动重新发布同版本。
- 发布先写 RELOAD_PENDING；exporter reload 成功才原子确认 APPLIED。重载失败返回 503，自动周期可重试；缺少产物路径不再虚报 APPLIED。
- 区分真正 published 和 unchanged/runtime verified 日志；局部失败返回 PARTIAL_FAILURE，全部失败返回 FAILED。
- 不用设备目标抓取成功率判定配置完整性，SNMP 超时不会触发重复发布。

## 验证与交付
详见 docs/walkthrough/walkthrough_20261021_1414_01_采集器自动同步恢复.md。现场仅运行新只读校验函数，没有修改生产文件、发布配置或重启容器。
