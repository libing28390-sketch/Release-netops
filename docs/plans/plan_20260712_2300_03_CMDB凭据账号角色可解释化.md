# CMDB 凭据账号角色可解释化实施计划

## 任务目标

在不改动数据库结构、不触碰明文密钥的前提下，解释并修复凭据中心中同类设备有时显示 `user`、有时显示 `admin` 的可理解性问题。

本轮目标不是重构完整凭据模型，而是先把当前 `credentials.username` 的含义从“看起来像角色”明确为“实际登录用户名”，并通过派生字段展示该用户名在设备双账号模型中的角色。

## 现状问题

1. 凭据中心当前展示 `credentials.username`，它是实际登录用户名，不是账号角色。
2. 历史创建链路存在不同优先级：
   - 设备接口链路通常按 `username -> normal_username -> admin_username` 写入凭据用户名。
   - 资产/双账号链路会根据 `auth_model` 和普通/管理员账号字段回填 legacy username。
3. 因此界面上看到的 `user`、`admin` 并非随机，而是不同设备保存到凭据表的真实登录用户名不同。
4. 用户无法仅从“用户名”列判断该账号是普通账号、管理员账号，还是历史单账号。

## 影响范围

- 后端：`backend/services/credential_service.py`
- 前端：`src/pages/CmdbManagementTab.tsx`
- 文档：`docs/plans/`、`docs/walkthrough/`

## 拟修改文件

1. `backend/services/credential_service.py`
   - 扩展凭据列表/详情返回，增加派生字段：
     - `account_role`
     - `account_role_label`
   - 扩展关联设备最小信息，但不返回任何密码、密钥、SNMP community。

2. `src/pages/CmdbManagementTab.tsx`
   - 凭据中心新增“账号角色”列。
   - 使用徽标展示：普通账号、管理员账号、登录账号、多角色、未关联。

3. `docs/walkthrough/walkthrough_CMDB凭据账号角色可解释化.md`
   - 记录实际修改、验证结果与剩余风险。

## 实施步骤

1. 检查凭据中心 API 与设备字段来源。
2. 后端根据绑定设备的 `normal_username`、`admin_username`、`auth_model` 推断账号角色。
3. 当前凭据关联多台设备且推断结果不一致时，标记为 `mixed`。
4. 无关联设备时标记为 `unbound`。
5. 前端新增只读展示列，不进入创建/编辑表单。
6. 运行后端语法检查、前端 lint 或说明已有无关失败。

## 账号角色推断规则

| 条件 | `account_role` | 展示 |
|---|---|---|
| 凭据未绑定设备 | `unbound` | 未关联 |
| 绑定设备用户名匹配 `admin_username` | `admin` | 管理员账号 |
| 绑定设备用户名匹配 `normal_username` | `normal` | 普通账号 |
| 绑定设备为单账号或无法匹配双账号字段 | `login` | 登录账号 |
| 多个绑定设备推断结果不一致 | `mixed` | 多角色 |

## 验证计划

1. `python -m py_compile backend/services/credential_service.py backend/api/credentials.py`
2. `npm run lint`
3. `git diff --check`
4. 如本地页面可用，打开 `/cmdb/credentials` 确认新增“账号角色”列。

## 风险与回滚思路

- 风险：派生角色依赖现有设备字段，如果历史数据没有填 `normal_username/admin_username`，会显示为“登录账号”。
- 风险：前端新增列可能使表格更宽，但不影响 CRUD。
- 回滚：删除后端派生字段与前端列即可，不涉及数据库迁移。
