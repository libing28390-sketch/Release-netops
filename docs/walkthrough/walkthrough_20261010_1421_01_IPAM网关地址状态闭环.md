# IPAM 网关地址状态闭环执行记录

## 完成摘要

- 前缀中合法且属于本 CIDR 的 `gateway` 地址现在会作为明确的网关占用项进入 IPAM 库存；若已有同前缀地址/发现记录，则在该记录上叠加网关标记，不重复造行。
- 列表与矩阵都能识别网关。未登记网关显示“前缀配置”并只读；矩阵显示绿色占用状态和 `GW` 标记，也不会将其列入空闲筛选。
- 前缀已用数和利用率将未重复计入的网关算作占用。`IP记录`、`自动发现`数量仍只统计实际库存/发现项目，另外显示“前缀网关”数。
- 矩阵按服务端分页信息加载全部数据；切换矩阵或网段会回到第 1 页，过期请求会被取消，加载失败时提供错误提示和重试。
- 没有修改数据库，也没有新增迁移。

## 实际修改文件

- `backend/services/ipam_service.py`
- `backend/services/ipam_inventory_scope.py`
- `src/pages/IPVlan/IPAddressTab.tsx`
- `docs/plans/plan_20261010_1421_01_IPAM网关地址状态闭环.md`

## 关键实现说明

- 增加前缀网关解析与使用量统计逻辑；只接受地址族匹配、落在网段内且不是 IPv4 网络/广播地址的网关配置。
- 前缀库存合并逻辑通过 `is_prefix_gateway` 和 `is_virtual_gateway` 明确区分派生网关、真实 IPAM 记录和自动发现记录。虚拟行继承前缀站点、网段、用途和已配置的网关设备信息。
- `/api/ipam/addresses` 的结果页数包含可见的派生行，摘要中的记录数单独排除虚拟网关，并增加 `gateways` 字段。
- `list_subnets`、IPAM 总览、利用率分析和前缀树共用同一占用口径，避免前缀表与 IP 页面各算各的。
- 页面禁止对虚拟网关编辑/释放；已有真实网关记录可编辑，但不能从地址表释放其网关占用，网关归前缀配置维护。

## 验证结果

- `python -m compileall -q backend/services/ipam_service.py backend/services/ipam_inventory_scope.py`：通过。
- `npm run lint`：通过（`tsc --noEmit`）。
- `node node_modules/vite/bin/vite.js build --outDir .codex-ipam-gateway-usage-build-20261010`：通过，处理 4319 个模块，输出与已有 `dist/` 隔离。
- `python scripts/validate_postgresql_only.py`：通过，0 项违规。
- `git diff --check`：通过；Git 仅提示若干已有工作区文件的 LF/CRLF 转换警告。
- 未运行 pytest 或其他测试用例；本轮按项目任务约束执行了类型检查、构建及静态检查。

## 浏览器与未执行项

- 在现有本地 IP 地址页面检查时，页面显示“加载 IP 地址库存失败，请重试”，因此本轮不能用实际数据端到端确认网关行和矩阵标记。浏览器使用的本地 API 当前不可用；没有启动后端，避免触发数据库初始化和后台任务。
- 未对部署服务器执行发布或数据变更。待本地/目标后端可用后，应复核 `10.200.7.0/24`：列表显示 `10.200.7.1` 和“前缀网关”，矩阵 `.1` 绿色且带 `GW`，前缀已分配数至少为 1。

## 风险与回滚

- 虚拟网关是只读展示视图，不会出现在 `ip_addresses` 表，也不会被计入 `IP记录` 或 `自动发现`；需要持久化接口/MAC/生命周期资料时仍需单独创建真实 IPAM 记录。
- 同一地址按前缀身份分别派生，支持不同 VRF/租户和父子网段，不在全局按裸 IP 去重。
- 回滚时恢复上述两处后端库存/统计逻辑和 `IPAddressTab` 页面即可；没有数据回填或迁移需要逆向处理。
