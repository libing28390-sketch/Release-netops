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
