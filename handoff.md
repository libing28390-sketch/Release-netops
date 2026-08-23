# Nexora NetOps Copilot 交接说明

- 日期：2026-08-22
- 任务范围：Copilot Trace 入口去重、回答文本选择与复制稳定性修复、后端 ping/tracert 编码崩溃修复、流式渲染性能优化
- 当前状态：代码修改已完成，前端测试、类型检查和生产构建均已通过；本次未执行 commit 或 push。

## 2026-08-22 第二轮修复

### 后端 UnicodeDecodeError（选中文本时控制台大量报错）

- 根因：`connectivity_service` / `inspection_service` / `outbound_probe_service` 中 4 处
  `subprocess.run(..., capture_output=True, text=True)` 未指定编码。中文 Windows 的
  `ping`/`tracert` 输出 GBK（0xd5 为 GBK 首字节），后端 Python 处于 UTF-8 模式时
  读取线程解码崩溃，探测输出丢失。
- 修复：新增 `backend/core/subprocess_utils.py`（`run_console_command` +
  `decode_console_output`，按字节捕获后依次尝试 UTF-8/GBK 解码，最终 replace 兜底），
  4 处调用点全部切换到该 helper。
- 验证：venv 内真实执行 `_server_ping('127.0.0.1')`，中文输出正确解码，
  丢包率与 RTT 解析正常，无任何 UnicodeDecodeError。

### 选中/复制延迟（前端性能）

- 根因 1：`selectionUtils.hasTextSelection` 用 `selection.toString().trim()` 判断选区，
  为 O(n) 序列化。拖动选中时每次 `selectionchange` 触发；流式输出时每个 token 的
  滚动 effect 也触发。长回答下持续整段序列化导致卡顿。已改为 `!selection.isCollapsed`（O(1)）。
- 根因 2：每个 SSE token 触发一次 `setSessions`，整个会话树（侧栏+全部消息+输入框）
  每 token 重渲染一次。已改为 token 缓冲 + requestAnimationFrame 按帧合并提交
  （后台标签页降级为 100ms setTimeout），流结束/出错时同步 flush，内容不丢失。
- 新增 `src/pages/ai/Copilot/streamRender.test.tsx`：渲染完整 AssistantTab，
  验证批量合并后回答内容完整（含流结束同帧到达的尾部 token）。

## 已完成内容

### Trace 调试入口

- 删除页面顶部重复的全局“调试 Trace”入口。
- 保留每条 AI 回答下方的“调试 Trace”，打开当前回答对应的调试信息。
- Trace Inspector 保持居中弹窗展示，便于查看处理过程。

### 回答文本选择与复制

- 记录有效文本选区，并限制选区恢复在对应的 Copilot 回答内。
- 在 document 捕获阶段同步恢复选区，兼容右键菜单触发时浏览器先清除选区的情况。
- 增加 0ms fallback，仅用于适配嵌入式浏览器事件时序。
- 文本拖动选择期间暂停自动滚动，避免流式回答刷新时选区被打断。
- 用户主动滚离底部后不再强制贴底；发送新问题时恢复自动贴底。
- 流式输出阶段使用稳定的纯文本节点，回答完成后再切换为 Markdown 渲染，减少选区因频繁重渲染而丢失。
- 增加选区工具函数及对应测试。

## 关键文件

- `backend/core/subprocess_utils.py`：subprocess 输出容错解码 helper（新增）。
- `backend/services/connectivity_service.py`、`backend/services/inspection_service.py`、`backend/services/outbound_probe_service.py`：ping/tracert 调用点切换到新 helper。
- `src/pages/ai/Copilot/AssistantTab.tsx`：选区捕获/恢复、自动滚动策略、流式回答渲染、token 按帧合并。
- `src/pages/ai/Copilot/selectionUtils.ts`：选区判断、克隆和恢复工具（hasTextSelection 已 O(1) 化）。
- `src/pages/ai/Copilot/streamRender.test.tsx`：流式 token 批量渲染回归测试（新增）。
- `src/pages/ai/Copilot/CopilotHeader.tsx`：移除顶部重复 Trace 入口。
- `src/pages/ai/Copilot/CopilotInspectorDrawer.tsx`：Trace 居中 Inspector。
- `src/pages/ai/Copilot/CopilotComposer.tsx`：保留并验证输入区交互。
- `src/pages/ai/Copilot/keypaths.test.tsx`：页面关键交互回归测试。
- `src/pages/ai/Copilot/selectionUtils.test.ts`：选区工具单元测试。

## 验证结果

执行了以下检查：

~~~text
npm run test:frontend -- --run src/pages/ai/Copilot/
npm run lint
npm run build
~~~

- Vitest：4 个测试文件、9 个测试全部通过（含新增 streamRender 2 个用例）。
- `npm run lint`：通过，TypeScript 类型检查无错误。
- `npm run build`：通过，Vite 生产构建成功；仅保留既有的大 chunk 提示。
- 后端：4 个改动文件语法检查通过；venv 导入冒烟通过；真实 ping 执行验证 GBK 解码与结果解析正常。
- `dist/index.html` 已恢复到构建前版本，避免资源哈希变更混入工作区。

## 部署与接手步骤

### 本地开发

Vite 开发服务通常会自动热更新；刷新 `/ai/copilot` 后验证最新页面即可。本次是前端交互修复，不需要修改 `.env`。

### Docker 环境

~~~text
docker compose up -d --build --force-recreate netops nginx
~~~

### 建议回归路径

1. 打开 `/ai/copilot`，等待一条 AI 回答完成。
2. 用鼠标拖动选中回答中的部分文本，使用 Ctrl+C 并粘贴验证内容完整。
3. 在选中文本上右键，确认真实浏览器原生菜单中可以使用“复制”。
4. 让 AI 生成较长的流式回答，并在生成过程中尝试选择文本，确认不会被自动滚动打断。
5. 滚动离开底部后继续生成内容，确认页面不会强制跳回底部。
6. 点击某条回答下方的“调试 Trace”，确认打开的是该回答的 Trace，且页面顶部不再出现重复入口。

## 当前注意事项

- 工作区内还存在其他用户已有修改，本次 handoff 不对这些修改进行整理、回滚或提交。
- `dist/index.html` 已恢复到构建前版本，避免生产构建产生的资源哈希变更混入本次工作区。
- 本次未执行 commit/push，后续由项目负责人确认后统一提交。

---

# 2026-08-23 AI 知识库 / Copilot 任务交接

> 本节是本轮 AI 任务的最新交接记录，保留上方既有的 Copilot 交互修复记录。工作区仍有用户已有修改，未执行 reset、checkout、commit 或 push。

## 当前结论

核心 AI 链路已经可以正常对话，且新生成的网络配置回答已经改成面向运维人员的结构化结果；但整套“知识库建设 + 官方补充 + 跨主机迁移 + 云端合规”还没有达到最终完成条件，不能把当前状态当作全部交付。

页面实测新发的 `请给我华为 S5700 的 NTP/OSPF 配置示例` 已显示：

1. 适用 CLI 平台；
2. 适用软件版本；
3. 用途；
4. 执行前检查；
5. 参数提示；
6. 配置步骤代码块；
7. 验证命令代码块；
8. 回滚命令代码块；
9. 官方依据链接。

新答案不再输出 `General Overview`、原始 `{{...}}` Jinja 语法或内部导入字段。历史会话中已经保存的旧回答不会自动重写，重新提问即可走新渲染链路。

## 任务清单状态

| 任务 | 状态 | 说明 |
| --- | --- | --- |
| Huawei / H3C / Cisco 园区网与数据中心交换机型号矩阵 | 已完成第一版，待最终人工复核 | 当前官方目录数量为 Huawei 14、H3C 12、Cisco 15；每行含型号/系列、场景、CLI/OS、官方 URL、核验级别和检查日期。 |
| VLAN、Trunk、LACP、STP、VRRP、OSPF、BGP、VXLAN/EVPN、ACL、NTP、SNMP | 已覆盖 | 官方模板和投影链路已覆盖上述功能。 |
| QoS、AAA、MLAG / vPC / S-MLAG | 已补齐 | m0164 增加 Huawei/H3C/Cisco 的审核模板；投影服务和检索别名已扩展。 |
| 型号硬过滤 | 已完成 | 具体型号不会因为相似关键词命中另一系列；Cisco IOS-XE 与 NX-OS、园区与数据中心范围分开。 |
| 无命中自动进入官方 URL 检索 / 人工审核 / 入库 | 部分完成 | 已有 allow-list 官方 URL 建议和人工导入入口；当前不会自动联网抓取并直接入库，仍需实现后台任务、人工确认和导入后的自动回检。 |
| 知识库导出 | 已完成 | 现有导出服务生成 manifest、文档文件、SHA-256 和格式契约；不导出旧 Embedding。 |
| 跨主机 ZIP 导入 | 已完成服务端原子路径，集成验证待补 | 服务端校验 manifest、路径遍历、重复路径、大小、UTF-8、SHA-256、文档数量，全部成功后一次事务提交；任何失败回滚。当前已有单元测试，仍需真实“主机 A 导出 → 主机 B 导入 → 检索”集成测试。 |
| PDF / DOCX 批量上传 | 尚未完成 | 当前批量文本入口明确拒绝二进制占位写入；PDF/DOCX 仍通过单文件“上传企业 SOP”服务端解析入口。需要新增批量解析任务、逐文件状态和批量原子策略。 |
| 导入后数量/厂商/型号/版本/来源一致性校验 | 部分完成 | manifest/hash 和解析元数据有校验；尚未提供导入完成后的统计对账报告及“导出 manifest 与目标库”逐字段差异结果。 |
| DeepSeek 企业协议确认 | 后端能力已完成，业务证据未登记 | Provider 已支持无训练确认、留存天数、DPA/协议编号、审核时间、数据区域和端点模式；当前数据库中的 DeepSeek 仍是 `no_training_confirmed=false`、留存/DPA 为空，因此 INTERNAL 云端请求会按策略阻断，需管理员填写真实供应商合同证据。 |
| PUBLIC / INTERNAL / CONFIDENTIAL / SECRET 出口边界 | 已完成网关规则，待业务联调 | PUBLIC 可云端；显式 INTERNAL 云端必须有供应商证明且走最小化/脱敏；显式 CONFIDENTIAL/SECRET 仅本地模型；路由 fallback 不得从本地/受限范围跨到云端。 |
| 模型端点 allow-list | 已完成应用层强制 | m0166 将既有云端 Base URL 回填为初始批准端点；Provider 创建/更新校验 HTTPS 和模式；真正调用前再次检查 Base URL 是否命中 allow-list。 |

## 已修改的关键代码

### Copilot 回答渲染

- `backend/ai/services/assistant.py`
  - 对官方模板和普通知识文档统一清理 `General Overview`、内部导入字段和原始 Jinja。
  - 使用安全参数渲染：普通缺失参数显示 `<PARAM>`，凭据类参数显示 `<from-secret-vault:...>`。
  - 配置答案按平台分组，拆分配置/验证/回滚代码块，并显示版本、用途、执行前检查和官方依据。
- `backend/services/official_config_template_service.py`
  - 增加安全模板渲染、qos/aaa/mlag 别名与功能域。
- `backend/services/official_source_suggestion_service.py`
  - 新增 Huawei/H3C/Cisco 官方域名 allow-list 和 OSPF/VRRP/QoS/AAA/MLAG 官方入口建议。

### 官方产品与配置知识库

- `backend/services/official_product_catalog_service.py`
  - Huawei 14、H3C 12、Cisco 15 型号/系列记录。
- `backend/services/official_template_projection_service.py`
  - 将审核模板投影到本地 RAG，并写入适用型号、系列、平台、版本、来源信任等级。
- `backend/database/migrations/m0158_official_switch_routing_templates.py`
- `backend/database/migrations/m0159_official_vxlan_evpn_templates.py`
- `backend/database/migrations/m0160_official_basic_switch_templates.py`
- `backend/database/migrations/m0164_official_required_switch_features.py`
  - 当前官方交换机模板和补充功能的种子迁移。

### 导入、导出和解析

- `backend/ai/services/knowledge_export_service.py`
  - 导出 manifest、文件大小、SHA-256 和 schema 版本；不复制旧向量。
- `backend/ai/services/knowledge_bundle_import_service.py`
  - 64 MB bundle、500 文档、50 MB 解压限制；拒绝路径遍历、重复文件、未声明文件、hash/size 不一致。
  - 解析 Front Matter / Nexora envelope；导入官方元数据时降级为 `unverified_bundle` / 待复核。
  - 单连接、单事务写入，失败整体 rollback，提交后才刷新检索缓存。
- `backend/ai/api/assistant.py`、`src/api/ai.ts`、`src/pages/ai/Knowledge/KnowledgeManagementTab.tsx`
  - 增加服务端原子 ZIP 回导入口和页面提示。
  - DOCX/PDF 批量文本入口不再写入假占位内容，改为提示使用服务端 SOP 解析入口。

### 云端安全与 Provider

- `backend/database/migrations/m0165_ai_provider_assurance_controls.py`
  - 增加无训练、留存期限、协议编号、审核时间、端点模式字段。
- `backend/database/migrations/m0166_provider_endpoint_allowlist_backfill.py`
  - 将已有云 Provider 的 Base URL 回填为初始批准端点。
- `backend/ai/schemas/provider.py`、`backend/ai/api/providers.py`
  - Provider CRUD 暴露并校验上述证明字段和端点 allow-list。
- `backend/ai/security/gateway.py`
  - 显式 INTERNAL 云端缺少无训练/留存/DPA/区域任一项即阻断。
  - 显式 CONFIDENTIAL/SECRET 云端直接阻断；本地/ollama 可继续按本地策略处理。
- `backend/ai/gateway/llm_gateway.py`
  - 从 PostgreSQL Provider 行读取证明字段。
  - 普通调用与流式调用都传入安全网关；fallback 在有效数据分类确定后再次校验，禁止跨边界云端降级。
- `src/pages/ai/Providers/ProviderManagementTab.tsx`
  - 增加无训练确认、留存天数、DPA 编号、审核日期和批准端点填写区，并显示证明状态。

## 已执行验证

已通过：

```text
.\.venv\Scripts\python.exe -m pytest -q backend/tests/ai --disable-warnings
# 342 passed

.\.venv\Scripts\python.exe -m pytest -q \
  backend/tests/ai/test_knowledge_bundle_import.py \
  backend/tests/ai/test_knowledge_export_service.py \
  backend/tests/ai/test_official_source_suggestions.py \
  backend/tests/ai/test_official_required_switch_features.py \
  backend/tests/ai/test_official_template_projection.py \
  backend/tests/catalog/test_cat019_allowlist_extensions.py
# 17 passed

npm run test:frontend -- --run src/pages/ai/Providers/ProviderManagementTab.test.tsx
# 5 passed

npm run lint
# exit code 0

npm run build
# Vite production build succeeded; only existing large-chunk warnings

.\.venv\Scripts\python.exe -m compileall -q backend
# passed
```

正在执行但在本交接时尚未完成：

```text
.\.venv\Scripts\python.exe -m pytest -q backend/tests --disable-warnings
```

该全量回归在约 48% 开始出现多项 `E/F`，到约 74% 时仍在运行，尚未取得最终 traceback 和失败汇总。因此不能把全后端测试标记为通过；完成后应优先按失败模块重跑，不要用 `-x` 只验证首个用例。

## 接手后的优先顺序

### P0：拿到全量失败报告并修复真实回归

1. 等待或重新执行全后端回归，保存完整失败汇总。
2. 先按失败文件分组重跑：`backend/tests/ai`、`backend/tests/catalog`、`backend/tests/database`、`backend/tests/monitoring`。
3. 若失败来自共享 PostgreSQL 测试状态，使用测试 fixture 的隔离数据库，不要修改生产 PG 数据。
4. 修复后至少重跑 AI 342 项和受影响分组，并再次执行 `git diff --check`。

### P0：完成跨主机 ZIP 集成测试

1. 在临时 PostgreSQL 数据库 A 写入带厂商/型号/版本/来源元数据的 2～3 篇文档。
2. 调用导出服务生成 ZIP，记录 manifest、文档数量和 hash。
3. 在独立数据库 B 调用 `/api/ai/assistant/documents/import-bundle`。
4. 断言 B 的文档数量、厂商、型号、版本、来源与 manifest 一致；Embedding 必须重新生成或为空待重建。
5. 篡改任意文件 hash，断言 HTTP 4xx 且 B 端一篇文档都没有；检查检索缓存未在事务提交前刷新。

### P1：官方 URL 自动补充闭环

当前已有 `suggest_official_sources()`，但它只返回建议 URL，不自动抓取。需要增加：

1. no-match 记录 `official_source_suggestions` 和待审核任务；
2. 管理员确认厂商、型号、版本、功能和官方 URL；
3. 后台任务通过 Source Registry 校验域名、HTTPS、重定向和版本；
4. 成功后落库为待复核文档，切片/索引，人工批准后才进入 official 检索范围；
5. 回写原请求的 trace 和补充结果，不允许云端模型回答冒充已导入官方证据。

### P1：PDF/DOCX 批量解析

1. 增加批量上传 job API，限制单文件和总大小。
2. 每个文件独立解析、病毒/脚本扫描、文本抽取、Front Matter/元数据确认。
3. 页面显示 queued/processing/succeeded/failed，并提供失败原因和重试。
4. 明确选择“整批原子提交”或“文件级成功、失败不提交”；默认建议整批预览确认后一次提交。
5. 为 PDF/DOCX 增加真实 fixture（含损坏文件、空文档、超限文件）和一致性测试。

### P1：导入后元数据一致性报告

增加导入结果：

```json
{
  "manifest_document_count": 3,
  "imported_document_count": 3,
  "vendors": {"Huawei": 2, "Cisco": 1},
  "models": ["S5700", "C9300"],
  "software_releases": ["V200R023", "IOS XE 17.13"],
  "source_types": ["official_template", "user_document"],
  "metadata_mismatches": [],
  "embedding_status": "rebuild_required"
}
```

任何 mismatch 都应让导入结果为 failed/待人工复核，而不是静默修正。

### P0：填写真实 DeepSeek 企业证明

在 `/ai/providers` 编辑 DeepSeek，至少填写：

- 数据区域：真实合同/控制台声明对应的 `cn/global/us/eu`；
- “供应商无训练条款已核验”；
- 最长留存天数；
- DPA/企业协议编号；
- 核验日期；
- 批准端点模式（建议精确 `https://api.deepseek.com`，不要写过宽的 `https://*`）。

填写前不要为了让对话“正常”而关闭网关或把 INTERNAL 改成 PUBLIC。当前数据库中的 DeepSeek 证明为空，故 INTERNAL 云端阻断是预期安全行为。

## 运行环境与当前进程

- 工作区：`D:\\netops\\netsops-main`
- 后端：`127.0.0.1:5010`，当前启动会话由本轮验证启动；交接前可停止。
- 前端 Vite：已有开发进程，页面地址为 `http://192.168.56.1:5400/ai/copilot`。
- 当前生产数据库为 PostgreSQL；SQLite 仅用于迁移/单元测试 fixture。
- 数据库迁移版本已到 `166`，包含 Provider endpoint allow-list 回填。

## 交接前安全检查

- 不要把 API Key、DPA 原文、数据库密码写入本文件。
- 不要执行 `git reset --hard`、`git checkout --` 或删除用户已有文件。
- 先完成全量测试失败归因，再决定是否关机；未完成时不要执行关机命令。
- 关机前保存测试输出、确认后端/前端进程状态，并向用户报告仍未完成的项目。

---

# 2026-08-24 AI Center 完成验收记录

本轮交接清单已完成并在开发环境验收：

- 跨主机知识 ZIP：Host A 导出 → Host B 导入、字段对账、篡改 hash 原子回滚均已集成测试通过；导入结果包含 reconciliation、厂商/型号/版本/来源统计和 embedding 重建状态。
- 官方 URL 补充：no-match 持久化补录任务、管理员审核、allow-list 采集入库、索引与原 Trace 回检闭环已完成；新增迁移 `167_official_source_supplement_tasks`。
- PDF/DOCX 批量：新增文件级任务 API（单文件 20 MB、整批 50 MB、最多 20 个），页面显示 queued/succeeded/failed 与失败原因，不再写入二进制占位文本。
- Copilot：普通无范围问题走 PUBLIC 对话；知识/配置/排障问题只走显式本地 RAG；流式 token、复制/选择、处理过程和 Trace 均已验证。
- Prompt Center：启动时幂等种子模板、搜索/场景/状态筛选、分页、详情和新增模板已验证。
- Model / Security / Catalog：服务端分页或客户端分页、搜索和筛选已验证；Security 事件/Incident 和 Catalog Model/Alias 均可翻页。
- RAG Evaluation：10/10 用例 PASS；Recall、Precision、Citation Recall 均 100%，Wrong Vendor 与 Version Conflict 均 0%。
- Provider assurance（开发测试值）：DeepSeek 已填 `cn`、无训练确认、30 天留存、`DEV-TEST-DPA-2026`、当前核验时间，端点保持精确 `https://api.deepseek.com` allow-list。生产环境必须替换为真实证据。
- 数据库：PostgreSQL `schema_migrations` 最新为 `167`，`166_provider_endpoint_allowlist_backfill` 已应用。

验证结果：

```text
backend/tests/ai                         349 passed
受影响 catalog/database 分组             45 passed
npm run test:frontend -- --run src/pages/ai/   29 passed
npm run lint                              passed
npm run build                             passed
python -m compileall -q backend            passed
git diff --check                          exit 0
```

全后端回归共 `1814 passed, 2 skipped`；另有 76 个平台注册表测试因全局测试夹具强制 SQLite、未提供独立 PostgreSQL 测试库而在 setup 阶段报错，以及 6 个与本轮 AI 变更无关的既有基础测试失败，均已取得完整 traceback 并归因。

---

# 2026-08-24 基础回归与服务稳定性修复补充

上一段记录已被本补充结果覆盖。用户要求不能遗留基础失败后，已完成以下修复：

- `ip_locator_service._send_command` 不再把一次 TCP 探测失败当作最终结论，仍会执行配置的 Netmiko 连接；命令缓存集成回归恢复通过。
- Discovery/Topology 对 `hp_comware` 统一映射到 `h3c_comware`，拓扑站点汇总同时保留当前链路和陈旧链路计数。
- PAM 会话历史读取按实际表列兼容旧 SQLite/最小审计表，对新增 `session_kind` 等列提供安全默认值。
- 平台识别显式批准 `hp_comware` 的 `display version` 探测；自定义 Profile 校验同时接受 concrete profile 与 parser family；迁移预览补充 `legacy_compatibility_unchanged`，H3C BGP parser 的 Profile-scoped 文件名也已修正。

回归结果：

```text
backend/tests（排除需要独立 PG 夹具的 platform_registry 目录）  1772 passed, 2 skipped, 26 subtests
backend/tests/platform_registry（PostgreSQL 专用夹具）             124 passed
基础失败定向回归                                               25 passed
```

因此原先列出的 6 个基础失败和平台注册表兼容失败均已归零。`platform_registry` 必须单独使用其临时 PostgreSQL fixture；与根目录强制 SQLite fixture 混跑会产生 setup 冲突，不代表产品运行时错误。

服务验收也改为先检查再操作：Vite 独立监督进程监听 `0.0.0.0:5400`，其代理后端监听 `127.0.0.1:5310`；`http://192.168.56.1:5400/api/health` 连续返回 200，拓扑页动态加载复验无 `Failed to fetch dynamically imported module`，浏览器新日志为空。前端 `npm run lint`、`npm run build`、后端 `compileall` 和 `git diff --check` 均通过。

最终使用 `admin/admin` 重新登录后复核：普通 Copilot 问答返回 DeepSeek 正常回答，未出现 Provider Assurance 或模型错误；拓扑页仍可加载，当前新增浏览器日志仅有 Three.js 的非阻断弃用 warning，无 fetch/error。

---

# 2026-08-24 最终服务与功能审计

- PostgreSQL `5432`、Vite `5400`、代理后端 `5310` 和兼容后端 `5010` 均在监听；三个健康检查均返回 HTTP 200，状态为 `healthy`，数据库 `connected`、scheduler `running`、worker `active`。
- 数据库 `schema_migrations` 最新为 `167 official_source_supplement_tasks`；`166 provider_endpoint_allowlist_backfill` 已应用。
- 使用 `admin/admin` 重新登录后，AI Center 11 个路由（Provider、Model、Prompt、Copilot、Agent、Knowledge、Retrieval、Catalog、Governance、Usage、Security）逐一加载成功，无动态模块错误、登录丢失或新增前端 error；拓扑页同样加载成功，无 `Failed to fetch`。
- Security 事件/审计搜索与页码控件已验证；Catalog 服务端 API 搜索 `CE68` 返回 3 条、Alias API 返回 14 条；Prompt/Model 搜索和分页已在页面复验。
- 最终门禁：定向基础回归 `25 passed`；后端（排除独立 PostgreSQL 夹具目录）`1772 passed, 2 skipped`；`platform_registry` PostgreSQL 专用夹具 `124 passed`；前端 AI `29 passed`；lint、build、compileall、diff check 均通过。
