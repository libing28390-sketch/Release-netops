# SNMP 高级 OID 厂商与自动识别

## 完成摘要

`/monitor/snmp-walk` 的高级 OID 查找现在始终显示资产导入模板中 `Vendor_Network` 的全部 41 个规范厂商，顺序和值均与 Excel 一致。选择私有 MIB 后，页面会把当前 CMDB 设备 ID 交给后端；后端只读获取 SNMP 系统身份信息，先查 LibreNMS 规则，再用 sysObjectID 映射和 sysDescr 作为回退。识别结果会自动筛选厂商；资产登记值与实测值冲突时提示冲突，识别失败时退回资产厂商并保留手动筛选。

自动识别接口限 Operator 及以上权限，按当前用户租户范围选择设备；SNMP 凭据只在服务端读取，响应不包含 community。MIB 列表和快速搜索都使用完整资产厂商目录作为许可范围。

## 实际修改文件

- `src/components/SnmpMib/MibNodeBrowser.tsx`
- `src/pages/SnmpWalkPage.tsx`
- `backend/api/devices.py`
- `backend/services/snmp_discovery_service.py`
- `backend/services/librenms_rule_service.py`
- `docs/plans/plan_20260924_2051_01_SNMP高级OID厂商自动识别.md`
- `docs/walkthrough/walkthrough_20260924_2051_01_SNMP高级OID厂商自动识别.md`

## 关键实现说明

- 前端复用资产管理的 `ALL_VENDOR_NAMES`，不再用“已有 MIB 数据的厂商集合”决定下拉选项。
- SNMP Walk 页面将已选 CMDB 设备的 ID 和资产厂商传给 MIB 浏览器；切换到私有 MIB 时自动识别并按观察到的规范厂商过滤。
- 后端通过已有资产查询和凭据解析逻辑获取目标，读取 `sysName`、`sysDescr`、`sysObjectID`。识别顺序为 LibreNMS 规则、企业 OID 前缀、sysDescr；未知结果明确返回，不会把资产登记值伪装成实测结果。
- LibreNMS 规则查询在缺少本地规则时调用现有规则初始化；该工作和数据库连接获取在工作线程执行，避免阻塞异步请求。
- 如果没有该厂商的 MIB 节点，筛选项仍保留并显示空结果。

## 验证命令与结果

- 对比 Excel `Vendor_Network`、后端 SNMP vendor registry：41 项、顺序完全一致，无遗漏或额外项。
- `python -m compileall -q backend/api/devices.py backend/services/snmp_discovery_service.py backend/services/librenms_rule_service.py`：通过。
- `npm run lint`：通过。
- `$buildOut = Join-Path $env:TEMP 'netsops-snmp-vendor-build-final-20260924'; npm run build -- --outDir "$buildOut"`：通过，4292 个模块转换，45.62 秒完成；输出未覆盖仓库 `dist`。
- `git diff --check`：通过。
- 实现过程中曾运行临时 MIB 浏览器组件测试，3 项通过；临时测试文件未保留在交付差异中。

## 未执行验证及原因

- 未对真实设备执行 SNMP 探测；本次没有使用设备凭据或发起真实网络访问。
- 未在实际部署数据库和 LibreNMS 源仓库环境中验证首次规则同步；规则读取复用现有服务，后端语法检查通过。

## 剩余风险与后续建议

- LibreNMS 规则首次同步可能需要后端能够访问现有规则源；若网络不可用，识别仍会尝试本地 sysObjectID/sysDescr 回退，无法判断时由用户手动选择资产厂商。
- 完整目录中的个别厂商在当前 MIB 仓库可能没有私有节点；这属于数据覆盖范围，目录仍与资产模板保持一致。
