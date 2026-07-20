# 运行数据采集 SSH 错误分类修复计划

## 任务目标

修复设备运行数据采集与自定义命令接口在 SSH 认证失败、传输失败、超时、旧算法协商失败等可预期网络错误场景下统一返回 `500 Internal Server Error` 的问题，使其与连接测试接口的 SSH 错误分类保持一致。

## 现状 / 问题

- `/api/devices/{device_id}/operational-data` 当前将非 `ValueError` 异常统一包装为 500。
- `/api/devices/{device_id}/parsed-command` 当前也将 SSH 类异常统一包装为 500。
- 连接测试弹窗已经可以识别 `ssh_authentication_failed`，但运行数据采集接口未复用该分类，导致同一个设备认证失败在不同入口表现不一致。
- 用户截图中的场景显示 ICMP 与 TCP/22 均正常，SSH 阶段为认证拒绝，因此更合理的 API 返回应为 400 类业务/依赖失败，而不是服务端 500。

## 影响范围

- 后端 API：`backend/api/devices.py`
- 后端测试：新增聚焦 SSH 错误分类的单元测试
- 不修改设备配置、不修改凭据、不改变实际 SSH 连接逻辑。

## 拟修改文件

- `backend/api/devices.py`
- `backend/tests/test_device_operational_ssh_errors.py`
- `docs/walkthrough/walkthrough_运行数据采集SSH错误分类修复.md`

## 实施步骤

1. 在设备 API 中新增运行数据/命令采集专用 SSH 错误响应构造函数。
2. 复用 `get_ssh_error_code()` 与 `build_ssh_error_guidance()`，保持与连接测试入口一致的错误码。
3. 将运行数据采集接口中的 SSH 分类错误返回为 400，并携带：
   - `detail`
   - `error_code`
   - `guidance`
   - `raw_error`
4. 将自定义命令查询接口采用同样的错误分类逻辑。
5. 保持未知异常仍返回 500，避免掩盖真实服务端缺陷。
6. 新增测试覆盖：
   - SSH 认证失败返回 400 + `ssh_authentication_failed`
   - SSH banner/传输失败返回 400 + `ssh_transport_unreachable`
   - 未知异常不被误分类

## 验证计划

- `python -m py_compile backend/api/devices.py backend/tests/test_device_operational_ssh_errors.py`
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_device_operational_ssh_errors.py -q`
- `git diff --check`

## 风险与回滚思路

- 风险：前端若只读取 `detail`，仍可正常显示字符串；若后续读取 `error_code`，也有结构化字段可用。
- 风险：未知异常仍返回 500，不会被本次逻辑吞掉。
- 回滚：移除新增 helper，并恢复两个接口的原始 `raise HTTPException(status_code=500, ...)` 分支即可。
