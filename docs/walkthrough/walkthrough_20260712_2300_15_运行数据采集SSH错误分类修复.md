# 运行数据采集 SSH 错误分类修复完成记录

## 完成摘要

已修复运行数据采集与自定义命令接口在 SSH 认证失败、传输层失败等已知网络连接问题下返回 `500 Internal Server Error` 的问题。

本次用户截图中的现象属于：

- ICMP 正常
- TCP/22 正常
- SSH 认证被设备拒绝

因此应用侧现在会将此类错误归类为 `ssh_authentication_failed`，并返回 400，而不是 500。

## 实际修改文件

- `backend/api/devices.py`
- `backend/tests/test_device_operational_ssh_errors.py`
- `docs/plans/plan_运行数据采集SSH错误分类修复.md`

## 关键实现说明

### 1. 新增运行数据采集 SSH 错误响应构造

新增 `_build_device_operation_ssh_failure_response()`：

- 复用 `get_ssh_error_code()`
- 复用 `build_ssh_error_guidance()`
- 对已知 SSH 错误返回结构化 400 响应
- 对未知异常返回 `None`，由调用方继续按 500 处理

### 2. 运行数据采集接口错误分类

`/api/devices/{device_id}/operational-data` 现在在捕获异常后会先判断是否属于已知 SSH 错误：

- `ssh_authentication_failed`
- `ssh_transport_unreachable`
- `ssh_transport_timeout`
- `legacy_ssh_algorithms`

命中后返回：

- `detail`
- `error_code`
- `guidance`
- `raw_error`
- `operation`
- `device`

### 3. 自定义命令接口错误分类

`/api/devices/{device_id}/parsed-command` 采用同样逻辑，避免同一设备问题在不同入口表现不一致。

## 验证命令与结果

### 语法检查

```powershell
python -m py_compile backend/api/devices.py backend/tests/test_device_operational_ssh_errors.py
```

结果：通过。

### 新增单元测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_device_operational_ssh_errors.py -q
```

结果：`3 passed in 1.00s`

覆盖场景：

- SSH 认证失败返回 400 + `ssh_authentication_failed`
- SSH banner/传输失败返回 400 + `ssh_transport_unreachable`
- 未知异常不会被误分类

### 后端相关回归测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_device_operational_ssh_errors.py backend\tests\test_phase1_phase2_cmdb_ipam.py backend\tests\test_cmdb_phase1.py backend\tests\test_cmdb_phase3_crud.py -q
```

结果：`20 passed in 7.04s`

### 差异检查

```powershell
git diff --check -- backend/api/devices.py backend/tests/test_device_operational_ssh_errors.py docs/plans/plan_运行数据采集SSH错误分类修复.md
```

结果：通过；仅出现 Git 的 LF/CRLF 工作区提示，不影响代码逻辑。

## 未执行验证及原因

- 未对真实网络设备执行 SSH 登录重试：这会依赖现场设备账号、AAA/VTY 配置和网络状态，不适合作为自动化验证。
- 未修改设备配置：本次只修复应用错误分类，不处理设备侧账号或 AAA 策略。

## 剩余风险 / 后续建议

- 如果 Core-SW1 仍显示 `ssh_authentication_failed`，应用已经能正确分类；后续需要检查设备侧：
  - 凭据中心绑定的账号是否正确
  - 密码是否与设备当前本地用户一致
  - AAA 是否允许该账号通过 SSH 登录
  - VTY 是否启用了正确认证方式，例如 `login local` 或 AAA method list
- 前端后续可以基于 `error_code` 做更细粒度提示，而不是只展示通用错误。
