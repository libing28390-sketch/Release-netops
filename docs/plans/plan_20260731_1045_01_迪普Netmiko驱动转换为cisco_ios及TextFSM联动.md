# 实施计划 - 迪普 Netmiko 驱动转换为 cisco_ios 及 TextFSM 联动

## 1. 任务目标
1. 解决 Netmiko 连接层面因不存在原生 `dptech_ios` 类引发 `Error: Unsupported 'device_type'` 的报错问题。
2. 将 Netmiko 传输驱动层（SSH 连接管道）的迪普 `device_type` 统一归一映射为 Netmiko 支持的官方标准 `cisco_ios`。
3. 确认并保证 Nexora 系统内部的 TextFSM 结构化解析引擎继续精准使用现有的 15 个 `dptech_ios_*.textfsm` 模板（如 `dptech_ios_show_ip_interface_brief.textfsm`）。

---

## 2. 根因分析
- **Netmiko 缺乏 dptech_ios 原生类**：Netmiko 是第三方 Python 库，其支持的 `device_type` 白名单中只有 `cisco_ios`、`hp_comware`、`huawei`、`ruijie_os`、`maipu` 等，无 `dptech_ios`。
- **职责解耦**：Netmiko 的职责是 SSH 交互与提示符等待；Nexora 的职责是解析与 TextFSM 匹配。迪普 CLI 提示符和命令语法完全兼容 `cisco_ios` SSH 交互，因此连接层使用 `cisco_ios`，解析层匹配 `dptech_ios_*.textfsm`。

---

## 3. 拟修改文件列表
- `backend/drivers/netmiko_driver.py` [MODIFY]
- `backend/engine/drivers/netmiko_driver.py` [MODIFY]
- `backend/services/inspection_service.py` [MODIFY]
- `backend/services/operational_data_service.py` [MODIFY]
- `docs/plans/plan_20260731_1045_01_迪普Netmiko驱动转换为cisco_ios及TextFSM联动.md` [NEW]

---

## 4. 实施步骤

1. **修改 Netmiko 驱动映射**：
   - 在 `netmiko_driver.py`、`engine/drivers/netmiko_driver.py`、`inspection_service.py` (`_netmiko_platform_type`) 和 `operational_data_service.py` (`PLATFORM_DEVICE_TYPE_MAP`) 中，将 `dptech`、`dptech_ios`、`dptech_conplat` 和 `dptech_conplat_fw` 统一下沉映射为 Netmiko 的 **`cisco_ios`**。
2. **保持 TextFSM 独立映射**：
   - 维持 `core/textfsm.py` 中的 `TEXTFSM_PLATFORM_MAP` 映射为 `dptech_ios`，确保解析时自动命中 `dptech_ios_*.textfsm`（系统现存 15 个迪普专属 TextFSM 模板）。

---

## 5. 验证计划

### 5.1 自动化测试
- 运行后端单元测试套件：
  `pytest backend/tests/vendor_audit/test_dptech_ios_full_textfsm.py`
  `pytest backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py`
- 运行前端代码检查：
  `npm run lint`

### 5.2 手动功能验证
1. 打开 `/automation/tasks`。
2. 对迪普设备 `dp-fw-01` 执行 `show ip interface brief`。
3. 验证 Netmiko 使用 `cisco_ios` 顺利建立 SSH 连接抓取输出，且 TextFSM 结构化解析成功。
