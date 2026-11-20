# 实施计划 - 锐捷 (Ruijie RGOS) 全量 TextFSM 模板开发与验证

## 1. 任务目标
根据用户提供的锐捷 (Ruijie RGOS / ruijie_os) 17 条真实 CLI 命令回显，按照 NTC-Templates 规约编写与健全 TextFSM 解析模板，确保自动化采集、诊断、巡检与 CMDB 同步能精准结构化提取邻居、VLAN、ARP、端口状态、光模块光功率诊断、CPU/内存/温度/风扇/电源及接口描述数据。

## 2. 拟修改与新增文件
### 2.1 TextFSM 模板文件 (`data/textfsm_templates/`)
- [NEW] `data/textfsm_templates/ruijie_rgos_show_lldp_neighbors.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_vlan.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_arp.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_interfaces_status.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_interfaces_transceiver.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_ip_route.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_ntp_status.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_fan.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_power.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_temperature.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_interfaces_description.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_cpu.textfsm`
- [NEW] `data/textfsm_templates/ruijie_rgos_show_memory.textfsm`

### 2.2 解析引擎与测试套件
- [MODIFY] `backend/core/textfsm.py` (配置命令别名归一化与模板绑定)
- [NEW] `backend/tests/vendor_audit/test_ruijie_rgos_full_textfsm.py`

## 3. 实施步骤
1. **编写 13 套新的 TextFSM 模板**，处理包含换行跨行设备名（如 LLDP System Name 换行）、连续 VLAN 端口多行折叠、光模块收发光功率 `Current diagnostic parameters` 以及电源/风扇/温度表单。
2. **注册别名与测试 Sample**：在 `backend/core/textfsm.py` 中绑定映射。
3. **单元测试与门禁验证**：使用真实 CLI 回显文本进行单元测试，验证每个字段提取率 100%。

## 4. 验证计划
- 运行 Pytest 单测：`.venv\Scripts\pytest.exe backend/tests/vendor_audit/test_ruijie_rgos_full_textfsm.py`
- 运行全量门禁：`.venv\Scripts\pytest.exe backend/tests/vendor_audit/`
