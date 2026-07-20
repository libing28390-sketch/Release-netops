# 华为华三硬件与高可用官方 CLI 样例

## 本批次目标

本批次补充日常巡检中常用的 BFD、堆叠/IRF、温度、风扇、电源和光模块命令。所有样例均保存在 `backend/tests/fixtures/cli/`，并通过同目录的 `*.meta.json` 记录官方文档地址、厂商、平台和型号族。

模板只新增到 `data/textfsm_templates/`，没有修改 `.venv/Lib/site-packages/ntc_templates/templates/` 下的 NTC 内置模板。华为 VRP8 与华三 Comware7 使用各自的模板前缀，避免跨厂商或跨平台误匹配。

## 样例与模板映射

| 厂商/平台 | 官方命令 | 模板 | 样例型号族 |
| --- | --- | --- | --- |
| Huawei VRP8 | `display bfd session all` | `huawei_vrpv8_display_bfd_session.textfsm` | S310/S5700 |
| Huawei VRP8 | `display fan` | `huawei_vrpv8_display_fan.textfsm` | S300/S500/S2700/S5700/S6700 |
| Huawei VRP8 | `display power` | `huawei_vrpv8_display_power.textfsm` | S300/S500/S2700/S5700/S6700 |
| Huawei VRP8 | `display stack` | `huawei_vrpv8_display_stack.textfsm` | S220/S310/S530 |
| Huawei VRP8 | `display temperature all` | `huawei_vrpv8_display_temperature.textfsm` | S300/S500/S2700/S5700/S6700 |
| Huawei VRP8 | `display transceiver interface ... verbose` | `huawei_vrpv8_display_transceiver_interface.textfsm` | Huawei Ethernet switches |
| H3C Comware7 | `display bfd session` | `h3c_comware_display_bfd_session.textfsm` | H3C switches |
| H3C Comware7 | `display environment` | `h3c_comware_display_environment.textfsm` | H3C switches |
| H3C Comware7 | `display fan` | `h3c_comware_display_fan.textfsm` | H3C switches |
| H3C Comware7 | `display irf` | `h3c_comware_display_irf.textfsm` | S5130S-HI/S5110V2/S3100V3-EI |
| H3C Comware7 | `display power` | `h3c_comware_display_power.textfsm` | H3C switches |
| H3C Comware7 | `display transceiver interface ...` | `h3c_comware_display_transceiver_interface.textfsm` | H3C switches |

## 官方来源

- Huawei BFD：<https://support.huawei.com/enterprise/en/doc/EDOC1100306155/81d122bb/bfd-configuration-commands>
- Huawei 风扇与温度：<https://support.huawei.com/enterprise/en/doc/EDOC1100365019/faf329d5/displaying-the-fan-status>
- Huawei 电源：<https://support.huawei.com/enterprise/en/doc/EDOC1100365019/63fa786f/displaying-power-supply-information>
- Huawei 堆叠：<https://support.huawei.com/enterprise/en/doc/EDOC1100381092/2825086b/checking-whether-a-stack-is-set-up-successfully>
- Huawei 光模块：<https://support.huawei.com/enterprise/en/doc/EDOC1100333876/94ef2802/displaying-optical-module-information>
- H3C BFD：<https://www.h3c.com/en/d_202301/1752404_294551_0.htm>
- H3C 硬件资源（环境、风扇）：<https://www.h3c.com/en/d_202212/1747761_294551_0.htm>
- H3C 电源：<https://www.h3c.com/en/d_202204/1583056_294551_0.htm>
- H3C IRF：<https://www.h3c.com/en/d_201909/1227147_294551_0.htm>
- H3C 光模块：<https://www.h3c.com/en/d_200806/607528_294551_0.htm>

## 验证方式

第四批独立测试：

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c_hardware.py -q
```

四批官方样例联合测试：

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c.py backend/tests/test_textfsm_official_huawei_h3c_operations.py backend/tests/test_textfsm_official_huawei_h3c_protocols.py backend/tests/test_textfsm_official_huawei_h3c_hardware.py -q
```

后续继续补充 VRP5、Comware5 和 Comware9 时，样例目录与模板前缀必须分别使用 `huawei_vrp`、`hp_comware` 和明确的 Comware9 平台标识，不能把不同平台的回显合并成一份样例。

## 只读采集目录接入

`backend/services/operational_data_service.py` 现在把以下类别纳入同一套只读采集目录：`ntp`、`environment`、`fan`、`power`、`stack`、`transceiver` 和 `eth_trunk`。快速查询界面会根据设备平台选择对应命令，例如：

- Huawei VRP8：`display temperature all`、`display stack`、`display eth-trunk`。
- H3C Comware7：`display environment`、`display irf`、`display link-aggregation verbose`。
- H3C Comware5：使用独立的 `hp_comware` 目录，不复用 Comware7 的 IRF/硬件命令。

目录缺少平台映射时返回空类别并显示明确的 catalog error，不再静默下发 Cisco 命令。采集仍通过 `auth_role=normal` 的只读快速查询入口执行；自定义命令入口保持单独的解析路径。
