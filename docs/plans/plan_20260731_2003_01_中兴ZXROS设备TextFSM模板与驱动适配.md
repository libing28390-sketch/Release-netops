# 实施计划 - 中兴 (ZTE ZXROS) 设备 TextFSM 模板与多厂商驱动适配

## 1. 任务目标
解决中兴 ZXROS 设备 CLI 命令解析不准确及模板缺失问题。根据用户提供的中兴 ZXROS 真实设备回显样例（LLDP邻居、VLAN、MAC表、ARP表、接口状态、三层接口状态、光模块状态、路由表、OSPF邻居、风扇状态、电源状态、温度明细、系统版本、日志、系统时钟等 18 条关键命令），编写并重构精细化 TextFSM 解析模板，完成后端规范化适配器 (`ZTENormalizer`)，并补全平台命令映射与自动化回归测试，确保中兴设备在资产采集、拓扑发现、巡检及运维诊断中精准解析。

---

## 2. 现状与根因分析
1. **旧模板解析偏差**：已有的 `zte_zxros_show_lldp_neighbor_brief.textfsm` 字段定义与中兴 ZXROS 实际输出列不匹配，无法正确解析多行折叠的 `ChassisID`、`peer-Port` 及 `hostname`。
2. **缺乏全量模板支持**：缺失 `show vlan`、`show mac table`、`show arp`、`show interface brief`、`show ip interface brief`、`show opticalinfo brief`、`show ip forwarding route`、`show ip ospf neighbor`、`show fan`、`show power`、`show temperature detail`、`show version`、`show logging buffer almlog`、`show clock` 等 14+ 个 TextFSM 模板。
3. **平台映射与规范化器未完备**：`backend/services/normalizers/` 目录中缺少中兴专属解析器 `zte.py` (`ZTENormalizer`)，`backend/services/operational_data_service.py` 中 `zte_zxros` 的 `PLATFORM_COMMANDS` 命令集仅定义了 `neighbors` 和 `isis`，缺少其他维度的指令映射。
4. **TextFSM 平台映射表**：`backend/core/textfsm.py` 中的 `TEXTFSM_PLATFORM_MAP` 缺少 `'zte'` / `'zxros'` -> `'zte_zxros'` 的快捷映射。

---

## 3. 拟修改与新增文件列表

### [NEW] 模板与规范化器文件
- `data/textfsm_templates/zte_zxros_show_vlan.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_mac_table.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_arp.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_interface_brief.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_ip_interface_brief.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_opticalinfo_brief.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_ip_forwarding_route.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_ip_ospf_neighbor.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_fan.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_power.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_temperature_detail.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_version.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_logging_buffer_almlog.textfsm` [NEW]
- `data/textfsm_templates/zte_zxros_show_clock.textfsm` [NEW]
- `backend/services/normalizers/zte.py` [NEW]
- `backend/tests/vendor_audit/test_zte_zxros_full_textfsm.py` [NEW]

### [MODIFY] 后端引擎与配置
- `backend/core/textfsm.py` [MODIFY]
- `backend/services/normalizers/factory.py` [MODIFY]
- `backend/services/operational_data_service.py` [MODIFY]

---

## 4. 实施步骤

1. **新建与更新 `data/textfsm_templates/` 下中兴 ZXROS TextFSM 模板**：
   - 编写 `zte_zxros_show_lldp_neighbor.textfsm` & `zte_zxros_show_lldp_neighbor_brief.textfsm`。
   - 编写 `zte_zxros_show_vlan.textfsm`。
   - 编写 `zte_zxros_show_mac_table.textfsm`。
   - 编写 `zte_zxros_show_arp.textfsm`。
   - 编写 `zte_zxros_show_interface_brief.textfsm`。
   - 编写 `zte_zxros_show_ip_interface_brief.textfsm`。
   - 编写 `zte_zxros_show_opticalinfo_brief.textfsm`。
   - 编写 `zte_zxros_show_ip_forwarding_route.textfsm`。
   - 编写 `zte_zxros_show_ip_ospf_neighbor.textfsm`。
   - 编写 `zte_zxros_show_fan.textfsm`。
   - 编写 `zte_zxros_show_power.textfsm`。
   - 编写 `zte_zxros_show_temperature_detail.textfsm`。
   - 编写 `zte_zxros_show_version.textfsm`。
   - 编写 `zte_zxros_show_logging_buffer_almlog.textfsm`。
   - 编写 `zte_zxros_show_clock.textfsm`。

2. **更新 TextFSM 核心处理模块 (`backend/core/textfsm.py`)**：
   - 在 `TEXTFSM_PLATFORM_MAP` 中添加 `'zte'`, `'zxros'`, `'zte_zxros'` -> `'zte_zxros'`。
   - 优化 `_clean_cli_output` 中对中兴 LLDP 邻居输出多行换行的预处理逻辑。

3. **创建中兴 Normalizer 与 Factory 注册 (`backend/services/normalizers/`)**：
   - 新建 `backend/services/normalizers/zte.py` (`ZTENormalizer`)。
   - 在 `backend/services/normalizers/factory.py` 中注册 `zte_zxros` / `zte` / `zxros` 平台。

4. **更新运维采集命令映射 (`backend/services/operational_data_service.py`)**：
   - 补充 `PLATFORM_COMMANDS['zte_zxros']` 全量数据项的 CLI 指令列表。

5. **自动化测试与回归验证**：
   - 创建 `backend/tests/vendor_audit/test_zte_zxros_full_textfsm.py`，使用用户提供的全部真实回显数据对所有模板进行断言测试。
   - 运行 pytest 门禁以及 `npm run lint` 检查。

---

## 5. 验证计划

### 5.1 自动化测试
- 运行中兴 TextFSM 全量解析测试：
  `pytest backend/tests/vendor_audit/test_zte_zxros_full_textfsm.py`
- 运行多厂商规范化适配器测试：
  `pytest backend/tests/normalizers/test_vendor_normalizers.py`
- 运行前端与类型门禁：
  `npm run lint`

### 5.2 手动/数据走查验证
- 验证所有 18 条真实样本在中兴 TextFSM 引擎下能 100% 成功解析且无遗漏字段。
