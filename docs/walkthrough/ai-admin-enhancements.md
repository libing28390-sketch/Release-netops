# AI 管理中心后续增强交付记录

更新时间：2026-08-31（Asia/Shanghai）

## 交付结论

本轮完成了 AI 管理中心清单中暂留的七项增强：Prompt 生命周期与服务端列表、Provider 高级筛选与服务端分页、产品目录租户自定义主数据维护，以及本轮 AI 管理页面新增文案的中英文国际化抽取。

自动化验证已完成：后端最终全量为 **1974 passed、0 failed、0 errors、26 subtests passed**；前端为 **49 files / 181 tests passed**；TypeScript、PostgreSQL-only scanner、Python compileall、生产构建和 `git diff --check` 均通过。已使用用户提供的管理员账号完成真实浏览器登录，并复核五个目标路由的关键路径：知识目录 `02_commands/h3c` 返回 1 篇文档，产品目录 Huawei 路径返回 3 个型号，Prompt 列表显示 10 个模板，模型路由说明和 Provider 高级筛选均可见。

## 1. Prompt 生命周期增强

### 1.1 服务端契约

Prompt 列表在无筛选参数时继续返回旧数组格式，保证现有调用方兼容；传入任意搜索、筛选或分页参数时返回分页对象，避免前端拉取全量数据后 `filter + slice`。

主要接口：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/ai/prompts` | 服务端 `search`、`scene`、`enabled`、`page`、`page_size`；搜索覆盖 code、名称、场景、厂商、平台、正文和输出契约摘要 |
| POST | `/api/ai/prompts/{prompt_id}/copy` | 复制为新的 Prompt 资产；原资产和原版本不被改写 |
| PATCH | `/api/ai/prompts/{prompt_id}` | 保存 Prompt 元数据或正文；支持 `expected_version` 乐观并发校验和 `change_reason` |
| GET | `/api/ai/prompts/{prompt_id}/versions` | 查询不可变版本历史 |
| GET | `/api/ai/prompts/{prompt_id}/versions/compare` | 对比两个版本，返回字段变化和统一 diff |
| POST | `/api/ai/prompts/{prompt_id}/versions/{version}/restore` | 从指定版本追加一个新版本；不会回写或删除历史版本 |
| GET | `/api/ai/prompts/{prompt_id}/audit` | 分页读取生命周期审计；支持关键词检索 |

`m0194_ai_prompt_lifecycle.py` 为 Prompt 版本补充 `change_reason`、`change_type` 和 `restored_from_version`，并建立生命周期查询索引。审计快照只返回字段哈希、长度和版本元数据，不返回 system/user/output 正文，避免把提示词内容或敏感变量写进审计响应。

### 1.2 页面行为

- Prompt 列表支持搜索、场景筛选、启停状态筛选和分页；筛选变化会回到第一页。
- 复制、编辑、启用/停用、版本列表、版本对比、版本恢复和审计记录均在当前详情工作区内完成。
- 编辑和恢复要求填写修改原因；更新携带当前版本号，发生并发冲突时保留页面状态并提示重新加载。
- 恢复是追加版本操作，页面展示来源版本，不破坏历史调用记录。
- dry-run 继续只使用固定脱敏合成变量，变量校验、输出 Schema 校验和敏感值屏蔽保持不变。

## 2. Provider 高级筛选与分页

`GET /api/ai/providers` 支持以下服务端参数：`search`、`data_region`、`health_status`、`enabled`、`provider_type`、`tag`、`page` 和 `page_size`。搜索覆盖名称、类型、端点和数据区域；标签按 JSON token 精确匹配，避免 `prod` 误匹配 `production`。分页响应包含 `items`、`total`、`page`、`page_size`、`total_pages` 和 `facets`，其中 facets 为当前数据集的区域、健康状态、类型和标签选项。

无参数请求继续返回旧数组格式，兼容已有 Provider 读调用。API Key 仍只在服务端和详情中以脱敏形式出现，测试连接仍只发送最小探测请求；Provider 列表使用“列表 + 当前详情”的主从布局，避免多个实例同时展开大块连接信息。

## 3. 产品目录租户主数据维护

### 3.1 数据和迁移

`m0193_knowledge_catalog_master_data.py` 增加租户范围的自定义 Vendor、Product Family、Series、Model、Alias 主数据表、状态字段、组合唯一约束、层级外键和查询索引。官方审核种子继续由只读投影提供；自定义数据与官方数据在读取层合并展示。

### 3.2 接口和安全边界

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/api/knowledge/catalog/custom/models` | 创建租户自定义 Model，并按层级补齐或复用自定义父节点 |
| PATCH | `/api/knowledge/catalog/custom/models/{model_id}` | 更新自定义 Model；支持 `expected_updated_at` 乐观并发校验 |
| DELETE | `/api/knowledge/catalog/custom/models/{model_id}` | 软删除自定义 Model，保留审计和历史可追溯性 |

写操作统一经过 `knowledge_catalog` 权限、租户范围、必填文本校验、官方/自定义重复校验和审计记录。官方种子、官方 Alias 和官方层级不能通过这些写接口修改；删除不会物理清除历史行，也不会误删官方数据。

## 4. 中英文国际化

新增 AI 管理页面文案集中在 `src/i18n/aiAdmin.ts`，覆盖 Prompt、Provider、产品目录、模型路由和知识库管理，以及各页面的预览、状态、审计、分页、错误反馈和文件名。Prompt dry-run 合成变量、版本类型、审计事件、目录解析结果和模型路由状态也按当前语言渲染，不再依赖中文硬编码；当前引用键已完成中英文成对检查，无缺失键。

## 5. 验证记录

### 自动化门禁

| 门禁 | 结果 |
| --- | --- |
| `pytest backend/tests --collect-only -q -p no:cacheprovider` | PASS，1974 tests collected |
| `pytest backend/tests -q -p no:cacheprovider` | PASS，1974 passed、0 failed、0 errors、26 subtests passed，2674.95 秒（44 分 34 秒） |
| TestClient 正序 / 倒序 / seed=20260830 随机 | PASS，12 / 12 / 12 passed |
| `scripts/validate_postgresql_only.py` | PASS，0 violation(s) |
| `python -m compileall -q backend scripts tests` | PASS |
| `npm run test:frontend -- --run` | PASS，49 files / 181 tests |
| `npm run lint` | PASS |
| `npm run build` | PASS，4259 modules，41.58 秒 |
| `git diff --check` | PASS；仅 Windows LF/CRLF 转换提示 |

全量测试开始前确认无 pytest 进程、无 `nexora_pytest_*` 临时目录；全量结束后会话已终止，临时目录仍为 0。浏览器验收完成后已停止开发服务，5310/5400 无监听。

### 浏览器验收状态

已启动项目既有 `npm run dev` 并确认前后端分别监听 5310/5400，使用用户提供的管理员账号登录后完成以下只读冒烟：

- `/ai/knowledge`：全部目录为 269 篇；选择 `02_commands/h3c` 后显示 1 篇匹配文档，并出现 H3C / H3C Switches / Comware facet。
- `/ai/catalog`：Vendor → Family → Series → Model 层级可见；选择 Huawei 后显示 CloudEngine 6800 下的 3 个型号。
- `/ai/prompts`：显示 10 个模板，搜索框、场景/状态筛选、版本、审计、预览和编辑入口可见。
- `/ai/models`：Model Route 标题、路由用途、Provider、默认/生效模型、健康状态和 Fallback 信息可见。
- `/ai/providers`：区域、健康、启用状态、类型、标签等高级筛选可见；当前实例详情按需展开，API Key 保持脱敏。当前租户实际有 1 个实例，多实例主从布局由组件结构和自动化测试覆盖。

浏览器运行日志未发现 error-level、5xx、重复 React key 或阻断性可访问性警告；相关登录后接口返回 200。停止验收服务后确认 5310/5400 均无监听。登录前出现的 `/api/tags/definitions` 401 属于未认证阶段的预期响应，不影响登录后验收。

## 6. 关键文件

- `backend/ai/api/prompts.py`、`backend/ai/schemas/prompt.py`
- `backend/ai/api/providers.py`、`backend/ai/schemas/provider.py`
- `backend/api/knowledge_catalog.py`、`backend/services/product_catalog_service.py`
- `backend/database/migrations/m0193_knowledge_catalog_master_data.py`
- `backend/database/migrations/m0194_ai_prompt_lifecycle.py`
- `src/api/ai.ts`
- `src/i18n/aiAdmin.ts`
- `src/pages/ai/PromptCenter/PromptCenterTab.tsx`
- `src/pages/ai/Providers/ProviderManagementTab.tsx`
- `src/pages/ai/Catalog/ProductCatalogManagementTab.tsx`
- `src/pages/ai/Models/ModelManagementTab.tsx`
- `src/pages/ai/Knowledge/KnowledgeManagementTab.tsx`
- `backend/tests/ai/test_prompt_center_contract.py`
- `backend/tests/ai/test_ai_admin_enhancements.py`
- `backend/tests/catalog/test_cat013_catalog_management.py`
