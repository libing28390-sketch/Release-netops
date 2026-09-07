# 资产导入 SNMP 凭据绑定 Walkthrough

## 完成摘要

资产导入模板现在支持通过 SNMP 凭据名称或凭据 ID 绑定 SNMP 凭据，并且有限选项已经配置为 Excel 原生下拉校验。管理入口新增 `Web管理` 选项，可按端口默认生成 HTTPS/443 或识别 HTTP/80；原有“SNMP 社区名 + SNMP 端口”导入方式继续兼容。

## 实际修改

- `backend/api/assets.py`
  - 增加 SNMP 凭据名称/ID 的统一解析与校验。
  - 创建、更新和批量导入共用绑定逻辑，仅允许当前支持的 SNMPv2 凭据且必须配置 community。
  - 更新接口先完成资产范围校验，再解析凭据名称，避免未授权请求探测凭据是否存在；名称与 ID 同时出现时以规范 ID 字段为准。
- `backend/tests/configuration/test_asset_management_method_import.py`
  - 覆盖名称绑定、非 SNMP 凭据拒绝、旧社区名兼容、缺失凭据拒绝等场景。
- `src/pages/AssetManagement/constants.ts`
  - 增加 `SNMP凭据`、`SNMP Credential`、名称/ID 别名映射；保留通用 `绑定凭据` 为 SSH 凭据。
- `src/pages/AssetManagement/index.tsx`
  - 导入预检增加 SNMP 端口范围、凭据名称与 ID 互斥、凭据与明文 community 互斥校验。
  - 导出优先输出凭据名称，接口只返回 ID 时回退输出 ID；备用模板和说明同步更新。
- `src/pages/AssetManagement/types.ts`
  - 增加可选 `snmp_credential_name` 字段。
- `src/pages/AssetManagement/constants.test.ts`
  - 增加 SNMP 凭据列标题和 Web 管理方式映射回归测试。
- `src/pages/AssetManagement/importUtils.ts`
  - 管理入口解析支持 `Web管理`/`Web Management`，默认映射为 Web 入口；端口 80 推断 HTTP，其余空端口默认 HTTPS/443。
- `src/pages/AssetManagement/importUtils.test.ts`
  - 增加通用 Web 管理入口解析及默认 HTTPS 的回归测试。
- `public/templates/asset_import_template.xlsx`
  - 在资产信息表追加 `SNMP凭据` 列，更新填写说明和参数参考。
  - 为资产类型、厂商、平台、状态、角色、设备分类、录入来源、投产状态、功能、区域、管理入口协议、启用状态和凭据模式增加原生下拉；端口和 U 高度增加数值范围校验。
  - 管理入口协议下拉包含 `SSH`、`Web管理`、`NETCONF`、`HTTP`、`HTTPS`、`NONE`。
  - 保留原有工作表、格式和已有列结构；模板中不写入真实或示例 community/凭据值。

## 使用行为

1. 先在系统中创建 SNMPv2 凭据。
2. 在模板的 `SNMP凭据` 列填写凭据名称（也兼容 `snmp_credential_id` 等 ID 列名）。
3. 在 `管理入口` 的 `管理协议` 列直接选择 `SSH`、`Web管理`、`HTTP`、`HTTPS` 等选项；填写 `Web管理` 时留空端口默认 HTTPS/443，填 80 则按 HTTP 处理。
4. 导入资产。系统会把凭据绑定到 `physical_assets` 和 `devices`，后续设备绑定不再需要逐台手工选择。
5. 如果继续填写旧的 `SNMP社区名` 和 `SNMP端口`，仍按原流程导入；同一行不能同时填写凭据和明文 community。

模板列按表头名称识别，因此静态模板将新列追加到资产信息表末尾不会影响现有列读取或校验规则。

## 验证结果

- 后端集成测试：
  - `python -m pytest backend/tests/configuration/test_asset_management_method_import.py backend/tests/test_asset_credential_binding.py backend/tests/rackvision/test_asset_import_contract.py -q`
  - 结果：`16 passed`。
  - 修改更新接口授权顺序后重新运行配置导入测试：`5 passed`。
- 前端回归测试：
  - `npm exec vitest run src/pages/AssetManagement/constants.test.ts src/pages/AssetManagement/importUtils.test.ts`
  - 结果：`2 files passed, 11 tests passed`。
- TypeScript 检查：`npm run lint`，通过。
- 生产构建：`npm run build -- --outDir .codex-tmp/asset-template-build`，通过（4269 modules transformed）；构建输出写入临时目录，未覆盖用户已有的 `dist` 改动。
- Python 编译检查：`py_compile` 覆盖修改后的后端模块和测试文件，通过。
- `git diff --check`：无空白错误（仅报告仓库既有换行符提示）。
- 静态模板检查：5 个工作表保持不变；资产信息表为 41 列，包含 `SNMP凭据`；资产信息表包含 12 条数据校验，管理入口包含 4 条数据校验；协议选项包含 `SSH`、`Web管理`、`NETCONF`、`HTTP`、`HTTPS`、`NONE`；模板中未发现 `public` 或其他示例 community。

## 未通过/未执行项目

- `scripts/validate_postgresql_only.py` 仍返回 1 个既有违规：`backend/database/migrations/m0211_device_tenant_scope.py` 中的 `sqlite-pragma`。该文件未被本次修改，违规与资产导入功能无关，需单独清理或纳入临时基线。
- 未运行全量后端测试和真实设备联调；本次变更未触发数据库迁移，也未对真实设备、凭据或生产数据执行写操作。
- 未在桌面版 Excel 中逐项点击验证下拉；Artifact Tool 渲染和导出的 OOXML `dataValidation` 区域检查已通过，最终行为依赖 Excel/WPS 对原生校验的显示。

## 剩余风险与边界

- 当前资产导入链路与现有采集器只支持 SNMPv2 凭据；SNMPv3 凭据会被后端拒绝，未在本次需求中扩展协议能力。
- 导入前仍需先创建凭据；模板只携带名称或 ID，不携带密码、community 等秘密值。
- 新列按表头解析，第三方自行制作模板时应使用支持的列名（如 `SNMP凭据` 或 `snmp_credential_name`）。
