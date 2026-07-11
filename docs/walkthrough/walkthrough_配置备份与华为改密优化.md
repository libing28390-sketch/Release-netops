# 验证报告与走查记录 - 配置备份与华为 VRP8 改密提交优化

## 变更内容

1. **备份提权策略**：
   在 [configs.py](file:///d:/netops/netsops-main/backend/api/configs.py) 中的备份单个设备方法中，在调用 `resolve_device_credentials` 后，优先读取 `admin_username` 与 `admin_password` 以保证极高的特权登录几率，消除使用 normal 账号没有配置 enable 密码时，执行 `show running-config` 被拦截的现象。
2. **非标准平台匹配**：
   在 [netmiko_driver.py](file:///d:/netops/netsops-main/backend/engine/drivers/netmiko_driver.py) 中，将 `comware` 等非标准平台名成功转换并归一化为 Netmiko 支持的标准平台。
3. **华为 VRP8 自动 Commit**：
   在 [password_rotation_service.py](file:///d:/netops/netsops-main/backend/services/password_rotation_service.py) 中，对华为设备自动补发 `'commit'` 指令提交候选配置。

## 验证结果

1. **后端单元与集成测试**：
   运行全部 353 项后端测试用例，**测试一次性全部通过**，未出现任何功能回归。
   ```bash
   ================= 353 passed, 1 warning in 152.79s (0:02:32) ==================
   ```
2. **口令测试脚本走查**：
   利用 `test_backup_acc_sw1.py` 进行局部连接和指令测试，在以特权用户方式调用后，成功连接 `172.16.255.11` (ACC-SW1)，免去了 `enable` 提升密码为空而受阻的问题，完美拉取了配置。
