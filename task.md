## Phase 3 (已完成)
- `[x]` Phase 3.1: Inventory Domain
  - `[x]` Create `src/store/inventoryStore.ts`
  - `[x]` Extract `inventoryRows`, `inventoryTotal`, `inventoryPage`, filters, sorting states from `App.tsx`
  - `[x]` Extract device handlers (`handleImport`, `handleExport`, `handleDeleteDevice`, etc.) from `App.tsx`
  - `[x]` Update `src/pages/InventoryDevicesTab.tsx` to use `useInventoryStore`
  - `[x]` Remove props from `App.tsx` passing into `AppMainContent.tsx` for Inventory
- `[x]` Phase 3.2: Monitoring Domain
  - `[x]` Create `src/store/monitoringStore.ts`
  - `[x]` Extract all `monitorXxx` states and fetch handlers from `App.tsx`
  - `[x]` Update `src/components/MonitoringCenter.tsx` to use `useMonitoringStore`
  - `[x]` Remove props from `App.tsx` for Monitoring
- `[x]` Phase 3.3: AppMainContent Cleanup
  - `[x]` Clean up `appProps` in `AppMainContent.tsx`
  - `[x]` Verify TypeScript types via `tsc --noEmit`

## Phase 4 — 继续轻量化拆分 App.tsx (起点 ~3912 行 → 目标 ~700 行)

- `[x]` Phase 4.1: Avatar + PageTitle 工具化
  - `[x]` Create `src/utils/avatarPresets.tsx` (avatarPresets / resolvePreset / renderAvatarContent)
  - `[x]` Create `src/hooks/usePageTitle.ts`
  - `[x]` Update `App.tsx` to consume them
  - `[x]` Verify via `npm run lint`
  - 进度: App.tsx 3912 → 3821 行 (-91)
- `[x]` Phase 4.2: Sidebar Nav + Command Palette
  - `[x]` Create `src/hooks/useCommandPalette.ts`
  - `[x]` Remove dead Sidebar group/section state from `App.tsx` (Sidebar 组件未被实例化使用)
  - 进度: App.tsx 3821 → 3643 行 (-178)
  - 注: 原 Sidebar.tsx 组件未被实际渲染，相关 GroupOpen/SectionOpen/recentSidebarPaths state 全部删除；如未来复用 Sidebar 需要重新接线
- `[x]` Phase 4.3: License Domain
  - `[x]` Create `src/hooks/useLicense.ts` (status / 60s polling / TAB_FEATURE_MAP enforcement)
  - 进度: App.tsx 3643 → 3553 行 (-90)
- `[x]` Phase 4.4: Profile Domain
  - `[x]` Create `src/hooks/useUserProfile.ts`
  - 进度: App.tsx 3553 → 3459 行 (-94)
- `[x]` Phase 4.5: Scenario Draft Domain
  - `[x]` Create `src/hooks/useScenarioDraft.ts`
  - 进度: App.tsx 3459 → 3380 行 (-79)
  - 备注: `handleCreateScenarioDraftFromTemplate` 暂留 App.tsx，依赖 config workspace state，待 Phase 4.7 一起迁
- `[x]` Phase 4.6: Topology Domain
  - `[x]` Create `src/hooks/useTopology.ts` (state + describeLink + evaluateSnapshot + 9 个 useMemo + handleExportMap + handleTriggerDiscovery)
  - `[x]` 顺手清理 App.tsx 中的死代码 legacy* helpers
  - 进度: App.tsx 3380 → 3002 行 (-378)
  - 备注: 暂未做 store 化（store 抽离推迟到真有跨组件需求时再做）；TopologyPage 现仍通过 mainContentProps 接收数据，4.12 一并处理
- `[x]` Phase 4.7: Config Workspace Domain
  - `[x]` Create `src/hooks/useConfigWorkspace.ts`
  - 进度: App.tsx 3002 → 2722 行 (-280)
- `[x]` Phase 4.8: Config Snapshots & Backup Domain
  - `[x]` Create `src/hooks/useConfigSnapshots.ts`
  - `[x]` Extract `copyTextWithFallback` to `src/utils/clipboard.ts`
  - 进度: App.tsx 2722 → 2377 行 (-345)
- `[x]` Phase 4.9: Device Form Actions
  - `[x]` Create `src/hooks/useDeviceFormActions.ts`
  - 进度: App.tsx 2377 → 2277 行 (-100)
- `[x]` Phase 4.10: Device Connection / SNMP / Detail
  - `[x]` Create `src/hooks/useDeviceConnectionAndSnmp.ts`
  - `[x]` Create `src/hooks/useDeviceDetail.ts`
  - 进度: App.tsx 2277 → 2116 行 (-161)
- `[x]` Phase 4.11: Inventory Import & Routing Misc
  - `[x]` Create `src/hooks/useInventoryImportExport.ts`
  - 进度: App.tsx 2116 → 2030 行 (-86)
  - 备注: 顺手清理了已不再使用的 `import * as XLSX`
- `[x]` Phase 4.12: 紧凑化 `mainContentProps`
  - `[x]` 把 290+ 行的对象字面量压缩成约 70 行（按域分组、单行多字段）
  - 进度: App.tsx 2030 → 1812 行 (-218)
  - 备注: 完整 Context 化重构（去掉 prop drilling）需要重写 1000+ 行的 `AppMainContent.tsx` 与各页面消费方式，作为后续 Phase 5 单独跟进，避免在一次提交中引入大面积变更

## 总结
- App.tsx 起点 3912 行 → 终点 **1812 行**（-2100，约 **-54%**）
- 新增 11 个 hook + 2 个 utils：
  - `src/hooks/usePageTitle.ts`
  - `src/hooks/useCommandPalette.ts`
  - `src/hooks/useLicense.ts`
  - `src/hooks/useUserProfile.ts`
  - `src/hooks/useScenarioDraft.ts`
  - `src/hooks/useTopology.ts`
  - `src/hooks/useConfigWorkspace.ts`
  - `src/hooks/useConfigSnapshots.ts`
  - `src/hooks/useDeviceFormActions.ts`
  - `src/hooks/useDeviceConnectionAndSnmp.ts`
  - `src/hooks/useDeviceDetail.ts`
  - `src/hooks/useInventoryImportExport.ts`
  - `src/utils/avatarPresets.tsx`
  - `src/utils/clipboard.ts`
- 验证：每一步均通过 `npm run lint`（tsc --noEmit）；多次跑 `npm run build` 全部通过
- 后续可选改进 (Phase 5)：
  - 完整 Context 化以消除 `mainContentProps` prop drilling
  - 把 `AppMainContent.tsx` (1047 行) 中各 case 的 page wrapper 重新拆分；可能需要让 page 直接消费 hook/store

## Phase 5: Context 化重构 ✅ 已完成

**目标**: 将 `mainContentProps` 巨大对象拆分为多个 React Context，实现更好的状态管理

**进度**: ✅ 已完成基础架构

### 已完成的工作

1. **创建 Context 架构** ✅
   - `CoreAppContext`: 核心应用状态 (路由、用户、设备)
   - `DashboardContext`: 仪表板相关状态
   - `InventoryContext`: 库存管理状态  
   - `AutomationContext`: 自动化相关状态
   - `ConfigContext`: 配置管理状态
   - `ManagementContext`: 用户管理、审计、合规状态
   - `TopologyContext`: 拓扑相关状态

2. **重构 App.tsx** ✅
   - 删除巨大的 `mainContentProps` 对象
   - 创建分域的 Context values
   - 用 `AppProviders` 包装应用

3. **重构 AppMainContent.tsx** ✅
   - 移除 props 接口，改用 Context hooks
   - 清理重复的变量声明
   - 添加必要的导入

4. **验证构建** ✅
   - 构建成功，核心架构工作正常

### 成果

- **代码组织**: 状态按业务域分离，更清晰的关注点分离
- **类型安全**: 每个 Context 都有明确的 TypeScript 接口
- **可维护性**: 更容易理解和修改特定域的状态
- **性能**: 避免了巨大 props 对象的传递

### 遗留问题 (已全部解决)

- `[x]` 一些 TypeScript 类型不匹配 (已解决，目前 `npx tsc --noEmit` 无任何报错)
- `[ ]` 部分 Context 接口可以进一步细化 (可选)
- `[ ]` 可以考虑添加 Context 的性能优化 (useMemo, useCallback) (可选)

**状态**: ✅ 核心重构与类型修复已全部完成，应用可正常构建、类型检查完全通过且稳定运行

### 文件变更统计

**新增文件**:
- `src/contexts/AppDomainContext.tsx` - 核心应用和仪表板 Context
- `src/contexts/AutomationContext.tsx` - 自动化相关 Context  
- `src/contexts/ConfigContext.tsx` - 配置管理 Context
- `src/contexts/ManagementContext.tsx` - 管理功能 Context
- `src/contexts/TopologyContext.tsx` - 拓扑相关 Context
- `src/contexts/AppProviders.tsx` - Context 组合器

**修改文件**:
- `src/App.tsx` - 移除 mainContentProps，添加 Context Providers
- `src/components/AppMainContent.tsx` - 改用 Context hooks

**删除文件**:
- `src/components/Sidebar.tsx` - 未使用的死代码
- `src/hooks/useSystem.ts` - 未使用的死代码

## Phase 6: Telemetry & SNMP 采集性能优化 (单体架构演进)

**目标**: 采用渐进式轻量化改造，优化多厂商 SNMP 采集吞吐，降低设备控制面压力，保障海量设备下的单体性能。

- `[x]` Phase 6.1: 后端采集逻辑分流 (A/B Dual Loops)
  - `[x]` 改造 `backend/engine/orchestrator.py`：
    - 设计 A-Loop (高频任务)：10s - 30s 周期，仅执行 Ping 探活及接口状态 (`ifOperStatus`) 检测。
    - 设计 B-Loop (中低频任务)：1m - 5m 周期，执行系统基本信息、CPU/内存/温度/风扇/电源状态以及接口流量/错包/丢包等指标采集。
    - 针对发现异常的设备，支持动态提升采集频率（临时触发高频诊断采集）。
- `[x]` Phase 6.2: 网络驱动批量采集升级 (SNMP GetBulk)
  - `[x]` 改造 `backend/services/snmp_service.py` 驱动模块：
    - 将原有基于 `PyWrapper.walk` 迭代或多次单条 `Get` 的方式，改写为对大批量表格数据使用 `client.bulk_walk` (或 `GetBulk`) 采集。
    - 配置合理的 `max_repetitions` (如对接口表设置为 20-50)，减少交互包往返次数。
    - 优化并行控制机制，确保单台设备的多个 OID 树请求（如接口名、状态、流量计数器等）通过 `asyncio.gather` 一次性并发发出。
- `[x]` Phase 6.3: 多厂商 OIDs 整理与 MIB 校验 (官方 MIB 比对 & 全面指标覆盖)
  - `[x]` **官方 MIB 比对与核查**:
    - **Cisco (IOS/XE/NX-OS/XR)**: 访问 Cisco MIB Locator，验证 `CISCO-PROCESS-MIB`, `CISCO-MEMORY-POOL-MIB`, `CISCO-ENHANCED-MEMPOOL-MIB`, `CISCO-ENVMON-MIB`, `CISCO-ENTITY-SENSOR-MIB` 以及 `CISCO-ENTITY-FRU-CONTROL-MIB`。
    - **Huawei (VRP)**: 访问华为官方 Support，验证 `HUAWEI-ENTITY-EXTEND-MIB` 中的 CPU、内存、环境指标。
    - **Juniper (Junos)**: 访问 Juniper MIB Explorer，验证 `JUNIPER-MIB` (`jnxOperatingTable`) 中的引擎与机箱硬件状态。
    - **Fortinet (FortiOS)**: 访问 Fortinet Support，验证 `FORTINET-FORTIGATE-MIB` 中的系统资源与硬件传感器监控。
    - **H3C (Comware)**: 验证 `HH3C-ENTITY-EXT-MIB`。
    - **Arista (EOS)**: 验证 `HOST-RESOURCES-MIB` 及标准 `ENTITY-SENSOR-MIB` (RFC 3433)。
  - `[x]` **指标覆盖规范清单 (指标覆盖度 100%)**:
    - **系统基础信息 (System)**:
      - `sysName` (`.1.3.6.1.2.1.1.5.0`)
      - `sysDescr` (`.1.3.6.1.2.1.1.1.0`)
      - `sysUpTime` (`.1.3.6.1.2.1.1.3.0`)
      - `sysLocation` (`.1.3.6.1.2.1.1.6.0`)
      - `sysContact` (`.1.3.6.1.2.1.1.4.0`)
    - **CPU 使用率 (CPU Usage)**:
      - Cisco (IOS/XE/NX-OS/XR): `cpmCPUTotal5minRev` (`.1.3.6.1.4.1.9.9.109.1.1.1.1.8`)
      - Huawei (VRP): `hwEntityCpuUsage` (`.1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5`)
      - Juniper (Junos): `jnxOperatingCPU` (`.1.3.6.1.4.1.2636.3.1.13.1.8`)
      - Fortinet (FortiOS): `fgSysCpuUsage` (`.1.3.6.1.4.1.12356.101.4.1.3.0`)
      - H3C (Comware): `hh3cEntityExtCpuUsage` (`.1.3.6.1.4.1.25506.2.6.1.1.1.1.6`)
      - Arista (EOS): `hrProcessorLoad` (`.1.3.6.1.2.1.25.3.3.1.2`)
    - **内存使用率 (Memory Usage)**:
      - Cisco (IOS/XE): `cempMemPoolHCUsed`/`Free` (`.1.3.6.1.4.1.9.9.221.1.1.1.1.18`/`20`) & `ciscoMemoryPoolUsed`/`Free` (`.1.3.6.1.4.1.9.9.48.1.1.1.5`/`6`)
      - Cisco (NX-OS): `cseSysMemoryUtilization` (`.1.3.6.1.4.1.9.9.305.1.1.2.0`)
      - Cisco (XR): `cpmCPUMemoryUsed`/`Free` (`.1.3.6.1.4.1.9.9.109.1.1.1.1.12`/`13`)
      - Huawei (VRP): `hwEntityMemUsage` (`.1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7`)
      - Juniper (Junos): `jnxOperatingBuffer` (`.1.3.6.1.4.1.2636.3.1.13.1.11`)
      - Fortinet (FortiOS): `fgSysMemUsage` (`.1.3.6.1.4.1.12356.101.4.1.4.0`)
      - H3C (Comware): `hh3cEntityExtMemUsage` (`.1.3.6.1.4.1.25506.2.6.1.1.1.1.8`)
      - Arista (EOS): `hrStorageUsed`/`Size` (`.1.3.6.1.2.1.25.2.3.1.6`/`5`)
    - **温度监控 (Temperature)**:
      - Cisco (IOS/XE): `ciscoEnvMonTemperatureValue` (`.1.3.6.1.4.1.9.9.13.1.3.1.3`)
      - Cisco (NX-OS/XR): `entSensorValue`/`Type` (`.1.3.6.1.4.1.9.9.91.1.1.1.1.4`/`1`)
      - Huawei (VRP): `hwEntityTemperature` (`.1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11`)
      - Juniper (Junos): `jnxOperatingTemp` (`.1.3.6.1.4.1.2636.3.1.13.1.7`)
      - Fortinet (FortiOS): `fgHwSensorEntValue` (`.1.3.6.1.4.1.12356.101.4.3.2.1.3` 过滤 Name 包含 "Temp")
      - H3C (Comware): `hh3cEntityExtTemperature` (`.1.3.6.1.4.1.25506.2.6.1.1.1.1.12`)
      - Arista (EOS): `entPhySensorValue`/`Type` (`.1.3.6.1.2.1.99.1.1.1.4`/`1` 过滤 Celsius 类型 8)
    - **风扇状态 (Fan Status)**:
      - Cisco (IOS/XE): `ciscoEnvMonFanState` (`.1.3.6.1.4.1.9.9.13.1.4.1.3`)
      - Cisco (NX-OS/XR): `cefcFanTrayOperStatus` (`.1.3.6.1.4.1.9.9.117.1.4.1.1.1`)
      - Huawei (VRP): `hwFanState` (`.1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7`)
      - Juniper (Junos): `jnxOperatingState` 过滤 Fan 类型 (`.1.3.6.1.4.1.2636.3.1.13.1.6`)
      - Fortinet (FortiOS): `fgHwSensorEntAlarmStatus`/`fgHwSensorEntValue` 过滤 Fan 类型 (`.1.3.6.1.4.1.12356.101.4.3.2.1.4`/`3`)
      - H3C (Comware): `hh3cEntityExtFanStatus` (`.1.3.6.1.4.1.25506.2.6.1.1.1.1.19`)
      - Arista (EOS): `entPhySensorValue` 过滤 RPM 类型 10
    - **电源状态 (PSU Status)**:
      - Cisco (IOS/XE): `ciscoEnvMonSupplyState` (`.1.3.6.1.4.1.9.9.13.1.5.1.3`)
      - Cisco (NX-OS/XR): `cefcFRUPowerOperStatus` (`.1.3.6.1.4.1.9.9.117.1.1.2.1.2`)
      - Huawei (VRP): `hwPowerStatusTable` (`.1.3.6.1.4.1.2011.5.25.31.1.1.13.1.2`)
      - Juniper (Junos): `jnxOperatingState` 过滤 Power/PEM 类型
      - Fortinet (FortiOS): `fgHwSensorEntAlarmStatus`/`Value` 过滤 Power/PSU 类型
      - H3C (Comware): `hh3cEntityExtPowerStatus` (`.1.3.6.1.4.1.25506.2.6.1.1.1.1.21`)
      - Arista (EOS): `entPhySensorValue` 过滤 Volts 类型 3
    - **标准接口指标 (Interface Metrics - IF-MIB / RFC 2863)**:
      - `ifDescr` (`.1.3.6.1.2.1.2.2.1.2`), `ifName` (`.1.3.6.1.2.1.31.1.1.1.1`), `ifAlias` (`.1.3.6.1.2.1.31.1.1.1.18`)
      - `ifOperStatus` (`.1.3.6.1.2.1.2.2.1.8`), `ifAdminStatus` (`.1.3.6.1.2.1.2.2.1.7`)
      - `ifSpeed` (`.1.3.6.1.2.1.2.2.1.5`), `ifHighSpeed` (`.1.3.6.1.2.1.31.1.1.1.15`) —— 自动按带宽适配，10G+ 使用 `ifHighSpeed`
      - **流量计数**: `ifInOctets`/`ifOutOctets` (32-bit)，对高带宽设备自动采集 `ifHCInOctets`/`ifHCOutOctets` (64-bit HC)
      - **错包监控**: `ifInErrors` (`.1.3.6.1.2.1.2.2.1.14`), `ifOutErrors` (`.1.3.6.1.2.1.2.2.1.20`)
      - **丢包监控**: `ifInDiscards` (`.1.3.6.1.2.1.2.2.1.13`), `ifOutDiscards` (`.1.3.6.1.2.1.2.2.1.19`)
      - **包数统计**: `ifInUcastPkts`/`ifOutUcastPkts` (32-bit) / `ifHCInUcastPkts`/`ifHCOutUcastPkts` (64-bit HC)
      - **状态变化**: `ifLastChange` (`.1.3.6.1.2.1.2.2.1.9`) —— 用于计算接口 Up/Down 持续时间
  - `[x]` **编写验证用例**:
    - 在 `backend/tests` 下增加单元测试，对 `_resolve_platform` 及新添加的 Fortinet OID 结构、批量解析逻辑进行离线/模拟测试。
    - 确保 `puresnmp` 库与异步架构完全对齐，避免在高并发下造成内存泄漏或文件描述符耗尽。