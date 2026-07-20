# 多厂商平台别名统一补齐计划

## 任务目标

在已修复 H3C 裸平台值 `h3c` 的基础上，补齐其他主流厂商的常见平台别名，避免数据库中保存非 canonical 平台值时 fallback 到 Cisco 命令或 Cisco Netmiko driver。

## 现状 / 问题

当前 canonical 平台值已有覆盖：

- `cisco_ios`
- `cisco_nxos`
- `huawei_vrp`
- `h3c_comware`
- `juniper_junos`
- `arista_eos`
- `ruijie_rgos`

但以下常见裸值/别名覆盖不完整：

- Cisco：`cisco`, `ios`, `iosxe`, `cisco_iosxe`, `nxos`, `nexus`
- Huawei：`huawei`, `vrp`, `ce`, `ce_vrp`, `ne`
- H3C：`h3c`, `comware`, `hp_comware`
- Juniper：`juniper`, `junos`
- Arista：`arista`, `eos`
- Ruijie：`ruijie`, `rgos`

## 影响范围

- 运行数据采集 operational command catalog
- NTC/TextFSM 平台映射
- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`

## 拟修改文件

- `backend/services/operational_data_service.py`
- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`
- `backend/tests/test_automation_credentials_and_platforms.py`
- `docs/walkthrough/walkthrough_多厂商平台别名统一补齐.md`

## 实施步骤

1. 在 operational service 的 `_PLATFORM_ALIAS` 中补齐主流厂商别名。
2. 在两个 Netmiko driver 的 alias 映射中补齐同一批别名。
3. 必要时补齐 `PLATFORM_DEVICE_TYPE_MAP` 与 `NTC_PLATFORM_MAP` 的直接 key。
4. 新增测试覆盖 Cisco/NXOS/Huawei/Juniper/Arista/Ruijie/H3C alias。
5. 运行聚焦测试与语法检查。

## 验证计划

- `python -m py_compile ...`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_automation_credentials_and_platforms.py -q`
- `git diff --check`

## 风险与回滚思路

- 风险：别名扩大后，某些历史上误填的平台值会被正确归一化，不再 fallback Cisco；这是预期行为。
- 回滚：移除新增 alias 和对应测试即可。
