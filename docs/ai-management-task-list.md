# AI 管理中心整改任务清单

> 适用页面：
> - `http://192.168.56.1:5400/ai/knowledge`
> - `http://192.168.56.1:5400/ai/catalog`
> - `http://192.168.56.1:5400/ai/prompts`
> - `http://192.168.56.1:5400/ai/models`
> - `http://192.168.56.1:5400/ai/providers`
>
> 执行状态（2026-08-31）：本清单中的核心整改以及本轮暂留的七项增强已经落地；代码、契约测试、前端回归、生产构建和登录后浏览器页面验收均已完成。清单中保留的 `[ ]` 项是独立的后续规划，不代表本轮七项增强遗漏。
>
> 本轮已完成：知识库目录浏览/筛选/导入闭环；产品目录 Vendor → Family → Series → Model 层级浏览；Prompt 场景资产扩充、编辑、版本、启停、变量校验和脱敏预览；模型路由解释及生效状态；Provider 多实例主从布局和失败错误码展示。
>
> 本轮已完成：Prompt 版本复制/对比/恢复、修改原因与审计、服务端搜索/筛选/分页；Provider 区域/健康/类型/标签筛选与服务端分页；产品目录租户自定义主数据增删改（官方种子保持只读）；以及 Prompt、Provider、Catalog、Model、Knowledge AI 管理页面中英文文案抽取。接口、权限、软删除、乐观并发控制和回归测试见 `docs/walkthrough/ai-admin-enhancements.md`。

## 本轮暂留增强验收（2026-08-30）

- [x] Prompt 支持从现有 Prompt 复制出独立资产，原版本和已调用版本保持不可变。
- [x] Prompt 支持版本对比、指定版本恢复、修改原因记录和分页审计；恢复通过追加版本完成，不回写历史版本。
- [x] Prompt 列表支持服务端搜索、场景筛选、启停状态筛选和分页，同时保留无参数请求的兼容响应。
- [x] Provider 支持区域、健康状态、Provider 类型、标签等服务端高级筛选，并返回筛选 facets。
- [x] Provider 列表支持服务端分页，同时保留无参数请求的兼容响应。
- [x] 产品目录支持租户自定义 Model 主数据的新增、编辑、软删除和恢复可见性控制；官方审核种子只读，写操作受权限、租户、审计和乐观并发保护。
- [x] Prompt、Provider、产品目录、模型路由和知识库管理页面新增中英文文案已抽取到现有 AI 管理国际化资源，并覆盖预览、状态、审计和错误反馈。

## 一、现状与问题定位

- [x] **知识库分类入口不可达（已处理）**：主页面已经渲染真实租户目录树，目录选择通过 `directory_path` 驱动服务端文档/facet 查询；批量上传和手动录入复用同一目录树。
- [x] **产品目录只有平铺筛选，没有可感知的分类浏览（已处理）**：页面新增服务端返回的 Vendor → Family → Series → Model 层级浏览、计数、当前路径和级联筛选，同时保留审核种子只读边界。
- [x] **提示词资产数量和内容覆盖不足（已处理）**：内置 Prompt 增加拓扑、健康、合规、变更、RAG、容量等运维场景，并补充编辑、版本历史、启停、变量检测、输出契约校验和脱敏预览。
- [x] **模型路由的作用说明不足（已处理）**：页面明确展示 Scene → Model Route → Model/Provider → Security Gateway → Provider 响应与审计，并显示默认模型、Fallback、Provider/Model 状态和不可调用提示。
- [x] **供应商多实例视图密度过高（已处理）**：页面改为 Provider 实例列表 + 当前实例详情的主从工作区，完整连接信息和测试结果只在当前实例详情中展示。

## 二、执行顺序

建议按以下顺序实施：

1. [x] P0：知识库目录分类真正接入页面主流程。
2. [x] P0：产品目录增加 Vendor → Family → Series → Model 的层级浏览和可验证筛选。
3. [x] P1：补充 Prompt 资产和生命周期管理（复制/对比等增强项另列后续）。
4. [x] P1：重做模型路由说明和有效路由展示。
5. [x] P1：重构 Provider 多实例布局。
6. [x] P1：补齐接口契约、权限、安全、响应式和回归测试。

---

## 三、P0：知识库分类和目录管理

### 3.1 明确分类边界

- [x] 约定两类概念并在 UI 中分开命名：
  - **知识来源类型**：企业 SOP、官方资料、企业规范、故障案例、系统示例。
  - **知识目录路径**：`01_product/...`、`02_commands/...` 等可嵌套目录。
- [x] 明确文档 `document_category` 与目录路径 `directory_path` 的关系：根目录用于导入定位/默认语义，文档明确元数据继续由服务端校验，不静默覆盖。
- [x] 明确目录删除策略：删除目录树不删除已入库文档；页面和服务端均明确这一点，文档路径迁移策略作为后续产品规则单独补充。

### 3.2 把目录树接入知识库主页面

- [x] 在 `KnowledgeManagementTab.tsx` 的文档工作区渲染现有 `DirectoryTreePicker`；宽屏采用目录区 + 文档工作区布局，窄屏自动堆叠为顶部目录筛选。
- [x] 目录树支持：选择目录、选择“全部目录”、展开/收起、新建根目录、新建子目录、重命名、删除、在当前目录导入文件。
- [ ] 选择目录时：
  - [x] 写入 `selectedDirectoryPath`。
  - [x] 重置 `currentPage` 为 1。
  - [x] 清空当前页勾选文档。
  - [x] 触发文档列表和 facets 的服务端查询。
  - [x] 页面显示当前目录路径和“清除目录筛选”操作。
- [x] 保留当前 `AbortController` / request id 保护，切换目录时取消旧请求，不能让旧目录的响应覆盖新目录结果。
- [x] 目录树加载、空目录、加载失败、无权限和操作失败均有独立状态。

### 3.3 导入流程使用真实目录树

- [x] 将批量上传和手动录入中的静态目录下拉框替换为可复用目录树选择器，选择结果使用完整 `path`。
- [x] 从目录树节点点击“在此目录导入文件”时，上传弹窗自动带入该目录，并显示完整导入前缀。
- [x] ZIP 解压后的相对路径与用户选择的目录合并时保留完整层级，避免重复根目录或丢失子目录。
- [x] 上传队列显示最终目录路径，并将服务端 `METADATA_DIRECTORY_CONFLICT` 转为可读提示。
- [x] 新建、重命名、删除目录成功后刷新树并同步当前选择；当前目录被删除时回退到“全部目录”。

### 3.4 知识库验收标准

- [x] 用户无需打开上传弹窗，就能在 `/ai/knowledge` 选择目录并让文档结果按目录变化。
- [x] 新建目录后，目录刷新出现在主页面和上传流程中，服务端负责持久化。
- [x] 目录筛选与来源类型、厂商、Family、Series、状态、关键词和分页可组合提交到服务端。
- [x] 选择空目录时不会回退为全部文档，文档区显示当前目录无匹配结果。
- [x] 目录操作受 `ai.knowledge.manage` 权限保护；只读角色只保留浏览入口，隐藏写操作。
- [x] 文档删除仍保留独立确认和原有文档安全策略。

### 3.5 可能涉及的文件

- [ ] `src/pages/ai/Knowledge/KnowledgeManagementTab.tsx`
- [ ] `src/api/ai.ts`
- [ ] `backend/ai/api/assistant.py`
- [ ] `backend/ai/services/knowledge_service.py`
- [ ] `backend/database/migrations/m0112_ai_knowledge_directories.py`（仅当现有契约不足时调整，不先重复建表）
- [ ] `backend/tests/ai/test_knowledge_directories.py`
- [ ] `backend/tests/ai/test_knowledge_pagination.py`

---

## 四、P0：产品目录分类浏览

### 4.1 主数据读写边界

- [x] **审核种子保持只读**：现有审核种子的层级浏览和筛选已接通，页面不会对官方主数据提供会失败的编辑入口。
- [x] 租户自定义 Model 主数据已单独落地：使用 PostgreSQL 迁移、租户范围、RBAC、审计、冲突校验、软删除和乐观并发控制；写入口只作用于自定义数据。
- [x] 在页面上明确标注：官方分类浏览读取审核种子；Alias 解析预览只负责候选解析，不会直接写入生产目录；自定义 Model 的写操作有独立权限和审计。

### 4.2 增加层级导航

- [x] 在 `ProductCatalogManagementTab.tsx` 增加“分类浏览”区域，表达层级：
  - [x] Vendor
  - [x] Product Family
  - [x] Series
  - [x] Model
- [x] 每个层级显示名称、代码和服务端层级索引中的匹配数量，不用当前页数组长度冒充全量数量。
- [x] 点击 Vendor / Family / Series / Model 会写入对应筛选条件、重置页码，并在表格上方显示当前路径。
- [x] 下级选项随上级节点收窄，避免跨 Vendor 展示无关 Series。
- [x] 提供清除层级选择；清除时同时清空依赖的下级筛选并回到第一页。
- [x] 移动端使用单列级联堆叠，宽屏才使用四列，不把层级固定挤压在窄屏上。

### 4.3 API 与数据契约检查

- [x] `/api/knowledge/catalog` 的 facets 增加服务端生成的层级导航索引；列表筛选契约保持明确。
- [x] 保持服务端搜索、筛选和分页；前端点击层级只更新查询条件，不拉取全量列表后自行切片。
- [x] 列表继续只返回摘要字段，详情或来源证据按需加载。
- [ ] Alias 队列也要能按 Vendor、Family、Series 和冲突状态定位，不能只按 Alias 文本搜索。
- [x] 所有本轮目录接口继续复用现有 AI 权限和租户范围；官方种子保持只读，租户自定义 Model 写接口使用独立权限、审计、软删除和乐观并发控制。

### 4.4 产品目录验收标准

- [x] 用户能够沿 Vendor → Family → Series → Model 逐级浏览，而不是只能打开下拉框猜分类。
- [x] 点击层级后，表格、总数、当前路径和筛选控件保持一致。
- [x] 无匹配结果、服务端错误、种子只读状态和 Alias 冲突均有明确反馈。
- [x] 列表请求仍按服务端分页返回；层级索引只返回导航摘要。
- [x] 官方审核种子不可编辑；租户自定义 Model 提供受权限保护的新增、编辑、软删除入口，删除不会物理清除历史审计记录。

### 4.5 可能涉及的文件

- [x] `src/pages/ai/Catalog/ProductCatalogManagementTab.tsx`
- [x] `src/api/ai.ts`
- [x] `backend/api/knowledge_catalog.py`
- [x] `backend/services/product_catalog_service.py`
- [ ] `backend/services/catalog_collection_service.py`
- [x] `backend/tests/catalog/test_cat013_catalog_management.py`
- [ ] `backend/tests/catalog/test_cat014_catalog_browse_versions.py`
- [ ] `backend/tests/catalog/test_cat018_catalog_collection_boundary.py`

---

## 五、P1：Prompt 提示词资产扩充

### 5.1 补充内置运维场景

- [x] 保留现有：Copilot 对话、命令解释、配置分析、Diff 分析、告警分析、故障排查。
- [x] 已补充内置场景：
  - [x] RAG 知识检索问答：要求引用文档、标注证据不足、禁止臆测。
  - [x] 设备健康巡检总结：从设备健康快照和时间窗生成结构化摘要。
  - [x] 链路与 LLDP/CDP 拓扑异常分析：区分邻居缺失、链路异常和缺失节点。
  - [x] 配置合规与安全基线审计：输出控制项、证据、严重级别和整改计划。
  - [ ] 备份差异与漂移分析：留作下一轮专门的配置漂移 Prompt。
  - [ ] IP/MAC 定位与资产关联解释：留作下一轮结合资产检索链路补充。
  - [x] 变更工单实施计划：输出前置检查、执行步骤、验证和回退步骤。
  - [x] 容量趋势与扩容建议：明确时间窗口、阈值、趋势和不确定性。
- [x] 每个本轮新增模板都补齐用途/适用输入、输出契约、输入变量和安全边界；页面提供脱敏合成预览。
- [x] 输出格式明确为 JSON，并在输出契约中给出主要字段、枚举和值类型约束。
- [x] 所有模板均禁止写入真实设备密码、SNMP community、私钥、API Key、Token 或未脱敏配置。

### 5.2 完善 Prompt 生命周期

- [x] 新增编辑已有 Prompt，而不只是创建；正文变更生成新版本。
- [x] 支持从当前版本复制出新 Prompt 资产；已被调用的版本保持不可变，避免历史审计失真。
- [x] 支持启用/停用，并在卡片上显示当前版本和状态。
- [x] 增加变量解析和校验：识别 `{{variable}}`，检查未闭合变量和预览变量覆盖情况。
- [x] 增加“使用示例 / dry-run”预览，使用固定脱敏合成数据，不发送真实设备数据到外部 Provider。
- [x] 详情页增加版本对比、更新时间、创建人、变更说明和审计记录。
- [x] 列表改为服务端搜索、场景筛选、状态筛选和分页；前端不再依赖全量 `filter + slice`。

### 5.3 Prompt 页面验收标准

- [x] 首屏能看出每个 Prompt 解决什么网络运维问题、需要哪些变量、输出什么格式。
- [x] 至少覆盖 Copilot、故障排查、命令、配置、Diff、告警、知识检索和合规审计等核心场景。
- [x] 编辑、停用、复制、版本对比/恢复和 dry-run 有成功、失败、空值、并发冲突和权限反馈。
- [x] dry-run 页面明确显示“脱敏合成预览”，不会展示或提交真实业务数据。
- [x] 正文保存以不可变版本记录，失败保存不会改变旧版本。

### 5.4 可能涉及的文件

- [x] `src/pages/ai/PromptCenter/PromptCenterTab.tsx`
- [x] `src/api/ai.ts`
- [x] `backend/ai/api/prompts.py`
- [ ] `backend/ai/prompts/manager.py`
- [x] `backend/ai/schemas/prompt.py`
- [x] `backend/database/migrations/m0194_ai_prompt_lifecycle.py`
- [x] `backend/tests/ai/test_prompt_center_contract.py`
- [ ] `backend/tests/ai/test_llm_001_037_multi_provider.py`

---

## 六、P1：模型路由说明和有效路由

### 6.1 页面需要解释的核心概念

- [x] 在 `ModelManagementTab.tsx` 增加可视化流程说明：业务请求 Scene → Model Route → Model/Provider → Security Gateway（脱敏/权限/数据分类）→ Provider 响应与审计。
- [x] 说明“全局默认模型”和“场景专用模型”的优先级，并展示当前系统默认模型。
- [x] 按 `backend/ai/gateway/router.py` 与 LLM Gateway 的真实行为显示无场景路由、停用模型/Provider、健康异常和 Fallback 状态。
- [x] 文案明确区分“使用全局默认”“路由目标不可用”和“健康异常后按已配置 Fallback 尝试”，不把配置路由包装成无条件自动故障转移。

### 6.2 增加可操作的路由读模型

- [x] 将当前“模型列表”和“场景路由”拆成清楚的两个区块，减少上下滚动时的认知负担。
- [x] 每个场景显示：场景中文名、code、用途说明、当前 Model、Provider、实际 Model Code、启用状态和健康状态。
- [x] 未配置场景路由时，直接显示全局默认模型及其 Provider。
- [x] 路由指向停用或不健康模型/Provider 时显示警告，并明确请求是否会失败或仅在主请求失败后进入兼容 Fallback。
- [x] 变更路由使用原有保存请求和成功/失败反馈，并在刷新后显示当前生效值。
- [ ] 提供“查看调用示例”或“复制配置摘要”，摘要中不得包含 API Key。

### 6.3 模型路由验收标准

- [x] 新用户不看文档也能回答：这个页面为什么存在、它影响哪些请求、模型与 Provider 的关系是什么。
- [x] 每个场景都能看出路由选择模型或全局默认模型；空路由不会产生歧义。
- [x] 页面文案与 `backend/ai/gateway/router.py` 的真实路由行为一致。
- [x] 禁用模型、禁用 Provider、健康异常和无默认模型均有可理解的页面状态；Provider 熔断继续由网关错误码处理。
- [x] 模型/路由列表在窄屏下采用响应式布局，不要求横向挤压。

### 6.4 可能涉及的文件

- [ ] `src/pages/ai/Models/ModelManagementTab.tsx`
- [ ] `src/api/ai.ts`
- [ ] `backend/ai/api/models.py`
- [ ] `backend/ai/gateway/router.py`
- [ ] `backend/ai/providers/registry.py`
- [ ] `backend/tests/ai/test_assistant_public_chat_routing.py`
- [ ] `backend/tests/ai/test_llm_001_037_multi_provider.py`

---

## 七、P1：Provider 多实例 UI 重构

### 7.1 推荐布局

- [x] 顶部只保留一套总览：Provider 总数、启用数、健康数、密钥配置数；不要在每张卡片里重复全局说明。
- [x] 多实例默认使用紧凑“列表 + 详情”主从布局：
  - [x] 列表列：名称、类型、启用状态、健康状态、数据区域、绑定模型数量、最近探测时间、主要操作。
  - [x] 详情区：Base URL、脱敏 API Key、超时、允许数据分类、绑定模型、最后测试结果。
- [x] 只有当前选中的 Provider 展开完整连接详情和测试结果，避免多个大卡片同时占满页面。
- [x] 当前版本支持名称/类型/端点搜索、区域/健康/类型/标签筛选，以及 Provider 数量增长后的服务端分页。
- [x] 保留“添加 Provider”主按钮，编辑、启停、删除、测试放在当前行和详情区。
- [x] 供应商类型使用短标签区分，移除每个实例的大面积强渐变。

### 7.2 交互和安全要求

- [x] 测试结果显示在当前 Provider 详情区，不再为每张卡片保留空测试区域。
- [x] 连接测试继续只发送最小探测请求，不带设备、配置或业务数据，并明确显示这一点。
- [x] API Key 只显示脱敏值；编辑时不回填旧 Key；新增或轮换 Key 的明文不进入日志、错误 toast 或页面详情。
- [x] 删除前继续读取删除预览并确认模型数、路由数引用；删除失败时保留页面状态。
- [x] 无 Provider、加载中、加载失败、无筛选结果和无权限状态分别设计。
- [x] 窄屏下优先保证名称、状态和主操作可见，长 URL 和错误码截断并提供 title/详情查看。

### 7.3 Provider 页面验收标准

- [x] 同时存在多个 Provider 时，用户可以在紧凑列表中比较名称、类型、状态和健康度。
- [x] 选中某个 Provider 后，能够查看完整连接详情并执行测试，不需要在多个大卡片之间寻找。
- [x] 失败测试可定位到当前 Provider、错误码和已有网关建议。
- [x] 页面不展示 API Key 明文，不因刷新、切换详情或错误处理泄漏敏感值。
- [x] 保持现有权限、确认、审计和安全网关行为不变。

### 7.4 可能涉及的文件

- [x] `src/pages/ai/Providers/ProviderManagementTab.tsx`
- [x] `src/api/ai.ts`
- [x] `backend/ai/api/providers.py`
- [ ] `backend/ai/providers/base.py`
- [ ] `backend/ai/security/gateway.py`
- [x] `src/pages/ai/Providers/ProviderManagementTab.test.tsx`
- [x] `backend/tests/ai/test_ai_admin_enhancements.py`
- [ ] `backend/tests/ai/test_provider_auth_failure_surface.py`
- [ ] `backend/tests/ai/test_provider_connection_security_fix.py`

---

## 八、跨模块质量门禁

### 8.1 前端与接口

- [x] 所有本轮 API 变化先更新 `src/api/ai.ts` 的类型和请求封装，再修改页面。
- [x] 本轮列表请求集中在页面数据层，展示区域不直接拼接底层请求细节。
- [x] Prompt、Provider、产品目录列表均处理 loading、首次空数据、筛选无结果、请求失败、权限拒绝和重试反馈。
- [x] 所有本轮筛选变化重置页码；服务端分页返回的 `total / page / page_size / total_pages` 与 UI 一致。
- [x] 保留中文/英文 i18n；本轮新增文案已抽取到 AI 管理国际化资源。
- [ ] 检查 1280px、1024px、768px 和手机宽度下的溢出、表格滚动、弹窗高度和操作可达性。

### 8.2 后端、安全与数据

- [x] 复用现有 AI RBAC、租户范围、审计和异常响应格式。
- [x] 不在响应、日志、错误详情或前端 state 中暴露 API Key、Token、SNMP community、私钥或未脱敏设备配置。
- [x] 所有外部 LLM 请求继续经过 AI gateway 和 Security Vault 脱敏；本轮没有新增直连 Provider 的业务路径。
- [x] 产品目录自定义主数据和 Prompt 生命周期字段分别通过 `m0193_knowledge_catalog_master_data.py`、`m0194_ai_prompt_lifecycle.py` 管理；迁移不改变官方审核种子边界。
- [x] 未以 SQLite 测试结果作为 PostgreSQL 兼容性证据；PostgreSQL-only scanner 通过。

### 8.3 验证命令

- [x] 前端全量测试：`npm run test:frontend -- --run`（49 个测试文件、181 个测试通过）。
- [x] TypeScript：`npm run lint`。
- [x] 生产构建：`npm run build`。
- [x] AI/知识库后端聚焦测试：Prompt 生命周期 4 个、Provider 增强 2 个、目录主数据 8 个，以及既有目录/知识库回归均通过。
- [x] 目录/目录主数据相关 catalog 和 knowledge 测试已运行；自定义主数据由 `m0193_knowledge_catalog_master_data.py` 提供迁移，Prompt 生命周期由 `m0194_ai_prompt_lifecycle.py` 提供迁移。
- [x] 仓库 PostgreSQL-only policy scanner：0 violation，通过。
- [x] 检查最终 diff 边界；保留工作区既有改动，不引入密钥、测试 token 或真实设备数据。

### 8.4 本轮验证记录

- [x] 登录后浏览器只读验收：已使用用户提供的管理员账号完成五个目标路由复核；`/ai/knowledge` 的 `02_commands/h3c` 返回 1 篇，`/ai/catalog` 的 Huawei 路径返回 3 个型号，`/ai/prompts` 显示 10 个模板，`/ai/models` 显示路由说明，`/ai/providers` 显示高级筛选和当前实例详情。运行日志无 error-level、5xx、重复 key 或阻断性可访问性警告。
- [x] 临时本地开发服务使用项目既有 `npm run dev` 启动，验收后已停止；未留下 `5310/5400` 监听进程。
- [x] 后端全量 `pytest backend/tests -q -p no:cacheprovider`：`1974 passed`、`0 failed`、`0 errors`、`26 subtests passed`，无失败。

## 九、最终交付检查

- [x] `/ai/knowledge`：主页面可选目录、导入可选目录、筛选结果真实变化。
- [x] `/ai/catalog`：层级分类可浏览、当前路径可见、只读边界清楚。
- [x] `/ai/prompts`：场景覆盖足够、模板内容可读、编辑/启停/版本历史/变量和输出可验证。
- [x] `/ai/models`：路由用途、优先级、当前生效模型、Provider 绑定和异常行为说明清楚。
- [x] `/ai/providers`：多实例可比较，详情按需展开，操作和安全信息不重复堆叠。
- [x] 关键路径有前端测试和后端契约测试，lint/build/全量 pytest 结果已记录。
