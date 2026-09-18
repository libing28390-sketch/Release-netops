# 修复资产导入 SNMP 凭据绑定与基于 LibreNMS 思想重构 LLDP-SNMP 拓扑发现方案

## 一、任务目标与背景

### 1.1 资产导入 SNMP 凭据未生效根因修复
* **问题现状**：在 `/assets/dashboard` 使用资产导入模板填写了“`SNMP凭据（推荐）`”（或从 `/cmdb/credentials` 选择凭据）导入后，设备看似未生效，详情弹窗中未配置，且 SNMP 探测与数据同步异常。
* **排查根因**：
  1. **Community 未解密同步**：后端批量导入逻辑中（`_create_linked_device`），只针对 SSH 普通凭据（`credential_id`）做了解析并同步 Community，遗漏了从独立的 `snmp_credential_id` 提取解密 Community，导致 `physical_assets.snmp_community` 和 `devices.snmp_community` 存入空字符串。
  2. **资产列表输出缺失凭据名称**：`/api/assets` 接口的公开白名单中未包含 `snmp_credential_name`，且未连接 `credentials` 表查询凭据名称；同时 `snmp_community_set` 仅根据本地字符串判断，导致前端列表、弹窗与导出显示为“未配置”或仅显示 UUID。
  3. **弹窗探测参数错误**：`AssetModal.tsx` 在探测主机名时强制回退 `'public'`，且向后台传了资产 ID 而非设备 ID，导致探测失败。
  4. **存量数据修补**：对当前已导入但 Community 为空的存量数据进行自动安全回填。

### 1.2 基于 LibreNMS 思路的 LLDP-SNMP 拓扑发现重构
* **问题现状**：现有网络拓扑发现依赖每台设备发起 SSH 会话并执行厂商特定的 CLI 命令（`show lldp neighbors detail`、`display lldp neighbor...`），经 TextFSM/正则提取。对于 300+ 台规模网络，频繁消耗有限的 VTY/SSH Session，侵入性强，模板维护量大，且容易与 Web SSH 堡垒机抢占通道。
* **LibreNMS 启发方案**：
  * 将采集协议重心迁移为 **SNMP LLDP-MIB 为主、SSH CLI 为兜底 Fallback**。
  * 利用标准 IEEE 802.1AB-2005 `LLDP-MIB`（`1.0.8802.1.1.2...`）与 Cisco `CISCO-CDP-MIB`（`1.3.6.1.4.1.9.9.23...`）直接通过 SNMP Walk 抓取对端系统名（`lldpRemSysName`）、对端接口（`lldpRemPortDesc` / `lldpRemPortId`）、本端接口（`lldpLocPortTable` 或 `ifDescr`/`ifName`）及对端管理地址（`lldpRemManAddrTable`）。
  * 归一化为统一 Neighbor 数据模型并写入拓扑链路库，SNMP 失败或无数据时才自动回退到现有 SSH CLI 链路。

---

## 二、影响范围与拟修改文件

1. **资产与凭据同步层**：
   * `backend/api/assets.py`：
     - 在 `_resolve_snmp_credential_binding` 和 `_create_linked_device` 中，解析 `snmp_credential_id` 时解密提取 `snmp_community`，并存入资产与设备记录。
     - 升级 `list_assets` 和 `get_asset` 查询 SQL，左连接 `credentials` 表获取 `snmp_credential_name`，加入 `_PUBLIC_ASSET_FIELDS`，修正 `snmp_community_set` 计算逻辑（有 community 或有有效 snmp_credential_id 均算已配置）。
   * `backend/api/devices.py`：
     - 增强 `probe-hostname` 接口，支持通过 `snmp_credential_id`、`device_id` 或 `asset_id` 自动定位并使用凭据中心解密后的 Community 探测主机名。
   * `src/pages/AssetManagement/components/AssetModal.tsx`：
     - 探测主机名时，如果已选择 `snmp_credential_id`，直接带入或传递 `device_id`，不再强制 fallback 为 `'public'`。

2. **SNMP 采集与拓扑发现层**：
   * `backend/services/snmp_service.py`：
     - 新增标准 IEEE 802.1AB `LLDP-MIB` 和 `CISCO-CDP-MIB` 的 SNMP Walk 收集与解析函数 `collect_lldp_neighbors_snmp(ip, community, port)`。
   * `backend/services/topology_service.py`：
     - 在 `_collect_device_observations` 入口处实现分层采集策略：
       1. 首选：若设备配置了 SNMP 凭据，先发起 SNMP LLDP/CDP 采集；
       2. 归一化：将 SNMP MIB 返回的邻居转换成标准 `observation`；
       3. 回退：若 SNMP 未配置或 SNMP 返回空/异常，且 SSH 端口开放，则无缝 fallback 执行现有 SSH CLI + TextFSM 流程。
   * `backend/tests/`：
     - 针对资产导入 SNMP 凭据绑定、回显以及 SNMP LLDP 采集逻辑编写自动化回归测试。

---

## 三、详细实施步骤

### 阶段一：修复资产导入与 SNMP 凭据绑定
1. **完善后端凭据解析与同步 (`backend/api/assets.py`)**：
   - 修正 `_resolve_snmp_credential_binding(conn, body)`：在校验并获取 `row['id']` 时，若 `body.snmp_community` 为空，同时将 `decrypt_credential(row['snmp_community'])` 回填到 `body.snmp_community`。
   - 修正 `_create_linked_device(conn, asset_id, body, user)`：在读取 `existing_snmp_cred_id` 时，提取并解密 `snmp_community`，保证存入 `devices.snmp_community`。
   - 修正 `list_assets` 与 `_sanitize_asset_item`：SQL 中 `LEFT JOIN credentials sc ON sc.id = pa.snmp_credential_id`，输出 `sc.credential_name AS snmp_credential_name`；计算 `item['snmp_community_set'] = bool(source.get('snmp_community') or source.get('snmp_credential_id'))`。
2. **修复主机名 SNMP 探测与弹窗交互 (`backend/api/devices.py` & `AssetModal.tsx`)**：
   - `probe_device_hostname` 接口增加对 `asset_id` 的兼容查询，并在提供了 `device_id`/`asset_id` 或 `credential_id` 时自动从凭据中心解析 Community。
   - `AssetModal.tsx` 在触发探测时正确传入 `device_id` 与绑定的凭据标识。
3. **数据一致性安全回填脚本**：
   - 检查现有 `physical_assets` 和 `devices` 中存在 `snmp_credential_id` 但 `snmp_community` 为空的记录，自动将凭据中心保存的密文同步过去。

### 阶段二：LibreNMS 式 SNMP LLDP/CDP 拓扑发现引擎
1. **构建标准 SNMP LLDP 驱动 (`backend/services/snmp_service.py`)**：
   - 实现标准 OID 定义：
     * `LLDP-MIB::lldpRemTable` (`1.0.8802.1.1.2.1.4.1.1`):
       - `.4`: ChassisIdSubtype, `.5`: ChassisId
       - `.6`: PortIdSubtype, `.7`: PortId
       - `.8`: PortDesc
       - `.9`: SysName
     * `LLDP-MIB::lldpRemManAddrTable` (`1.0.8802.1.1.2.1.4.2.1`):
       - `.3`: ManAddr (Remote IP)
     * `LLDP-MIB::lldpLocPortTable` (`1.0.8802.1.1.2.1.3.7.1.3` / `.4`):
       - 本地端口映射与 `IF-MIB::ifDescr` / `ifName` 关联
     * `CISCO-CDP-MIB::cdpCacheTable` (`1.3.6.1.4.1.9.9.23.1.2.1.1`):
       - `.6`: DeviceId, `.7`: DevicePort, `.4`: Address
   - 编写 `collect_snmp_lldp_neighbors(ip, community, port, local_if_map=None)`，统一清洗并输出字典列表：
     `{ "local_interface": ..., "neighbor_name": ..., "neighbor_interface": ..., "management_ip": ..., "protocol": "lldp" | "cdp" }`
2. **拓扑服务接入双模采集器 (`backend/services/topology_service.py`)**：
   - 在 `_collect_device_observations` 中优先调用 `_collect_neighbors_with_snmp`；
   - 成功获取观测链路时记录采集源为 `snmp-lldp`；
   - 遇到未配置凭据、SNMP 超时或 MIB 无数据时，记录日志并优雅 fallback 到现有 `_collect_neighbors_with_netmiko`；
   - 这样老旧设备继续走 CLI，绝大多数支持 LLDP-MIB 的现代设备走 SNMP，零消耗 SSH Session。

---

## 四、验证计划

1. **自动化单元测试与集成测试**：
   - 运行现有的资产管理与导入测试：`pytest backend/tests/configuration/test_asset_management_method_import.py`。
   - 新增资产导入带 `snmp_credential_name` 后的 Community 校验与列表回显测试。
   - 新增 SNMP LLDP MIB 数据解析与拓扑归一化回归测试。
2. **前端与接口检查**：
   - 运行 `npm run lint` 验证前端代码质量。
   - 测试调用 `GET /api/assets` 验证 `snmp_credential_name` 正确回显且 `snmp_community_set` 为 `true`。
3. **真实场景回归**：
   - 模拟使用 `asset_import_template.xlsx` 导入带 `snmp-ro` 凭据的网络设备，验证数据库中 `physical_assets` 和 `devices` 均完整落地凭据 ID 和 Community。

---

## 五、风险与回滚思路
* **向后兼容性**：原有通过 SSH CLI 采集拓扑的全部 TextFSM 模板与流程完整保留作为备选兜底；原有手动输入本地 Community 或使用 SSH 凭据的逻辑完全不变。
* **回滚机制**：如需回滚，只需在拓扑采集入口关闭 SNMP 优先开关，即可无缝切回纯 SSH 采集。
