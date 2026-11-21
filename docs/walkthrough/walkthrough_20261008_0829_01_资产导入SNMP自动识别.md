# 资产导入 SNMP 自动识别执行记录

## 完成摘要

资产导入提交成功后，Nexora 现在会用该资产管理 IP 和已绑定的 SNMP 凭据读取 `sysObjectID`、`sysDescr`、`sysName`，通过本地 LibreNMS 识别规则解析厂商/平台，再尝试匹配 SNMP 指标 Profile。只有唯一、兼容、已验证且同时包含 CPU/内存定义的 Profile 才会自动绑定。识别失败、凭据缺失、匹配歧义或 Profile 未验证都只返回状态，不回滚已导入资产。

每台设备不需要单独部署或配置 LibreNMS 实例。现有 LibreNMS 原生采集运行时仍是另一条链路。

## 实际修改文件

- `backend/api/assets.py`：资产提交后调用身份识别，汇总每行结果；只对成功提交的设备执行。
- `backend/services/snmp_import_identification_service.py`：加载已绑定凭据、探测 SNMP 身份、检测规则/候选歧义、补齐空白身份字段，并绑定安全的指标 Profile。
- `backend/services/snmp_service.py`：新增 SNMPv3 标量 GET 传输。
- `backend/services/snmp_discovery_service.py`：向识别结果增加软件版本字段。
- `backend/requirements.txt`：增加 `puresnmp-crypto`，为 SNMPv3 AES/DES 提供隐私加密插件。
- `src/pages/AssetManagement/index.tsx`：显示自动识别、Profile 绑定和未完成原因。
- `backend/tests/configuration/test_asset_management_method_import.py`、`backend/tests/snmp/test_snmp_transport.py`：增加导入绑定、歧义保护、无凭据保护及 v3 传输回归。

## 关键行为

- 导入事务先提交，之后才探测；SNMP 超时不撤销资产。
- 不使用设备表默认的 `public` 作为探测凭据；必须有本次导入明确绑定的凭据或填写的 Community。
- 只填充空白的厂商、平台、型号和版本字段，不覆盖用户填写值；厂商冲突不绑定。
- 规则或 Profile 同分歧义时不猜；Profile 未验证、缺 CPU/内存定义或与资产字段不兼容时不绑定。
- SNMPv3 支持 noAuthNoPriv、MD5/SHA 认证及 AES/DES 加密。SHA-2 认证算法和非空 Context Name 当前明确回报不支持，不降级到 v2c。
- API 响应不包含 Community、认证密码或隐私密码；监控同步在自动绑定之后触发。

## 验证命令与结果

- `pytest backend/tests/configuration/test_asset_management_method_import.py -q`：11 项通过（基础完整导入回归）。
- `pytest backend/tests/configuration/test_asset_management_method_import.py -q -k 'auto_identifies_device or commits_asset_then_enrolls_with_bound_snmpv3_profile'`：2 项通过，覆盖当前自动绑定、Profile 歧义保护和 SNMPv3 导入状态。
- `pytest backend/tests/configuration/test_asset_management_method_import.py -q -k 'persists_web_only_management_method'`：1 项通过，确认无凭据时不使用默认 Community。
- `pytest backend/tests/snmp/test_snmp_transport.py -q`：4 项通过，包含 SNMPv3 SHA/AES 参数构造。
- `npm run lint`：通过，`tsc --noEmit` 退出码 0。
- `python -m py_compile`（修改过的 Python 文件）：通过。
- `git diff --check`：通过；Git 仅提示 Windows 工作区的 LF/CRLF 转换提示，没有空白错误。

## 未执行验证及剩余风险

- 没有对 `192.168.204.128` 或真实 AP 发起探测，也没有部署本次改动；SNMP 行为由 mock 回归验证。上线后还需要从资产导入结果确认实际识别/绑定状态，并在 Grafana 验证 AP/CPU/内存查询。
- 没有唯一且可执行的本地 Profile 时，设备会显示已识别但未绑定；这不会自动创建一个未经验证的 OID 模板。
- SNMPv3 SHA-2 与 Context Name 暂不支持自动探测。
- 回滚只需移除导入后的识别调用、UI 状态和 v3 依赖；若需要撤回已绑定结果，清空对应 `devices.snmp_metric_profile_id`，保留资产和原始人工字段。
