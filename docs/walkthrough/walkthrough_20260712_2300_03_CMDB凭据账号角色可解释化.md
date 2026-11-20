# CMDB 凭据账号角色可解释化完成记录

## 完成摘要

本轮完成了凭据中心“用户名看起来有时是 user、有时是 admin”的可解释化改造。

核心结论：凭据中心原先展示的 `username` 是实际登录用户名，不是账号角色。由于设备创建、资产创建和双账号回填链路历史上对 `username`、`normal_username`、`admin_username` 的选择优先级不同，所以凭据表中会出现不同的真实登录用户名。

本轮没有修改数据库结构，也没有触碰明文密码、密钥或 SNMP community，只增加了后端派生字段和前端只读展示。

## 实际修改文件

1. `backend/services/credential_service.py`
   - 新增 `account_role` 和 `account_role_label` 派生字段。
   - 根据绑定设备的 `normal_username`、`admin_username` 推断凭据账号角色。
   - 保持关联设备公开返回最小化，仅返回 `id`、`hostname`、`ip_address`。

2. `src/pages/CmdbManagementTab.tsx`
   - 凭据中心新增“账号角色 / Account Role”只读列。
   - 新增角色徽标展示：
     - 普通账号
     - 管理员账号
     - 登录账号
     - 多角色
     - 未关联

3. `docs/plans/plan_CMDB凭据账号角色可解释化.md`
   - 记录本轮实施计划。

## 关键实现说明

### 账号角色推断

后端推断规则如下：

| 条件 | 派生值 | 展示 |
|---|---|---|
| 凭据未绑定设备 | `unbound` | 未关联 |
| 凭据用户名匹配设备 `admin_username` | `admin` | 管理员账号 |
| 凭据用户名匹配设备 `normal_username` | `normal` | 普通账号 |
| 无法匹配普通/管理员账号字段 | `login` | 登录账号 |
| 一个凭据被多台设备引用且角色推断不一致 | `mixed` | 多角色 |

### 安全边界

- 不返回密码、enable 密码、私钥、SNMP community。
- 推断过程只读取已有设备账号名字段。
- `devices` 关联列表仍保持最小公开字段，避免额外扩大 API 暴露面。

## 验证命令与结果

### 后端语法检查

```powershell
python -m py_compile backend\services\credential_service.py backend\api\credentials.py
```

结果：通过。

### Diff 空白检查

```powershell
git diff --check
```

结果：通过，仅出现 Windows 换行提示。

### 前端 TypeScript 检查

```powershell
npm run lint
```

结果：未完全通过，但失败点是既有无关问题：

```text
src/pages/RackManagement/index.tsx(1163,21): error TS2322:
Type '(deviceId: string, newStartU: number) => void' is not assignable to type
'(deviceId: string, newStartU: number) => Promise<void>'.
```

该错误在本轮修改前已经存在，文件不属于本次凭据中心改造范围。

## 未执行验证及原因

- 未修复 `RackManagement/index.tsx` 的 lint 失败：该问题属于机柜管理页面既有类型问题，和本轮凭据中心改造无关。建议作为独立质量修复处理。
- 未新增数据库迁移：本轮仅增加派生字段，不需要 schema 变更。

## 剩余风险

1. 历史数据如果没有维护 `normal_username` 或 `admin_username`，凭据会显示为“登录账号”，这是保守推断。
2. 如果一个凭据被多台设备共享，且不同设备上同名账号角色不同，会显示为“多角色”。这不是错误，而是在提醒该凭据已经跨角色复用。
3. 当前仍是过渡方案。后续企业级模型建议把凭据账号角色正式模型化，例如引入设备凭据绑定表或账号用途枚举。

## 后续建议

1. 独立修复 `RackManagement/index.tsx` 的 Promise 返回类型问题，恢复全量 `npm run lint` 绿灯。
2. 继续执行 CMDB-002：明确 `physical_assets`、`devices`、`interfaces` 的字段权威边界。
3. 后续凭据模型建议演进为：
   - 凭据实体只表示密钥材料与登录方式。
   - 设备-凭据绑定关系表示用途，例如 `normal_login`、`privileged_login`、`snmp_ro`、`snmp_rw`。
