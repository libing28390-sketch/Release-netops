# AI 发布门禁与 UAT-04 复测记录

- 执行日期：2026-09-05
- 记录更新：2026-09-06
- 基线：`073c5ea570fc20a6b49a6fe58730beeaa5da2dfd`
- 分支：`main`，推送后 `origin/main` 与本地同步
- 发布结论：`HOLD — NOT A RELEASE CANDIDATE`
- 证据边界：本记录只保存状态、指标、路由、调用类型、来源身份和脱敏标识；不保存完整问题、完整模型回答、凭据、API key、设备地址或原始配置正文。

## 1. 远端门禁

### Knowledge Engine Evaluation #12

- Run：[33975278083](https://github.com/libing28390-sketch/netsops/actions/runs/33975278083)
- 结果：成功；job `EVAL-010 small fixed set (PostgreSQL)` 成功
- 用途：v3 signed 50-anchor、标准 PostgreSQL、隔离 PostgreSQL/pgvector、review gate
- 总耗时：约 1 分 57 秒；job 约 1 分 52 秒
- artifact：`knowledge-eval-33975278083`，约 38.6 KB
- artifact SHA-256：`8345049fadd5a3db4482333d658097b3782410922c2d9d5d92fbda0a1a6eed7b`

### Backend Pytest Check #319

- Run：[33975278030](https://github.com/libing28390-sketch/netsops/actions/runs/33975278030)
- 结果：成功
- 总耗时：约 7 分 41 秒
- 输入：隔离 PostgreSQL/pgvector、CI 专用测试配置；无发布 artifact

### Build and Sync to Release Repo #485

- Run：[33975277962](https://github.com/libing28390-sketch/netsops/actions/runs/33975277962)
- 结果：成功；提交 SHA 与本记录基线一致
- 总耗时：约 14 分 07 秒
- Ubuntu job：[101330770284](https://github.com/libing28390-sketch/netsops/actions/runs/33975277962/job/101330770284)，成功，约 10 分 50 秒
  - 前端/Vitest：`53/53` 测试文件、`195/195` 测试结果通过
  - 完整 Knowledge Engine release gate：成功
  - PostgreSQL/pgvector：成功启动并完成门禁
- Windows job：[101332281860](https://github.com/libing28390-sketch/netsops/actions/runs/33975277962/job/101332281860)，成功，约 2 分 33 秒
  - sanitized `Release-netops` 的 `windows` 分支已发布
  - 该分支最新可定位提交：`6ff86ca`
  - Windows 发布产物已存在；未把个人运行文件或 `.codex` 状态带入发布树
- workflow 环境契约：Python 3.11、Node `22.22.2`、PostgreSQL/pgvector 17；v3 signed Dataset 已由 workflow 显式引用。
- 非阻断提示：GitHub Actions 的 checkout/setup-python/upload-artifact action 报告其 Node 20 runtime 将被 runner 的 Node 24 替代；本次 job 成功，该提示需后续单独升级 action 主版本时再处理。

## 2. 本地 UAT-HUA-VLAN-LOCAL-01

- 页面：已登录本地 Nexora Copilot，`http://192.168.56.1:5400/ai/copilot`
- 服务：前端 `5400`、后端 `5310`、PostgreSQL `5432`
- 结果：`PASS`
- 场景：混合中英文的 Huawei VRP VLAN + Access 只读配置请求
- 首轮范围识别：`vendor=Huawei`、`feature=access_port`，页面要求补充平台信息
- 选择平台：`Huawei VRP`
- 终态路由：本地知识直出；`intent=knowledge_retrieval`
- 命中文档：`official-template-official-huawei-access-port`
- 命中内容特征：Access-port 专用模板，包含 `port link-type access` 与 `port default vlan`；未返回广义 VLAN 模板
- 来源：1 个 `official_template`，`trust=official`，`validation=validated_official`
- 检索元数据：`source=local_rag`、`status=hit`、`final_document_count=1`、`cross_platform_search=false`、`wrong_vendor_count=0`、`version_conflict_count=0`
- 安全与调用边界：风险 `low`、`external_egress=false`、`cli_executed=false`、设备连接 `false`、模型输入/输出 token `0`
- Trace：页面 Trace Inspector 可用；记录了意图、过滤条件、来源身份、request/trace 标识和消息哈希模式；未导出原始 payload 到本记录
- 来源链接：[Huawei VLAN configuration examples](https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans)

## 3. 本地自动化回归摘要

- 查询归一化与意图解析：`20 passed`
- 官方模板 fallback：`5 passed`
- anchor review/baseline：`9 passed`
- CI 等价 AI/Knowledge focused suite：`836 passed, 1357 deselected`
- 本记录只把浏览器案例 `UAT-HUA-VLAN-LOCAL-01` 标记为通过；不能据此把完整 UAT-001、真实 Sidecar 或生产发布标记为完成。

## 4. 尚未关闭的发布阻断

- 真实 BGE reranker model ready、灰度和资源证据
- 真实 Docling Sidecar 批量 PDF/DOCX 对比
- 真实 Langfuse metadata-only trace 与故障旁路
- 纳入范围 Provider 的 live matrix 与 resilience 证据
- 完整 UAT-001 的四厂商逐案例签署，以及 UAT-01/02/03/05
- 目标生产数据库备份、迁移、恢复、Kill Switch 和正式回滚
- dirty worktree 收口、Release Candidate SHA/tag、变更清单、回滚方案和正式审批

因此，本轮远端 CI 与 UAT-04 已有可审计证据，但 readiness 仍保持 `HOLD`。

## 5. 2026-09-06 浏览器 UAT-001 增量（初次旧运行实例观察）

- 已在同一已登录 Chrome 会话中补跑四厂商各 5 个案例，以及 UAT-02/UAT-03 的流程、资产、告警、IP/MAC、排障和安全负向矩阵。
- 逐案例的脱敏终态、来源、外发、CLI 和人工签署字段见 [浏览器 UAT-001 脱敏矩阵记录](../knowledge-engine/eval/eval-browser-uat-live-20260906.md)。
- 本批未 push、未部署、未连接设备、未执行 CLI；Provider 429/超时/熔断恢复仍未通过浏览器注入故障，因此不把 UAT-03 记为完全闭环。
- 发现一个需修复的前端展示问题：厂商/平台冲突澄清卡中的平台候选按钮把内部候选对象序列化到用户可见文案，包含租户标识；未观察到跨租户数据读取，但该项保持 `PARTIAL`。
- 告警查询在空 `alert_ids` 上进入受控 Provider 通用参考，未生成确定性本地告警计数；该项保持 `PARTIAL`。

## 6. 2026-09-06 本地修复与运行态版本核对

用户恢复任务后，本地工作区完成两项针对 2026-09-05 浏览器缺陷的修复，并完成自动化回归：

- 平台冲突澄清：产品解析器富对象只投影规范化 `cli_platform` 字符串，不再把租户、型号、产品系列或其他内部字段序列化到用户可见候选项。
- 告警聚合：明确的告警数量、未恢复数量和最近 24 小时新增数量由 PostgreSQL 租户范围内事实只读聚合；非流式和流式 Assistant 路径均标记为 `local_operation`、`external_egress=false`，不把告警明细放入模型上下文。
- Ubuntu 部署脚本：移除删除源码、测试、文档和草稿目录的生产清理动作；保留源码和 Git 元数据。脚本中既有的 `git reset --hard origin/main` 行为未在本轮改变，仍需单独审批后处理。

本地验证证据：定向修复回归 `22 passed`；修复后 AI 全量复跑 `563 passed in 243.19s`；PostgreSQL-only `0 violation(s)`；`npm run lint`/`tsc --noEmit` 通过；Git Bash `bash -n deploy-ubuntu.sh` 通过；`git diff --check` 通过。完整后端直接收集仍有 3 个与本次改动无关的既有 `conftest` 导入错误；排除这些文件后得到 `2200 passed`、`26` 个 subtests 通过和 1 个既有 IPAM 测试 schema 失败，故不将其宣称为完整后端通过。

当前已登录浏览器连接的运行实例没有加载本工作区版本：平台冲突复测仍显示旧的内部对象候选文案，告警复测仍落到旧的意图服务不可用回退。因此这两项不能记为 live UAT `PASS`，也没有在本轮部署、重启、生产写入、设备连接或 push。发布结论保持 `HOLD — NOT A RELEASE CANDIDATE`；详见 [2026-09-06 浏览器 UAT 脱敏矩阵记录](../knowledge-engine/eval/eval-browser-uat-live-20260906.md)。

页面 Trace 进一步显示告警回包为正常 SSE，但意图元数据是 `GENERAL_QA`/`chat`，`route_model=null`，Provider/模型未上报，随后进入本地安全回退；当前健康接口为 200 且数据库已连接，页面路由模型显示 `unhealthy`。这证明问题位于旧运行实例的意图路由/Provider 状态，而不是前端渲染或浏览器网络断开。

## 7. 2026-09-06 当前工作区运行态复测（13:01–13:03）

在上一节记录的旧运行实例退出后，使用当前工作区重新执行 `npm run dev`，并继续使用已登录的 Chrome 页面 `http://192.168.56.1:5400/ai/copilot`。本节是当前运行态证据，上一节的 stale 结论仍保留为历史审计记录。

- **平台冲突澄清：** 当前页面的候选按钮仅显示规范化的 `Huawei VRP`、`Huawei YunShan V300`、`Huawei YunShan V600` 和 `display version` 标签；未出现租户、产品对象、型号或其他内部字段序列化。
- **告警本地聚合：** 新建空会话后，页面显示未恢复 `23` 条、最近 24 小时新增 `72` 条、范围总数 `412` 条。Trace 为 `Intent=alarm_search`、`execution_mode=local_operation`、`external_egress=false`、输入/输出 Token 为 `0`、耗时约 `7 ms`；处理步骤注明 PostgreSQL 聚合且未调用大模型改写。
- **未确认高风险操作：** 新建空会话后，页面显示“执行前安全确认 / 高风险 · 需确认 R3”，要求补充目标设备、变更内容与确认；Trace 为 `execution_mode=local_clarification`、`external_egress=false`、`cli_executed=false`、输入/输出 Token 为 `0`、耗时约 `4 ms`，未连接设备。
- **Provider egress 修正：** 早先运行态曾在意图 Provider 熔断前等待约 30 秒；已新增 `_deterministic_high_risk_decision`，危险短语在意图 Provider 之前直接进入本地确认，不再产生这类外发和等待。结构化意图回归 `25 passed`，安全/路由四文件聚焦回归 `29 passed`，完整 `backend/tests/ai` 为 `565 passed in 232.34s`，`git diff --check` 无错误（仅 CRLF 提示）。
- **边界：** 本节没有点击确认、没有执行设备操作、没有部署或 push；Provider 429/连接超时/读取超时/熔断恢复的浏览器故障矩阵、四厂商逐案例人工签署、生产迁移/回滚和 Release Candidate 仍未完成，发布结论继续为 `HOLD — NOT A RELEASE CANDIDATE`。
