# 国内交换机/路由器 Netmiko 平台适配基线

## 本轮范围

本轮只纳入当前环境中 Netmiko 已提供 SSH handler 的平台：

| 厂商 | 平台键 | Netmiko handler | 当前状态 |
| --- | --- | --- | --- |
| 锐捷 | `ruijie_rgos` | `ruijie_os` | 已有官方样例与自定义模板 |
| 中兴 | `zte_zxros` | `zte_zxros` | 已注册平台，等待官方设备 CLI 回显样例 |
| 迈普 | `maipu` | `maipu` | 已注册平台，等待官方设备 CLI 回显样例 |

DCN、迪普、烽火暂不进入资产平台选项，也不进入本轮模板开发；等 Netmiko handler 和官方 CLI 样例都具备后再单独评估。

## 锐捷官方样例

样例文件位于：

- `backend/tests/fixtures/cli/ruijie/ruijie_rgos/show_version/rgos_eg1000s.txt`
- `backend/tests/fixtures/cli/ruijie/ruijie_rgos/show_ip_interface_brief/rgos_rsr.txt`

来源均为锐捷官方支持文档：

- https://www.ruijie.com.cn/fw/wt/18252/
- https://www.ruijie.com.cn/fw/wt/36825/

对应模板：

- `data/textfsm_templates/ruijie_rgos_show_version.textfsm`
- `data/textfsm_templates/ruijie_rgos_show_ip_interface_brief.textfsm`

## 约束

1. 资产录入时保存厂商与平台，锐捷旧值 `ruijie_os` 只作为兼容别名，统一归一到 `ruijie_rgos`。
2. ZTE 与迈普即使暂时没有模板，也保留自身平台键；命令目录为空时不发送 Cisco 命令。
3. 每个新命令必须先有官方厂商文档回显，再添加对应平台模板和测试；不使用现场猜测数据替代官方样例。
4. NTC 内置模板目录不修改；所有新增模板放在 `data/textfsm_templates/`。

## 验证命令

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_textfsm_official_ruijie.py backend/tests/test_asset_platform_catalog.py backend/tests/test_operational_data_catalog.py -q
```
