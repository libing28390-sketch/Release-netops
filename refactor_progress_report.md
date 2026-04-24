# 自动化模块重构与拆分进展报告 (2026-04-24)

## 1. 总体目标
本次重构的主要目标是将 `App.tsx` 中臃肿的自动化运维逻辑剥离到独立的 React Hook (`src/hooks/useAutomation.ts`) 中。通过逻辑与 UI 的分离，提高代码的可维护性、可测试性，并最终减小主入口文件的体积。

## 2. 核心变更记录

### 2.1 逻辑层：`src/hooks/useAutomation.ts`
该 Hook 现在成为了自动化模块的“大脑”。

*   **状态管理中心化**：迁移了包括 `jobs`, `scenarios`, `playbookExecutions`, `quickQuery` 等在内的 50 多个状态变量。
*   **功能函数封装**：
    *   **Playbook 执行核心**：封装了 `runPlaybook`, `executePlaybook`, `runQuickPlaybook` 等复杂异步逻辑。
    *   **快速查询与解析**：封装了 `runQuickQuery`, `runParsedCustomCommand` 以及表格数据的处理逻辑。
    *   **审批流程控制**：集成了配置变更的飞书审批验证流程 (`handleRequestApproval`, `handleVerifyApproval`)。
*   **工具函数恢复**：
    *   `extractVars`: 负责解析 Jinja2 风格的变量 (`{{ var }}`)。
    *   `splitLines`: 负责将用户输入的命令字符串解析为干净的数组。
    *   `formatQuickQueryRawOutput`: 负责处理原始 SSH/Telnet 回显的格式化。

### 2.2 展示层：`src/App.tsx`
*   **消费 Hook 逻辑**：通过解构赋值的方式，将 `useAutomation` 返回的逻辑重新连接到 UI 组件。
*   **瘦身初步成果**：删除了约 1500 行的原始业务逻辑代码，改为调用 Hook。
*   **稳定性修复**：针对拆分过程中出现的“函数未定义”错误，重新建立了正确的引用链路。

## 3. 关键问题修复 (Bug Fixes)

在拆分过程中，由于部分函数在 `App.tsx` 的其他板块（如配置中心）也有使用，导致了若干运行时报错。目前已全部修复：

| 错误类型 | 报错信息 | 修复方案 |
| :--- | :--- | :--- |
| **ReferenceError** | `extractVars is not defined` | 将解析正则表达式重新封装在 Hook 中并导出，在 `App.tsx` 中重新解构。 |
| **ReferenceError** | `quickQueryTable is not defined` | 在 Hook 中重新定义并导出 `quickQueryTable` 的 `useMemo` 计算逻辑。 |
| **ReferenceError** | `runQuickPlaybook is not defined` | 找回并重构了丢失的快速执行函数，确保了“执行”页面的按钮功能恢复。 |
| **ReferenceError** | `applyScriptVars is not defined` | 修复了脚本变量替换逻辑，确保自定义命令中的变量能正确填充。 |

## 4. 当前状态 (Current State)

*   **构建状态**：执行 `npm run build` 通过，无编译错误。
*   **核心功能**：
    *   [x] 自动化作业列表加载
    *   [x] Playbook 场景解析与执行
    *   [x] 快速查询 (Terminal/Table 视图)
    *   [x] 导出 Excel 功能
    *   [x] 变量自动提取
*   **文件体积**：`App.tsx` 目前约为 5236 行。虽然依然很大，但逻辑已经模块化，大部分是 UI 结构代码。

## 5. 后续计划

为了进一步实现 `App.tsx` 的极致瘦身，建议按以下阶段继续：

### 第二阶段：UI 板块组件化 (即将开始)
*   **提取 `MonitoringCenter`**：将 800+ 行的监控 UI 移入 `src/pages/MonitoringCenter.tsx`。
*   **提取 `InventoryTab`**：将库存管理的 JSX 结构独立出来。
*   **提取 `ConfigCenterTab`**：将配置备份、对比、搜索的 UI 逻辑彻底剥离。

### 第三阶段：全局状态优化
*   考虑引入更轻量的状态管理方案，减少 `App.tsx` 中顶层解构赋值的长度（目前解构了 100 多个变量，这部分也可以进一步精简）。

---
**报告人**: Antigravity AI  
**日期**: 2026年04月24日
