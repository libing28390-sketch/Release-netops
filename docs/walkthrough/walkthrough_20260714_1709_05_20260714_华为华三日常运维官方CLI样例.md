# 华为/华三日常运维 CLI 官方样例第二批

## 本批次范围

本批次继续只覆盖华为和华三，并按平台隔离：

| 厂商 | 平台 | 命令 | 处理方式 |
| --- | --- | --- | --- |
| Huawei | VRP8 | `display arp all` | `huawei_vrpv8_display_arp_all.textfsm` |
| Huawei | VRP8 | `display lldp neighbor brief` | `huawei_vrpv8_display_lldp_neighbor_brief.textfsm` |
| Huawei | VRP8 | `display mac-address` 变体 | `huawei_vrpv8_display_mac_address.textfsm` |
| H3C | Comware7 | `display arp all` | `h3c_comware_display_arp_all.textfsm` |
| H3C | Comware7 | `display lldp neighbor-information list` | NTC 内置模板（只读） |
| H3C | Comware7 | `display mac-address` 变体 | `h3c_comware_display_mac_address.textfsm` |
| H3C | Comware7 | `display vlan brief` | NTC 内置模板（只读） |

## 官方样例来源

- Huawei ARP：<https://support.huawei.com/enterprise/en/doc/EDOC1100419271/be8e56cf/configuration-examples-for-arp>
- Huawei LLDP：<https://support.huawei.com/enterprise/en/doc/EDOC1100248438/8def618c/lldp-configuration-commands>
- Huawei MAC：<https://support.huawei.com/enterprise/en/doc/EDOC1100333649/e1d83431/display-mac-address--ap-id--ap-name->
- H3C ARP：<https://www.h3c.com/en/d_201909/1227166_294551_0.htm>
- H3C LLDP：<https://www.h3c.com/en/d_201905/1176179_294551_0.htm>
- H3C MAC：<https://wwwsg.h3c.com/en/d_202602/2752476_294551_0.htm>
- H3C VLAN：<https://www.h3c.com/en/d_201905/1189999_294551_0.htm>

每个 fixture 都在同目录配套 `.meta.json`，声明厂商、平台、型号族、命令和官方来源。测试不会把 VRP8 样例混入 VRP5，也不会把 Comware7 样例混入 Comware5。

## 设计约束

1. 不修改 `.venv/Lib/site-packages/ntc_templates/templates` 中的内置模板。
2. 自定义模板只放在 `data/textfsm_templates/`，并以平台前缀命名。
3. 模板查找同时兼容项目的下划线命名和 NTC 历史模板中的连字符命名；这只是读取路径兼容，不会改写 NTC 文件。
4. 官方文档中的提示符和命令同行、厂商 banner、静态 ARP 短格式均在项目模板或清洗层处理。

## 验证命令

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c_operations.py -q
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c.py backend/tests/test_textfsm_official_huawei_h3c_operations.py backend/tests/test_textfsm_engine.py -q
```

当前第二批专项测试 7 项通过；联合官方样例和引擎回归测试 29 项通过。

## 后续批次

下一批建议继续补充 BGP/OSPF/BFD、NTP、Eth-Trunk/端口聚合、堆叠/IRF、光模块收发器、温度/电源/风扇，并继续先查 NTC 内置覆盖，再按 VRP5、VRP8、Comware5、Comware7/9 分目录采集官方样例。
