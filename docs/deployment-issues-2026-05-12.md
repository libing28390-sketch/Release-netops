# 问题记录 — 2026-05-12

> 记录当日开发过程中发现并修复的问题，供后续排查参考。

---

## 1. 首页应用卡片缺少"平台管理"

**现象**：下拉菜单（TopHeader）有 9 个应用，首页卡片只展示 8 个，缺少"平台管理"。

**根因**：`src/pages/HomePage.tsx` 的 `apps` 数组只定义了 8 个条目，漏掉了 `platform`（平台管理 → `/audit`）。

**修复**：
- 在 `HomePage.tsx` 的 `apps` 数组末尾补充 `{ id: 'platform', label: '平台管理', ... path: '/audit', ... }`
- 同步导入 `SlidersHorizontal` 图标

---

## 2. 用户个人资料缺少真实姓名、手机号、邮箱字段

**现象**：工单选人弹窗只显示登录名（如 `libing`），无法展示真实姓名和联系方式；搜索只支持用户名精确匹配。

**根因**：`users` 表没有 `display_name`、`phone`、`email` 字段；前端 `ProfileModal` 和用户管理表单也没有对应输入项。

**修复**：
- `backend/database.py`：`ensure_column` 新增 `display_name`、`phone`、`email` 三列
- `backend/api/users.py`：所有 SELECT/INSERT/UPDATE 语句加入三个新字段；`_hydrate_user_row` 返回新字段；`/session` 接口查询也加入新字段
- `src/types.ts`：`User` 和 `SessionUser` 接口加入 `display_name?`、`phone?`、`email?`
- `src/components/ProfileModal.tsx`：`ProfileFormState` 加三个字段；个人设置弹窗在"用户名"下方加一行三列输入框（真实姓名 / 手机号 / 邮箱）
- `src/App.tsx`：`openProfileModal` 初始化新字段；`handleSaveProfile` 提交时带上新字段
- `src/pages/UsersTab.tsx`：`UserFormState` 加三个字段；用户列表加"真实姓名"列（含手机/邮箱小字）；新建/编辑表单加三个输入框
- `src/hooks/useUserManagement.ts`：`createEmptyUserForm` 和 `handleEditUser` 加入新字段
- `src/pages/ChangeOrderTab.tsx`：选人弹窗（初审人/终审人）展示真实姓名+联系方式小字；搜索同时匹配 `display_name`、`phone`（输入"李"能匹配"李兵"，输入"lib"能匹配"libing"）

---

## 3. 前端开发服务器端口 4300 被 Windows 系统保留

**现象**：`npm run dev` 启动时报 `Error: listen EACCES: permission denied 0.0.0.0:4300`。

**根因**：Windows Hyper-V 将端口范围 4241–4340 保留，4300 在其中，Node.js 无法绑定。

**验证命令**：
```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

**修复**：`vite.config.ts` 中 `server.port` 从 `4300` 改为 `4350`（在保留范围之外）。

---

## 4. ARP 采集失败（No ARP entries collected）

**现象**：ARP 扫描日志显示 `No ARP entries collected`，IP 工具箱 ARP 表为空。

**根因（双重）**：

**根因 A**：`backend/services/operational_data_service.py` 的 `_build_connection_params` 函数在 2026-05-05 的提交（`e9f160a`）中引入了 `auth_role` 支持，但直接读取 `device_info.get('normal_password')` 或 `device_info.get('password')` 等字段，这些字段在数据库中是 `enc:v1:...` 加密字符串，没有解密就传给 netmiko，导致 SSH 认证失败。

**根因 B**：`_load_eligible_devices` 中的凭据检查只看 `creds['username']`（普通账号），对于 `auth_model='dual'` 的设备，普通账号可能为空，导致设备被过滤掉。

**修复**：
- `operational_data_service.py`：`_build_connection_params` 改为调用 `resolve_device_credentials(device_info)` 统一解密，不再直接读取加密字段
- `ip_locator_service.py`：`_load_eligible_devices` 检测 `auth_model`，dual 模式优先取 `admin_username` + `admin_password`；解析好的凭据存入 `_ssh_username`/`_ssh_password`/`_ssh_enable` 临时字段

---

## 5. ARP 采集速度从 ~2s 退化到 ~30s

**现象**：ARP 采集耗时从之前的约 2 秒变为约 30 秒（日志：`Collected 309 entries from 3 devices in 30.9s`）。

**根因**：`ubuntu-server2`（`linux` 平台）被纳入 ARP 采集，但 Linux 没有 `show ip arp` 命令，netmiko 连上去后等待超时（约 30 秒）。

**修复**：`ip_locator_service.py` 的 `_load_eligible_devices` 加入平台过滤，`linux`、`windows` 等服务器平台直接跳过，只采集网络设备的 ARP 表。

```python
_ARP_UNSUPPORTED_PLATFORMS = frozenset({
    'linux', 'linux_ssh', 'linux_telnet',
    'windows', 'windows_ssh',
    'paloalto_panos',
})
```

---

## 6. MAC 地址表采集未过滤路由器

**现象**：IP 定位时，MAC 地址表查询会尝试连接路由器，但路由器没有二层 MAC 地址表，浪费时间且可能超时。

**根因**：`locate_ip` 函数中 MAC 表查询的设备过滤逻辑只排除 `role='router'` 的设备，其他角色（firewall、gateway 等）仍会被查询。

**修复**：改为黑名单过滤，明确排除 `router`、`firewall`、`gateway`、`server`、`linux`、`windows` 角色的设备。

```python
_MAC_EXCLUDED_ROLES = frozenset({'router', 'firewall', 'gateway', 'server', 'linux', 'windows'})
switch_devices = [d for d in all_eligible if (d.get('role') or '').lower().strip() not in _MAC_EXCLUDED_ROLES]
```

---

## 7. 网络设备录入缺少设备分类和功率字段

**需求**：资产管理的网络设备录入需要"设备分类"（交换机/路由器/防火墙等）和"额定功率(W)"字段，用于机柜功率统计。

**修复**：
- `backend/database.py`：`devices` 表加 `device_category`（TEXT）和 `power_watts`（INTEGER）；`racks` 表加 `power_capacity_watts`；`device_types` 表加 `power_watts`（均通过 `ensure_column` 幂等迁移）
- `backend/api/devices.py`：CREATE/UPDATE SQL 加入 `device_category`、`power_watts` 两个新字段
- `backend/schemas/schemas.py`：`RackCreate`/`RackUpdate` 加 `power_capacity_watts`；`DeviceTypeCreate`/`DeviceTypeUpdate` 加 `power_watts`
- `backend/services/rack_service.py`：
  - `create_rack`/`update_rack` 传递 `power_capacity_watts`
  - `create_device_type`/`update_device_type` 传递 `power_watts`
  - `get_rack_layout` 返回 `power_used_watts`、`power_capacity_watts`、`power_utilization_pct`
  - `get_rack_stats` 汇总全局 `total_power_capacity_watts`、`total_power_used_watts`、`power_utilization_pct`
- `src/pages/AssetManagementTab.tsx`：`EMPTY_FORM` 加 `device_category`、`power_watts`；表单加"设备分类"下拉（交换机/路由器/防火墙/负载均衡/无线AP/其他）和"额定功率(W)"输入框
- `src/pages/RackManagementTab.tsx`：
  - `RackStats` 接口加功率字段
  - 机柜创建/编辑表单加"最大功率(W)"输入框（含说明：0 表示不限制）
  - 设备型号表单加"功率(W)"输入框
  - 顶部统计卡片展示全局功率利用率（有容量配置时才显示）
  - 机柜详情面板展示单机柜功率（>80% 红，>60% 黄，<60% 绿）

**机柜功率参考**：

| 机柜类型 | 常见功率上限 |
|---|---|
| 普通网络机柜（接入/汇聚交换机） | 2–4 kW |
| 标准服务器机柜（混合负载） | 4–8 kW |
| 高密度计算机柜（GPU/AI服务器） | 15–30 kW |
| 超高密度（液冷） | 50–100 kW+ |

**展示规范**（参考 NetBox/华为 iMaster）：进度条颜色 < 60% 绿，60–80% 黄，> 80% 红；显示格式 `已用 W / 容量 W (利用率%)`；当前实现为额定功率（铭牌值），实测功耗需后续对接 PDU SNMP 扩展。

---

## 8. .env 环境变量分离（开发 vs 生产）

**问题**：`.env` 中 `ENVIRONMENT=production`，本地开发时应为 `development`，两者混用导致本地看不到完整错误信息。

**修复**：
- 创建 `.env.local`（已在 `.gitignore` 中忽略），只写 `ENVIRONMENT=development`，其余配置继承 `.env`
- `backend/core/config.py`：`env_file` 改为 `(_ENV_FILE, _ENV_LOCAL_FILE)` 元组，`.env.local` 后加载优先级更高；新增 `IS_PRODUCTION`、`IS_DEVELOPMENT` 便捷变量
- `backend/database.py`：`load_dotenv` 同步加载 `.env.local`（若存在），与 `config.py` 加载顺序保持一致，避免两者读到不同的 `DATABASE_URL`

**说明**：
- 本地有 PG → 用 PG（`.env` 里的连接串生效）
- 部署服务器无 `.env.local` → 直接用 `.env`，`ENVIRONMENT=production`
- 不需要写入 README，部署脚本从 `.env.example` 生成 `.env`，天然是生产配置

**验证**：
```bash
python -c "import sys; sys.path.insert(0,'backend'); from core.config import settings; print(settings.ENVIRONMENT)"
# 本地输出: development
# 生产输出: production
```

**本地验证生产构建效果**：
```bash
npm run build && npx vite preview --port 4399
```

---

## 9. MAC 变更记录缺少分页和搜索

**现象**：IP 工具箱"MAC 变更"Tab 没有分页，数据量大时全部渲染，且无法搜索过滤。

**修复**：`src/pages/IPLocatorPage.tsx`
- 新增 `macFilter`、`macPage`、`macPageSize` state
- API 请求 `limit` 从 200 改为 1000（前端分页）
- 控制栏加搜索框（支持 IP/MAC/厂商/设备名模糊匹配）
- 表格渲染改为与 ARP 表一致的分页样式（使用 `Pagination` 组件）
- IP 列支持点击跳转到 IP 定位 Tab

---

## 10. 工单管理（change-order-management）Bugfix — Phase A–E

**背景**：工单管理模块存在 5 个缺陷簇（1.1–1.5），采用探索优先（先写测试暴露 bug，再修复）的方法论。

### 10.1 集群 1.3 — 审批人去重 / 权限组绕过

**现象**：
- POST 创建工单时，`change_groups_json=[]` 的用户可被指定为初审人（空组短路绕过）
- PUT 更新工单时，可将初审人改为申请人自己（PUT 路径缺少去重校验）
- transition 到 `final_review` 时，可将终审人设为申请人或初审人（transition 路径缺少权限组校验）

**根因**：`_resolve_assignment_user` 中 `if groups and 'initial_reviewer' not in groups` 的 `if groups` 短路；PUT 和 transition 路径未复用 `_validate_assignment_rules`。

**修复**：
- `backend/api/change_orders.py`：修正 `_resolve_assignment_user` 短路 bug；新增 `_validate_assignment_rules` 集中校验；三条写路径（POST/PUT/transition）统一调用
- 测试：`backend/tests/test_cluster_1_3_approver_dedup.py`（7 个测试全部通过）

### 10.2 集群 1.4 — 状态机终态 + 驳回回流字段清理

**现象**：
- `completed`/`rolled_back`/`cancelled` 等终态可被再次 transition（隐式空集，行为正确但不可见）
- 工单 `initial_review → rejected → draft` 后，`initial_reviewer_username` 等 6 个字段仍保留上一轮审批人信息

**修复**：
- `ALLOWED_TRANSITIONS` 显式声明终态为 `set()`，加模块级断言防止未来漂移
- `api_transition_change_order`：`new_status == 'draft'` 时清空 6 个审批人字段，并从 `result_detail` 中 pop `initial_review_at`、`approved_at`，保留 `rejected_reason`
- 测试：`backend/tests/test_cluster_1_4_state_machine.py`（4 个测试全部通过）

### 10.3 集群 1.1 — 场景化命令模板强制化

**现象**：提交非草稿工单时，`command_template={}` 或 `mode='manual'` 的工单被接受，初审人看不到可执行命令。

**修复**：
- 新增 `_validate_template_completeness`，要求 `mode='template'`、`scenario_id` 非空、`preview.execute` 非空
- 通过 `FEATURE_TEMPLATE_REQUIRED` 环境变量开关（默认 OFF，Stage 2 上线时开启）
- 前端 `ChangeOrderTab.tsx`：移除 `commandMode === 'template' && !scenarioId` 的静默回落分支；submit 按钮在无场景时禁用；四阶段命令预览（pre_check/execute/post_check/rollback）

### 10.4 集群 1.2 — 变更控制表字段与附件

**现象**：工单无变更控制表结构化字段，进入实施阶段无附件校验。

**修复**：
- `backend/database.py`：新增 `control_sheet_json` 列（`change_orders` 表）和 `change_order_control_sheet_attachments` 表
- `backend/api/change_orders.py`：新增 `POST /api/change-orders/{order_id}/control-sheet` 上传接口（MIME 白名单、20 MiB 限制、审计事件）；transition 到 `initial_review` 时校验 9 个结构化字段；transition 到 `implementing` 时校验至少 1 个附件
- 通过 `FEATURE_CONTROL_SHEET` 环境变量开关（默认 OFF）
- 前端：创建/编辑向导加"变更控制表"可折叠步骤；详情页展示控制表字段、附件列表、时间线特殊图标；CSV 导出包含控制表字段；历史工单显示 `control_sheet_missing` 提示横幅

### 10.5 集群 1.5 — 视图过滤语义对齐

**现象**：`my_todo` 无 `todo_kind` 标签；`group_todo` 与 `get_summary` 的 SQL 不同源；`my_drafts` 语义文档缺失。

**修复**：
- `change_order_service.py`：`my_todo` 返回行加 `todo_kind ∈ {review, implement, modify}`；`_build_group_todo_conditions` 共享函数同时供 `list_change_orders` 和 `get_summary` 使用；`my_drafts` 严格过滤 `status='draft'` 并加文档注释
- 前端 `ChangeOrderTab.tsx`：个人待办拆分为"待我审核 / 待我实施 / 待我修改"三个子 Tab（`FEATURE_TODO_SUBTABS=true`）

### 10.6 Phase E — Fix-checking PBTs（属性测试）

新增 7 个 fix-checking PBT 文件，覆盖 P1–P7 所有正确性属性：

| 文件 | 覆盖属性 |
|---|---|
| `test_pbt_p1_template_enforcement.py` | P1 命令模板强制化 |
| `test_pbt_p2_control_sheet_enforcement.py` | P2 控制表字段与附件 |
| `test_pbt_p3_approver_rules.py` | P3 审批人规则（POST/PUT/transition 三路径） |
| `test_pbt_p4_state_machine.py` | P4 状态机终态 |
| `test_pbt_p5_reject_cleanup.py` | P5 驳回回流字段清理 |
| `test_pbt_p6_view_contract.py` | P6 视图过滤契约 |
| `test_pbt_p7_preservation.py` | P7 保留性（BG 编号、RBAC、列表过滤、模板/书签/validate-ticket） |

### 10.7 Phase F — 集成测试

新增 `backend/tests/test_integration_18.py`，覆盖：
- 18.1 端到端主路径（initial_review → final_review → approved → implementing → completed）
- 18.2 驳回回流路径（rejected → draft → 重新提交 → completed）
- 18.3 跨视图一致性（4 个账号并发查询 my_todo/group_todo/my_drafts/my_participated）

### 10.8 Phase F — Feature Flags & 迁移脚本

- `backend/api/change_orders.py`：`FEATURE_TEMPLATE_REQUIRED`、`FEATURE_CONTROL_SHEET` 环境变量开关
- `src/pages/ChangeOrderTab.tsx`：`FEATURE_CONTROL_SHEET`、`FEATURE_TODO_SUBTABS` 前端开关
- `.env.example`：补充三个 feature flag 说明
- `backend/scripts/migrate_change_order_dual_role.py`：扫描并清理存量双角色脏数据（申请人 == 审批人），dry-run 默认，`--apply` 才执行

---

## 11. 临时调试文件清理

删除以下遗留的临时调试脚本和游离数据库文件：

| 文件 | 说明 |
|---|---|
| `write_test.py` | `print(42)` 测试文件 |
| `gen_test.py` | `x=1; print(x)` 测试文件 |
| `backend/check_executions.py` | 查询 instant_executions 的调试脚本 |
| `backend/check_results.py` | 查询 execution_device_results 的调试脚本 |
| `backend/debug_device.py` | 查询特定 IP 设备的调试脚本 |
| `backend/find_target.py` | 按 UUID 查找记录的调试脚本 |
| `backend/_check_audit.py` | 查询审计事件的调试脚本 |
| `netops.db` | 根目录游离 SQLite 文件（非 `data/` 目录） |
| `backend/netops.db` | backend 目录游离 SQLite 文件 |
| `backend/netsops.db` | 拼写错误的游离 SQLite 文件 |

保留：`_purge_bogus_backups.py`（有实际用途的运维脚本，清理损坏的配置快照）。
