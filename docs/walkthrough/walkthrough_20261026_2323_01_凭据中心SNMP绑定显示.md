# 凭据中心 SNMP 绑定显示修复

## 结果

凭据中心之前只按 SSH 普通账号和特权账号字段汇总设备，遗漏 `snmp_credential_id`，所以 `snmp-ro` 的关联设备列显示为“—”。此前只读数据库核验发现 `snmp-ro` 被 15 条资产记录和对应的 15 条设备记录引用；这两组是同一批逻辑设备，并非 30 台。

修复后，列表和详情会读取设备及关联资产上的凭据字段，将 SNMP 关联显示为“SNMP 采集”角色和“采集”标签；关联资产没有设备记录时也会被计入。删除检查同样覆盖资产和设备引用，避免在使用中的 Profile 被误删。SNMP 关联不会进入 SSH 普通/特权凭据替换操作。

这解释了凭据中心截图为何显示未绑定，但不代表设备此前实际没有绑定 SNMP Profile。该界面缺陷本身也不会导致 SNMP 请求超时；`.10.254` 和 `.10.255` 的设备探测结果仍应按 SNMP 响应/Community 情况单独诊断。

## 修改文件

- `backend/services/credential_service.py`：列表、详情和在用计数包含设备/资产 SNMP 凭据关联；SNMP Profile 的角色固定标记为采集。
- `backend/tests/configuration/test_credential_list_batching.py`：覆盖列表与详情、设备从关联资产继承 SNMP 凭据、独立资产引用及删除保护。
- `src/pages/CmdbManagementTab.tsx`：显示 SNMP 采集角色和标签，屏蔽 SSH 凭据绑定操作。
- `src/pages/CmdbManagementTab.test.tsx`：验证管理员视图下 SNMP 标签不是普通/特权 SSH 绑定操作。

## 验证

- `.venv/Scripts/python.exe -m pytest backend/tests/configuration/test_credential_list_batching.py -q`：2 passed。
- `npm run test:frontend -- --run src/pages/CmdbManagementTab.test.tsx`：2 passed。
- `npm run lint`：通过。
- `node node_modules/vite/bin/vite.js build --outDir .codex-build-validation-credential-snmp-20261026`：构建通过，产物写入隔离目录。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过；Git 仅提示工作区 LF/CRLF 转换。

## 边界

本次没有更改任何资产/Profile 绑定值，没有读取或显示 Community 明文，也没有修改交换机配置。没有重启或部署运行中的服务；凭据中心页面需在应用加载此代码版本后才能看到新显示。
