# 实施计划 - 配置备份与华为 VRP8 改密提交优化

## 问题分析

1. **备份无法提权（Enable）问题**：配置备份功能（在 `/config/backup` 点击备份全部）连接 Cisco 设备时报错。这是由于备份模块 `backend/api/configs.py` 内部统一使用 `creds.get('username')`，它在凭证解耦的设计中被解析为普通权限账户（如 `user`）。普通账户登录设备后处于 User EXEC 模式（`>`），无法执行 `show running-config`。此时设备又未设置单独的 enable 密码，导致 Netmiko 提权尝试被拒。
2. **华三设备备份 Unsupported device_type 问题**：由于华三设备在数据库中的 `platform` 为非标准的 `comware`，Netmiko 驱动在匹配时由于找不到该键而原样传递了 `comware` 导致报错。
3. **华为 VRP8 改密不生效问题**：华为 VRP8 采用两阶段配置提交机制。在配置模式下执行了改密命令后，必须显式调用 `commit` 提交才能真正使配置生效，否则只停留在 candidate 阶段，导致口令上收（takeover）认证失败。

## 解决方案

1. **备份优先使用特权账号**：修改 `backend/api/configs.py` 的 `_backup_one`，让其优先从解析的 credentials 中读取 `admin_username` 与 `admin_password`，保证登录直接进入特权 EXEC 模式，无需额外的 enable 动作。
2. **驱动中对非标准平台别名映射归一化**：在 `backend/engine/drivers/netmiko_driver.py` 中的 `_map_device_type` 添加 comware 及 华为 VRP 等别名的转换，让其正确返回 `hp_comware` 和 `huawei`。
3. **华为改密命令加入 commit**：修改 `backend/services/password_rotation_service.py` 的 `rotate_password` 核心逻辑，在使用 send_config 发送密码修改命令后，若是华为设备，则发送一次 `'commit'` 动作，使配置在 VRP8 上得以真正写入应用。该步骤被设计为独立的配置块下发，以防不支持 commit 的 VRP5 报 CLI 错误而影响正常改密逻辑。

## 验证计划
1. 运行 pytest 自动化测试套件。
2. 手动或通过测试脚本对 `ACC-SW1` 进行备份，确认在无 enable 密码时正常获取到配置。
3. 测试华为 VRP8 设备上收修改口令，确保能自动提报 commit。
