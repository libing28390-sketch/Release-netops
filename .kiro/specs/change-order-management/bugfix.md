# Bugfix Requirements Document — change-order-management

## Introduction

变更工单管理 (`/change-orders/*`) 是平台核心审批流之一，涉及新建变更工单、个人待办、组内待办、我参与的、我的关注、全部工单、草稿箱等多个视图，以及"创建中 / 草稿 / 初审中 / 终审 / 实施 / 完成"的流转链路。当前功能在场景化命令模板、变更控制表、审批人去重与权限组校验、状态机一致性以及各视图过滤语义五个方向上存在明显缺陷，导致：

- 申请人可以自由手写命令提交审批，初审/终审人缺少"固定格式模板"作为审核抓手，审核质量难以保证；
- 没有"变更控制表"结构化字段或附件上传，实施阶段的"实施人/复核人/设备 IP/变更前准备/实施过程/实施后验证/业务验证/回退方案"无法归档，复盘与合规无据可查；
- 审批人相关的去重与权限组校验仅在创建接口部分路径生效，存在通过更新接口或阶段切换绕过的可能；
- 状态机里"创建中"与 `draft` 语义未对齐，被驳回后回到 `draft` 的旧评审信息未清理；
- 各 Todo / 参与 / 关注 / 草稿箱视图的过滤语义在代码实现和产品语义之间存在歧义。

本次 bugfix 覆盖上述 5 类缺陷，目标是在**不破坏现有已通过审批/实施/完成工单流转能力**的前提下，修复上述行为并把视图语义固化为可回归的契约。

## Bug Analysis

### Current Behavior (Defect)

#### 1.1 场景化命令模板未强制化
1.1 WHEN 申请人新建变更工单 THEN 系统默认将命令输入模式置为 `manual`（手工输入），允许申请人提交任意自由文本命令，没有强制要求选择场景化模板或配置模板作为命令来源。
1.2 WHEN 申请人提交一张使用手工命令的变更工单 THEN 系统在工单详情与审核界面中仅展示扁平的命令列表，不提供"场景 / 平台 / 变量 / 预检 / 执行 / 后检 / 回退"分阶段的结构化视图，初审/终审人无法基于固定格式快速审核。
1.3 WHEN 申请人在 `template` 模式下选中场景但未填必填变量或未生成可执行命令 THEN 后端 `commands_template` 快照仍然可能写入空 `preview.execute`，或者前端绕过校验仅用 `device.platform` 构造一个空 `scenario_id` 的模板（`ChangeOrderTab.tsx` 中 "Template mode but no scenario selected" 分支）。

#### 1.2 变更控制表字段与上传步骤缺失
1.4 WHEN 申请人创建或提交变更工单 THEN 系统没有"变更控制表"相关字段（变更时间、实施人、复核人、设备 IP、变更前准备、实施过程、实施后验证、业务验证、回退方案）的结构化录入入口，也没有变更控制表模板下载或表单生成步骤。
1.5 WHEN 申请人或实施人进入"实施"阶段 THEN 系统没有上传变更控制表文件（或附件）的接口、数据库字段或 UI 步骤，`ChangeOrderCreate` / `ChangeOrderUpdate` 模型中均不存在 `control_sheet_*` 或 `attachments` 字段，`change_orders` 表也未持久化该数据。
1.6 WHEN 工单流转到"完成"或"已回溯" THEN 系统没有将变更控制表作为强制归档件落入工单时间线，无法根据工单号检索对应的变更控制表记录。

#### 1.3 审批人去重与权限组校验缺陷
1.7 WHEN 被指派为初审人或终审人的用户的 `change_groups_json` 为空列表 THEN `_resolve_assignment_user` 中的 `if groups and 'initial_reviewer' not in groups` 判断因 `groups` 为假而被跳过，系统会把一个不属于任何审批权限组的用户接受为合法审批人。
1.8 WHEN 申请人通过 `PUT /api/change-orders/{order_id}` 更新已有工单，把 `assigned_initial_reviewer_id` / `assigned_final_approver_id` 改为自己或改成同一个人 THEN 系统直接接受并更新（`api_update_change_order` 路径只调用了 `_normalize_assignment_payload` 和 `_normalize_command_template_payload`，没有复用创建接口中的去重校验逻辑）。
1.9 WHEN 初审人在初审阶段通过 `POST /api/change-orders/{order_id}/transition` 将状态转为 `final_review`，并在 `body.assigned_final_approver_id` 中切换一个新的终审人 THEN 系统只根据 `users` 表读出 `username` 即写入 `updates`，没有校验该终审人是否与工单的初审人、申请人重复，也没有校验该终审人是否具备 `final_approver` 权限组及 `Administrator` 角色。

#### 1.4 状态机完整性与回流缺陷
1.10 WHEN 用户在产品界面看到"创建中"状态 THEN 后端并没有与之对应的 `creating` 状态，`ALLOWED_STATUSES` 只列出 `draft / initial_review / final_review / approved / implementing / completed / rollback_in_progress / rolled_back / rejected / failed / cancelled`，"创建中"对应的行为未明确定义，产品语义与系统状态脱节。
1.11 WHEN 工单从 `initial_review` 或 `final_review` 被驳回回到 `draft` THEN 系统只更新 `status` 与 `rejected_reason`，但不清理已有的 `initial_reviewer_id` / `initial_reviewer_username` / `final_approver_id` / `final_approver_username` / `result_detail.initial_review_at` / `result_detail.approved_at` 等字段，下一轮重新提交时审计链路与时间戳存在残留。
1.12 WHEN 工单处于 `rolled_back` / `rejected` / `completed` / `cancelled` 等产品预期的终态 THEN `ALLOWED_TRANSITIONS` 中这些状态未显式列为"无出边"的终态（缺失键），使得将来引入新状态时容易被错误地允许转出。

#### 1.5 各视图过滤语义不正确
1.13 WHEN 申请人查看"个人待办" (`my_todo`) THEN 系统将状态为 `approved` 的工单也计入申请人的待办，但 UI 文案仍为"待办"，没有明确表达"需要开始实施"，用户无法区分"需要我审核"和"需要我实施"。
1.14 WHEN 一张工单在创建时已指派了具体的 `assigned_initial_reviewer_id` 或 `assigned_final_approver_id` THEN 该工单在"组内待办" (`group_todo`) 中对同组其他成员完全不可见，产品语义是否如此未在任何文档/规则中固化。
1.15 WHEN 当前用户既是工单的 `requester_username`，同时又是 `assigned_initial_reviewer_username` 或 `assigned_final_approver_username`（历史数据或配置错误造成） THEN 该工单会同时出现在"我参与的"和其它视图中，且系统没有在 UI 或服务端去重提示。
1.16 WHEN 用户打开"草稿箱" (`my_drafts`) THEN 系统只按 `requester_username = ? AND status = 'draft'` 过滤，如果该用户的草稿在被驳回后状态变成 `rejected`（而不是退回 `draft`），草稿箱视图会把它丢失；产品语义上"被驳回的我自己的工单"应归到"个人待办"而非"草稿箱"，但这条规则未在需求层固化。

### Expected Behavior (Correct)

#### 2.1 场景化命令模板强制化
2.1 WHEN 申请人新建变更工单 THEN 系统 SHALL 默认将命令输入模式置为"模板模式"，要求申请人从场景库或配置模板库中选择一个模板，并禁止以空 `scenario_id` 且 `commands` 为空的方式提交非 `draft` 状态的工单。
2.2 WHEN 申请人提交使用模板模式的工单 THEN 系统 SHALL 将 `command_template` 快照（包含 `scenario_id` / `scenario_name` / `platform` / `variables` / `preview.pre_check` / `preview.execute` / `preview.post_check` / `preview.rollback` / `generated_at`）持久化到工单，并在工单详情/审核界面按"预检 / 执行 / 后检 / 回退"四阶段展示，初审人和终审人 SHALL 能在同一视图中看到模板名、平台、变量与各阶段命令。
2.3 WHEN 申请人在模板模式下必填变量缺失或模板渲染后 `preview.execute` 为空 THEN 系统 SHALL 拒绝提交（HTTP 400），错误信息需指出缺失的变量名或空渲染的场景，且不得回落到"用 `device.platform` 构造空 `scenario_id` 模板"的静默分支。

#### 2.2 变更控制表字段与上传步骤补齐
2.4 WHEN 申请人创建或编辑变更工单 THEN 系统 SHALL 提供"变更控制表"结构化字段录入入口，字段集至少包含：`change_time`（变更时间窗口）、`implementer`（实施人，用户 ID + 用户名）、`co_reviewer`（复核人，用户 ID + 用户名）、`device_ips`（设备 IP 列表）、`pre_check`（变更前准备，富文本/多行）、`execution`（实施过程）、`post_verify`（实施后验证）、`business_verify`（业务验证）、`rollback_plan`（回退方案）；工单提交到 `initial_review` 时上述字段 SHALL 必填。
2.5 WHEN 申请人或实施人进入"实施"阶段 THEN 系统 SHALL 提供变更控制表附件上传接口 `POST /api/change-orders/{order_id}/control-sheet`，接受常见文档格式（pdf / doc / docx / xlsx），持久化在工单的 `control_sheet_attachments` 集合中，并在审计事件（`change_order.control_sheet_uploaded`）和时间线中留痕。
2.6 WHEN 工单流转到 `completed` 或 `rolled_back` THEN 系统 SHALL 在工单详情页、时间线与导出视图中展示变更控制表的结构化字段与附件清单，并支持按工单号检索变更控制表。

#### 2.3 审批人去重与权限组校验补齐
2.7 WHEN 任意被指派为初审人或终审人的用户的 `change_groups_json` 为空列表 THEN 系统 SHALL 视为"未授权该审批权限组"，直接返回 HTTP 400 并提示"用户未加入 initial_reviewer / final_approver 权限组"，禁止将其作为审批人。
2.8 WHEN 申请人通过 `PUT /api/change-orders/{order_id}` 更新工单的初审人或终审人字段 THEN 系统 SHALL 复用创建接口的完整校验：`assigned_initial_reviewer_id != requester_id`、`assigned_final_approver_id != requester_id`、`assigned_initial_reviewer_id != assigned_final_approver_id`、以及权限组/角色校验，任一条不满足均返回 HTTP 400。
2.9 WHEN 初审人在 `initial_review → final_review` 的 transition 中通过 `body.assigned_final_approver_id` 切换终审人 THEN 系统 SHALL 校验该终审人：① 非 `requester_id`、② 非当前 `initial_reviewer_id`、③ 属于 `final_approver` 权限组且角色为 `Administrator`，任一条不满足均返回 HTTP 403 / 400 并保持工单原状态不变。

#### 2.4 状态机完整性与回流补齐
2.10 WHEN 用户在产品界面使用"创建中"概念 THEN 系统 SHALL 将"创建中"定义为"工单创建表单尚未提交到服务端"的前端态（不落库），并在文档与 UI 文案上把"草稿"明确区分为"已保存到服务端但未提交初审"的 `draft` 状态；状态流转文档中的六态 SHALL 对齐为：草稿 / 初审中 / 终审 / 实施 / 完成（+ 异常态 rejected / rollback_in_progress / rolled_back / failed / cancelled）。
2.11 WHEN 工单从 `initial_review` 或 `final_review` 被驳回回到 `draft` THEN 系统 SHALL 在同一事务中清理 `initial_reviewer_id` / `initial_reviewer_username` / `final_approver_id` / `final_approver_username` / `approver_id` / `approver_username` / `result_detail.initial_review_at` / `result_detail.approved_at` 等上一轮审批留痕字段，只保留 `rejected_reason` 以及时间线里的驳回事件。
2.12 WHEN 工单处于 `rolled_back` / `rejected`（重开后路径除外）/ `completed` / `cancelled` THEN 系统 SHALL 在 `ALLOWED_TRANSITIONS` 中将这些状态显式声明为空集（终态），任何 transition 到其它状态的请求 SHALL 返回 HTTP 400 "Invalid transition"。

#### 2.5 各视图过滤语义固化
2.13 WHEN 申请人查看"个人待办" (`my_todo`) THEN 系统 SHALL 在"个人待办"中区分两类条目：① 需要我审核的工单（我是指派的初审/终审人且 `status` 为对应阶段），② 需要我实施的工单（我是 `requester_username` 且 `status in ('approved','implementing','rejected')`），并在 UI 文案上分别展示"待我审核"与"待我实施"，后端 `my_todo` 查询 SHALL 返回这两类条目的并集。
2.14 WHEN 一张工单已指派具体 `assigned_initial_reviewer_id` 或 `assigned_final_approver_id` THEN 系统 SHALL 在"组内待办" (`group_todo`) 中对其他组员仅展示"未指派具体审批人"的工单，并在文档中把此语义固化为"组内待办 = 当前阶段审批人未指派且我在对应权限组"。
2.15 WHEN 当前用户既是工单的 `requester_username` 又是 `assigned_initial_reviewer_username` / `assigned_final_approver_username` THEN 系统 SHALL 在 `_resolve_assignment_user` 与 transition 校验中直接拒绝该组合（应与申请人不能审核自己的规则一致），从根源上避免视图重复出现。
2.16 WHEN 用户打开"草稿箱" (`my_drafts`) THEN 系统 SHALL 只展示 `requester_username = 当前用户 AND status = 'draft'` 的工单；被驳回的工单 (`status = 'rejected'`) SHALL 出现在"个人待办"而非"草稿箱"。

### Unchanged Behavior (Regression Prevention)

#### 3.1 工单生命周期与编号
3.1 WHEN 申请人保存一张状态为 `draft` 的工单 THEN 系统 SHALL CONTINUE TO 允许不指派初审人/终审人、不填命令地保存到草稿箱，并按 `BG + YYYYMMDD + 0001~9999` 规则生成 `order_number`。
3.2 WHEN 工单按 `draft → initial_review → final_review → approved → implementing → completed` 正常推进 THEN 系统 SHALL CONTINUE TO 按 `ALLOWED_TRANSITIONS` 允许每一步的状态变更，记录 `actual_start` / `actual_end` / 时间线事件。

#### 3.2 审批与实施阶段的既有权限
3.3 WHEN 当前用户是工单 `assigned_initial_reviewer_id` 且角色不是 `Viewer` THEN 系统 SHALL CONTINUE TO 允许其在 `initial_review` 阶段 transition 到 `final_review` 或 `rejected`。
3.4 WHEN 当前用户是工单 `assigned_final_approver_id` 且角色为 `Administrator` THEN 系统 SHALL CONTINUE TO 允许其在 `final_review` 阶段 transition 到 `approved` / `rejected` / `initial_review`。
3.5 WHEN 当前用户是工单 `requester_username` 或 `Administrator` THEN 系统 SHALL CONTINUE TO 允许其在 `approved` / `implementing` 阶段推进实施、标记完成/失败、触发回溯。
3.6 WHEN 当前用户是 `Administrator` THEN 系统 SHALL CONTINUE TO 允许删除任意工单（`DELETE /api/change-orders/{id}`）。

#### 3.3 视图与列表过滤的既有契约
3.7 WHEN 用户使用 `assignee` / `requester` / `search` / `priority` / `status` / `order_type` / `created_from` / `created_to` / `completed_from` / `completed_to` / `scheduled_from` / `scheduled_to` 任一查询参数 THEN 系统 SHALL CONTINUE TO 按现有语义过滤并分页返回。
3.8 WHEN 用户切换语言（中/英）查看"全部工单" / 详情 / 时间线 THEN 系统 SHALL CONTINUE TO 按既有字段（标题、描述、状态、优先级、目标设备等）正确展示，不因字段集新增而丢失原有字段。

#### 3.4 模板库、书签与自动化联动
3.9 WHEN 用户将工单保存为模板 (`POST /api/change-order-templates`) 或列表 / 查看 / 删除模板 THEN 系统 SHALL CONTINUE TO 按既有接口契约工作。
3.10 WHEN 用户对工单加/取消收藏 (`POST /api/change-orders/{order_id}/bookmark`) 或查询我的收藏 (`GET /api/change-orders-bookmarks`) THEN 系统 SHALL CONTINUE TO 返回正确的收藏集合。
3.11 WHEN 自动化执行页面通过 `GET /api/change-orders/validate-ticket/{order_number}` 校验工单 THEN 系统 SHALL CONTINUE TO 按 `approved / implementing` 状态 + 计划时间窗口的既有规则返回有效性。
