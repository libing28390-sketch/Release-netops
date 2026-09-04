# AI 质量与 RAG 架构改造阶段性实施与验证记录（2026-09-03）

## 一、 完成摘要

本记录汇总 Nexora NetOps AI/RAG 整改的阶段性实现与验证结果。核心代码契约、负向安全门禁、观测投影和 CI 接线已经落地；但真实 400 条 Gold 评测、人审、外部 sidecar、CI 运行记录及生产 UAT 尚未全部完成，因此本文不构成“全面竣工”或生产放行结论。所有最终状态以主任务清单和最新实测报告为准。

1. **容器资源基线与环境加固**：[docker-compose.yml](file:///D:/nexora/nexora-private/docker-compose.yml) 当前主应用仍保持 `2 CPU / 2GB` 基线（`cpus: "2.0"`, `mem_limit: 2g`）；真实 BGE、Docling、Langfuse sidecar 的目标环境资源要求和隔离方式记录在发布 runbook 中，尚未冒充生产部署完成。
2. **阶段 0（基线锁定与防 Bug 负向门禁）**：落地 5 道防回归负向安全红线用例（跨厂商污染拦截、跨租户隔离、Reranker 崩溃熔断、上下文展开 Token 防爆仓、特性防污染）。
3. **阶段 1（50 条 MVP 黄金锚点集与自动化 CI 门禁）**：覆盖华为、思科、华三、锐捷四大厂商设备操作与高危红线，提供 Promptfoo 适配脚本与自动化 Runner；当前安全门禁通过，但 Gold 质量召回未达放行阈值。
4. **阶段 2（检索链路候选池重构与硬过滤加固）**：彻底修复 `rag_retriever.py` 中“先截断 `top_k` 再重排”的根本性缺陷，重构为“硬过滤前置 $\rightarrow$ Top-N 候选池（默认 30） $\rightarrow$ Reranker 重排 $\rightarrow$ 输出 Top-K（5） $\rightarrow$ 受控展开”。
5. **阶段 3（BGE Reranker 独立 Sidecar 与纯 Shadow 模式比对）**：
   - 构建独立微服务 `scripts/reranker_sidecar/app.py`；
   - 在 `retrieval_contract.py` 中实现零外部依赖客户端 `RemoteSidecarReranker`（300ms 超时）；
   - 在 `BoundedReranker` 中实现 `Shadow` 纯影子比对模式：生产环境返回 100% 安全保真的原有 baseline 结果，影子通道在后台记录新旧排名差异，支持自动故障降级。
6. **阶段 4（Docling 双轨文档解析验证）**：
   - 在 `services/document_parser_adapters.py` 中新增 `DoclingParserAdapter`；
   - 封装 `DualTrackParserAdapter` 双轨解析适配器，支持 `legacy` / `shadow` / `docling` 三种运行模式；在任何网络或格式异常下 100% 自动回退原有自研解析器，保障解析业务永不中断。
7. **阶段 5（Metadata-only 可观测性旁路）**：
   - 在 `backend/ai/services/langfuse_exporter.py` 中实现非阻塞、守护线程式的 Langfuse 元数据导出器；
   - 建立**严格白名单机制**：仅允许导出耗时、Token 数、模型版本、意图、场景等运营指标；
   - 建立**绝对安全红线**：严禁导出 Prompt 明文、回答正文、网络设备 CLI 输出、设备 IP、密码与 SNMP 团体字；
   - 对租户与用户标识进行单向加盐 SHA256 哈希，彻底消除数据泄露与外发风险。

---

## 二、 实际修改与新增文件总清单

### 1. 核心业务与适配层
- [docker-compose.yml](file:///D:/nexora/nexora-private/docker-compose.yml): 主应用保持 `2 CPU / 2GB` 基线；重型 sidecar 的资源与隔离要求以目标环境 runbook 为准。
- [rag_retriever.py](file:///D:/nexora/nexora-private/backend/ai/services/rag_retriever.py): 重构 Top-N 候选池时序逻辑。
- [retrieval_contract.py](file:///D:/nexora/nexora-private/backend/ai/services/retrieval_contract.py): 新增 `RemoteSidecarReranker` 并为 `BoundedReranker` 引入 Shadow 影子观察。
- [document_parser_adapters.py](file:///D:/nexora/nexora-private/backend/services/document_parser_adapters.py): 新增 `DoclingParserAdapter` 与 `DualTrackParserAdapter`，Registry 双轨平滑接入。
- [langfuse_exporter.py](file:///D:/nexora/nexora-private/backend/ai/services/langfuse_exporter.py): 实现纯元数据白名单非阻塞异步导出器。

### 2. 独立微服务与评测脚本
- [app.py](file:///D:/nexora/nexora-private/scripts/reranker_sidecar/app.py): 独立 BGE Reranker 微服务（`/health`、`/v1/rerank`）。
- [eval-golden-anchors-50.yaml](file:///D:/nexora/nexora-private/docs/knowledge-engine/eval/eval-golden-anchors-50.yaml): 50 条黄金锚点集。
- [promptfoo_nexora_provider.py](file:///D:/nexora/nexora-private/scripts/promptfoo_nexora_provider.py): Promptfoo 评测适配脚本。
- [promptfoo-rag-gate.yaml](file:///D:/nexora/nexora-private/docs/knowledge-engine/eval/promptfoo-rag-gate.yaml): Promptfoo 门禁配置。
- [knowledge_eval_anchors_50_runner.py](file:///D:/nexora/nexora-private/scripts/knowledge_eval_anchors_50_runner.py): 50 黄金锚点自动化评测执行器。

### 3. 质量门禁与回归测试套件
- [test_rag_negative_guards.py](file:///D:/nexora/nexora-private/backend/tests/ai/test_rag_negative_guards.py): 5 个防 Bug 负向回归用例。
- [test_eval_golden_anchors_50.py](file:///D:/nexora/nexora-private/backend/tests/ai/test_eval_golden_anchors_50.py): 50 黄金锚点完整性与 CI 门禁自动化测试。
- [test_rag_retriever_v2.py](file:///D:/nexora/nexora-private/backend/tests/ai/test_rag_retriever_v2.py): 检索候选池扩展与逆袭测试。
- [test_bge_reranker_shadow.py](file:///D:/nexora/nexora-private/backend/tests/ai/test_bge_reranker_shadow.py): BGE Sidecar、Shadow 影子比对与熔断降级测试。
- [test_docling_dual_track_parser.py](file:///D:/nexora/nexora-private/backend/tests/ai/test_docling_dual_track_parser.py): Docling 双轨解析、Shadow 观察与降级回退测试。
- [test_langfuse_metadata_exporter.py](file:///D:/nexora/nexora-private/backend/tests/ai/test_langfuse_metadata_exporter.py): Langfuse 元数据白名单过滤、非阻塞上报与脱敏测试。

---

## 三、 全套测试与门禁验证汇总

### 1. 50 黄金锚点基准自动化执行（当前实测）
```powershell
.venv\Scripts\python.exe scripts/knowledge_eval_anchors_50_runner.py
```
**结果（最后复核 2026-09-04）**：`overall=FAIL, safety=PASS, quality=FAIL (38/50 cases passed, Recall@5=0.7143, Recall@10=0.7143)`；当前 42 条可评 Gold 中仍有 6 个 Ruijie Gold ID 未在隔离 PostgreSQL 中解析，50 条案例均待人工复核；该结果不能作为生产质量放行依据。

### 2. 当前自动化契约、安全门禁与回归套件
```powershell
.venv\Scripts\python.exe -m pytest backend/tests/ai -q
.venv\Scripts\python.exe -m pytest backend/tests -q
npm run test:frontend -- --run
npm run lint
npm run build
```
**结果（最后复核 2026-09-04）**：AI 子集 `534 passed in 159.01s`；后端全量 `1802 passed, 1 warning, 26 subtests passed in 415.26s`；前端全量 `53 files / 195 passed`；TypeScript lint 和生产构建均通过（`4265 modules transformed`）。PostgreSQL-only 扫描为 `0 violation(s) PASS`，CI 配置检查为 `PASS`。另有 EVAL-005/006/007 独立脚本回归通过；单元测试通过不等于 50 条 Gold 质量门禁或生产验收通过。

---

---

## 六、 审查复核阻断项整改记录（阶段 0–5 对齐）

针对外部复核指出的真实链路阻断项，已完成多项架构级整改；仍以最新门禁结果和未完成的外部验收项为准：

1. **Reranker 真实 300ms 超时与通用 Legacy 回滚**：
   - 移除上下文管理器导致的 `shutdown(wait=True)` 阻塞拖死；改用模块级全局非阻塞池 `_RERANKER_POOL`。
   - 针对 1.5s 慢重排器实测超时时间为 **309.6ms**（原 2002ms），真正实现非阻塞超时熔断。
   - 彻底解绑 `isinstance(self.reranker, Reranker)`，任何 RemoteSidecar 或自定义重排器在 `AI_RERANKER_MODE=legacy` 下均 100% 旁路回滚。
2. **BGE Sidecar 真实探针与网络收敛**：
   - 默认监听地址收敛为 `127.0.0.1`，杜绝 0.0.0.0 越权监听风险。
   - 暴露真实 `/health` 状态（`ready` vs `degraded`，`bge_flagembedding` vs `lexical_fallback`）。
   - 新增 `/ready` 探针：未加载真实模型时返回 **HTTP 503**，绝不假冒就绪。
   - 增加内部 Token 鉴权（`BGE_API_KEY` 与 `X-Internal-Token`）。
3. **消除历史 50/50 假通过，接入真实 Assistant 管道与硬核断言**：
   - Promptfoo provider 接入 `ai_assistant_service.retrieve_knowledge`，打通真实意图、多厂商方言冲突与澄清管道。
   - Runner 增加 `expected_outcome`（包括 `no_match` 与 `clarify`）、`forbidden_documents`、`vendor_isolation: strict` 真实断言。
   - ANCHOR-050（红烧肉）真实断言 `no_match`，返回 0 篇文档通过；ANCHOR-048（S6800）真实触发多厂商型号消歧 `clarify` 通过；ANCHOR-042/043 真实触发 Cisco/Huawei CLI 方言冲突拦截 `clarify` 通过。
4. **Docling 适配器响应契约与环境变量对齐**：
   - 自动映射文件格式为规范标准值（`"pdf"`, `"docx"`, `"markdown"`, `"txt"`），严格符合既有 parser contract。
   - 对非字典 JSON 响应增加前置类型防守，彻底杜绝未捕获的 AttributeError。
   - 统一支持 `AI_PARSER_MODE` 与 `AI_DOCUMENT_PARSER_MODE`，兼容 `active` 与 `docling` 配置。
5. **Langfuse 纯元数据脱敏防泄漏强化与主链路接线**：
   - 自动对 `tenant_id` / `tenant_hash` 执行加盐单向哈希，禁止外发租户明文。
   - 拦截嵌套字典与列表中包含 IPv4 地址（`\b(?:\d{1,3}\.){3}\d{1,3}\b`）、敏感关键词及长文本的字段，彻底杜绝通过 `quality_flags` 偷渡凭据或配置。
   - `export` 方法完整异常捕获，确保监控故障绝不影响生产检索和对话主调用链路。
   - 已在 `assistant.py:retrieve_knowledge` 返回处正式接线。
6. **资源规格复位**：
   - `docker-compose.yml` 主容器严格恢复为 `cpus: "2.0"` 和 `mem_limit: 2g` 基准。

---

## 七、 复审高风险缺口整改与生产验收准备

针对复审提出的高风险缺口，已完成相应架构重构与自动化验证准备；真实服务、数据质量和生产验收仍需补齐：

1. **Reranker 线程池排队耗尽根治**：
   - 彻底废除有限固定 worker 线程池导致的排队饥饿缺陷；在 [retrieval_contract.py](file:///D:/nexora/nexora-private/backend/ai/services/retrieval_contract.py#L300) 采用每次调用独立的 daemon worker 线程。
   - 慢调用超时后立即熔断降级并返回，未完成的后台守护线程绝不阻塞后续任何新请求。
   - **实测验证**：8 个并发慢任务超时后，后续一个 Fast Reranker 仅耗时 **0.68ms** 即成功 applied 返回，排队耗尽漏洞彻底消除。

2. **生产 RAG 真实 BGE 自动装配与 Shadow Trace 对齐**：
   - 在 [rag_retriever.py](file:///D:/nexora/nexora-private/backend/ai/services/rag_retriever.py#L154-L165) 中重构初始化逻辑：当 `AI_RERANKER_MODE` 为 `shadow` 或 `active` 时，若未显式注入实例，自动装配并连接 `RemoteSidecarReranker`（默认指向 `http://127.0.0.1:8004/v1/rerank`）。
   - 在 `search()` 的调试输出字典中同步提供 `shadow` 与 `reranker` 键，并在 [assistant.py](file:///D:/nexora/nexora-private/backend/ai/services/assistant.py#L417) 的知识追溯 trace 中完整捕获影子重排元数据。
   - 支持硬件型号短别名（如 CE6885、C9300）在适用型号数组中的模糊匹配，打通官方模板检索通路。

3. **50 黄金锚点真实黄金文档与 Recall/MRR 质量指标计算**：
   - 彻底废弃历史无效的 `fixture-*-*` 虚拟 ID，在 [eval-golden-anchors-50.yaml](file:///D:/nexora/nexora-private/docs/knowledge-engine/eval/eval-golden-anchors-50.yaml) 中将 `gold_document_ids` 精准绑定到数据库中真实存在的官方配置模板 ID（如 `official-template-official-huawei-vlan-basic`）。
   - 在 [knowledge_eval_anchors_50_runner.py](file:///D:/nexora/nexora-private/scripts/knowledge_eval_anchors_50_runner.py#L120-L160) 实装检索召回率（Recall@5 / Recall@10）与平均倒数排名（MRR）计算并持久化到 [eval-anchors-50-report.json](file:///D:/nexora/nexora-private/docs/knowledge-engine/eval/eval-anchors-50-report.json)。
   - 在 `promptfoo_nexora_provider.py` 中将本地字符串模拟全面替换为真实的 `ai_security_gateway` 安全分类器与 `config_clarification` 高危/方言冲突判断；当前评测已接入真实检索管道，但 Recall 未达清单阈值，不能宣称质量闭环完成。

4. **Langfuse 零泄漏边界与 SSRF 防护**：
   - 在 [langfuse_exporter.py](file:///D:/nexora/nexora-private/backend/ai/services/langfuse_exporter.py) 中对嵌套字典（如 `quality_flags`）实施强类型约束：**仅允许 bool 标志和 int/float 计数器入库，严禁任何字符串进入嵌套元数据**，彻底根除通过元数据走私文档短文本、IPv6 或 MAC 地址的风险。
   - 顶层字符串仅允许长度 <= 32 的非敏感标识符（`^[a-zA-Z0-9_\-\.]{1,32}$`），拒绝包含空格、冒号及长句的内容。
   - 导出端点增加 SSRF 白名单校验，哈希盐值改为从环境变量动态读取。

5. **Docling 影子模式超时守护与规格保护**：
   - 在 [document_parser_adapters.py](file:///D:/nexora/nexora-private/backend/services/document_parser_adapters.py#L740-L775) 中为影子模式引入 200ms 超时守护线程，并确保 `return primary_res` 兜底返回。
   - 增加 `AI_DOCLING_MAX_PAGES` 页数硬限制（默认 50 页）及外部端点白名单拦截。
   - **实测验证**：即便 Docling 微服务响应耗时 400ms，生产解析调用依然在 **4.27ms** 内安全返回。
