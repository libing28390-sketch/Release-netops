# TextFSM / Playbook 剩余任务收口实施计划

## 目标

在不伪造真实设备证据的前提下，完成工作区内可闭环的剩余任务：注册表 UI 体验、页面级回归基础设施、功能开关与角色权限验证、隔离写流程回归、质量门禁和审查清单更新。

## 当前问题与范围

- `/automation/textfsm-registry` 已具备核心能力，但路由标题未纳入中英文页面标题映射，SYSTEM 只读字段缺少只读视觉态，Sandbox 空态缺少就地提示，详情区存在嵌套滚动和 Toast 遮挡风险。
- `package.json` 没有前端测试脚本，当前没有组件/E2E 测试基础设施。
- 真实 Huawei VRP5、国产设备和真实 Playbook Apply 属于外部环境验收；若缺少明确设备、租户和变更窗口，只能标记为未验证，不能用本地 fixture 替代。
- 工作树中的重复 m0090 文件需要先做内容和引用审计，再由用户确认归属，不直接删除。

## 拟修改文件

- `src/hooks/usePageTitle.ts`
- `src/pages/ParserRegistryTab.tsx`
- `src/components/AppMainContent.tsx`（仅在 Toast 避让需要时）
- `package.json`、`package-lock.json`、`vitest.config.ts`（页面测试基础设施）
- `src/pages/ParserRegistryTab.test.tsx`
- `src/pages/PlatformRegistryTab.test.tsx`
- `src/components/PlaybookVersionEditor.test.tsx`
- `backend/tests/platform_registry/test_legacy_compatibility_flags.py`
- 相关测试 mock/helper 文件
- 对应 `docs/walkthrough/` 验证报告和审查清单

## 实施步骤

1. 提取/补齐注册表 UI 状态辅助逻辑，保持 API、权限和持久化语义不变。
2. 补齐中英文标题、只读样式、Sandbox 就地帮助、滚动布局和 Toast 避让。
3. 建立最小可维护的 Vitest + DOM 测试环境，覆盖成功、失败、空态、权限、SYSTEM 只读和关键生命周期入口。
4. 使用隔离测试夹具执行创建/Fork/Sandbox/样例/提交/审批/发布/回滚与乐观锁回归；浏览器写流程不触碰当前业务租户，保留为需要一次性测试租户的外部验收项。
5. 复核旧链路开关的消费者、平台绑定和 `UNSUPPORTED_ACTION` 行为；不在没有版本周期观测证据时删除旧目录。
6. 串行执行后端专项、完整后端、前端 lint、前端测试和 production build，并更新审查清单与 walkthrough。

## 验证计划

- `npm run lint`
- `npm run test:frontend -- --run`
- `npm run build`
- `pytest backend/tests/platform_registry -q -p no:cacheprovider`
- `pytest backend/tests/vendor_audit -q -p no:cacheprovider`
- `pytest backend/tests -q`
- 浏览器检查中文/英文切换、SYSTEM 只读态、Sandbox 空态和隔离写流程
- PostgreSQL 迁移状态、业务数据计数、审计记录和测试租户清理

## 风险与回滚

- 前端测试依赖增加会改变 lockfile；若依赖安装或浏览器环境不可用，保留后端/静态回归并记录阻塞，不弱化断言。
- UI 改动仅限注册表页面和通用 Toast 容器；可通过回滚对应文件恢复。
- 写流程测试必须使用隔离租户/临时库，任何异常先停止，不执行真实设备 Apply。
- 真实设备、审批窗口和旧链路版本观测由用户提供授权与范围后另行验收。

## 执行结果（2026-08-04）

- UI 已补齐 `textfsm-registry` 中英文页面标题、SYSTEM 只读视觉态、Sandbox 空回显就地提示、详情区滚动边界、Toast 避让，以及切换/加载失败时清空旧模板内容的保护。
- 已增加 Vitest + React Testing Library + jsdom 基础设施；3 个测试文件共 11 项通过，覆盖开关关闭/开启、SYSTEM 只读、Template Developer/Release Manager/Viewer、Sandbox 成功/失败、租户草稿、Diff、样例、生命周期入口和模板切换失败保护。
- 旧链路兼容开关回归新增 2 项：关闭 `LEGACY_TEXTFSM_FILE_FALLBACK_ENABLED` 不再返回旧文件名；关闭 `LEGACY_COMMAND_CATALOG_ENABLED` 对未注册平台返回空命令而不是旧目录命令。
- 质量门禁结果：平台注册专项 91 passed；厂商回归 285 passed；完整后端 507 passed、1 warning、25 subtests；`npm run lint`、`npm run test:frontend -- --run`、`npm run build` 均通过（build 保留既有大 chunk warning）。
- 业务 PostgreSQL 只读核对：schema migration 96/96；parser templates 119、versions 119、samples 0、parser audit logs 0；设备 16 台，其中 10 台 `platform_profile_id` 为空且 `platform_source=LEGACY`，未自动绑定。
- 浏览器复核时服务连接中断，刷新显示 `Failed to fetch`；因此本轮没有把浏览器写流程、真实设备命令、真实 Playbook Apply/审批当作完成证据。
