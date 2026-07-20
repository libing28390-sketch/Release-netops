# 华为/H3C 官方 CLI 样例与平台化 TextFSM 模板 Walkthrough

## 本次目标

仅为 Huawei 与 H3C/HP 平台增加官方回显驱动的 TextFSM fixture 和自定义模板：

- Huawei VRPv5：`huawei_vrp`
- Huawei VRPv8：`huawei_vrpv8`
- H3C Comware v5：`hp_comware`
- H3C Comware v7/v9：`h3c_comware`

没有修改 `ntc-templates` 安装目录中的任何内置模板。

## 新增内容

### 平台专属模板

- `huawei_vrpv8_display_cpu_usage.textfsm`
- `huawei_vrpv8_display_ip_routing_table_statistics.textfsm`
- `hp_comware_display_version.textfsm`
- `h3c_comware_display_version.textfsm`
- `h3c_comware_display_cpu_usage.textfsm`
- `h3c_comware_display_memory.textfsm`
- `h3c_comware_display_ip_routing_table_statistics.textfsm`

现有的 `huawei_vrp` 与 `hp_comware` 自定义模板继续保留，分别作为 VRPv5 和 Comware v5 的自定义解析入口。

### 官方 fixture

fixture 位于 `backend/tests/fixtures/cli/`，每个回显文件都有 `.meta.json`，记录厂商、平台、软件族、型号、命令、官方来源 URL、章节和期望字段。

使用的官方来源包括：

- Huawei `display cpu-usage`、`display memory-usage`、`display version`、路由统计和接口摘要 Command Reference/故障处理文档。
- H3C Comware v5/v7/v9 的 `display version`、`display cpu-usage`、`display memory`、接口摘要和路由统计 Command Reference。

## 解析兼容性修正

官方文档经常使用以下形式：

```text
<HUAWEI> display version
<Sysname> display memory
```

`smart_parse_cli()` 现在会先移除华为/H3C 提示符前缀，再识别命令回显；同时兼容 Huawei banner 的大小写差异。该处理只发生在输入清洗层，没有改动 NTC 内置模板。

## 验证结果

```text
.venv\\Scripts\\python.exe -m pytest backend/tests/test_textfsm_official_huawei_h3c.py backend/tests/test_textfsm_engine.py -q
22 passed

.venv\\Scripts\\python.exe -m pytest backend/tests -q
397 passed, 1 warning
```

warning 为现有 FastAPI/Starlette/httpx 依赖的弃用提示，不是本次模板变更引入的失败。

## 后续扩展

下一批按相同规则补充接口、ARP、MAC、VLAN、LLDP、OSPF、BGP、BFD、NTP、日志、风扇、电源、环境和光模块命令。若 NTC 已有模板，只增加官方 fixture 与平台路由测试，不创建同名自定义模板。
