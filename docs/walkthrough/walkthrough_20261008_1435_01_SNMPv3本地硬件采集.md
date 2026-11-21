# SNMPv3 本地硬件采集完成记录

## 完成摘要

修复了已绑定 SNMPv3 凭据在 Nexora 本地采集链路中被识别为“未配置”的问题。凭据解析、只读 SNMP GET/WALK、规则驱动的硬件发现、定时样本采集及 SNMP 诊断端点现在都使用服务端绑定的 SNMPv3 profile。设备仍使用 Nexora 本地 collector 与本地规则，不要求在 Docker Compose 中部署 LibreNMS。

支持 `noAuthNoPriv`、`authNoPriv`、`authPriv`；认证算法支持 MD5、SHA-1、SHA-224、SHA-256、SHA-384、SHA-512；隐私算法支持当前凭据契约允许的 AES-128 与 DES。SHA-2 通过 puresnmp 插件扩展实现，按 RFC 7860 的截断长度生成 HMAC。无凭据、缺字段或不支持的算法会被判为无效配置，不会降级成空 community 或公共默认值。

浏览器仅提交设备 ID 和版本，密钥由后端从已绑定凭据解密，日志不打印 v3 秘钥，诊断响应不包含秘钥。旧客户端即使仍提交默认的 v2c，也会在设备已绑定 v3 profile 时使用绑定凭据。

## 实际修改文件

- `backend/services/vault_service.py`
- `backend/services/snmp_service.py`
- `backend/services/snmp_hardware_poller_service.py`
- `backend/services/snmp_hardware_probe_service.py`
- `backend/services/librenms_diagnostic_service.py`
- `backend/api/devices.py`
- `backend/puresnmp_plugins/auth/sha2_common.py`
- `backend/puresnmp_plugins/auth/sha224.py`
- `backend/puresnmp_plugins/auth/sha256.py`
- `backend/puresnmp_plugins/auth/sha384.py`
- `backend/puresnmp_plugins/auth/sha512.py`
- `src/components/SnmpMib/components/LiveWalkInspector.tsx`
- `src/components/SnmpMib/TemplateBindingModal.tsx`
- `src/components/SnmpMib/BuiltinPresetBindingModal.tsx`
- `backend/tests/security/test_collector_snmpv3_profile.py`
- `backend/tests/snmp/test_snmp_transport.py`
- `backend/tests/snmp/test_snmp_walk_api.py`
- `backend/tests/snmp/test_snmp_hardware_probe_service.py`
- `backend/tests/monitoring/test_snmp_hardware_poller_service.py`
- `backend/tests/monitoring/test_librenms_diagnostic_service.py`
- `backend/tests/monitoring/test_telemetry_orchestrator_execution.py`
- `src/components/SnmpMib/components/LiveWalkInspector.test.tsx`

## 关键实现

1. 凭据解析从设备绑定的 SNMP credential row 读取用户名、安全级别、算法、context 和解密后的密钥，并生成显式 `configured` / `configuration_error` 状态。
2. v3 profile 贯穿 scalar GET、WALK、typed/bulk WALK、接口健康采集和标准系统信息查询；硬件 poller 不再依赖 community 来判断 v3 是否配置。
3. 诊断与规则绑定的接口验证从服务端选择已绑定的安全 profile；不允许浏览器传入密钥，也不允许无绑定 profile 的手工目标使用 v3。
4. puresnmp 本身没有 SHA-2 认证插件，新增 SHA-224/256/384/512 插件，并验证算法映射、摘要长度与认证校验。
5. 前端增加 SNMPv3 Profile 选项和对应错误提示。版本选择不暴露任何认证或隐私密钥。

## 验证命令与结果

- `.venv\\Scripts\\python.exe -m pytest backend/tests/security/test_collector_snmpv3_profile.py backend/tests/snmp/test_snmp_transport.py backend/tests/snmp/test_snmp_walk_api.py backend/tests/snmp/test_snmp_hardware_probe_service.py backend/tests/monitoring/test_snmp_hardware_poller_service.py backend/tests/monitoring/test_librenms_diagnostic_service.py backend/tests/monitoring/test_telemetry_orchestrator_execution.py -q`：66 passed。
- `.venv\\Scripts\\python.exe -c "from puresnmp.plugins.auth import create; print([len(create(n).authenticate_outgoing_message(b'key',b'msg',b'engine')) for n in ('sha224','sha256','sha384','sha512')])"`（`PYTHONPATH=backend`）：输出摘要长度 `[16, 24, 32, 48]`。
- `npm run test:frontend -- src/components/SnmpMib/components/LiveWalkInspector.test.tsx`：3 passed。
- `npm run lint`：通过（`tsc --noEmit`）。
- `.venv\\Scripts\\python.exe scripts/validate_postgresql_only.py`：通过，0 violations。
- `git diff --check`：通过。
- 本次涉及的 Python 模块 `py_compile` 检查通过。

## 未执行验证与剩余风险

- 未在真实 SNMPv3 设备上验证网络连通性、代理端 ACL、用户权限、engine ID/time 同步和设备支持的具体算法组合；本次测试使用受控假客户端和本地加密插件。
- 未连接用户的 Ubuntu 主机、未读取或使用其登录凭据、未部署或重启服务。因此此提交仅说明源码和自动化测试已修复，目标机器仍需部署新版本后才能观察到变化。
- 设备需在 Nexora 中绑定有效 SNMPv3 profile。仓库 Dockerfile 已设置 `PYTHONPATH=/app/backend`，使 puresnmp 能发现本仓库 SHA-2 插件；自定义启动方式需保留等价配置。
- 若设备只支持 AES-192/256 或其他当前 profile 校验未列入的算法，会明确判为不支持；数据模型和 transport 当前按 AES-128/DES 范围实现。
- 无数据库 schema 变更；回滚本次代码变更即可恢复旧 transport，现有凭据和设备配置不需回滚。
