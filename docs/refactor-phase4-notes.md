# 前端轻量化拆分 Phase 4 记录

时间：2026-05-21
范围：`src/App.tsx` 拆分（从 3912 行 → 1812 行，-2100 行 / -53.7%）

---

## 一、本轮已完成的拆分

| Phase | 主题 | 新增文件 | App.tsx 减少 |
|---|---|---|---|
| 4.1 | Avatar + PageTitle 工具化 | `utils/avatarPresets.tsx`、`hooks/usePageTitle.ts` | -91 |
| 4.2 | Sidebar 死代码清理 + Command Palette | `hooks/useCommandPalette.ts` | -178 |
| 4.3 | License Domain | `hooks/useLicense.ts` | -90 |
| 4.4 | Profile Domain | `hooks/useUserProfile.ts` | -94 |
| 4.5 | Scenario Draft Domain | `hooks/useScenarioDraft.ts` | -79 |
| 4.6 | Topology Domain + legacy 死代码 | `hooks/useTopology.ts` | -378 |
| 4.7 | Config Workspace Domain | `hooks/useConfigWorkspace.ts` | -280 |
| 4.8 | Config Snapshots & Backup | `hooks/useConfigSnapshots.ts`、`utils/clipboard.ts` | -345 |
| 4.9 | Device Form Actions | `hooks/useDeviceFormActions.ts` | -100 |
| 4.10 | Device Connection / SNMP / Detail | `hooks/useDeviceConnectionAndSnmp.ts`、`hooks/useDeviceDetail.ts` | -161 |
| 4.11 | Inventory Import / Export + 清 XLSX 导入 | `hooks/useInventoryImportExport.ts` | -86 |
| 4.12 | 紧凑化 `mainContentProps`（按域分组成单行） | — | -218 |

每个 Phase 完成后均跑 `npm run lint`（即 `tsc --noEmit`）；4.5 / 4.6 / 4.8 / 4.12 节点跑了完整 `npm run build`，全部通过。

---

## 二、过程中发现但未在本轮处理的问题

### 1. AppMainContent 的 `appProps` 类型为 `any`，存在 prop 不一致风险
**位置：`src/components/AppMainContent.tsx:56`**

```ts
const AppMainContent: React.FC<{ appProps: any }> = ({ appProps }) => {
```

整个组件通过 `any` 接收 290+ 个字段。本轮在排查 4.5（Scenario Draft）时发现 `handleSaveTemplate`、`handleCreateScenarioDraftFromTemplate`、`handleOpenTemplateDeploy` 三个回调被 `AppMainContent` 解构使用，但 **`mainContentProps` 中根本没传入** —— 这些字段在运行时是 `undefined`。当用户点击"保存模板 / 从模板创建场景 / 推送到自动化"这三个动作时，会触发 `undefined is not a function`。

> 暂未修复理由：本轮拆分不涉及行为变更；后续 Phase 5 做 Context 化时一并修。

**建议修法（任选其一）**：
- 把这 3 个 handler 加入 `mainContentProps`（简单、立即可用）
- Phase 5 把 `AppMainContent` 改为消费 Context（结构更干净）

### 2. `Sidebar.tsx` 组件已不被使用但仍存在
**位置：`src/components/Sidebar.tsx`（包括 `useSystem.ts` 引用链）**

实际渲染由 `AppLayout.tsx` 使用 `ModuleSubNav`；`Sidebar.tsx` 没有任何调用方。本轮把 `App.tsx` 中相关的 GroupOpen / SectionOpen / recentSidebarPaths 死代码清理掉了，但 `Sidebar.tsx` 自身（约 700 行）保留未删除。

> 暂未删除理由：删除组件文件可能影响其他未发现的引用；建议作为 Phase 5 的清理任务先做反向引用搜索后统一删除。

### 3. `App.tsx` 的 `mainContentProps` 仍然存在 prop drilling
本轮把它从对象字面量 290 行压缩到 70 行（按域分组的紧凑书写），但它本质上仍是把所有 hook/store 状态向下传递的"上帝对象"。彻底解决需要：
- 引入 `AppDomainContext`，按域细分 Provider；
- 让各 Tab 页面（`InventoryDevicesTab` 已经是这种模式）直接从 hook/store 消费；
- 把 `mainContentProps` 拆掉。

### 4. `import * as XLSX` 等大体积依赖在 `App.tsx` 里造成额外打包
- `xlsx`：本轮已迁到 `useInventoryImportExport.ts` / `useConfigWorkspace.ts`，App.tsx 主入口包不再静态依赖。
- `recharts`、`html-to-image`：现在都已经从子模块按需引入。
- `lucide-react`：App.tsx 还有一长串 icon 导入（部分图标在拆分后已不再使用），可以做一次精简。

### 5. Vite 构建仍提示主 chunk > 500KB
```
dist/assets/index-*.js 749 kB │ gzip: 196 kB
```
来自 `react-vendor`、`charts-vendor`、`export-vendor` 等。可考虑：
- `manualChunks` 进一步拆分；
- 大体积页面（RackManagement / ChangeOrder）改 `React.lazy` 已在做，但 `index` 主包仍偏大。

---

## 三、Phase 5 候选任务（按优先级）

1. **修复 1（AppMainContent 缺失的 3 个 prop）**：先把缺失字段加入 `mainContentProps`，避免运行时 undefined 错误。
2. **删除 Sidebar.tsx 死组件**：先 grep 确认无引用、再删除组件文件与相关的未使用 hook。
3. **AppDomainContext 重构**：把 `mainContentProps` 拆成多个 Context（auth / inventory / config / topology / automation / monitoring / alerts / management）。预计 App.tsx 再减 ~250 行（→ ~1500 行）。
4. **AppMainContent 1047 行进一步分解**：每个 case 拆成独立组件文件，AppMainContent 自己只做路由分派。
5. **图标导入精简**：扫描实际使用的 lucide 图标，删除未使用的。

---

## 四、本轮未触及的领域

- 后端 `backend/main.py` 已在前一次重构中从 1881 行 → 485 行，本轮未触及。
- `App.tsx` 中 `fetchSharedData` 仍然是个大 useCallback，其内部依赖多个 store setter；未单独抽离（影响可控，故保留）。
- `automationBridge` 路由跳转逻辑（约 50 行）仍在 App.tsx 内联；不大且耦合 useAutomation 状态，暂留。

---

## 五、新增文件清单（按目录）

```
src/utils/
  avatarPresets.tsx        51 行
  clipboard.ts             30 行

src/hooks/
  usePageTitle.ts                      95 行
  useCommandPalette.ts                120 行
  useLicense.ts                       133 行
  useUserProfile.ts                   216 行
  useScenarioDraft.ts                 141 行
  useTopology.ts                      436 行
  useConfigWorkspace.ts               401 行
  useConfigSnapshots.ts               429 行
  useDeviceFormActions.ts             143 行
  useDeviceConnectionAndSnmp.ts       182 行
  useDeviceDetail.ts                  125 行
  useInventoryImportExport.ts         112 行
```

合计新增 14 个文件、约 2614 行；App.tsx 净减 2100 行。多出来的约 500 行是 hook 必要的样板（参数类型、interface、props 透传等），属于合理代价。
