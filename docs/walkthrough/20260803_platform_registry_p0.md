# 2026-08-03 P0 PostgreSQL 验收 walkthrough

## 验收范围

本轮继续收口自定义平台、TextFSM、Playbook 权限和统一 Action Resolver。生产数据库和自动化验收口径均为 PostgreSQL；后端共享隔离夹具和平台注册专项均使用临时 PostgreSQL 数据库。

## 关键路径

1. `devices.platform_profile_id` → 当前 `PUBLISHED platform_release` → `platform_release_actions`。
2. 业务消费者调用 `execute_platform_action()`；绑定设备的未映射动作返回 `UNSUPPORTED_ACTION`，不回退到厂商直连。
3. Playbook 入队前校验目标设备的 tenant/site/device-group 范围，执行结果按版本、Release、命令和 Parser 追溯。
4. 输出保留历史明文已隔离，公开 API 不返回原始回显；敏感配置备份无加密能力时失败关闭。

## PostgreSQL 证据

- 现有开发库：迁移最新版本 `84`；重复迁移返回 `0`。
- 全新临时库：26 Action Definition、11 SYSTEM Profile、11 PUBLISHED Release、204 Release Action；两类 Playbook 历史明文计数均为 `0`。
- 约束：`fk_devices_platform_profile`、`fk_platform_profiles_current_release`、`ck_platform_releases_status`。
- 临时数据库已在验收结束后删除。

## 质量门禁

- `pytest backend/tests/platform_registry -q`: 35 passed
- `pytest backend/tests/vendor_audit -q`: 281 passed
- `pytest backend/tests -q`: 445 passed，25 subtests passed
- `pytest backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py -q`: 90 passed
- `npm run lint`: passed
- `npm run build`: passed；仅有 chunk size warning
- `python -m compileall`、`git diff --check`: passed

- `GET /api/platform-registry/migration/preview`: 只读返回旧平台绑定、未知平台和文件模板冲突；专项测试覆盖“报告冲突但不修改 devices”。

全量后端测试已在临时 PostgreSQL 会话库通过；当前仍不将 P0 功能清单标记为全部完成，是因为平台/模板写入及浏览器验收、完整资源权限矩阵、设备识别/绑定 API、迁移预览和首批国产厂商真实样例适配尚未收口，而不是质量门禁失败。

## P0 最终收口

- Connectivity 加载设备信息时已包含 `platform_profile_id`；绑定平台注册设备执行 ping/traceroute 会返回 `UNSUPPORTED_ACTION`，不再绕过 Resolver 进入任意命令执行。
- TextFSM 在线测试改用独立 Sandbox；Discovery 不持久化原始 CLI 回显，Inspection 持久化前脱敏，Playbook 输出继续使用加密、保留期和读取审计。
- 新增 `m0085_system_profile_adaptation_status`，国产 SYSTEM Profile 在缺少真实生产回显时标记为 `UNVERIFIED/MISSING`，不伪造样例或模板。
- 资源权限目录和推荐角色已落地，平台/TextFSM/Playbook 审批、发布、回滚使用资源级权限依赖。
- 最终 PostgreSQL 门禁：迁移版本 **85**；平台注册专项 **37 passed**；vendor audit **281 passed**；完整后端 **447 passed, 1 warning, 25 subtests passed**；Python compile、lint、build、diff check 全部通过。
- P0 已完成并通过质量门禁；`PLATFORM_REGISTRY_ENABLED=0` 默认策略保持不变，P1 开始建设 TextFSM 注册表开发、样例上传/测试和发布前回归闭环。

## P1 首片：TextFSM 注册表与平台识别

- TextFSM 模板开发已具备租户隔离、版本草稿、Sandbox 测试、字段契约校验、历史样例回归和 `DRAFT → IN_REVIEW → APPROVED → PUBLISHED → DEPRECATED` 生命周期；创建者不能自审，发布前必须通过测试。
- 测试样例使用密文保存并带保留期；密钥不可用时拒绝保存，列表接口只返回样例元数据。SYSTEM 模板不可直接编辑，可 Fork 为租户模板。
- 平台识别已支持声明式 contains/starts_with/ends_with/equals/regex、ALL/ANY、否定和置信度排序；同分返回识别冲突，不自动绑定。人工绑定校验租户及 Site/设备组作用域，并支持锁定防覆盖。
- 自动识别只执行连接驱动白名单中的 `show/display version`，原始识别回显只在内存中用于匹配，不写入普通记录也不返回给 API 客户端。
- 前端新增 `/automation/textfsm-registry` 独立开发页，提供草稿、字段契约、Sandbox 测试、加密样例上传和版本流转操作；原有 `/automation/textfsm` 兼容页保持不变。
- 新增 Pydantic 请求模型固定注册表、识别和绑定 API 的长度、编码与回显边界；`npm run lint` 和 `npm run build` 通过。
- 新增迁移：`m0086_parser_template_lifecycle_security`、`m0087_device_binding_scope_columns`。当前 PostgreSQL 平台专项 **45 passed**。
- P1 尚未全部完成：编辑器/Diff/浏览器验收、真实设备识别命令采集、完整资源矩阵及 Playbook/P2 健康度闭环仍在继续。

## P1 识别闭环补充

- 增加模板级历史样例回归 API：`POST /api/parser-templates/{id}/regression-test`，仅针对可变版本执行，沿用加密样例解密、Sandbox 和字段契约校验。
- 增加设备侧标准路由：`POST /api/devices/{id}/platform-detect`、`PUT /api/devices/{id}/platform-binding`；设备详情页提供自动识别、人工指定和人工锁定，锁定状态仍由后端阻止普通用户覆盖。
- `m0088_seed_domestic_platform_identification_rules` 已为 6 个国产平台写入清单关键字。开发 PostgreSQL 当前迁移版本为 **88**，规则计数分别为：中兴 5900/1800 `3/2`、锐捷 S6K/EG `2/2`、迪普/迈普 `2/2`。
- 本轮质量门禁：平台注册专项 **51 passed**、vendor audit **281 passed**、完整后端 **461 passed，1 warning，25 subtests passed**；`npm run lint`、`npm run build`、Python compile 和非 dist diff check 通过。已在已登录浏览器只读核验 TextFSM 注册表页面，未执行写入。
- 未完成项保持明确：编辑器语法高亮/行号与 Diff、真实设备在线采集、完整 Site/设备组资源矩阵、受控 Playbook 编辑、写入流程浏览器验收以及 P2 健康度闭环。

## P1 TextFSM 编辑器 Diff 补充

- 注册表开发页现已提供带行号的模板编辑区、基线版本选择、源码增删 Diff；大模板超出比较预算时使用线性逐行降级，避免浏览器卡顿。
- 解析结果 Diff 展示基线与当前版本的记录数、字段新增和字段移除；历史回归继续由后端统一执行加密样例、Sandbox 和字段契约校验。
- 本轮验证：平台注册专项 **51 passed**，完整后端 **461 passed，1 warning，25 subtests passed**；`npm run lint`、`npm run build`、compileall 和非 dist diff check 通过。
- 仍待完成：最新构建的浏览器交互验收、真实设备在线识别、完整 Site/设备组资源矩阵、受控 Playbook 编辑和 P2 健康度闭环。

## P1 Playbook 受控执行边界补充

- Playbook 定义校验现已限制阶段结构、Action 参数数量、重复次数和总步骤数：单个 Action 最多 32 个参数，重复最多 10 次，总步骤最多 200 个；原始命令和未知 Action 继续 fail-closed。
- Playbook 执行请求现已限制目标设备最多 200 台且不得重复，并限制并发 1-20、变量最多 64 个、`dry_run` 类型和 `commit_confirmed_ttl` 范围；错误码按具体失败原因返回并进入审计链路。
- 本轮 PostgreSQL/质量门禁：平台注册专项 **53 passed**；完整后端 **463 passed，1 warning，25 subtests passed**；`compileall`、`npm run lint`、`npm run build` 和非 dist diff check 通过。
- 本轮未宣称 P1 完成：条件/分支/通知步骤、受控 Playbook 编辑器、最新构建浏览器交互验收、真实设备在线识别、完整 Site/设备组矩阵以及 P2 健康度/失败闭环仍未收口。

## P1 Playbook 重复与分支语义补充

- `repeat` 不再只是定义校验字段：引擎会按 1-10 次实际展开受控 Action，并将展开后的执行次数计入 200 步上限。
- 新增受控 `branch` 选择器，条件只读取 Playbook 变量或设备安全元数据，使用固定比较操作符，不执行表达式、Python、Shell 或正则脚本；满足条件走 `then`，否则走 `else`，控制流最多 4 层。
- `notification`、审批等未落地步骤不会被忽略，当前会在结构校验阶段以 `UNSUPPORTED_STEP_TYPE` 拒绝，避免出现“界面显示成功但执行未发生”。
- 本轮 PostgreSQL/质量门禁：平台注册专项 **58 passed**，Playbook 专项 **17 passed**，完整后端 **468 passed，1 warning，25 subtests passed**；既有前端 lint/build 结果保持通过。
- 后续仍需收口通知/审批步骤、Playbook 版本编辑器、最新构建浏览器交互、真实设备识别、完整 Site/设备组矩阵及 P2 健康度失败闭环。

## P1 Playbook 通知步骤补充

- 受控步骤新增 `notification` 类型，仅接受标题、消息和固定级别；自定义 webhook、渠道配置、凭据和超长文本在结构校验阶段拒绝。
- 执行时只调用租户范围内的通知分发，Playbook 不接触 webhook/Secret；Dry Run 不发外部通知，执行结果仅返回状态、成功渠道数量和失败渠道名称。
- 通知失败记录 `PLAYBOOK_NOTIFICATION` 审计事件并使任务进入部分失败，但不触发设备配置回滚；未配置渠道按 `no_configured_channels` 记录。
- 本轮 PostgreSQL/质量门禁：平台注册专项 **61 passed**，Playbook 专项 **20 passed**，完整后端 **471 passed，1 warning，25 subtests passed**；compileall、前端 lint 和非 dist diff check 通过。
- 尚未完成：审批步骤、Playbook 版本编辑器、浏览器交互验收、真实设备识别、完整 Site/设备组矩阵及 P2 健康度/失败闭环。
