好问题。全新部署不会有这个问题——因为全新部署会从头执行 `CREATE TABLE IF NOT EXISTS`，新 schema 里已经有 `risk_level` 和 `risk_summary` 了。

但**已有数据库升级**时会有问题，因为 `CREATE TABLE IF NOT EXISTS` 对已存在的表不做任何事。我们刚才加的 `ALTER TABLE` 迁移逻辑就是为了处理这种情况。

让我全面扫一下，看看还有没有类似的"代码里用到但迁移逻辑里没有"的列：

Now I have all the information needed. Let me compile the complete analysis.

Now I have a complete picture. Let me compile the final analysis.

---

## 数据库 Schema 不一致分析报告

### 分析方法

1. 从 `database.py` 提取每张目标表的 `CREATE TABLE` 列 + 所有 `ensure_column` / `ALTER TABLE ADD COLUMN` 迁移列
2. 扫描 `backend/api/*.py` 和 `backend/services/*.py` 中的 INSERT/UPDATE/SELECT 语句
3. 对比找出"代码用到了但 schema 里没有"的列

---

### 各表 Schema 汇总

#### `pam_sessions`
**CREATE TABLE 列：** `id, request_id, asset_id, device_id, requester_username, access_level, login_username, connect_method, target_ip, target_port, status, connected_at, closed_at, close_reason, duration_seconds, command_count, recording_path, risk_level, risk_summary, session_token, token_expires_at, token_consumed, created_at, updated_at`

**ALTER TABLE 迁移新增：** `risk_level`, `risk_summary`（已在 CREATE TABLE 里，迁移是兼容旧库的）

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `pam_access_requests`
**CREATE TABLE 列：** `id, asset_id, device_id, requester_user_id, requester_username, access_level, reason, status, reviewer_username, review_comment, expires_at, created_at, updated_at`

**ALTER TABLE 迁移新增：** `session_id`（`database.py` 第 1782 行）

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `devices`
**CREATE TABLE 列：** `id, hostname, ip_address, platform, status, compliance, sn, model, version, role, site, uptime, connection_method, username, password, current_config, config_history, cpu_usage, memory_usage, interface_data, snmp_community, snmp_port, cpu_history, memory_history, temp, fan_status, psu_status, sys_name, sys_location, sys_contact`

**ALTER TABLE 迁移新增（ensure_column）：** `normal_username, normal_password, admin_username, admin_password, auth_model, normal_password_last_rotated, normal_password_expires_at, admin_password_last_rotated, admin_password_expires_at, enable_password_last_rotated, enable_password_expires_at, management_port, is_managed, takeover_error, asset_id, vendor, lifecycle_status, enable_password, priv_username, credential_source, vault_path, onboarding_status, onboarding_updated_at, password_last_rotated, password_expires_at, rotation_status, device_category, power_watts`

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `playbook_executions`
**CREATE TABLE 列：** `id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, phases_json, results_json, total_devices, success_count, failed_count, partial_count, created_at, updated_at`

**ALTER TABLE 迁移新增：** `platform, total_devices, success_count, failed_count, partial_count`（已在 CREATE TABLE 里，迁移是兼容旧库的）

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `execution_device_results`
**CREATE TABLE 列：** `id, execution_id, device_id, hostname, ip_address, status, error_message, phases_json, started_at, completed_at, duration_ms`

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `scheduled_jobs`
**CREATE TABLE 列：** `id, name, job_type, action_type, cron_expr, scheduled_at, device_scope, device_filter, commands, script_id, is_config, config_reason, enabled, status, approved_by, approved_at, last_run_at, last_run_status, run_count, created_by, created_at, updated_at`

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `change_orders`
**CREATE TABLE 列：** `id, order_number, title, description, order_type, priority, status, requester_id, requester_username, approver_id, approver_username, target_devices_json, commands_json, rollback_plan, risk_level, scheduled_start, scheduled_end, authorization_exempt, actual_start, actual_end, result_summary, result_detail_json, approval_token, rejected_reason, created_at, updated_at`

**ALTER TABLE 迁移新增（ensure_column）：** `initial_reviewer_id, initial_reviewer_username, final_approver_id, final_approver_username, assigned_initial_reviewer_id, assigned_initial_reviewer_username, assigned_final_approver_id, assigned_final_approver_username, command_template_json, authorization_exempt, approval_token, rejected_reason, control_sheet_json`

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

#### `physical_assets`
**CREATE TABLE 列：** `id, asset_type, asset_tag, serial_number, vendor, model, hostname, datacenter, rack, rack_unit, management_ip, business_ip, device_role, vlan, uplink_switch, uplink_port, status, purchase_date, warranty_expiry, department, notes, created_at, updated_at`

**ALTER TABLE 迁移新增（ensure_column）：** `vlan, uplink_switch, uplink_port, lifecycle_status, platform, connection_method, username, password, normal_username, normal_password, admin_username, admin_password, enable_password, auth_model, normal_password_last_rotated, normal_password_expires_at, admin_password_last_rotated, admin_password_expires_at, enable_password_last_rotated, enable_password_expires_at, credential_source, vault_path, requires_strict_audit, snmp_community, snmp_port, management_port, is_managed, takeover_error, u_height, planned_start_u`

**API 代码引用的列：** 全部在 schema 中存在 ✅

**结论：无问题**

---

### 总结

**所有 8 张重点表均未发现 schema 不一致问题。**

代码中引用的每一个列名，要么在对应表的 `CREATE TABLE` 语句中定义，要么通过 `ensure_column()` / `ALTER TABLE ADD COLUMN` 迁移语句补充。`database.py` 的迁移设计采用了"幂等 ensure_column"模式，能安全地为旧数据库补列，不会出现运行时 `no such column` 错误。

全部干净，没有其他类似问题。

---

**结论**

**全新部署不会有任何问题**，`CREATE TABLE IF NOT EXISTS` 会直接建出包含所有列的完整表。

**已有数据库升级也不会有问题**，`database.py` 用的是"每次启动自动检查并补列"的模式：

```python
# 每次启动时执行，幂等安全
pam_ses_cols = _table_columns(cursor, 'pam_sessions')
if 'risk_level' not in pam_ses_cols:
    cursor.execute("ALTER TABLE pam_sessions ADD COLUMN risk_level TEXT DEFAULT 'low'")
```

今晚的 `risk_level` 问题是个历史遗留——那两列是后来加进 `pam.py` 查询的，但当时忘了同步写迁移逻辑。现在已经补上了，以后不会再出现。

其他 7 张核心表（`devices`、`change_orders`、`physical_assets` 等）都有完整的 `ensure_column` 迁移覆盖，可以放心升级。