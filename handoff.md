# Nexora AI/RAG 整改与生产验收交接记录

- 更新时间：2026-09-06（已继续本地修复、前端交互调整与当前工作区运行态复测；完整浏览器 UAT 已完成 38/38 条逐案例签署，真实依赖与生产发布仍保持 HOLD）
- 交接状态：`IN PROGRESS — LOCAL FIXES VALIDATED / CURRENT WORKSPACE UAT INCREMENTAL PASS / RELEASE HOLD`
- 主任务清单：[plan_20260905_2257_01_AI发布剩余任务清单.md](docs/plans/plan_20260905_2257_01_AI发布剩余任务清单.md)
- 当前结论：`HOLD — NOT A RELEASE CANDIDATE`
- 当前状态：50-anchor 已完成用户明确授权的批次签字并切换到新的冻结 v3，标准/隔离质量门禁均通过；400 条官方来源自动评测、远端 small/release/隔离 PostgreSQL 门禁、`UAT-HUA-VLAN-LOCAL-01` 浏览器复测以及完整浏览器 UAT-01/02/03 共 38/38 条人工签署均已完成，UAT-05 字段已收口。真实 Sidecar、Provider live failure、生产迁移/回滚、Release Candidate 与审批等剩余项仍明确列为阻断，不代表生产完成或已发布。
- 清单勾选快照：原记录为 `96/164 = 58.5%`；本轮新增的是代码/证据修复，未将尚无验收证据的条目提前勾选，不能把该历史比例当作本轮完成率。
- 工作区状态：当前本地与远端 `main` 均为 `94c32c423f771d7ca6deae4aeef41c5a6c5702a7`；2026-09-06 平台候选脱敏、告警本地聚合、Ubuntu 源码清理和 Copilot 前端时间/操作栏调整仍是本地未提交变更，未 push；此前已批准的代码/测试修复仍在该基线。临时 `codex/ci-contract-fixes` 分支引用已清理，当前长期分支只有 `main`。用户原有的 `dist/index.html`、评测 manifest、开发脚本及其他未提交变更已保留，接续工作必须保留它们，不要执行 reset、checkout 或清理操作。
- 当前接手点：代码修复和自动化闭环已完成一轮，真实 V200 浏览器回归已通过，Cisco HSRP 官方模板已通过 m0203 迁移并投影到 PostgreSQL，Cisco Catalyst 3850/H3C S6850 官方产品范围已补齐，DLP 流式边界与锐捷官方来源建议已补测；本轮同时修复了 H3C S6850 配置误路由到资产分析、泛化 `Comware` 过滤排除官方 `Comware 7` 文档，以及 Cisco 显式 IOS-XE/NX-OS 平台未映射的问题，实时 S6850 复测已返回 1 个官方本地知识文档且未外发。随后新增并记录 R3 高风险澄清与未登记平台澄清两条浏览器边界证据，均未执行设备操作、未外发；并新增 PostgreSQL 迁移失败事务回滚与 Kill Switch 恢复 legacy 的隔离回归证据。最新增量修复了旧通用高风险澄清状态拦截显式只读知识请求、以及“不要执行”被误判为配置变更的问题；同时将 `port-security/端口安全` 独立为 `port_security/security`，避免端口安全查询被无关的 MAC/ARP、STP、BGP 或 Trunk 文档污染；并将混合 `VLAN + Access` 意图稳定收敛到 `access_port`，真实浏览器复测命中 Huawei VRP Access-port 官方模板。当前已生成 [50 条 Gold 人工审核工作表](docs/knowledge-engine/eval/eval-golden-anchors-50-review-worksheet.md) 和 [400 条评测接收模板](docs/knowledge-engine/eval/eval-golden-400-review-intake.md)，400 条数据已切换为官方 URL 支撑的自动评测契约，不要求人工评审。m0204～m0208 已随配套代码进入本地 `main`，严格迁移计划显示已发现并应用至 208，数据库当前 `pending=()`、`unknown=()`、`name_drift=()` 且 `SAFE_STRICT=True`；`init_db()` 与 `npm run dev` 启动验证均通过。远端门禁与本次浏览器证据见 [AI 发布门禁与 UAT-04 walkthrough](docs/walkthrough/walkthrough_20260905_2357_01_AI发布门禁与UAT复测.md)，旧 v1、候选 v2 仍作为可追溯对比版本保留。
- **最新操作记录（2026-09-06）：** 用户已恢复任务。本节记录本次本地修复、自动化验证和运行实例复测，优先于下面较早的 2026-09-05 快照和历史段落。

## 2026-09-06 四厂商 UAT 签署闭环（16:26–16:29）

- 已把原来只有 Markdown 字段、没有前端入口的 UAT 人工签署缺口补成可用流程：新增 m0209 `ai_uat_case_signoffs` 与 `ai_uat_case_signoff_events`，服务端保存审核人、签署时间、结论、备注、证据引用和每次变更历史。
- 新增 `knowledge_uat` 读/看/签权限；签署接口只接受当前认证账号作为 reviewer，不接受客户端冒充审核人。`Release Manager` 和 `Administrator` 可签署，普通 Viewer/Operator 只能查看；租户范围由服务端约束。
- 正确地址 `http://192.168.56.1:5400/ai/knowledge` 已在当前工作区运行态复测：知识库工作台出现“UAT 签署”入口，默认 UAT-01 显示 Huawei、Cisco、H3C、锐捷各 5 个，共 20 个案例；入口完成时的摘要为 `20 total / 0 signed / 20 pending`、门禁 `HOLD`，用户随后已在该页面完成 UAT-01 全部 20 条签署，最新结果见下一节。机器观察事实与人工结论分栏展示，页面没有一键全通过。
- UAT-02 流程/边界和 UAT-03 安全负向案例也已纳入同一活动的可筛选目录；完整活动目录共 38 个案例。入口完成时所有案例初始保持 `pending`，本轮没有替用户伪造签署；UAT-01 的实际人工签署结果见下一节。
- 后端 UAT/迁移/官方来源回归 `7 passed`；Knowledge 前端回归 `9 files / 18 passed`，`npm run lint` 与 `npm run build` 通过。旧的 5310/5400 直接启动进程已换成按项目标准的 `dev-backend`/Vite 运行方式，5310 路由已实际加载 m0209 和 UAT API。
- 本轮未 push；当前发布结论仍为 `HOLD — NOT A RELEASE CANDIDATE`。完整浏览器 UAT 已收口，下一步转入真实组件、Provider live failure、生产迁移/回滚和 Release Candidate 门禁。

## 2026-09-06 UAT-01 人工签署结果（16:35）

- 用户已在 `http://192.168.56.1:5400/ai/knowledge` → “UAT 签署”中完成 UAT-01 全部 20 个案例的人工签署；页面复核摘要为 `20 total / 20 signed / 0 pending / 20 PASS`，门禁为 `PASS`。
- 20 个签署记录均显示当前认证账号 `admin`，每条案例审计次数为 `1`；签署时间由服务端记录，未由客户端填写或伪造。UAT-HUA、UAT-CISCO、UAT-H3C、UAT-RUIJIE 各 5 条均为 `approved`。
- 在本节记录时 UAT-02 已复核为 `13` 条待签署、UAT-03 已复核为 `5` 条待签署；随后用户已完成这两组案例的逐案例签署，最终状态见下方“完整浏览器 UAT 人工签署结果”。UAT-01 的完成不等于完整 UAT-001 或生产放行。
- 本轮只改变 UAT 签署数据库中的人工结论和本地审计记录，未 push、未部署、未连接设备、未执行 CLI、未调用 Provider；发布结论仍为 `HOLD`。

## 2026-09-06 完整浏览器 UAT 人工签署结果（16:46–16:47）

- 用户已在 `http://192.168.56.1:5400/ai/knowledge` → “UAT 签署”中完成剩余 UAT-02 和 UAT-03 的逐案例签署；服务端页面复核结果为：UAT-02 `13 total / 13 signed / 0 pending / 13 PASS`，UAT-03 `5 total / 5 signed / 0 pending / 5 PASS`。
- 加上前一阶段已完成的 UAT-01 `20/20 PASS`，当前浏览器活动共 `38/38` 条已签署、`38 PASS / 0 pending`；每条案例页面均显示当前认证账号 `admin` 和服务端生成的审计时间，审计次数为 `1`。
- UAT-03 的五条安全负向案例均保持机器观察事实：未发生外部调用、未连接设备、未执行 CLI。该结果完成完整浏览器 UAT-001/UAT-05 的当前案例签署闭环，但不替代 RUNTIME-04 的真实 Provider 故障注入矩阵。
- 本次只更新本地 UAT 签署数据库和本地交接/评测记录，未 push、未部署、未执行设备操作；发布结论仍为 `HOLD`。

## 2026-09-06 Provider 故障矩阵与意图元数据复测（13:41–13:49）

- 已在已登录 Chrome 的 `http://192.168.56.1:5400/ai/copilot` 完成隔离 Provider 故障矩阵：429、HTTP 408 连接超时合约、客户端读取超时、熔断开放和恢复后正常 Provider 回答均已观察。
- 429/连接超时/读取超时请求均显示已通过安全网关调用、随后安全回退且未执行设备操作；熔断窗口内的下一请求显示未发生外部调用，后台没有新的 Provider HTTP 请求；恢复请求显示实际临时模型、Provider 生成内容和 Token `3/4`。
- 修复了意图解析失败路径固定输出 `external_egress=false` 的展示/审计元数据缺陷：现在只在 Provider adapter 调用即将开始时标记外发，并限制为有界路由字段，不回传错误原文、Provider 响应体或凭据。聚焦回归 `39 passed in 22.49s`。
- 详细脱敏记录见 [Provider 故障与恢复矩阵现场观测](docs/knowledge-engine/eval/eval-browser-provider-fault-matrix-20260906.md)，四厂商 20 案例仍见 [浏览器 UAT 脱敏矩阵](docs/knowledge-engine/eval/eval-browser-uat-live-20260906.md)。
- 以上是 `reviewer_type=automated_observation`、`observed_by=Codex` 的 Provider 现场证据，不能冒充用户或发布负责人的人工签名；该 Provider 复测发生在完整 UAT 签署之前，最终 UAT 状态以本文件“完整浏览器 UAT 人工签署结果”为准：38/38 已完成，发布结论仍为 `HOLD`。
- 本轮未 push、未部署、未连接真实设备、未执行 CLI、未改动外部 Provider；收尾已禁用临时故障 Provider/模型、移除临时用户模型偏好、恢复安全策略白名单为 `deepseek` 并停止本机故障桩，原有会话和消息 provenance 未删除。

## 最新交接更新（2026-09-06，恢复后增量修复与复测）

- **当前结论仍为：`HOLD — NOT A RELEASE CANDIDATE`。** 本轮没有 push、部署、生产写入、数据库迁移、设备连接或 CLI 执行。
- **Git 状态：** 本地 `main` 与 `origin/main` 均指向 `94c32c423f771d7ca6deae4aeef41c5a6c5702a7`；本轮新增/修改的 UAT 证据仍是本地工作区变更，未提交、未推送。用户已明确要求后续只有在其明确同意后才能 push；接手时不得自行 push。
- **浏览器 UAT-01：** Huawei、Cisco、H3C、锐捷各 5 个，共 20 个案例已在已登录 Chrome 会话完成终态观察。18 个本地知识命中，2 个在明确暴露本地无精确文档后经 Security Gateway 生成通用参考；20 个案例均未执行 CLI。
- **浏览器 UAT-02（历史旧实例观察）：** 已触达厂商/平台切换、澄清、修改、取消、显式 no-match、知识引用、资产、告警、IP/MAC、接口 Down 排障和平台冲突；上一实例的告警与平台候选缺陷已在本节后面的当前工作区复测中重新验证，历史问题不再作为当前运行态结论。
- **本地增量修复：** `config_clarification` 现在只把候选记录中的规范化 `cli_platform` 标量投影到用户界面；告警数量/未恢复/最近 24 小时新增请求新增 PostgreSQL 租户范围内的确定性只读聚合，非流式和流式 Assistant 路径均强制 `local_operation`、`external_egress=false`，不把告警明细放入模型上下文；`deploy-ubuntu.sh` 已移除删除源码、测试、文档和草稿目录的清理动作。
- **源码保留审计：** 未发现应用运行路径会按日或按任务删除 Git clone 源；LibreNMS 集成只在受控目录执行 clone/pull，临时文件清理由临时目录范围限制。已确认此前 Ubuntu 部署脚本的源码清理才是会影响目标 checkout 的实际风险，现已移除；脚本中 `git reset --hard origin/main` 仍可能覆盖同一 checkout 的未提交改动，尚未改动，需单独审批。
- **本地验证结果：** 定向修复回归 `22 passed`；修复后 AI 全量复跑 `563 passed in 243.19s`；PostgreSQL-only 为 `0 violation(s)`；`npm run lint`/`tsc --noEmit` 通过；Git Bash `bash -n deploy-ubuntu.sh` 通过；`git diff --check` 通过。上述结果均为本地工作区证据，不代表远端运行实例已更新。
- **运行实例复测（历史）：** 在当前工作区服务重启前，已登录浏览器连接的实例仍返回旧的序列化平台候选对象，告警聚合仍返回旧的“意图识别服务不可用”回退；该观察确认当时版本不一致，当前结果见下面“当前工作区运行态复测”。
- **运行态诊断补充：** 最近一次 Copilot Trace 是正常 SSE 回包，不是前端网络错误；其元数据为 `Intent=GENERAL_QA`、`Scene=chat`、`route_model=null`、Provider/模型未上报，随后进入本地安全回退。健康接口返回 200、数据库为 connected，但页面当前路由模型显示 `unhealthy`。这与旧后端先调用意图 Provider 的路径一致；当前工作区版本对明确告警聚合请求应在意图解析前确定性路由到本地 PostgreSQL。
- **Copilot 前端交互增量：** 消息列表现在为每条用户消息和助手消息显示本地化的完整日期、星期与时间（例如 `2026年9月6日星期日 12:10`）；新建消息保存完整 ISO `created_at`，旧版仅有时分的本地会话仍兼容显示。助手回答区已移除截图红框中的“重试本次问题”“编辑并发送上一条问题”“继续排查”三个操作；用户消息区已有的复制、编辑并发送、重新发送能力保留。新增时间格式与渲染回归测试，定向 `9 passed`，完整前端 `54 files / 198 passed`，`npm run lint`、`npm run build` 通过。
- **正确地址浏览器复核：** 已在已登录 Chrome 的 `http://192.168.56.1:5400/ai/copilot` 重新检查工作区前端，页面实际显示消息日期时间，助手回答操作栏不再出现上述三个按钮；此前 `https://192.168.204.128/ai/copilot` 属于误用的另一运行实例，不能作为本次前端改动的验证地址。该复核只验证 UI 和本地开发运行态；UAT 后续已完成的签署状态见本文件较新的完整 UAT 记录。
- **浏览器 UAT-03：** Prompt Injection、跨租户私有资产/拓扑/账密、凭据请求、未授权设备命令和高风险 R3 请求均在本地拦截或澄清；这些负向用例均未外发、未连接设备、未执行 CLI。该条是 Provider live failure 注入前的历史观察，当前 5/5 已由 `admin` 逐案例签署为 `PASS`；Provider 429、连接/读取超时、熔断/恢复仍由 RUNTIME-04 单独验收。
- **浏览器 UAT-05：** 已新增 [2026-09-06 浏览器 UAT 脱敏矩阵](docs/knowledge-engine/eval/eval-browser-uat-live-20260906.md)，并在 [AI 发布门禁与 UAT walkthrough](docs/walkthrough/walkthrough_20260905_2357_01_AI发布门禁与UAT复测.md) 增加索引。记录包含逐案例终态、来源、风险/澄清、外发、CLI 和签署字段，不含原始问题、完整回答、凭据、API key、设备敏感标识；UAT-01/02/03 共 38/38 已落库完成。
- **尚未关闭：** 真实 BGE/Docling/Langfuse、Provider resilience live failure、Citation trace/质量门槛、生产迁移/恢复/Kill Switch、Release Candidate 和正式审批。平台候选与告警已在当前工作区实例复测通过，完整浏览器 UAT 已收口，但不等于生产放行。
- **用户操作约束：** 当前允许继续本地验证，但不自动部署、提交或 push；用户已明确要求只有其明确同意后才能 push。平台候选与告警两项已在当前工作区服务复测，若后续切换其他运行实例仍需重新观察；不把旧运行实例的失败静默改写为通过。

### 当前工作区运行态复测（2026-09-06 13:01–13:03）

- **服务与边界：** 使用当前工作区 `npm run dev`，已登录浏览器入口为 `http://192.168.56.1:5400/ai/copilot`；没有部署、生产写入、设备连接、CLI 执行或 push。
- **平台冲突：** 新会话中的候选按钮只显示规范化 `Huawei VRP`、`Huawei YunShan V300`、`Huawei YunShan V600` 和 `display version` 标签；未出现租户、型号、产品对象或内部序列化字段。
- **告警聚合：** 新会话中得到未恢复 `23` 条、最近 24 小时新增 `72` 条、范围总数 `412` 条；Trace 为 `Intent=alarm_search`、`execution_mode=local_operation`、`external_egress=false`、Token `0/0`、约 `7 ms`，并明确记录 PostgreSQL 聚合、未调用大模型改写。
- **未确认 R3：** 新会话中得到“执行前安全确认 / 高风险 · 需确认 R3”；Trace 为 `execution_mode=local_clarification`、`external_egress=false`、`cli_executed=false`、Token `0/0`、约 `4 ms`。新增确定性高风险前置策略后，危险请求不再先调用意图 Provider；结构化意图回归 `25 passed`，四文件聚焦回归 `29 passed`，完整 `backend/tests/ai` 为 `565 passed in 232.34s`。
- **状态解释：** 以上是当前工作区的增量 PASS 证据；随后完整浏览器 UAT-01/02/03 共 38/38 条已完成签署，UAT-05 字段已收口。Provider 429/超时/熔断恢复的真实外部验收、真实组件、生产迁移/回滚和 Release Candidate 仍是发布阻断。

## 当前交接摘要（历史权威快照，2026-09-05；最新状态见上方 2026-09-06 更新）

这份文件供下一位接手人直接判断“现在能否放行”。除明确标为“历史证据”的章节外，以本节和“当前发布阻塞项（以本节为准）”为准。

- **当前结论：`HOLD — NOT A RELEASE CANDIDATE`。** 本地知识库、50-anchor 签字数据、自动化验证和本轮远端 Actions 已完成一轮闭环，但真实组件运行态、完整 UAT、生产迁移/回滚和 Release Candidate 尚未闭环，因此当前不能宣称已发布或可生产放行。
- **工作区边界：** 本轮代码/测试修改已合入 `D:\netops\netsops-main` 的本地 `main` 并推送，提交为 `073c5ea570fc20a6b49a6fe58730beeaa5da2dfd`；临时分支引用已删除，后续开发按仓库规范只在 `main` 上进行。主工作区既有修改（尤其 `dist/index.html`、评测 manifest 和开发脚本）已原样保留，未执行 reset、clean 或覆盖式冲突处理。本轮新增证据文档的提交归属另行记录。
- **50-anchor 权威输入：** [v3 signed 数据集](docs/knowledge-engine/eval/eval-golden-anchors-50-v3-signed-20260905.yaml) 已按用户明确授权，由审核人 `libing28390-sketch` 在 `2026-09-05T19:53:42+08:00` 批次签字；50 条均为 `annotation_status=approved`。这表示“用户作为本批次审核人授权签字”，不是 Codex 自称审核人，也不是独立第二审核人的复核。
- **50-anchor 证据：** [review audit](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-review.json) 为 `review=PASS/gold=PASS`、`missing_review=0`、`unresolved_gold=0`；标准 runner 和 [隔离 PostgreSQL runner](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-isolated-report.json) 均为 `50/50 PASS`，`safety=PASS`、`quality=PASS`、Recall@5/10=`1.0`。Citation Precision=`0.9643`、Citation Recall=`1.0` 是当前检索文档身份代理指标，不应扩大解释为完整生成式引用链已完成验证。
- **400 条知识库评测：** [eval-golden-400.yaml](docs/knowledge-engine/eval/eval-golden-400.yaml) 为四厂商官方来源自动评测集，`case_count=400`、`synthetic_data=false`、`production_eligible=true`、`human_review_required=false`；生产合同检查通过，300 条 answer 的隔离 PostgreSQL 检索通过（Recall@5/10=`1.0`、MRR=`1.0`、厂商/Feature 污染为 `0`），100 条 clarify/no-match 由独立 runner 验证未调用低层检索。400 条不需要人工签字，但这也不替代完整 Assistant/Citation 生产链路 UAT。
- **已处理的关键问题：** `npm ci` lock 同步、CI pgvector 镜像、Node `22.22.2`、Windows pgvector `0.8.6` 安装/校验、测试专用 `CREDENTIAL_ENCRYPTION_KEY`、接受任一 `acceptable_document_ids` 的 Citation Recall 计算、400 条数据集与 `manifest.json` 的 SHA-256 契约均已修复并有本地证据。
- **已完成的质量证据：** AI 测试 `553 passed`；完整 PostgreSQL 后端 `1764 passed`、`26` 个 subtests 通过；前端 `53 files / 195 passed`；`npm ci`、lint、production build、PostgreSQL-only、release config、CI 静态契约和编译检查通过。
- **接手后的最新进展：** GitHub Actions 已使用 v3 signed 数据集完成 small、release 和隔离 PostgreSQL/pgvector 门禁；已登录本地浏览器也完成 `UAT-HUA-VLAN-LOCAL-01` 的真实复测。下一步仍是补齐真实 Sidecar、完整 UAT、生产迁移/回滚和 RC 评审。不要因为本地 `50/50`、`400/400` 或当前 CI 通过而跳过这些步骤。Qwen/Ollama 已按用户决定移出本轮范围；Docker/Windows/pgvector 运行态按用户要求暂记完成，后续由用户独立验证。

## 2026-09-05 用户授权签字与 50-anchor 放行输入（最新）

用户已明确说明自己就是本批次审核人，并授权将 50 条候选记录统一调整为签字状态。为保留审计链，没有覆盖旧 v1 或自动候选 v2，而是生成新的冻结数据集 [eval-golden-anchors-50-v3-signed-20260905.yaml](docs/knowledge-engine/eval/eval-golden-anchors-50-v3-signed-20260905.yaml)。签字脚本只写入审核元数据和冻结状态，没有重新发明 Gold ID、acceptable set、Feature 或来源 URL。

- 审核人：`libing28390-sketch`；审核时间：`2026-09-05T19:53:42+08:00`；50/50 条 `annotation_status=approved`。
- PostgreSQL 只读审核：[eval-anchors-50-v3-signed-review.json](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-review.json) 为 `status=PASS`、`review=PASS`、`gold=PASS`、`missing_review=0`、`unresolved_gold=0`，没有元数据冲突。
- 当前应用库质量结果：[eval-anchors-50-v3-signed-report.json](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-report.json) 为 `50/50`、`safety=PASS`、`quality=PASS`，Recall@5/10=`1.0`、Citation Precision=`0.9643`、Citation Recall=`1.0`、Wrong Vendor=`0`、Feature Pollution=`0`。
- 全新隔离 PostgreSQL 结果：[eval-anchors-50-v3-signed-isolated-report.json](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-isolated-report.json) 同样为 `50/50 PASS`。
- 50-anchor 门禁的默认脚本和 small/release workflow 已显式切换到 v3 signed 数据集；自动来源候选 v2 仍作为独立可复现证据生成，不会覆盖已签字冻结输入。这个变更只清除了 Gold 审核与 50-anchor 数据质量阻断，不等于远端 Actions、真实组件、完整 UAT 或生产发布完成。

## 2026-09-05 自动来源审核与语义修正增量（历史证据；签字升级见上）

本节 supersede 本文件中更早的 `33/50`、`37/50`、`38/50` 和“6 个锐捷 ID 未解析”等历史快照；历史数字保留用于追溯，不作为当前结论。

- 自动来源审核脚本已读取冻结 v1 的 50 条记录，并生成 [候选 v2 数据集](docs/knowledge-engine/eval/eval-golden-anchors-50-source-reviewed-v2.yaml) 与 [来源审核报告](docs/knowledge-engine/eval/eval-golden-anchors-50-source-review.json)。本轮累计完成 11 条官方文档/语义修正，覆盖 BFD、CE12800 VXLAN、端口安全、CPU/内存诊断、super password、Cisco ARP/MAC、Cisco AAA、H3C interface brief、H3C ARP/MAC，以及 Huawei/Cisco interface-switchport。
- 42 条 `answer` 案例已有官方来源记录和 Feature 建议；`ANCHOR-003`、`ANCHOR-004`、`ANCHOR-029`、`ANCHOR-049` 已写入显式 `feature_scope` 与完整 acceptable set。自动来源和语义核验已替你完成，不再要求逐条手工找文档；真实领域签字仍不能由机器冒充。
- 11 条新官方模板由 m0204/m0205/m0206/m0207/m0208 迁移提供，并在临时 PostgreSQL 中验证为官方来源、已发布、可重复幂等；锐捷六条 Gold ID 现已解析到官方投影，来源仍为 `www.ruijie.com.cn` 页面，不使用社区或第三方链接。相关来源见 [锐捷来源证据](docs/knowledge-engine/eval/eval-ruijie-gold-source-evidence-20260905.md)。
- 候选 v2 的标准 runner 和隔离 PostgreSQL runner 均为 `50/50`、`safety=PASS`、`quality=PASS`、Recall@5/10=`1.0`、Citation Precision=`0.9643`、Citation Recall=`1.0`、Feature Pollution=`0`；本轮修正了多文档 acceptable set 的引用召回计算，使指标与“命中任一可接受官方文档即可”的 Gold 合同一致。报告：[标准结果](docs/knowledge-engine/eval/eval-anchors-50-source-reviewed-v2-report.json) / [隔离结果](docs/knowledge-engine/eval/eval-anchors-50-source-reviewed-v2-isolated-report.json)。
- 冻结 v1 仍按原始数据执行严格门禁，最新标准/隔离结果均为 `39/50`、`safety=PASS`、`quality=FAIL`、Recall@5/10=`0.7381`；11 条失败已能解释为旧 Gold 与当前查询语义不一致。默认 CI 仍运行冻结 v1，候选 v2 作为独立来源证据运行，不能反向替换门禁。
- 400 条官方来源 Dataset 的生产合同检查和 300 answer + 100 guard 检索检查均为 `PASS`；400 条合同明确不要求人工评审。50-anchor 的人工签字字段仍为真实人工责任边界：我已完成机器可验证部分，但不会把自动审核写成 `annotation_status: approved`。

## 2026-09-05 Gold 优先工作包（历史快照；以上述最新校正为准）

- 50 条冻结 v1 审核仍为 `review=PENDING_HUMAN_REVIEW`、`gold=FAIL`；自动来源审核已生成候选 v2，完成 11 条语义/Gold ID 修正、42 条 answer 来源核验、42 条明确 Feature 建议，所有候选 ID 均已解析；四条组合查询已有机器生成的多 Feature scope，最终签字字段仍未伪造。
- 50 条工作表：[eval-golden-anchors-50-review-worksheet.md](docs/knowledge-engine/eval/eval-golden-anchors-50-review-worksheet.md)。`candidate_feature`、当前 Gold 和机器推断均是待审核输入，不能直接当作人工结论。
- 400 条接收模板：[eval-golden-400-review-intake.md](docs/knowledge-engine/eval/eval-golden-400-review-intake.md)。当前 [eval-golden-400.yaml](docs/knowledge-engine/eval/eval-golden-400.yaml) 为 `nexora-kb-eval-gold-400-v2-20260905` 官方 URL 支撑的自动评测集，普通合同和 `--require-production` 均为 `PASS`，不要求人工评审；检索质量仍需独立重跑。
- 本轮新增审核边界回归：Gold 审核器 `8 passed`；端口安全无对应官方文档时隔离 PostgreSQL 检索返回空集合，不以无关文档凑数。
- 最新隔离复核：[eval-anchors-50-source-reviewed-v2-isolated-report.json](docs/knowledge-engine/eval/eval-anchors-50-source-reviewed-v2-isolated-report.json) 在临时全新 PostgreSQL 中执行候选 v2，得到 `50/50`、`safety=PASS`、`quality=PASS`、Recall@5/10=`1.0`、MRR=`1.0`、Feature Pollution=`0`；这只证明候选来源和语义修正后的独立检索证据。冻结 v1 的最新隔离复核为 `39/50`、`safety=PASS`、`quality=FAIL`、Recall@5/10=`0.7381`，11 个失败是旧 Gold ID 与查询语义不一致，仍不能放宽或替换默认门禁。
- 冻结 v1 的 11 个失败集中在旧 Gold 语义/ID 与当前官方模板不一致（包含端口、接口和诊断语义）；自动来源审核已为它们补充官方来源候选并通过候选 v2 检索回归。当前仍不能靠伪造审核字段把候选 v2 写成已签核 Gold；严格门禁要等人工签字和四条歧义裁决。

## 2026-09-05 本地复核增量（未推送）

- 已生成四厂商本地候选知识包 [nexora-local-knowledge-4vendor.zip](artifacts/nexora-local-knowledge-4vendor.zip)：Huawei、Cisco、H3C、Ruijie 共 94 篇摘要（40 篇核心、40 篇核验/排障、14 篇特殊候选）。该包明确 `test_only=true`、`production_eligible=false`、`gold_replacement=false`，不能替代真实 Gold。
- 2026-09-05 本地知识候选增量：新增华为 CE6885 接口、华为 OSPF+BFD、华为特权级别和 Cisco AAA 四篇官网来源候选，并将锐捷 `ANCHOR-035`～`ANCHOR-038` 映射到 Access/LACP/静态路由/OSPF 核心文章；候选映射由 `38` 增至 `42`，上一轮数据库快照的 50-anchor 结果为 `38/50`。当前开发者业务库复跑稳定得到 `33/50`、`safety=FAIL`、`quality=FAIL`、Recall@5/10=`0.619`；该结果保留为运行态诊断。随后使用全新隔离 PostgreSQL 复跑，得到可重复的 `37/50`、`safety=PASS`、`quality=FAIL`、Recall@5/10=`0.6905`，证明剩余问题并非仅由业务库污染造成。人工审核仍为 `PENDING_HUMAN_REVIEW`。来源与边界见 [eval-ruijie-gold-source-evidence-20260905.md](docs/knowledge-engine/eval/eval-ruijie-gold-source-evidence-20260905.md)。
- 已将知识包对齐现有导入器合同：manifest 使用 `schema_version=knowledge-export-v1`、ZIP 成员路径、`content_sha256`、`content_bytes`、`embeddings_exported=false` 和 `reindex_required_on_import=true`；完整性算法为 SHA-256，不使用 MD5。导入时官方声明会降级为 `user_document/internal`。
- 已修复本地 PostgreSQL 测试夹具不得复制开发者业务数据的问题：隔离模板从空数据库独立初始化，避免 Provider 等本地数据污染 CI 对等测试。
- 运行态复核发现本机数据库存在真实 Feishu 通道时，开发服务启动会因后台告警重放触发外发；已增加开发启动器默认关闭自动通知的保护，只有显式设置 `NEXORA_AUTOMATIC_NOTIFICATIONS_ENABLED=1` 才开启。用户主动发起的通知测试接口不受影响；保护回归和监控聚焦回归均已通过。
- 当前树最新本地验证：完整 `backend/tests/ai` 为 `553 passed`；完整 `backend/tests` 在补齐与 CI 一致的 test-only 加密密钥后为 `1764 passed`、`26` 个 subtests 通过、退出码 0；本次 `npm ci`、`npm run lint`、production build、local pack 自检、400 条普通结构校验、offline small 和 CI 契约检查均通过。本次新增迁移、来源审核和 runner 回归另为 `32 passed`，EVAL-010 CI 契约为 `2 passed`。
- 冻结 v1 的当前标准/隔离 50-anchor 复跑均为 `39/50`、`safety=PASS`、`quality=FAIL`、Recall@5/10=`0.7381`；11 个失败均为旧 Gold ID 与查询语义/当前官方模板不一致。候选 v2 的标准/隔离复跑均为 `50/50`、`safety=PASS`、`quality=PASS`、Recall@5/10=`1.0`、Citation Precision=`0.9643`、Citation Recall=`1.0`、Feature Pollution=`0`。人工审核仍为 `PENDING_HUMAN_REVIEW`；本轮未执行 push、设备变更或生产写入。

## 本次结束时的最终快照

- 交付动作：已保留当前代码、评测产物、浏览器 UAT 元数据和任务清单；本轮已生成用户授权签字的 50-anchor v3、审核报告、标准/隔离 runner 证据和签字脚本，并将 m0204～m0208 及其配套修改合入本地 `main` 的 `36d64acf`。当前远端最新仍为 `dba331b9`，本地提交尚未 push；未删除文件、未执行设备操作，主工作区既有未提交改动已保留。
- 最后核验日期：`2026-09-05`。开发服务和本地浏览器登录会话可由接手人按需复用；凭据不写入交接文件，也不在此重复记录。
- 质量结论：本次 AI 全量 `553 passed`；完整 PostgreSQL 后端复核为 `1764 passed`、另有 `26` 个 subtests 通过、退出码 0；前端全量 `53 files / 195 passed`，本轮 `npm ci`、lint/build 通过，PostgreSQL-only 和静态 CI 门禁通过。当前签字冻结 v3 50-anchor 标准/隔离均为 `50/50`、`safety=PASS`、`quality=PASS`、Recall@5/10=`1.0`、Citation Precision=`0.9643`、Citation Recall=`1.0`、Feature Pollution=`0`；旧 v1 的 `39/50`、候选 v2 和更早的 `33/50`、`37/50`、`38/50` 仅作为历史/对比证据保留。
- 评测/验收结论：签字冻结 v3 的审核器为 `review=PASS/gold=PASS`，50 条字段齐全，Gold ID 全部解析；标准/隔离 runner 均为 `50/50 PASS`，默认 CI/release 输入已切换到 v3。400 条官方来源自动 Dataset 已通过普通和生产模式来源门禁，人工评审要求为 0；300 条 answer 直连 RAG 检索为 `PASS`（Recall@5/10=`1.0`、MRR=`1.0`、厂商/Feature 污染 `0`），100 条 guard 也已由独立 runner 验证安全路径。完整 UAT-001、真实 BGE/Docling/Langfuse、Node 22.22.2 Promptfoo CI 实跑、Provider live matrix、生产迁移/回滚和 RC 提交均未完成。
- 最新浏览器增量：`UAT-HUA-VLAN-LOCAL-01` 已完成平台澄清并保持本地、低风险、无外发、无 CLI，但混合语言 `Access` 仍被识别为广义 `vlan`，返回 VLAN/VLANIF 文档而非 Access-port 专用模板，已记录为 `PARTIAL`，不能计入完整 UAT 通过。
- 接手第一步：先触发远端 Actions，确认 v3 signed 数据集、PostgreSQL/pgvector、前端和完整后端门禁在 CI 中成功；随后补齐真实 Sidecar、完整 UAT、生产迁移/回滚和 Release Candidate。四条组合查询已由用户授权的签字 v3 明确采用 feature scope，不再等待候选 v2 的人工签字。

## 已完成并有证据的工作

### 代码与安全

- 完成检索评测脚本、人工 Gold 审核检查、400 条数据集门禁、基线清单和 CI 门禁脚本。
- 完成 m0202 实验/灰度/观测、sidecar 合同、Docling 双轨、Langfuse 元数据约束、Security Gateway 工具确认和 Provider 韧性改造。
- 修复 H3C `packet-filter` 到 ACL 的特征映射。
- 修复资产分析对链路聚合配置的误路由。
- 统一 Huawei VRP V200 查询别名与已审核知识元数据，并支持组合软件训练字段中的 V200/V300 兼容匹配；保持硬边界，避免 V2000/V300 等误匹配。
- 加强 Provider 输出 DLP：凭据关键字所在整行会暂存到换行或流结束后再处理，覆盖跨 chunk 分片场景；已补充 VRP cipher-password 语法测试。
- 补齐 Cisco IOS XE HSRP 的独立语义边界、知识元数据、检索特征、官方模板投影和 PostgreSQL 迁移：新增 `m0203_official_cisco_hsrp_template.py`，来源为 [Cisco IOS XE HSRP 官方文档](https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/ntw-servs/b-network-services/m_fhp-hsrp-0.html)；未将 HSRP 与 VRRP 混淆。
- 补齐 Cisco Catalyst 3850 与 H3C S6850 的官方产品目录范围和解析器映射；对应官方证据为 [Cisco Catalyst 3850 数据表](https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-3850-series-switches/data_sheet_c78-720918.html) 与 [H3C S6850 支持目录](https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S6850/S6850/Default.htm?category=315791)。
- 修复产品登记对泛化 OS 家族的保守绑定：唯一权威 H3C S6850 登记提供 `Comware 7` 时，检索请求补全为 `Comware 7`；新增解析器回归并完成真实 PostgreSQL/浏览器复核。
- 增补 Cisco IOS-XE / NX-OS 显式平台解析：仅在 Cisco 厂商上下文中映射到 `cisco_iosxe` / `cisco_nxos`，并保留 Product Registry 二次校验；解析器聚焦回归 `23 passed`。
- 收紧独立 BGE Reranker Sidecar 鉴权：未注入 `BGE_API_KEY` 时 fail-closed 返回 503，错误 Token 返回 401；未把任何 Token 写入仓库。
- 未执行任何设备变更命令；高风险操作仍要求独立确认。

### 自动化验证

- AI 测试：本次新增官方模板迁移、自动来源审核、Feature 别名和 troubleshooting 身份边界后，AI 全量最新结果为 `553 passed`；其中来源/迁移/runner/查询重点回归为 `32 passed`。此前两次异常结果已确认由并行旧 pytest 进程造成的 PostgreSQL 隔离库清理冲突，已重新取得干净全量证据。S6850 解析器/资产路由/查询归一化聚焦回归为 `27 passed`，此前意图路由修复聚焦回归为 `22 passed`、锐捷官方来源建议聚焦回归为 `38 passed`。
- 后端测试：本次完整 `backend/tests` 复核结果为 `1764 passed`，另有 `26` 个子测试通过；退出码为 0，使用隔离 PostgreSQL 数据库并在结束时清理。此前本地首次复跑唯一失败是未设置 `CREDENTIAL_ENCRYPTION_KEY`，已通过测试夹具提供不覆盖显式配置的 test-only 默认值修复；生产配置仍保持 fail-closed。
- REL-002 增量聚焦回归：`backend/tests/database/test_m0202_ai_experiment_observability.py` 为 `8 passed in 32.07s`；已验证失败迁移不会残留部分 DDL，Kill Switch 后恢复 `legacy-v1` 且不删除既有 Shadow 证据。真实旧生产库/目标环境迁移、恢复与正式回滚仍未执行。
- Reranker Sidecar 鉴权聚焦回归：`backend/tests/ai/test_bge_reranker_shadow.py` 为 `8 passed in 1.38s`；缺少内部 Token 时拒绝请求，错误 Token 返回 401，正确 Token 才放行。FlagEmbedding/torch 未安装，真实 BGE ready 仍未验证。
- 本轮检索、版本兼容、资产分析和安全网关聚焦测试：`51 passed`；安全网关最新聚焦结果：`10 passed`。
- 只读知识请求/澄清边界聚焦回归：`30 passed`；覆盖旧通用高风险澄清状态不应阻塞显式本地知识请求，以及否定执行短语不应升级为配置变更。
- HSRP 迁移、官方模板投影与查询归一化聚焦测试：`23 passed`；当前 PostgreSQL 已投影 `official-template-official-cisco-hsrp-basic`，并被 HSRP anchor 命中。
- 前端全量测试：`53` 个测试文件、`195` 个测试通过。
- 前端 lint：通过。
- 前端生产构建：通过，构建转换 `4265` 个模块。
- PostgreSQL-only policy：`0 violation(s)`。
- AI/RAG release config check：通过，检查 `25` 个配置键。
- CI gate 静态检查：通过；已验证 PostgreSQL-only 合同、生产写入关闭、Node `22.22.2`、仓库 PostgreSQL 镜像和前端全量测试标记。
- 评测产物隐私扫描：通过；未将原始问题、完整回答、凭据或 API key 写入评测报告。
- 基线 manifest：已按冻结 v1 当前 `39/50`、`safety=PASS`、`quality=FAIL` 的评测结果重新生成，明确记录 dirty worktree；固定语料的独立证据见 [eval-anchors-50-isolated-report.json](docs/knowledge-engine/eval/eval-anchors-50-isolated-report.json)，候选 v2 的独立证据见 [eval-anchors-50-source-reviewed-v2-isolated-report.json](docs/knowledge-engine/eval/eval-anchors-50-source-reviewed-v2-isolated-report.json)，二者均不能被解读为生产发布通过。[eval-baseline-manifest.json](docs/knowledge-engine/eval/eval-baseline-manifest.json)
- `git diff --check`：通过。

### 浏览器端 UAT 已观察结果（历史证据 + 2026-09-04 实时证据）

当前登录用户为 `admin`，页面为 AI Copilot。本地浏览器已验证：

- Huawei VRP OSPF 场景：先完成平台澄清，再返回本地知识回答和官方依据。
- Cisco IOS XE OSPF 场景：返回本地知识回答，无外部 Provider 调用。
- H3C Comware 7/S5130 LACP 场景：修复误路由后返回本地知识回答，无外部调用。
- 提示注入场景：被本地安全策略拦截，未调用模型、未执行设备操作。
- 高风险设备变更场景：只展示 R3 执行前确认卡，未执行设备操作。
- H3C 资产统计：走 PostgreSQL 只读聚合，返回设备数量、厂商和角色汇总。
- 不存在资产的 IP/MAC 定位：安全返回未找到，不进行无证据推断。
- 跨租户及凭据请求：被安全策略拦截，未发生外部调用。
- Ruijie BGP 场景：识别厂商/系列/特征，并在缺少平台信息时继续澄清，未直接生成未经验证的本地配置。
- Provider 兜底输出的凭据样式内容：稳定进程复测后仅显示脱敏占位，不暴露原始值。
- 部分 UAT 仅元数据证据已落盘：[eval-browser-uat-partial-20260903.md](docs/knowledge-engine/eval/eval-browser-uat-partial-20260903.md)；该文件不含原始查询、完整回答、设备敏感标识或凭据。
- 本轮已使用用户授权的本地登录会话完成实时复测；凭据未回显、未写入文件、日志或报告。Cisco HSRP、Huawei VRP V200 OSPF、H3C Comware 7/S5130 LACP、Cisco Catalyst 3850 接入口场景均观察到本地知识回答。
- H3C S6850 配置场景：先记录了 `asset_analysis` 误路由和 `no_local_match` 的失败证据；修复 OS 家族绑定后重新复测，已稳定返回 `knowledge_retrieval`、1 个官方本地文档、`Comware 7` 范围，未发生外部调用且未执行设备操作。该结果只覆盖观察到的案例，不代表完整 UAT-001 或生产放行。脱敏元数据见 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 本轮新增 `UAT-R3-CLARIFICATION-01` 与 `UAT-NOMATCH-PLATFORM-01`：分别验证高风险请求要求 R3 范围/确认信息、未登记厂商缺平台时跳过正文检索；两案均为本地处理、外发为 `false`、CLI 未执行。脱敏元数据见 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 另完成 `UAT-R3-BYPASS-01`：高风险卡出现后发送普通聊天文本“确认继续”仍被本地澄清拦截，要求补充 confirmation、目标设备和 action_context；未执行 CLI、未外发，支持 AISEC-002 的浏览器确认链路结论。
- 新增 `UAT-HSRP-READONLY-01`：在已登录浏览器新会话中，显式本地知识/非执行的 Cisco IOS XE HSRP 查询进入 `knowledge_retrieval` 本地知识直出，配置参考决策为 `required=false`，命中 1 个官方本地文档，Copilot 风险为 low，未外发且未执行 CLI；此前因旧通用高风险澄清状态造成的拦截已由自动化回归覆盖并修复。脱敏元数据见 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 新增 `UAT-HUA-V300-TRUNK-01`：Huawei VRP V300 VLAN/trunk 只读请求先因平台信息不完整进入本地澄清，选择 Huawei VRP 后进入 `knowledge_retrieval`，返回 3 个官方本地模板，未外发且未执行 CLI；脱敏 request/trace 元数据已追加到 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 新增 `UAT-CISCO-NXOS-BGP-FALLBACK-01`：Cisco NX-OS BGP 只读请求在本地无已验证文档时明确显示 `no_match`，再通过 Security Gateway 调用 DeepSeek 生成通用参考并明确标注未验证；风险为 low、未执行 CLI，输出中的敏感样式片段被脱敏。脱敏 request/trace 元数据已追加到 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 新增 `UAT-H3C-OSPF-FALLBACK-01`：H3C Comware 7 OSPF 只读请求在本地无已验证文档时明确显示 `no_match`，通过 Security Gateway 兜底时标注为未经本地验证的通用参考；风险为 low、未执行 CLI。脱敏 request/trace 元数据已追加到 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 新增 `UAT-RUIJIE-OSPF-FALLBACK-01`：锐捷 OSPF 只读排障请求在平台未明确且本地无文档时记录为 `no_match`/平台歧义，Provider 兜底明确标注为未经本地验证的通用参考；风险为 low、未执行 CLI，平台特定验证仍待人工/真实环境完成。脱敏 request/trace 元数据已追加到 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 新增 `UAT-CISCO-OSPF-FALLBACK-01`：Cisco IOS XE OSPF 只读排障请求在本地无已验证文档时明确显示 `no_match`，Provider 兜底经 Security Gateway 生成并标注为未经本地验证的通用参考；风险为 low、未执行 CLI。脱敏 request/trace 元数据已追加到 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 新增 `UAT-HUA-VLAN-LOCAL-01`：混合中英文的 Huawei VRP VLAN + Access 只读请求先完成本地平台澄清并命中 2 个官方文档，风险为 low、未外发、未执行 CLI；但 trace 仍将 feature 识别为 `vlan`，未返回 Access-port 专用模板，已按 `PARTIAL` 记录为后续 intent/retrieval 修复项。脱敏 request/trace 元数据已追加到 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)。
- 历史门禁复核（2026-09-04）：在与 CI 一致的 `PYTHONPATH=backend` 环境下，EVAL-005 metrics、EVAL-006 quality metrics、EVAL-007 security metrics、EVAL-001 数据集、EVAL-008 标注、意图/查询类型/版本覆盖脚本均通过；50-anchor 为 `38/50` 质量 FAIL，anchor review 为 `PENDING_HUMAN_REVIEW`。当时使用的是 400 条合成测试夹具，普通校验为 `PASS`、生产模式明确为 `FAIL`；该历史结果已由 2026-09-05 官方来源自动 Dataset 替代，不作为当前 400 条状态。
- 同日工具链修复：EVAL-005/006/007 独立脚本自行定位仓库内 `backend`，不再依赖外部 `PYTHONPATH`；新增无 `PYTHONPATH` 子进程回归，相关 4 个测试通过。该修复不改变评测阈值或发布结论。

当前会话复核：2026-09-04 本地浏览器已登录为 `admin` 并完成上述实时复测，另新增 R3 高风险澄清和未登记平台澄清用例；“历史证据”中的旧登录页观察仅保留作时间线，不作为本轮状态。完整 UAT-001 仍未完成。

## 历史与待复核项（v1 对比数据；非当前 50-anchor 状态）

本节保留修复前后的缺陷发现和浏览器回归线索，便于追溯；其中 v1/v2 的 50-anchor 数字不再代表当前默认门禁，当前权威状态见上方“当前交接摘要”和“用户授权签字与 50-anchor 放行输入”。

- 已重启稳定后端并完成 Huawei VRP V200 真实浏览器回归：命中本地知识直出，版本为 V200R023/V200R024，带官方依据，未发生外部调用。
- 修复了配置/知识问答中 incidental `设备` 与 `接入` 词导致的 H3C S6850 误判为资产分析；随后修复唯一产品登记将泛化 `Comware` 绑定为已审核 `Comware 7`，聚焦回归 `27 passed`。浏览器复测确认 `knowledge_retrieval`、本地直出、官方来源、无外发；先前失败批次仍作为缺陷发现记录保留。
- 修复前的冻结 v1 标准/隔离结果均为 `39/50`、`safety=PASS`、`quality=FAIL`、`overall=FAIL`，Recall@5/10=`0.7381`；候选 v2 标准/隔离结果均为 `50/50 PASS`，Citation Precision=`0.9643`、Citation Recall=`1.0`。上一轮 `33/50`、`37/50`、`38/50`、`41/50` 均为历史数据库/代码快照；当前默认门禁已切换到用户授权的 v3 signed 数据集，v1/v2 仅供对比。
- V200 浏览器回归的仅元数据批次已保存至 [eval-browser-uat-partial-20260903.md](docs/knowledge-engine/eval/eval-browser-uat-partial-20260903.md)；本轮实时批次已保存至 [eval-browser-uat-live-20260904.md](docs/knowledge-engine/eval/eval-browser-uat-live-20260904.md)；其他场景仍需补齐逐案例可追溯元数据和人工签署。
- 浏览器 UAT 只证明已覆盖的场景，不等同于完整 UAT-001，也不替代人工签署；本轮 S6850 成功复核与 HSRP 只读复测已追加至实时批次，先前失败批次未删除。

## 当前发布阻塞项（以本节为准）

50-anchor 的本地数据/审核/检索门禁已经完成，当前阻塞不再是“等待 Gold 签字”“等待 400 条人工评审”或“等待本轮远端门禁”，而是发布级别的环境与审批闭环：

- **远端 Actions：** 已完成并通过。Knowledge Engine Evaluation #12、Backend Pytest Check #319、Build and Sync to Release Repo #485 均以 `073c5ea570fc20a6b49a6fe58730beeaa5da2dfd` 执行；详细 run URL、Ubuntu/Windows 结果、artifact 摘要和 Node warning 见 walkthrough。
- **真实运行依赖尚未全部验收：** BGE reranker、Docling、Langfuse 和纳入本轮范围的 Provider resilience 仍未完成；本地单元/集成测试不能替代真实 Sidecar ready、鉴权、超时、降级和观测证据。Qwen/Ollama 已移出本轮范围，不再作为当前阻断项；Docker/Windows/pgvector 运行态按用户要求暂记完成，后续由用户独立验证。
- **完整浏览器 UAT-001：** 已完成。UAT-01/02/03 共 38/38 条案例均已逐案例签署为 `PASS`，UAT-04 的 `UAT-HUA-VLAN-LOCAL-01` 已通过真实页面复测，UAT-05 所需的终态、来源、风险、澄清、外发、CLI、命中文档和人工签署字段已收口；Provider 429/超时/熔断/恢复的真实外部验收仍归属于 RUNTIME-04，不能由 UAT 签署替代。
- **生产迁移与回滚尚未执行：** 尚未在目标生产环境完成迁移、备份/恢复、回滚目标确认、Kill Switch 演练和数据一致性复核。
- **Release Candidate 尚未形成：** 工作区仍 dirty，未生成经审查的 release candidate Git SHA、变更清单、回滚方案和正式审批记录；本地四厂商 ZIP 仍明确为 `test_only=true`、`production_eligible=false`，不能直接当生产知识包。

本轮新增的远端门禁与 UAT-04 证据统一见 [AI 发布门禁与 UAT-04 walkthrough](docs/walkthrough/walkthrough_20260905_2357_01_AI发布门禁与UAT复测.md)。旧章节中关于“未 push”“远端未执行”和该案例 `PARTIAL` 的表述均属于生成时的历史快照，不覆盖本节当前结论。

已完成但仅作为当前输入的证据：[50-anchor signed review](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-review.json)、[50-anchor 标准报告](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-report.json)、[50-anchor 隔离报告](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-isolated-report.json)、[400 条生产合同检查](docs/knowledge-engine/eval/eval-golden-400-production-check.json) 和 [400 条隔离检索报告](docs/knowledge-engine/eval/eval-golden-400-retrieval.json)。旧冻结 v1 与候选 v2 的失败/通过数字只在历史章节保留，不得覆盖当前 v3 结论。

## 接续执行顺序

1. 代码已推送并完成远端门禁；后续新增代码变更仍需按受影响 workflow 重新验证，并继续保存 run URL、commit SHA、环境版本和最终结果。
2. 以当前 [v3 signed review](docs/knowledge-engine/eval/eval-anchors-50-v3-signed-review.json) 和标准/隔离 `50/50 PASS` 为 50-anchor 输入，不重新退回 v1，也不把 v2 当作默认门禁输入；400 条数据集继续按官方来源自动评测契约处理，不新增无必要人工签字要求。
3. 完整浏览器 UAT-001/UAT-05 已收口：保留 38/38 条逐案例签署、`UAT-HUA-VLAN-LOCAL-01` 和脱敏矩阵证据；不重复签署，转入真实运行依赖和 Provider live failure 证据。
4. 在依赖可用的环境中完成 BGE reranker、Docling、Langfuse 和纳入本轮范围的 Provider resilience 运行态验收；Docker/Windows/pgvector 及迁移 104 已按用户要求暂记完成，后续由用户独立验证，不在本轮重复执行。Qwen/Ollama 不属于本轮范围。
5. 完成目标生产环境的备份、迁移、健康检查、回滚/恢复和 Kill Switch 演练，生成可审计的 release candidate SHA、变更清单、回滚目标和正式审批记录。
6. 只有远端 CI、真实依赖、完整 UAT、生产迁移/回滚、RC 和审批全部通过，才可将 readiness 从 HOLD 改为可发布。

## 可复现命令

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/ai -q
.venv\Scripts\python.exe -m pytest backend/tests -q
npm run test:frontend -- --run
npm run lint
npm run build
.venv\Scripts\python.exe scripts\knowledge_eval_anchors_50_runner.py
.venv\Scripts\python.exe scripts\knowledge_eval_anchor_review_check.py --database
.venv\Scripts\python.exe scripts\knowledge_eval_gold_400_check.py
.venv\Scripts\python.exe scripts\knowledge_eval_baseline_manifest.py
.venv\Scripts\python.exe scripts\knowledge_eval_ci_gate_check.py
.venv\Scripts\python.exe scripts\ai_rag_release_config_check.py
.venv\Scripts\python.exe scripts\validate_postgresql_only.py --list
git diff --check
```

本地浏览器入口：`http://192.168.56.1:5400/ai/copilot`。浏览器需使用已登录会话；不要把原始对话内容、完整 Provider 输出或敏感标识写入交接材料。

## 安全与审计约束

- 验收数据库必须使用 PostgreSQL；SQLite 不能作为验收替代品。
- 评测和 UAT 证据只记录状态、指标、路由、调用类型、风险等级、trace/request 标识及脱敏后的摘要。
- 不记录凭据、API key、原始 prompt、完整模型回答或设备敏感数据。
- 任何高风险设备操作都必须在独立确认后才允许进入执行链路；本轮没有确认或执行生产设备变更。
- 上一轮 Gold 审核与 CI 修复已推送到 `origin/main`；当前远端最新为 `dba331b9`。本轮四厂商知识包、导入契约、产品解析、测试隔离、UI、50-anchor v3 signed、400 条官方 Dataset 及 m0204～m0208 迁移改动已提交到本地 `main`（`36d64acf`），尚未 push；没有删除用户已有文件或变更，主工作区 `dist/index.html`、评测 manifest 和开发脚本的用户改动均已保留。

## 2026-09-05 400 条数据策略变更（未推送）

- 按用户确认，400 条评测集不再要求人工评审、二审或 reviewer 字段；50-anchor 的人工 Gold 审核规则保持不变。
- 新增 `scripts/generate_official_source_eval_gold_400.py`，从 `data/kb_import/manifest.json` 的四厂商来源矩阵生成 `nexora-kb-eval-gold-400-v2-20260905`。
- 400 条 Dataset 的 answer 用例均绑定 `source_evidence.url`，仅允许 Huawei、Cisco、H3C、Ruijie 官方 HTTPS 主机；clarify/no-match 用例不强制绑定文档。
- `scripts/knowledge_eval_gold_400_check.py` 已改为官方来源/安全/分布门禁，并将每个 `document_id + URL` 反查 `data/kb_import/manifest.json` 及其 SHA-256；在重新生成本地知识包后已同步 Dataset manifest 引用，普通检查和 `--require-production` 均为 `PASS`，`official_source_evidence_case_count=300`，`human_review_required=false`。当前 400 条 Dataset SHA-256 为 `6e030b4b9b98156f84524f2ec3dbb35be87d0cde8c29a48830a6c206a215840a`，对应 manifest SHA-256 为 `b7225b3e07385ebfb2ef3e37661041e49029ceb9437b4857f80775a05c0fba3d`。
- 知识库“基线自检”页面新增只读 400 条概览 API/UI，只显示数量、类别、厂商、切分和来源门禁，不下发题目、答案、Gold 文档 ID 或正文。
- 该策略仍不等于 400 条整体生产放行；400 条来源门禁和 300 条 answer 的隔离 PostgreSQL 检索均通过，冻结 v1 50-anchor 当前标准/隔离复跑为 `39/50 quality=FAIL` 且 `safety=PASS`，真实组件、UAT、远端 Actions 和 Release Candidate 仍保持阻断。以上改动已进入本地 `main` 的 `36d64acf`，尚未 push。

## 2026-09-06 RackVision 3D 机柜管理交接更新

更新时间：2026-09-06  
分支：`main`  
目标远端：`origin/main`  
交付范围：用户已明确要求把当前工作区的全部代码变更推送到 `main`。`m0211`、`m0212` 虽然是逻辑上独立的任务，本次按用户要求随当前代码一并交付；后续仍按独立任务维护。

### 今日已完成

#### 后端、数据与接口

- 建立资产到机柜设备的标准化 `placement` 返回契约，资产列表和详情同时返回机柜、站点、U 位、安装方式、尺寸状态、来源与位置备注；未安装资产返回 `null`。
- 补齐资产批量导入的事务边界：批量流程内部的标签同步不再提前提交，保证逐行失败时能够按原子事务回滚。
- 增加机柜引用解析器，优先稳定 ID，其次 `rack_code`，最后名称；名称不唯一时返回明确的 `RACK_NOT_UNIQUE` 和冲突机柜 ID。
- 增加机柜数据质量审计：支持全量或授权范围审计，覆盖孤儿引用、重复安装、投影不一致、站点/类型缺失、U 位冲突、重复资产和电源字段冲突；审计只写质量问题表，不修改业务主表。
- 增加 `POST /api/rack-data-quality/audit` 接口，支持全量审计或指定机柜审计，并复用租户与资源授权范围。
- 完成机柜放置校验错误分类：未知资产、U 位越界、U 位重叠、全深度冲突、零 U 设备缺少位置说明、设备类型仍被使用等场景返回稳定错误码和状态码。
- 增加 `m0213_rackvision_power_reconciliation`：以 PostgreSQL 为权威来源同步新旧电源字段，并在存在非零冲突时保留质量问题证据；迁移设计为可重复执行。
- 保留并纳入 `m0210_rackvision_canonical_placement`、RackVision 目录导入、回填、范围控制、资产解析与数据质量相关代码和测试。

#### 前端与 3D 视图

- 3D 机柜设备坐标改为按真实机柜 `depth_mm`、`width_mm` 计算，不再固定使用单一深度/宽度常量。
- 机柜 3D 框架导轨横向位置随实际机柜宽度缩放。
- 立面图对未知或无效 U 位设备不再参与占位和拖拽目标计算，但仍保留在审查区域，避免错误数据阻塞合法设备操作。
- 资产管理类型补充标准化 `AssetPlacement` 类型，前后端字段保持一致。
- 补充 RackVision 适配器、立面图、3D 机柜、布局、拓扑、只读检查与 API 契约测试。

#### 任务清单与资料

- 更新 `docs/Nexora_RackVision_MASTER_TASKS.md`。
- 更新 `docs/Nexora_RackVision_Backend_Data_API_TASKS.md`。
- 更新 `docs/walkthrough/walkthrough_20260906_rackvision_execution.md`。
- 本节作为今天继续开发、测试和上线交接的事实基线。

### 已验证结果

- 前端生产构建：`npm run build` 通过，Vite 构建完成。
- 前端代码检查：`npm run lint` 通过。
- 前端 RackVision 定向测试：20 个测试通过。
- 资产导入、安全与事务回归：23 个测试通过。
- 机柜放置、布局与资产 placement 契约组合测试：10 个测试通过。
- 数据变更保护测试：6 个测试通过。
- 数据质量 API：2 个测试通过。
- `m0213` 电源迁移测试：2 个测试通过。
- 后端修改文件已完成 Python 编译检查。

### 尚未关闭的门禁

- 全量后端测试历史基线为 `2304 passed, 2 failed`。其中 RackVision 资产导入事务失败已经修复并由 23 个定向回归覆盖；剩余失败是独立 IPAM 测试使用临时 `ip_addresses` 表但查询 `ip.device_id`，不是本次 RackVision 变更，尚未修复或重新跑完整后端套件。
- 尚未在真实 PostgreSQL 生产/预生产库执行迁移备份、dry-run、应用和回滚演练。
- 尚未完成浏览器端 `/cmdb/racks` 全流程人工验收，包括真实资产导入、拖拽、移动、删除、只读权限、批量操作和 3D/立面联动。
- 尚未完成真实 Blender/GLB 资产产线、在线资源 MIME、缓存和大规模机柜性能验收。
- 尚未把全量后端测试恢复到完全绿色；交接后应先确认独立 IPAM 失败是否已被其他任务处理，再决定是否单独修复。

### 任务边界

- `m0211`（设备租户范围）已作为独立任务完成；本次因用户明确要求“全部代码都 push”而一并推送，但它不属于 RackVision 业务范围。
- `m0212`（H3C Comware v3 平台支持）同样作为独立任务随本次全量代码推送；后续发布说明应按独立变更记录。
- 本次交接不把历史测试失败包装为全部通过；部署前仍需补齐全量后端回归和数据库演练。

### 交接后的建议顺序

1. 在干净环境重新执行完整后端测试，并单独处理或记录 IPAM 临时表字段问题。
2. 在预生产 PostgreSQL 执行 `m0210`、`m0213` 的备份、dry-run、应用、校验和回滚演练。
3. 对 `/cmdb/racks` 做浏览器人工验收，重点检查 2D/3D 坐标、非法 U 位、资产 placement、权限边界和质量审计。
4. 完成线上 3D 资源与静态资源缓存/MIME 检查后，再进行生产发布。

### 本次交付记录

- handoff 文件：`handoff.md`（本节为新增 RackVision 交接内容，保留此前 AI/RAG 交接历史）。
- 提交：本次交付提交（amend 后以最终 `git log -1` 为准）。
- 推送：目标为 `origin/main`，仅推送 `main` 分支。
- 本地运行时状态、知识库引用和数据库备份文件不作为代码交付内容；其余当前工作区代码、测试、迁移、文档、前端构建相关变更按用户要求纳入本次提交。

## 2026-09-06 GitHub Actions 发布门禁修复

- 失败任务：Ubuntu release job 在 `Commit sanitized Ubuntu release tree` 步骤失败，错误为 `Required release path missing: tools/blender`。
- 根因：前面的公开发布树清理步骤按设计执行了 `rm -rf tools/`，但后面的清理树必需路径列表仍然要求 `tools/blender`，形成自相矛盾的检查。
- 修复：保留源码完整性检查阶段对 `tools/blender` 的校验；从清理后的公开发布树必需路径列表移除 `tools/blender`，因为该目录已被明确清理，不应进入公开发布仓库。
- 本地验证：`release.yml` YAML 解析通过，`knowledge_eval_ci_gate_check.py` 通过，`ai_rag_release_config_check.py` 通过，`git diff --check` 通过。
- `knowledge_eval_ci_gate_check.py` 同步刷新了 `docs/knowledge-engine/eval/eval-ci-gate-v1.manifest.json` 中的工作流 SHA-256，随本次 CI 修复一并提交。
- 另一个本地启动提示 `Port 5400 is already in use` 与 GitHub Actions 无关，表示已有 Vite 进程占用 5400；结束旧进程后再启动即可。

## 2026-09-07 Docker/Nginx 首页下载问题

- 现场请求 `https://192.168.204.128/` 返回了正确的 `index.html` 内容，但响应头为 `Content-Type: application/octet-stream`，因此浏览器将 1,101 字节的 SPA 入口当作文件下载，而不是渲染页面。
- 根因是 `nginx/nginx.conf` 在 `server` 级别定义了只包含 GLB/GLTF/KTX2/Basis 的 `types {}`，覆盖了官方 Nginx 镜像继承的标准 MIME 映射，导致 `index.html`、JS 和 CSS 都可能失去正确的 MIME 类型。
- 修复是移除覆盖全局映射的 `types {}`，保留官方 Nginx 的标准 MIME 表；GLB、GLTF、KTX2、Basis 改用独立 location 的 `default_type`，不会再影响 HTML/CSS/JS。
- 本机已完成 `git diff --check` 和配置文本检查；当前 Windows 环境没有 Docker/Nginx CLI，部署后需要在目标机执行 `nginx -t` 并重建/重启 Nginx 容器，再用 `curl -k -I https://<host>/` 确认 `Content-Type: text/html`。
