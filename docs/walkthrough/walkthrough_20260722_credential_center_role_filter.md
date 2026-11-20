# 凭据中心角色与关联设备展示优化

## 本次变更

- 凭据新增 `account_role` 字段：普通账号、特权账号、通用账号、未指定。
- 资产手动绑定时，普通账号下拉框优先展示普通/通用凭据，特权账号下拉框优先展示特权/通用凭据；历史未分类凭据仍保留为兼容项。
- 凭据中心列表只返回前 5 台关联设备和总数，点击 `+N 台` 后再请求完整设备列表。
- 新建资产不再默认填入 SNMP Community `public`，改为可选空值；历史数据和后端兼容默认逻辑不受影响。
- 凭据中心表单不再维护 SNMP Community；该字段仅保留在资产/设备采集配置中。
- 特权角色的中文展示统一为“特权账号”，不再使用“管理员账号”。
- 资产导入模板保留 `绑定凭据`、`绑定特权凭据` 两列，示例 SNMP Community 也改为空。

## 验证记录

- `\.venv\Scripts\python.exe -m pytest backend/tests/test_credential_management_sync.py -q`：6 passed。
- `\.venv\Scripts\python.exe -m pytest backend/tests -q`：130 passed，2 个既有 `isolated_db` fixture 缺失错误，位于 `scheduled_jobs/test_outbound_expected_ip.py`，与本次变更无关。
- `npm exec tsc -- --noEmit --pretty false`：通过。
- `npm run build`：通过；仅保留 Vite 原有大 chunk 警告。
- 资产导入模板检查：服务器模板 38 列、网络设备模板 34 列，两个凭据字段存在，SNMP Community 示例为空。
