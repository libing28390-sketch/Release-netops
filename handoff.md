# Nexora NetOps 知识库 Docker 迁移问题交接

> 交接日期：2026-08-31（Asia/Shanghai）
> 下一次跟进：2026-09-01
> 当前状态：问题已定位到 Docker 端知识库导入链路，尚未修改业务代码或线上数据

## 1. 用户目标

将本机知识库迁移到 Docker 部署环境，并确保：

- 本机已有的知识文档不会因为 Docker 新建数据库而丢失。
- 文档可以按厂商、平台、目录和 Metadata 正确迁移。
- 文档能够在 Docker 端重新切片并生成向量。
- 不重复导入 Docker 已经初始化的官方知识。
- 导入失败时可以定位到具体文档和具体阶段，而不是只显示统一的 500 错误。

## 2. 已确认的部署与数据事实

### Docker 数据库是独立数据卷

Docker Compose 使用独立 PostgreSQL 服务和命名卷：

- 服务：`db`
- 容器：`nexora-db`
- 数据卷：`nexora-pgdata:/var/lib/postgresql/data`
- 应用容器：`nexora-netops`

本机 PostgreSQL 数据不会随着以下操作进入 Docker：

- `git push`
- Docker 镜像构建
- `docker compose up -d`
- 前端构建

数据库迁移需要使用 PostgreSQL 备份恢复，或者使用项目的知识库导出 ZIP。

### Docker 当前知识库数量

用户在 Docker 服务器执行了只读 SQL，结果为：

```text
knowledge_source_type | documents
----------------------+----------
official_template     | 63
official_url          | 41
----------------------+----------
合计                   | 104
```

此前还确认：

```text
status | documents | chunks
-------+-----------+-------
active | 104       | 104
```

并且：

```text
tenant         | documents | chunks
---------------+-----------+-------
tenant-default | 104       | 104
```

以及：

```text
total_chunks | vector_ready_chunks
-------------+--------------------
104          | 104
```

结论：Docker 当前只有初始化的官方知识，不是本机完整知识库；当前没有 `internal_sop`、`internal_standard`、`case` 或 `user_document` 数据。

### 页面上的向量统计存在实现限制

当前 `ready_indexes` 统计值使用文档总数，并不是真正的 `embedding_vector IS NOT NULL` 切片数。因此页面显示 104/100% 不能单独证明所有向量都已经正确生成，需要使用 SQL 查询真实向量数量。

## 3. 本机知识库与导出 ZIP 事实

本机当前导出范围为 269 篇文档，截图显示：

- 文件队列：269 个文件。
- 文件总大小：约 2.7 MB。
- 文档名称主要类似：
  - `huawei.ce16800.product_registry.series-doc...`
  - `huawei.cloudengine-16800...`
  - `huawei.cloudengine-5800...`
- 文档来源看起来是厂商产品目录/官方资料，不是企业内部 SOP。

在本机代码和数据库上做过只读导出包校验，当前导出服务重新生成的 269 篇包结果为：

```text
document_count：269
parsed：269
metadata_mismatches：0
vendors：
  Cisco：46
  H3C：41
  Huawei：174
  Ruijie：8
source_types：
  official_template
  official_url
```

因此当前已排除：

- ZIP 缺少文档。
- ZIP manifest 数量与文件数量不一致。
- 当前导出器生成的 manifest 与文档 Metadata 存在已知不一致。
- 单纯因为 ZIP 中包含多个厂商而无法通过导出器生成。

## 4. 当前 ZIP 导入行为

### 入口位置

知识库管理页面为：

```text
/ai/knowledge
```

不是：

```text
/ai/copilot
```

当前界面没有独立的“导入 Nexora ZIP”按钮。入口是：

```text
知识库管理
→ 文档与版本
→ 右上角“上传”
→ 批量上传
→ 选择 .zip
```

当前通用批量上传文件选择器允许 `.zip`，但“上传企业 SOP”专用入口不允许 `.zip`。

### ZIP 内部结构

当前导出服务将所有文件放到扁平的：

```text
documents/
```

目录下，例如：

```text
manifest.json
documents/huawei.xxx.md
documents/cisco.xxx.md
```

真实的厂商、平台、目录、型号和版本主要放在每篇 Markdown 的 JSON/YAML Front Matter 与 `manifest.json` 中，而不是 ZIP 的物理目录层级中。

因此当前上传弹窗中展示的：

- 知识分类目录
- 资料来源
- 目标网络厂商
- 目标平台

并不能用一个全局值代表 ZIP 内全部 269 篇文档。ZIP 迁移模式应该显示 manifest 汇总，而不是继续显示普通文件批量上传字段。

### 导入不会复制旧 Embedding

当前设计是：

```text
读取正文和 Metadata
→ Docker 端重新解析
→ Docker 端重新切片
→ Docker 端重新生成 Embedding
→ 写入 Docker PostgreSQL
```

ZIP 不携带本机旧向量、租户身份、ACL、服务端主键和完整版本历史。

### 当前导入不会自动去重

`add_document_and_chunk()` 会生成新的 `doc_xxx` ID 并执行 INSERT。当前没有基于 `content_hash` 的跨环境去重、跳过或更新逻辑。

因此完整导入本机 269 篇时，Docker 可能从：

```text
104 篇
```

增加到：

```text
104 + 269 = 373 篇
```

其中可能包含 Docker 已有的 104 篇官方资料重复副本。

此外，ZIP 导入会将官方来源声明降级为未复核的用户导入文档，这是当前安全策略，不应直接绕过。

## 5. 已发生的失败

用户在 Docker 上提交 269 篇 ZIP 后，页面中 269 篇全部显示失败，并提示：

```text
知识库导出包导入失败，已回滚全部变更
Request ID: web_...
```

Docker 后端日志：

```text
2026-08-31 23:48:29,917 [ERROR] (PID:7) [req:web_b22ef6b5-48ea-4b3f-bf9d-9b347a112aa8, user:admin] backend.main: Route: POST /api/ai/assistant/documents/import-bundle | Status: 500 | Duration: 13739.73ms | Auth: 1.88ms | Handler: 13737.60ms

2026-08-31 23:51:39,516 [ERROR] (PID:7) [req:web_1a5c4195-b41c-43b0-86fe-97c304f38d46, user:admin] backend.main: Route: POST /api/ai/assistant/documents/import-bundle | Status: 500 | Duration: 13538.66ms | Auth: 3.53ms | Handler: 13535.07ms
```

### 从日志可以排除的方向

- 不是登录失败：用户 `admin` 登录成功。
- 不是权限失败：请求已经进入导入接口并执行了约 13.5 秒。
- 不是 Nginx 300 秒超时。
- 不是 ZIP 超过 64 MB：上传包约 2.7 MB。
- 不是部分提交：接口设计为原子事务，失败后应全部回滚。

### 当前最可能的失败阶段

```text
ZIP 校验通过
→ 某篇文档重新解析/切片/生成向量/写入 PostgreSQL 时抛出普通异常
→ 接口捕获异常
→ 统一返回 HTTP 500
→ 所有文档回滚
```

当前接口在 [backend/ai/api/assistant.py](D:/netops/netsops-main/backend/ai/api/assistant.py) 中捕获未知异常后，只返回：

```text
KNOWLEDGE_BUNDLE_IMPORT_FAILED
知识库导出包导入失败，已回滚全部变更
```

没有记录失败文档路径、失败阶段或安全的异常类型，因此用户提供的路由日志不足以直接判断根因。

## 6. 当前待确认假设

按优先级排序：

1. Docker 后端在某篇官方文档的重新切片、Embedding 或数据库写入阶段抛出异常。
2. Docker 使用的后端代码和本机生成 ZIP 的代码版本不一致。
3. Docker 端 Embedding 模式、维度或运行时配置与本机不一致。
4. 269 篇同步导入在单个请求/事务中规模过大，触发某个运行时边界。
5. 某个具体文档在 Docker 当前解析器或 PostgreSQL schema 下触发特殊异常。
6. 如果 Docker 端没有最新导入接口，前后端版本可能来自不同 Release 分支。

目前没有证据支持“顶部 Huawei VRPv5 选择导致 500”。在 ZIP 分支中，服务端应使用每篇文档自身 Metadata；顶部字段主要是普通文件批量导入字段，当前 UI 展示方式容易造成误解。

## 7. 明天第一步：保留现场并获取可定位错误

### 7.1 先确认失败后数据库没有新增

在 Docker 服务器执行：

```bash
docker compose exec -T db sh -lc '
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "
SELECT status, COUNT(*) AS documents
FROM ai_document
GROUP BY status
ORDER BY status;
"
'
```

预期仍然是 active 104，证明原子回滚生效。

### 7.2 查看导入接口是否在目标代码中

在 Docker 部署目录确认当前仓库来源和提交：

```bash
git remote -v
git log -1 --oneline
```

注意：项目默认 Docker 部署脚本使用：

```text
https://github.com/libing28390-sketch/Release-netops.git
```

而此前代码推送到的是私有 `netsops` 仓库。若使用默认 `scripts/deploy-docker.sh`，私有仓库中的最新修改不会自动进入 Docker。

### 7.3 查看当前容器的错误日志

现有接口会吞掉原始异常，所以先查是否有同一时间段的其他 Embedding/数据库错误：

```bash
docker logs --since 30m nexora-netops 2>&1 | grep -C 40 -E 'import-bundle|KNOWLEDGE_BUNDLE|Embedding|embedding|Traceback|dimension|timeout|429|ERROR'
```

如果没有原始 traceback，不要继续重复上传整包；需要在代码中增加安全的结构化异常日志，至少记录：

- request_id
- 阶段：read_bundle / parse / reconcile / chunk / embedding / database
- 文档路径或稳定哈希
- 错误类别和安全错误摘要
- 已处理数量
- 当前事务状态

不得记录正文、密码、Token、API Key 或原始敏感 Metadata。

## 8. 明天的最小验证方案

不要再次上传 269 篇整包。按以下顺序验证：

1. 从本机导出 1 篇官方文档。
2. 导入 Docker。
3. 如果 1 篇失败，优先查后端版本、Embedding 配置、pgvector 维度和单篇文档错误。
4. 如果 1 篇成功，继续测试 5 篇。
5. 如果 5 篇成功，再按 20～50 篇拆包。
6. 每批成功后检查文档数、切片数和真实向量数。

建议第一批选择单一厂商、单一目录、单一平台的文档，便于定位 Metadata 差异。

成功后的统计预期不是“文档数等于切片数”。应检查：

```text
vector_missing_chunks = 0
vector_ready_chunks = total_chunks
```

## 9. 迁移方案决策

### 方案 A：完整 PostgreSQL 迁移

适用场景：要求 Docker 和本机完全一致，包括原文档、切片、向量、官方类型、版本关系和数据库关联。

基本流程：

```text
本机 pg_dump
→ 安全传输
→ 备份 Docker 当前数据库
→ 在维护窗口恢复
→ 执行迁移检查
→ 验收知识库和业务数据
```

风险：会迁移整个数据库，可能包含用户、设备、任务、凭据、审计等非知识库数据；不得直接覆盖生产数据库而不先备份。

### 方案 B：知识库 ZIP 迁移

适用场景：只迁移知识正文和 Metadata，让目标环境重新切片和生成向量。

当前限制：

- 不自动去重。
- 不自动更新已有文档。
- 不完整迁移目录树、版本历史和 ACL。
- 官方来源会降级为待复核用户导入。
- 269 篇同步导入可能使单请求/单事务过大。

如果继续使用，必须：

- 先排除 Docker 已有的 104 篇官方资料。
- 先按 1、5、20～50 篇小批量验证。
- 记录每批导入清单。
- 导入前备份 Docker 数据库。

### 方案 C：实现真正的知识库迁移任务

长期推荐增加独立迁移模式：

```text
上传 ZIP
→ 校验 manifest
→ 展示厂商/平台/目录/状态汇总
→ 按 content_hash 与目标库比对
→ 只导入新增文档
→ 已存在文档可选择跳过或更新
→ 分批后台切片和生成向量
→ 提供进度、失败文档和迁移报告
```

前端应：

- 增加明确的“导入 Nexora 知识库 ZIP”按钮。
- 检测到 `knowledge-export-v1` 后切换到迁移模式。
- 隐藏普通上传的全局目录、来源、厂商和平台字段。
- 显示 manifest 汇总，而不是仅显示 `documents/` 文件路径。
- 显示“旧向量不迁移，目标机重新生成”。
- 显示已存在文档数量、将新增数量和重复数量。

后端应：

- 将导入转换为后台任务或可恢复批次。
- 为每篇文档记录阶段状态。
- 将失败文档和安全错误摘要写入迁移报告。
- 增加幂等键/正文哈希去重。
- 明确是否保留官方来源类型，并要求管理员确认。
- 保持租户隔离和权限边界。

## 10. 不能做的操作

- 不要把 PostgreSQL 数据目录提交到 Git。
- 不要把 `.dump` 文件提交到 Git。
- 不要把真实 `.env`、API Key、凭据或用户数据写入交接文档。
- 不要重复导入同一个 269 篇 ZIP。
- 不要在没有备份的情况下执行 `docker compose down -v`。
- 不要直接删除 `nexora-pgdata` 以“重新试一下”。
- 不要为了保留官方状态而绕过当前的来源信任策略。

## 11. 关键代码位置

- Docker PostgreSQL 数据卷：[docker-compose.yml](D:/netops/netsops-main/docker-compose.yml:25)
- Docker 镜像构建和前端同步：[Dockerfile](D:/netops/netsops-main/Dockerfile:52)
- Docker 默认 Release 仓库：[scripts/deploy-docker.sh](D:/netops/netsops-main/scripts/deploy-docker.sh:7)
- 知识库导出格式：[backend/ai/services/knowledge_export_service.py](D:/netops/netsops-main/backend/ai/services/knowledge_export_service.py:1)
- ZIP 原子导入：[backend/ai/services/knowledge_bundle_import_service.py](D:/netops/netsops-main/backend/ai/services/knowledge_bundle_import_service.py:222)
- ZIP HTTP 接口与通用 500 包装：[backend/ai/api/assistant.py](D:/netops/netsops-main/backend/ai/api/assistant.py:921)
- 文档切片、Embedding 和 PostgreSQL 写入：[backend/ai/services/knowledge_service.py](D:/netops/netsops-main/backend/ai/services/knowledge_service.py:1450)
- 前端上传和 ZIP 检测：[src/pages/ai/Knowledge/KnowledgeManagementTab.tsx](D:/netops/netsops-main/src/pages/ai/Knowledge/KnowledgeManagementTab.tsx:807)
- 前端 ZIP 文件选择器：[src/pages/ai/Knowledge/KnowledgeManagementTab.tsx](D:/netops/netsops-main/src/pages/ai/Knowledge/KnowledgeManagementTab.tsx:2613)
- API 请求 ID 处理：[src/api/http.ts](D:/netops/netsops-main/src/api/http.ts:40)
- Nginx API 超时：[nginx/nginx.conf](D:/netops/netsops-main/nginx/nginx.conf:115)

## 12. 明天建议的执行顺序

```text
1. 只读确认失败后仍为 104 篇
2. 确认 Docker 当前仓库、提交和前后端版本
3. 增加或临时启用安全的导入阶段日志
4. 用 1 篇文档做最小导入测试
5. 根据日志判断 Metadata / Embedding / DB / 版本问题
6. 修复根因并补充失败路径测试
7. 再决定使用小批量 ZIP，还是 PostgreSQL 迁移
8. 最后再改造独立的 ZIP 迁移 UI 和后台任务
```

### 交接结论

Docker 当前的 104 篇是独立 PostgreSQL 数据卷中的官方初始化知识；本机 269 篇是更完整的官方知识集合。当前 ZIP 包本身通过本机解析和 Metadata 校验，但 Docker 的 269 篇原子导入在约 13.5 秒后返回 500，原始异常被接口隐藏，尚未确认具体失败文档和失败阶段。

明天应先获取可定位的后端异常，再决定是修复当前 ZIP 导入链路、拆批迁移，还是采用 PostgreSQL 备份恢复。不要把这次问题直接归因于目录或平台下拉框，也不要继续重复提交完整 269 篇 ZIP。

## 13. 2026-09-01 执行更新

> 本节覆盖本次 AI 对话能力整改执行状态；上文 Docker ZIP 迁移问题仍需在实际 Docker 环境中单独验证，不以本节结果替代。

- 已生成并持续更新 `docs/AI对话能力整改任务清单_20260901.md`，按 P0/P1 正式范围和 P2 Instructor 隔离预研记录阶段证据。
- 已完成并复测意图结构化、主动澄清、多轮槽位、RAG 查询计划/权限过滤、工具调用安全、前端状态展示、Provider 网关韧性和 PostgreSQL 发布门禁。
- IP/MAC 定位现为本地确定性只读路径：不向外部 Provider 发送运维标识符；查询优先使用租户隔离的 `arp_table`/`mac_table`，旧无租户 `arp_cache` 仅保留默认租户兼容回退。
- 当前已配置的 DeepSeek 连通性和模型探测通过；Qwen/Ollama 按用户决定暂不部署、不纳入本轮验收。
- 最终代码状态下已通过浏览器完成不少于 10 个独立 Copilot 会话，包含普通问答、资产统计、IP/MAC、本地告警、知识澄清、OSPF 排查和高风险 `shutdown` 确认；无设备变更。
- 最终门禁证据：AI 测试 `409 passed`；后端全量 `1639 passed, 1 warning, 26 subtests passed`；前端 `192 passed`；TypeScript 检查、Vite 生产构建、离线 strict 评测和 CI 评测配置检查均通过。
- 已复跑离线检索/实体解析、产品/系统/版本/引用质量、安全出站与敏感信息策略评测脚本，全部 `PASS`；这些结果只代表固定夹具/策略契约，不替代真实 Provider 质量指标。
- 尚未勾选项保持诚实：真实 Provider 结构化成功率/纠正成功率、带标注意图准确率、生产语料 Top-5 召回率，以及 Instructor 与内部 Pydantic 的真实 Provider 对比，均需后续批准的独立实验或真实标注数据；不以离线契约测试冒充实测。

## 14. 2026-09-01 任务进度总结与推送记录

### 当前完成情况

- 本轮正式范围为 P0/P1 AI 对话整改：意图结构化、主动澄清、多轮槽位、知识查询计划与权限过滤、混合检索/引用、工具计划、高风险确认、Provider 网关韧性、Security Vault 脱敏及 AI 中心前端状态展示均已实现。
- IP/MAC 等 `CONFIDENTIAL` 运维标识符已改为租户隔离的本地确定性只读定位；不会把原始标识符送到当前云端 DeepSeek，也不会因为云端分类拒绝而进入错误的普通问答路径。
- Instructor 仅完成隔离边界验证，生产继续使用内部 Pydantic 结构化方案；没有新增未评审依赖，也没有绕过 Nexora AI Gateway 的调用链。
- Qwen/Ollama 当前未配置，按用户决定暂不部署、不纳入本轮验收；不伪造跨 Provider 实测结果。

### 验证证据

- 后端全量：`1639 passed, 1 warning, 26 subtests passed`。
- AI 专项：`409 passed`；AI/Knowledge 聚焦门禁：`616 passed, 1010 deselected, 1 warning`。
- 前端：`52 test files passed, 192 tests passed`；`npm run lint` 通过；`npm run build` 通过，Vite 转换 `4263 modules`。
- 离线 strict 评测、CI 配置检查、检索/实体解析、产品/系统/版本/引用质量、安全出站与敏感信息策略脚本均为 `PASS`；这些仅证明固定夹具和代码策略契约，不替代真实 Provider 质量指标。
- 浏览器 Copilot 已完成修复后最终 10 个独立会话：普通问答、资产统计、IP/MAC 定位、告警/知识澄清、OSPF 排查和 `shutdown` 高风险确认均有终态；未执行设备变更，未出现 `ASSISTANT_CONTEXT_ERROR` 或“只读数据准备失败”。
- DeepSeek 已完成最小连通性与模型探测；开发服务当前保持运行，前端地址为 `http://192.168.56.1:5400/`，后端为 `http://127.0.0.1:5310`。

### 仍明确保留的后续项

- `ai-dialog-remediation-v1-baseline.json` 已补充真实 Provider 小样本结果：8/8 首轮结构化成功，Provider 错误 0；`intent.v1` 带标注意图准确率 4/8，`intent.v2` 为 5/8。schema correction 本轮没有触发，纠正成功率保持 `null/not_observed`；生产语料 Top-5 召回率仍需专项标注语料评测。
- Instructor 与内部方案的真实 Provider 成功率、延迟、Token 对比，以及安全评审版本范围和真实适配器专项验证，仍待未来有批准的实验 Provider 后再做；本轮只完成 Gateway-only 隔离测试和 ADR。
- Docker ZIP 导入已在本机通过 8 项阶段诊断、脱敏、回滚和跨主机 PostgreSQL/pgvector 回归；目标 Docker 主机的真实容器部署、单篇/1/5/20–50 篇导入仍待现场执行。本机没有 Docker CLI，也没有待导入 ZIP。
- 本次额外尝试的 24 条浏览器评测批次因测试页面句柄失效被中断，未将其结果计入证据；最终 10 会话业务验收仍以已完成的修复后记录为准。

### Git 状态

- 当前分支：`main`；远端：`origin`，目标分支：`origin/main`。
- 本次执行前已完成工作区审计；未提交真实密码、Token、API Key 或其他敏感凭据。
- 本轮新增源码、测试、评测产物和文档当前仍在本地工作区，尚未提交或推送；如需写入 `origin/main`，下一步需先由操作者明确授权提交/推送，并在提交前复核工作区中的既有删除项、`.codex` 配置和 `data/backups/` 未跟踪内容。

## 15. 2026-09-01 余项执行记录

### 实时 Provider 评测

- 新增审核样例与显式联网评测器：`docs/knowledge-engine/eval/ai-dialog-live-provider-v1.json`、`scripts/ai_live_provider_eval.py`。未传 `--allow-live-provider` 时脚本直接退出，不访问 Provider；输出不包含模型原文、Prompt 正文或凭据。
- 通过 PostgreSQL 持久化安全策略加载后，真实 DeepSeek `deepseek-v4-flash` 评测完成两轮，每轮 8 条样例、8 次 Provider 请求、0 次 Provider 错误。
- 输出预算根因已修复：完整 `IntentDecision` 在原 `max_tokens=512` 下出现 `finish_reason=length`；现改为有界 `INTENT_MAX_OUTPUT_TOKENS=1024`，并升级意图边界 Prompt 到 `intent.v2`。
- `intent.v1`：首轮结构化成功率 `8/8`，带标注意图准确率 `4/8`，平均延迟 `6772.62 ms`，输入/输出 Token `4846/5753`。
- `intent.v2`：首轮结构化成功率 `8/8`，带标注意图准确率 `5/8`，平均延迟 `5099.88 ms`，输入/输出 Token `5534/3912`；没有 schema correction，因此纠正成功率为未观测而不是 0。
- 完整结果见 `docs/knowledge-engine/eval/ai-dialog-live-provider-report-20260901.json`；Qwen/Ollama 未配置，不声明跨 Provider 结果，生产 Top-5 召回未测。

### Docker ZIP 导入与 Instructor

- `_ImportDiagnostics` 详情改为明确白名单，阶段和状态也限制为低基数枚举；异常摘要额外屏蔽文档路径，新增任意回调字段、正文、路径和口令回归。
- 导入测试：`backend/tests/ai/test_knowledge_bundle_import.py` 与 `backend/tests/ai/test_knowledge_bundle_cross_host_integration.py` 共 `8 passed`。
- Instructor 隔离与评测器纯函数测试共 `5 passed`；未安装 Instructor、未新增生产依赖、未建立直连 Provider 路径。
- 新增并补齐 `docs/knowledge-engine/architecture/ADR-001-INSTRUCTOR-STRUCTURED-OUTPUT.md`，结论为继续使用内部 Pydantic，未来仅在批准的 Gateway adapter 和独立量化实验下复审。

### 本轮代码与验证状态

- PostgreSQL-only 门禁：`0 violation(s)`，PASS。
- AST/JSON 产物校验：PASS。
- 后端全量门禁：`2046 passed, 26 subtests passed`，无失败。
- 相关意图结构化与评测器测试：`25 passed`；导入/跨主机测试：`8 passed`；Instructor 隔离与评测器测试：`5 passed`。
- 本机未安装 Docker CLI；没有在未授权的目标环境执行容器重建、停止卷或真实 ZIP 导入。
