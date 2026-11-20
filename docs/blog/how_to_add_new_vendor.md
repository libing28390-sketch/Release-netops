# Nexora NetOps 新增设备厂商与平台开发指南

当系统需要接入新的网络设备厂商或平台（例如接入“新华三 H3C V9”或“迈普 Maipu VPower”等）时，需要从 **物理模板、后端字典、前端快捷映射** 三个层面对齐其命令及解析。

以下是完整的开发及配置步骤：

---

## 第一步：设计并创建 TextFSM 模板

TextFSM 模板负责解析设备返回的原始文本并提取结构化字段。

1. **命名规范**：
   自定义模板必须放置于 `data/textfsm_templates/` 目录中，文件名采用小写并以下划线分隔：
   ```
   {normalized_platform}_{normalized_command}.textfsm
   ```
   *示例*：
   若平台标准化名称为 `maipu`，执行命令为 `show interface brief`，则模板文件名应为：
   `data/textfsm_templates/maipu_show_interface_brief.textfsm`

2. **内容规范**：
   声明所需要的提取字段，例如接口状态包含 `INTERFACE`、`STATUS`、`SPEED` 等，并编写对应的正则解析状态机（可参考同目录下其他厂商的成熟模板）。

---

## 第二步：配置后端平台解析字典

后端是决定命令下发与解析路由的核心。需修改 [operational_data_service.py](file:///d:/netops/netsops-main/backend/services/operational_data_service.py)：

1. **Netmiko 驱动关联 (`PLATFORM_DEVICE_TYPE_MAP`)**：
   在文件约第 51 行的 `PLATFORM_DEVICE_TYPE_MAP` 字典中，将平台名称映射到 Netmiko 的内置驱动名称。
   ```python
   PLATFORM_DEVICE_TYPE_MAP = {
       ...
       'my_new_platform': 'cisco_ios',  # 如果使用类 Cisco 驱动
   }
   ```

2. **别名规范化 (`_PLATFORM_ALIAS`)**：
   在文件约第 143 行的 `_PLATFORM_ALIAS` 字典中配置平台别名，兼容用户在资产管理或主机导入时输入的非标平台/厂商名。
   ```python
   _PLATFORM_ALIAS = {
       ...
       'new_vendor': 'my_new_platform',
       'new_vendor_os': 'my_new_platform',
   }
   ```

3. **快捷命令目录映射 (`COMMAND_CATALOG`)**：
   在文件约第 188 行的 `COMMAND_CATALOG` 字典中新增您平台的命令映射。**注意：此处填写的命令在被归一化处理后，必须能 1对1 命中您第一步创建的 TextFSM 模板文件名。**
   ```python
   COMMAND_CATALOG = {
       ...
       'my_new_platform': {
           'interfaces': ['show interface status'],
           'neighbors': ['show lldp neighbors'],
           'arp': ['show arp all'],
           'mac_table': ['show mac-address-table'],
           'vlan': ['show vlan'],
           'routing_table': ['show ip route'],
           'environment': ['show environment'],
           'version': ['show version'],
           'logs': ['show logging'],
           'interface_description': ['show ip interface brief'],
           'uptime': ['show version'],
       },
   }
   ```

---

## 第三步：配置前端快捷指令面板

需要修改前端 UI，将按钮与具体的命令字符串进行关联。需修改 [index.tsx](file:///d:/netops/netsops-main/src/pages/AutomationExecute/index.tsx)：

1. **新增平台判定条件**：
   在组件渲染逻辑中（约第 330-350 行），定义用于识别该平台的布尔 Flag。
   ```typescript
   const isNewPlatform = useMemo(() => {
     const platform = selectedDevice?.platform?.toLowerCase() || '';
     const vendor = selectedDevice?.vendor?.toLowerCase() || '';
     return platform.includes('new_platform') || vendor.includes('new_vendor');
   }, [selectedDevice]);
   ```

2. **绑定快捷命令 (`queryPresets`)**：
   在约第 370 行的 `queryPresets` 数组中，针对您新增的平台，微调各快捷按钮需要下发的 CLI 字符串：
   ```typescript
   {
     icon: '📡',
     label: '接口状态',
     labelEn: 'Interfaces',
     group: 'net',
     scope: 'network',
     operationalCategory: 'interfaces',
     cmds: isHuawei || isH3c
       ? 'display interface brief'
       : isNewPlatform
       ? 'show interface status'  // <--- 绑定您刚才配置的命令字
       : 'show ip interface brief',
   }
   ```

3. **支持结构化解析权限 (`operationalCategory` 保护)**：
   针对“光模块状态”、“NTP同步”、“BFD会话”和“电源风扇”等并不是所有平台都配套了模板的高级查询，需在 `operationalCategory` 的三元表达式中加上您的平台标志，允许其走 TextFSM 结构化解析流程（否则会降级为纯文本 `CLI` 状态展示）：
   ```typescript
   operationalCategory: isHuawei || isH3c || isCisco || isNewPlatform ? 'ntp' : undefined
   ```

---

## 第四步：自测与验证

1. **一致性检查**：
   您可以临时在项目根目录下创建一个 `check.py` 脚本来快速验证映射：
   ```python
   import os, re
   from backend.services.operational_data_service import COMMAND_CATALOG
   
   platform = 'my_new_platform'
   for category, cmds in COMMAND_CATALOG[platform].items():
       for cmd in cmds:
           filename = f"{platform}_{re.sub(r'[^a-z0-9]+', '_', cmd.lower())}.textfsm"
           exists = os.path.exists(f"data/textfsm_templates/{filename}")
           print(f"[{'OK' if exists else 'MISSING'}] {category}: {cmd} -> {filename}")
   ```

2. **单元测试回归**：
   在后台执行 pytest 回归测试，确保新增的平台配置字典不破坏已有的测试集：
   ```bash
   .\.venv\Scripts\python.exe -m pytest backend/tests/
   ```
