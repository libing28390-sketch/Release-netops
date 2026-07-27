# SNMP 凭据独立关联与安全回显

## 问题

资产编辑页把 SNMP 凭据放进了 SSH 普通凭据选择框。凭据中心里的 `snmpv2` 记录虽然已经保存了 `public`，但没有独立关联关系；同时，资产接口把 Community 加密后直接当普通表单值使用，编辑时既不会正确回显状态，空值保存还可能覆盖已有值。

## 修复

- 为 `physical_assets` 和 `devices` 增加独立的 `snmp_credential_id`。
- 资产页面新增 SNMP 凭据选择框，SNMPv2 凭据不再出现在 SSH 普通/特权凭据列表中。
- SNMP 绑定不会修改 SSH 的 `credential_id` 或 `admin_credential_id`。
- Community 不向前端返回明文或密文，只返回 `snmp_community_set`；编辑页显示“已安全存储，留空保持不变”。
- 编辑资产时 Community 为空表示保持已有值，不再误清空。
- 采集解析优先使用独立 SNMP 凭据，其次才使用资产本地 Community或兼容的旧 SSH 凭据字段。

## 数据核验

当前数据库中 `snmp-community` 凭据的类型是 `snmpv2`，Community 解密值为 `public`，但设备关联数为 0；这正是页面无法在资产上体现该凭据的原因。

数据库迁移：`m0040_add_snmp_credential_binding`。
