# SSH 连接测试加密凭据解析修复实施计划

## 任务目标

修复 `/api/devices/connect` 在 SSH 深度登录测试中可能把 `enc:v2:`/`enc:v1:` 加密凭据字符串直接传给 Netmiko/Paramiko 的问题，并移除日志中输出凭据值的安全风险。

## 现状问题

用户测试 ACC-SW2 SSH 登录失败，后台日志显示：

```text
pwd_val='enc:v2:...'
Error reading SSH protocol banner
```

这说明当前连接测试路径拿到的 `password` 仍是加密后的存储值，而不是解密后的真实密码。

同时日志中的 `pwd_val` 会暴露加密凭据材料，不符合项目安全要求。

## 影响范围

- `backend/api/devices.py`
- `docs/walkthrough/walkthrough_SSH连接测试加密凭据解析修复.md`

## 拟修改文件

1. `backend/api/devices.py`
   - 新增一个小型 payload 密码解析 helper。
   - 当 payload 中传入 `enc:v1:` 或 `enc:v2:` 时，先调用 `decrypt_credential` 解密。
   - `device_id` 场景优先使用已解析的设备凭据；payload 明文密码仍允许临时覆盖。
   - 删除 `pwd_val` 日志，只保留密码是否存在和长度，不输出凭据内容。

## 实施步骤

1. 检查 `/api/devices/connect` 调用链。
2. 修复 `_resolve_connection_target` 的 payload password 判断。
3. 移除敏感日志输出。
4. 运行后端语法检查。
5. 运行 diff 空白检查。

## 验证计划

1. `python -m py_compile backend/api/devices.py`
2. `git diff --check`

## 风险与回滚思路

- 风险低：只影响连接测试凭据解析，不改数据库。
- 明文临时密码仍可按原逻辑覆盖设备保存凭据。
- 回滚：恢复 `_resolve_connection_target` 中原始 password 选择逻辑即可。
