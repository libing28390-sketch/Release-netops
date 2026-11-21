# 国产厂商 Playbook 官方与 Excel 核验

## 核验范围

- Excel：`C:\Users\NINGMEI\Desktop\中兴锐捷迪普迈普厂商适配模板.xlsx`
- 代码：`backend/api/playbooks/builtin_scenarios.py`、`backend/api/playbooks/scenarios.py`、国产平台命令目录及 TextFSM 平台映射。
- 厂商资料：锐捷 RGOS、中兴 ZXROS、迪普 ConPlat、迈普 MyPower 的官方公开资料。

## 结论

1. Excel 共包含锐捷交换机/路由器、迪普防火墙、迈普交换机、中兴交换机/路由器六个工作表，平台分别对应 RGOS、ConPlat、MyPower、ZXROS。
2. 现有运行数据采集已经有国产平台命令目录，但原 Playbook 平台目录只有 Cisco、Huawei、H3C、Arista、Juniper，国产平台无法在 Playbook 中作为内置平台使用。
3. 已新增国产平台内置定义及“国产平台只读巡检”场景。该场景只执行 `show` 采集命令，`execute` 为空，不会进入配置模式或修改设备。
4. 锐捷和中兴的自动保存命令按官方公开资料使用 `write`；迪普和迈普没有在当前公开资料中找到足以覆盖所有型号的统一写盘命令，因此不自动猜测保存命令。
5. Excel 中“中兴路由器 / show running-config”的示例回显混入了 `show logging buffer nat` 和 `show clock`，判定为异常样本，未将其作为解析模板或命令语法依据。

## 三方核对依据

- 锐捷官方资料出现 `show mac-address-table`、`show arp`、`show memory`、`show clock`，并展示 RGOS 配置保存使用 `write`：
  [锐捷官方产品问题与命令示例](https://image.ruijie.com.cn/Upload/Article/5e872a9a-7b46-48be-8fb6-9cbd86ab8fe1/%E9%94%90%E6%8D%B7%E4%BA%A4%E6%8D%A2%E6%9C%BA%E4%BA%A7%E5%93%81%E7%BA%BF%E9%97%AE%E9%A2%98%E4%B8%80%E6%9C%AC%E9%80%9A%EF%BC%88V1.0%EF%BC%89/%E4%BA%A4%E6%8D%A2%E6%9C%BA%E4%BA%A7%E5%93%81%E7%BA%BF%E9%97%AE%E9%A2%98%E4%B8%80%E6%9C%AC%E9%80%9AV1.0/8a9dd6dc-0910-42bd-8d61-dfd9c34f038c.htm)
- 中兴官方 ZXCSL CLI 文档明确要求配置完成后使用 `write` 保存：
  [中兴官方 CLI 配置](https://csl.zte.com.cn/manual_zh/topics/1684391333553.html)
- 迪普官方资料确认 ConPlat 是其设备操作系统并提供 CLI/SSH 管理接口，但未在当前公开资料中确认跨系列统一的写盘命令：
  [迪普 ConPlat 官方技术白皮书](https://www.dptech.com/index.php?a=show&c=index&catid=664&id=51&m=content)
- 迈普官方产品资料确认 MyPower 平台提供 Running Config、System Version、Show IP Route 等 CLI 快捷查询能力；具体型号命令仍应以设备版本手册为准：
  [迈普官方产品资料](https://www.maipu.com/Goods/Details/95)

## 代码变更

- `PLATFORMS` 新增 `ruijie_rgos`、`zte_zxros`、`maipu`、`dptech_conplat`、`dptech_conplat_fw`。
- Playbook 平台别名新增 `ruijie_os`、`zxros`、`mypower`、`dptech_ios` 等映射，避免平台名称进入 Cisco 默认分支。
- 新增国产平台只读巡检内置场景，并按厂商隔离命令列表。
- 为锐捷和中兴登记官方确认的 `write`；迪普/迈普保持不自动写盘。
- 为国产平台登记配置快照查询命令，配置变更前可保留运行配置快照。

## 验证命令

```text
.\.venv\Scripts\python.exe -m pytest -q backend/tests/vendor_audit/test_domestic_playbook_catalog.py backend/tests/vendor_audit/test_huawei_vrp5_cli_output.py backend/tests/test_playbook_platform_aliases.py
21 passed

.\.venv\Scripts\python.exe -m pytest -q backend/tests/vendor_audit
271 passed

npm run lint
passed
```

剩余风险：迪普和迈普不同型号/版本的 CLI 仍需要设备实测回显或厂商型号手册才能继续扩展为可写配置 Playbook；当前只读巡检不承担配置下发职责。
