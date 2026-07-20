# SSH 连接测试加密凭据解析修复完成记录

## 完成摘要

针对 ACC-SW2 SSH 深度登录测试失败的问题，完成后端连接测试路径修复和原因定位。

本次日志显示两个问题：

1. 后端连接测试拿到的 `password` 是 `enc:v2:` 加密存储值，没有被解析为真实密码。
2. Paramiko 报错 `Error reading SSH protocol banner`，说明 TCP/22 建立后目标没有正常返回 SSH banner。

本轮已修复第 1 个系统侧问题，并移除了敏感日志输出。

## 实际修改文件

1. `backend/api/devices.py`
   - 新增 `_resolve_payload_password`。
   - 当请求 payload 中传入 `enc:v1:` 或 `enc:v2:` 时，先调用 `decrypt_credential` 解密。
   - `device_id` 场景下，payload 明文密码仍可临时覆盖保存凭据；payload 加密值不再直接传给 SSH 驱动。
   - 删除 `pwd_val=...` 日志，改为只打印 `pwd_present` 和 `pwd_len`。

2. `docs/plans/plan_SSH连接测试加密凭据解析修复.md`
   - 记录实施计划。

## 关键诊断结论

### 系统侧问题

日志中出现：

```text
pwd_val='enc:v2:...'
```

说明 SSH 连接测试曾经把加密凭据字符串当作密码传入。这会导致后续认证失败，并且日志暴露了加密凭据材料。

### 设备/网络侧问题

用户界面显示：

```text
ICMP: reachable
TCP/22: reachable
SSH login: failed (读取 SSH 协议 Banner 失败)
```

本地只读 banner 探测结果：

```text
BANNER_PROBE_ERROR: Unable to read data from the transport connection...
```

说明测试端能连到 22 端口，但目标没有在超时时间内返回标准 SSH banner，例如：

```text
SSH-2.0-Cisco-...
```

因此这不是典型的账号密码错误。典型账号密码错误通常会先完成 SSH banner 和算法协商，然后返回 `Authentication failed`。

## 验证命令与结果

### 后端语法检查

```powershell
python -m py_compile backend\api\devices.py
```

结果：通过。

### Diff 空白检查

```powershell
git diff --check
```

结果：通过，仅出现 Windows 换行提示。

### 敏感日志残留检查

```powershell
rg -n "pwd_val|password!r|admin_password!r|normal_password!r|snmp_community!r|DEBUG CONNECT TARGET" backend -S
```

结果：未发现 `pwd_val` 或密码 repr 输出残留；仅保留脱敏后的 `DEBUG CONNECT TARGET`。

### SSH banner 只读探测

使用 TCP socket 连接 `172.16.255.12:22` 并等待 banner。

结果：TCP 建立后未收到 SSH banner，读超时/失败。

## 剩余风险

1. 系统侧加密凭据解析已修复，但 ACC-SW2 仍可能因为设备 SSH 服务、VTY/ACL、AAA、并发限制或中间安全设备策略导致 banner 不返回。
2. 如果设备 SSH 版本或算法过旧，后续可能从 banner 问题变成算法协商问题，需要再看新的错误码。
3. 如果修复后能进入认证阶段但失败，则再检查用户名、真实密码、enable secret 和设备 AAA。

## 建议下一步

1. 重启后端服务，让 `backend/api/devices.py` 的修复生效。
2. 重新测试 ACC-SW2 的 SSH 校验。
3. 如果仍是 banner 失败，在设备侧检查：
   - `show ip ssh`
   - `show running-config | section line vty`
   - `transport input ssh`
   - `access-class` / ACL
   - AAA 登录策略
   - VTY 会话占满或安全设备限速/拦截
