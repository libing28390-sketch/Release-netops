# 走查与验证报告：修复SNMP凭据导入与LLDP/CDP SNMP拓扑发现重构

## 1. 任务概述

本次任务主要解决两个核心问题：
1. **资产导入 SNMP 凭据未生效问题**：在 `/assets/dashboard` 使用 Excel 批量导入资产或手动新建/编辑资产时，通过凭据中心（`/cmdb/credentials`）绑定的 SNMPv2 凭据在导入后未解密下发到设备和物理资产，且 API 返回中缺失 `snmp_credential_name` 导致前端无法正确展示和探测。
2. **拓扑邻居发现重构（LLDP/CDP SNMP-First + SSH Fallback）**：借鉴 LibreNMS xDP 发现机制，将标准 IEEE 802.1AB `LLDP-MIB` 和 `CISCO-CDP-MIB` 作为网络拓扑发现的第一采集通路。设备若配置了 SNMP 凭据，直接通过零 SSH 会话、轻量级的 SNMP Walk 获取邻居关系与管理 IP；若设备未配置 SNMP 或未开启 LLDP，则无缝透明回退至既有的 Netmiko SSH CLI + TextFSM 命令采集。

---

## 2. 修改文件清单

| 文件路径 | 修改性质 | 说明 |
| :--- | :--- | :--- |
| `backend/api/assets.py` | 核心修复 | 补充 `snmp_credential_name` 公开字段投影；在 `_resolve_snmp_credential_binding` 中解密并在 `_create_linked_device` / `_sync_device_from_asset` 中将凭据同步到 `devices` 和 `physical_assets`；更新 `list_assets` / `get_asset` SQL 关联查询输出 `snmp_credential_name` 和 `device_id`。 |
| `backend/api/devices.py` | 增强 | `probe_device_hostname` 支持传入 `credential_id` 并兼容通过 `asset_id` 查询设备与凭据，保证 SNMP 主机名探测能直接基于绑定的凭据中心凭据生效。 |
| `src/pages/AssetManagement/components/AssetModal.tsx` | 修复 | 主机名探测请求中传入 `credential_id: form.snmp_credential_id` 与准确的 `device_id`，避免未填团体字时错误使用 'public' 默认值导致认证失败。 |
| `backend/services/snmp_service.py` | 核心新增 | 新增 `collect_snmp_lldp_neighbors`：多厂商通用的标准 IEEE 802.1AB LLDP-MIB（`lldpRemTable`、`lldpRemManAddrTable`、`lldpLocPortTable`）与 `CISCO-CDP-MIB`（`cdpCacheTable`）并发 Walk 解析引擎。 |
| `backend/services/topology_service.py` | 核心改造 | 在 `_collect_device_observations` 中引入 SNMP-First 发现通路：优先尝试 SNMP Walk 采集邻居与管理 IP，成功则返回 `method='snmp'` 且不消耗任何 SSH 进程；失败或无数据时透明回退至既有 SSH CLI + TextFSM。 |
| `backend/tests/configuration/test_asset_management_method_import.py` | 测试加固 | 增加对 `snmp_community` 解密正确性以及 `list_assets` 输出 `snmp_credential_name` / `snmp_community_set: true` 的断言。 |
| `backend/tests/topology/test_snmp_lldp_discovery.py` | 新增测试 | 覆盖 LLDP-MIB 解析（本地端口、对端主机名、对端端口、对端管理IP）、CDP 备用发现逻辑以及拓扑收集优先使用 SNMP 并跳过 SSH 连接的单元测试。 |

---

## 3. 验证结果与命令

### 3.1 资产导入与凭据透传自动化测试
- **执行命令**：
  ```bash
  $env:PYTHONPATH='backend'; .venv\Scripts\pytest.exe backend/tests/configuration/test_asset_management_method_import.py
  ```
- **测试结果**：
  ```
  collected 5 items
  backend\tests\configuration\test_asset_management_method_import.py ..... [100%]
  5 passed in 77.59s
  ```
- **验证项**：
  - `snmp_credential_name="import-snmp-monitor"` 正确绑定到 `snmp_credential_id="cred-import-snmp"`。
  - `physical_assets.snmp_community` 和 `devices.snmp_community` 正确存储了密文并在解密后匹配 `community-import-only`。
  - `list_assets` API 返回了 `snmp_credential_name="import-snmp-monitor"` 和 `snmp_community_set=True`。

### 3.2 SNMP LLDP/CDP 拓扑发现自动化测试
- **执行命令**：
  ```bash
  $env:PYTHONPATH='backend'; .venv\Scripts\pytest.exe backend/tests/topology/test_snmp_lldp_discovery.py
  ```
- **测试结果**：
  ```
  collected 3 items
  backend\tests\topology\test_snmp_lldp_discovery.py ... [100%]
  3 passed in 34.55s
  ```
- **验证项**：
  - `test_collect_snmp_lldp_neighbors_success`：成功解析标准 IEEE 802.1AB 本地端口、对端系统名（自动清理域名后缀）、对端端口及对端管理 IP。
  - `test_collect_snmp_cdp_fallback_when_lldp_empty`：在设备未开启 LLDP 时，自动通过 CISCO-CDP-MIB 采集对端设备名、接口及管理 IP。
  - `test_topology_service_collects_snmp_first`：拓扑服务在设备具备 SNMP 配置且采集成功时，直接返回 SNMP 观测记录，完全不发起 SSH 探测，不消耗 VTY 会话。

### 3.3 前端 TypeScript 类型检查
- **执行命令**：
  ```bash
  npm run lint
  ```
- **测试结果**：
  ```
  > nexora@1.0.8 lint
  > tsc --noEmit
  # 退出码 0，全量类型检查无任何错误
  ```

---

## 4. Windows 环境本地验证指引（用户操作指南）

您当前的 Windows 环境已经具备完整运行环境（Vite 开发服务器正在 `http://localhost:5173` 运行）：

### 验证一：资产管理 SNMP 凭据导入与编辑展示
1. 打开浏览器访问：`http://localhost:5173/assets/dashboard`。
2. 点击右上角 **“导入资产”**，使用您的 Excel 模板（在 `SNMP凭据` 列填入凭据中心的名称，例如 `snmp-ro`）。
3. 导入成功后：
   - 列表中该资产的详情/编辑弹窗中，展开 SNMP 折叠区，**SNMP 凭据** 下拉框会自动选中对应的凭据（例如 `snmp-ro (SNMPv2c)`）。
   - 团体字下方会显示绿色的 **`✓ 已配置（不会回显明文）`** 状态标签。
4. 在弹窗中点击 **“探测”**（SNMP 主机名探测）：
   - 系统会自动调用 `/api/devices/probe-hostname` 并通过已绑定的 `snmp_credential_id` 获取团体字，向设备的 MIB-II `sysName.0` 发起只读探测并自动回填主机名。

### 验证二：网络拓扑的 SNMP 极速发现
1. 访问 `http://localhost:5173/topology`（或网络拓扑页面）。
2. 当选择配置了 SNMP 凭据的网络设备触发拓扑发现时：
   - 后端会优先使用 SNMP Walk 直接获取所有物理邻居链路和管理 IP，耗时仅需百毫秒级且不占用设备的 SSH VTY 会话。
   - 若某些老旧设备或未开 SNMP 的设备执行发现，系统会自动、平滑地切换为既有的 Netmiko SSH 执行 `display/show lldp neighbor`。
