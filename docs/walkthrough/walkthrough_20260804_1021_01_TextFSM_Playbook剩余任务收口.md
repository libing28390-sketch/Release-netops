# TextFSM / Playbook 剩余任务收口执行记录

## 完成摘要

本轮完成工作区内可安全闭环的剩余事项：TextFSM 注册表中英文标题、SYSTEM 只读视觉态、Sandbox 空态提示、滚动与 Toast 避让、模板切换失败保护；Vitest 页面回归基础设施；旧链路兼容开关的防回退断言；前后端质量门禁；业务 PostgreSQL 只读审计。未伪造真实设备或 Playbook Apply 证据，也未写入现有租户数据。

## 实际修改文件

- `src/hooks/usePageTitle.ts`：增加 `textfsm-registry` 中英文标题映射。
- `src/pages/ParserRegistryTab.tsx`：增加布局测试标识、详情滚动区、SYSTEM 只读样式、Sandbox 就地提示，以及模板切换/详情失败时清空旧编辑器内容。
- `src/components/ToastNotification.tsx`：调整全局 Toast 底部避让和窄屏宽度。
- `package.json`、`package-lock.json`、`vitest.config.ts`：引入 Vitest + RTL + jsdom 和 `test:frontend` 脚本。
- `src/pages/ParserRegistryTab.test.tsx`：Sandbox、开关、角色、租户草稿、Diff、样例、生命周期入口和模板切换失败保护回归。
- `src/pages/PlatformRegistryTab.test.tsx`：Viewer 只读和 Platform Maintainer 三步创建向导回归。
- `src/components/PlaybookVersionEditor.test.tsx`：声明式步骤模板和非法 JSON 回归。
- `backend/tests/platform_registry/test_legacy_compatibility_flags.py`：两个 LEGACY 兼容开关的关闭行为回归。
- `docs/plan/20260804_自定义平台_TextFSM_Playbook最终收口任务清单.md`：更新后的任务清单。
- `docs/plans/plan_20260804_1021_01_TextFSM_Playbook剩余任务收口.md`：同步实施计划与实际结果。

工作树中此前已有的后端、迁移、Huawei fixture 和文档改动均保留，未覆盖或清理；构建产生的 `dist/index.html` 已恢复到构建前版本。

## 关键验证

| 验证 | 结果 |
| --- | --- |
| `\.venv\Scripts\python.exe -m pytest backend/tests/platform_registry -q -p no:cacheprovider` | 91 passed |
| `\.venv\Scripts\python.exe -m pytest backend/tests/vendor_audit -q -p no:cacheprovider` | 285 passed |
| `\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider` | 507 passed、1 warning、25 subtests passed；warning 为既有 Starlette/httpx 弃用提示 |
| `npm run lint` | 通过 |
| `npm run test:frontend -- --run` | 3 个文件、11 passed |
| `npm run build` | 通过；仅有既有大 chunk warning |
| 业务 PostgreSQL 只读审计 | schema migration 96/96；templates 119、versions 119、samples 0、parser audit logs 0 |
| 设备绑定只读审计 | 16 台设备，6 台已绑定，10 台 `platform_profile_id` 为空且 `platform_source=LEGACY` |
| Huawei Release 只读审计 | `huawei_vrp` 已发布 `get_link_aggregation` 命令为 `display eth-trunk` |
| 重复 m0090 审计 | 正式文件与工作树重复文件 SHA256 相同；未发现代码引用；未替用户删除 |

## 浏览器复核

服务连接稳定时，DOM 复核确认页面标题为 `TextFSM 注册表 | Nexora`，主标题为 `TextFSM 注册表开发`，SYSTEM 元数据字段带只读属性/样式，Sandbox 空态显示“请先填写测试回显”，主详情滚动区的横向溢出被隐藏。随后服务连接中断，刷新显示 `Failed to fetch`；切换模板时旧编辑器内容可能短暂残留，已加入清空保护。由于服务不可用，本轮没有执行浏览器写流程。

## 未执行验证及原因

- 真实 Huawei VRP5 命令执行：缺少明确设备、窗口和回显留存授权。
- 一次性测试租户浏览器写流程：当前服务断线，且不允许向现有业务租户写入模板、样例、平台或审批数据。
- 真实国产平台在线识别：缺少中兴、锐捷、迪普、迈普设备及脱敏回显。
- 真实 Playbook Dry Run/Apply/审批：缺少授权实验设备和审批范围；本轮不以 fixture 代替。
- LEGACY 开关全消费者关闭演练：当前仍有 10 台未绑定设备，需先完成映射和一个版本周期观测。

## 剩余风险与建议

1. 启动服务并确认 `/api/parser-templates/capabilities`、模板版本 API 稳定后，再做一次浏览器只读和一次性测试租户写流程。
2. 对 10 台 LEGACY 设备逐台确认 vendor/platform/driver/command 链，禁止自动绑定或静默回落 Cisco。
3. 在实验环境关闭旧链路开关，完整验证未映射动作返回 `UNSUPPORTED_ACTION` 后再观察一个版本周期。
4. 由用户决定重复 m0090 文件的保留/移除；该文件当前与正式迁移内容完全相同但位于错误目录。
