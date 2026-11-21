# 实施计划 - 动态注册 Netmiko dptech_ios 设备类

## 1. 任务目标
通过在 Netmiko 的全局分发映射表 (`netmiko.ssh_dispatcher.CLASS_MAP`) 中动态扩展注册 `dptech_ios` 类，使 Netmiko 官方依赖库原生支持 `device_type='dptech_ios'`，实现连接层与解析层统一采用 `dptech_ios`。

---

## 2. 根因与技术原理
1. **Netmiko 校验原理**：Netmiko 在实例化 `ConnectHandler` 时，会校验 `device_type` 是否存在于 `CLASS_MAP` 字典中；由于迪普为国产厂商，第三方 Netmiko 官方源码中未直接内置该字符串键名。
2. **动态扩展注册 (Monkey Patch / Custom Registration)**：在 Python 运行时将 `dptech_ios` 绑定为 Netmiko 的 `CiscoIosSSH`（其 SSH 管道能力基类），无需改动外部 Netmiko 安装包文件，即可让全系统及 Netmiko 原生接受 `device_type='dptech_ios'`。

---

## 3. 拟修改文件列表
- `backend/drivers/netmiko_driver.py` [MODIFY]
- `backend/engine/drivers/netmiko_driver.py` [MODIFY]
- `backend/services/inspection_service.py` [MODIFY]
- `backend/services/operational_data_service.py` [MODIFY]
- `docs/plans/plan_20260731_1050_01_动态注册Netmiko_dptech_ios设备类.md` [NEW]

---

## 4. 实施步骤

1. **注册 `dptech_ios` 至 Netmiko 注册表**：
   在驱动加载与连接构建入口处，执行：
   ```python
   from netmiko.ssh_dispatcher import CLASS_MAP, CLASS_MAP_BASE
   from netmiko.cisco import CiscoIosSSH
   CLASS_MAP['dptech_ios'] = CiscoIosSSH
   CLASS_MAP_BASE['dptech_ios'] = CiscoIosSSH
   ```
2. **统一底层驱动映射为 `dptech_ios`**：
   - 将 `dptech`、`dptech_conplat` 和 `dptech_conplat_fw` 统一在 Netmiko 映射层收敛为 `dptech_ios`。

---

## 5. 验证计划

### 5.1 自动化测试
- 运行后端单元测试与动态注册验证：
  `pytest backend/tests/vendor_audit/test_dptech_ios_full_textfsm.py`
  `pytest backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py`
- 运行前端与代码检查：
  `npm run lint`

### 5.2 手动功能验证
1. 打开 `/automation/tasks`。
2. 对迪普设备 `dp-fw-01` 执行命令，校验 Netmiko 接受 `device_type='dptech_ios'` 连接并成功抓取输出。
