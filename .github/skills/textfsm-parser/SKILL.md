---
name: "textfsm-parser"
description: "Converts network CLI output to structured JSON using TextFSM and templates. Invoke when parsing commands or building multi-vendor CLI data extraction."
---

# CLI Parsing Expert Skill

你负责 NetPilot 的 CLI 输出解析，核心配置在 `core/textfsm.py`。

---

## 项目中的 TextFSM 集成

- **初始化函数**：`configure_ntc_templates()` — 在应用启动时自动查找 ntc-templates 路径。
- **环境变量**：设置 `NET_TEXTFSM` 指向模板目录，Netmiko 的 `use_textfsm=True` 会自动查找。
- **查找顺序**：
  1. 已安装的 `ntc_templates` 包目录
  2. 项目根目录 `ntc-templates/ntc_templates/templates/`
  3. 找不到时 graceful fallback — 日志 WARNING，不阻塞启动。

## 模板适配状态

参考项目根目录的 `NTC_TEMPLATE_ADAPTATION_STATUS.md`，记录了各厂商模板适配进度。

## 解析模式

Netmiko 驱动中的使用方式：

```python
# netmiko_driver.py 中的 execute_command()
output = connection.send_command(command, use_textfsm=True)
# 如果 TextFSM 解析成功，output 是 list[dict]
# 如果失败，output 是原始字符串
```

## 厂商模板命名规范

ntc-templates 的模板文件命名格式：

```
{platform}_{command}.textfsm
```

示例：
- `cisco_ios_show_ip_interface_brief.textfsm`
- `huawei_vrp_display_interface_brief.textfsm`
- `arista_eos_show_interfaces_status.textfsm`

## 新建 TextFSM 模板

当 ntc-templates 没有覆盖某命令时：

1. 创建模板文件，放入 `ntc-templates/ntc_templates/templates/` 目录。
2. 更新同目录下的 `index` 文件，添加映射行。
3. 模板语法要点：
   - `Value` 行定义变量和正则。
   - `Start` 状态开始匹配。
   - `Record` 记录一行数据。
   - `Value Required` 标记必填字段。

```textfsm
Value INTERFACE (\S+)
Value IP_ADDRESS (\d+\.\d+\.\d+\.\d+)
Value STATUS (up|down|administratively down)

Start
  ^${INTERFACE}\s+${IP_ADDRESS}\s+\w+\s+\w+\s+${STATUS} -> Record
```

## 注意事项

- 华为 VRP 和 H3C Comware 命令格式与 Cisco 差异较大，模板不可混用。
- 解析失败时返回原始文本（而非抛异常），由调用方决定后续处理。
- 优先使用已有 ntc-templates，避免重复造轮子。
