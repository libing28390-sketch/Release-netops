# H3C Comware 路由查询修复 — 完成报告

## 完成摘要

修复了 H3C Comware V7 设备（AGG-SW1, 192.168.96.222）在自动化任务中执行 `display ip routing-table` 失败的问题。

**根因**：Playbook 引擎凭据解析优先选择低权限用户 `user`，该用户无权执行 `screen-length disable`，导致 Netmiko 无法禁用分页 → 长输出在 `---- More ----` 处暂停 → Netmiko 等不到提示符超时报错。

**修复方案**：
1. 调整凭据优先级为 `username > admin_username > normal_username`（与 automation.py 的 `auto` 模式一致）
2. 新增 `safe_send_command` 包装器，对 Comware 设备自动构造灵活的 expect_string，失败时回退到 timing 模式

## 实际修改文件

| 文件 | 变更 |
|------|------|
| [`ssh_compat.py`](file:///d:/netops/netsops-main/backend/drivers/ssh_compat.py) | +45 行：新增 `safe_send_command()` |
| [`operational_data_service.py`](file:///d:/netops/netsops-main/backend/services/operational_data_service.py) | 2 处 `send_command` → `safe_send_command` |
| [`inspection_service.py`](file:///d:/netops/netsops-main/backend/services/inspection_service.py) | 1 处 `send_command` → `safe_send_command` |
| [`ip_locator_service.py`](file:///d:/netops/netsops-main/backend/services/ip_locator_service.py) | 1 处 `send_command` → `safe_send_command` |
| [`engine.py`](file:///d:/netops/netsops-main/backend/api/playbooks/engine.py) | 凭据优先级从 `normal > username > admin` 改为 `username > admin > normal` |

## 关键实现说明

### safe_send_command 工作原理

1. **Comware 自适应 expect_string**：检测 `device_type` 包含 `hp_comware` 时，自动构造 `[<\[]?{base_prompt}[>\]]` 正则，同时匹配用户视图 `<prompt>` 和系统视图 `[prompt]`
2. **异常回退**：捕获 `Pattern not detected` / `Timeout` 异常后，自动回退到 `send_command_timing` 模式
3. **对非 Comware 设备**：透传到原始 `send_command`，零影响

### 凭据优先级修复

```diff
- dd['username'] = creds.get('normal_username') or creds.get('username') or ...
+ # username > admin_username > normal_username (auto mode)
+ for u_key, p_key in [('username','password'), ('admin_username','admin_password'), ...]:
```

## 验证命令与结果

```
$ python verify_creds.py
OLD playbook credential: username=user    # ← 旧逻辑选了低权限用户
NEW playbook credential: username=admin   # ← 新逻辑选了有权限的用户
```

## 未执行验证及原因

- 未能执行端到端 SSH 连接测试（测试脚本中硬编码的密码已变更，认证失败）
- 需要重启后端服务后在 UI 上重试 H3C 路由查询验证

## 剩余风险/后续建议

1. **重启后端验证**：需重启 FastAPI 服务使代码生效，然后在 `/automation/tasks` 重试 H3C 路由查询
2. **低权限场景**：如果业务需要用低权限账号连接 H3C 设备，建议在设备侧给 `user` 账号授予 `screen-length disable` 权限
3. **其他 Comware 设备**：修复覆盖所有使用 Netmiko `send_command` 的调用路径，对后续新增 Comware 设备同样生效
