# SNMP 资产导入模板规范化结果

## 完成摘要

统一了静态下载模板和前端后备模板中的凭据说明。网络设备表的字段明确为可选的 SNMPv2 凭据名称，静态样例不再预填虚构的 `snmp-ro`。Operator 下载模板时会从凭据中心生成 SNMPv2 名称下拉项，并通过隐藏工作表提供选项；SNMPv3、SSH 或无 Community 的凭据不会进入下拉列表。填写说明要求凭据名精确匹配、核实 `user-h3c`/`admin-h3c` 等 SSH 样例名称，并说明填写 SNMP 凭据时应清空 SNMP 社区名。说明页还标注重复资产会跳过、不会更新旧凭据绑定。

旧版“SNMP凭据（推荐）”等表头仍保留映射兼容。

## 实际修改文件

- `public/templates/asset_import_template.xlsx`
- `backend/api/assets.py`
- `backend/tests/configuration/test_asset_import_template.py`
- `src/pages/AssetManagement/index.tsx`
- `src/pages/AssetManagement/constants.ts`
- `src/pages/AssetManagement/constants.test.ts`
- `docs/plans/plan_20260923_2121_01_SNMP资产导入模板规范化.md`
- `docs/walkthrough/walkthrough_20260923_2121_01_SNMP资产导入模板规范化.md`

## 验证结果

- 使用工作区表格工具导入、编辑、导出、重新导入并渲染工作簿；已目视检查网络设备表和填写说明页。
- XLSX 对比确认保留 6 张工作表、25 条原生数据校验、46 个命名区域、冻结窗格、筛选器及公式数量；网络设备示例的 SNMP 凭据名称已清空。
- `.\.venv\Scripts\python.exe -m pytest backend/tests/configuration/test_asset_management_method_import.py backend/tests/configuration/test_asset_import_template.py -q`：7 项通过，覆盖既有导入绑定、只生成当前 SNMPv2 下拉项、拒绝将类似公式的凭据名写成公式，以及没有 SNMPv2 凭据时返回可用模板。
- `npm run test:frontend -- --run src/pages/AssetManagement/constants.test.ts src/pages/AssetManagement/importUtils.test.ts`：2 个测试文件、19 项测试通过。
- `npm run lint`：通过。
- `npm run build -- --outDir C:/Users/NINGMEI/AppData/Local/Temp/asset-template-edit-01a0b8f8-304a-7941-a549-861656d17f77/build`：Vite 生产构建通过；构建产物中的静态后备模板与源文件 SHA-256 相同。
- `git diff --check`：本次 TypeScript 文件无空白错误。

## 未执行验证与剩余限制

- 没有运行全量后端测试；只运行了资产导入与动态模板相关的针对性测试。
- SNMPv3 资产导入能力未在本次范围内变更；静态模板和浏览器本地生成的旧版本后备模板也不含租户专属的下拉项，但都会明确标注准确的 SNMPv2 名称要求。
- 本次未部署到线上；生产环境需在发布后下载新模板验证。

## 工作区保护

本次只修改上面列出的模板、后端模板路由、前端生成逻辑和测试、协作文档。工作区中已有的拓扑代码和诊断文档未改动。
