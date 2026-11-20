# IPAM 功能导航与地址空间联动预览

## 本次改动

- IPAM 菜单按“地址空间”“动态地址”“IPAM 工作台”分组，每组下的页面入口支持展开和收起。
- 地址空间下放置“网段、IP 地址、地址池、VIP”；动态地址下放置“DHCP 租约”；工作台下放置“利用率、IP 定位、IP 对账”。
- 移除 IPAM 内容区顶部的横向页面标签，页面入口统一从左侧模块子菜单进入。
- 从侧栏切换 IP 地址、地址池和 VIP 时保留 `prefix_id`。进入网段列表会清除旧网段范围。
- 地址池和 VIP 页面继续共享当前网段范围；地址池创建默认使用当前网段，VIP 列表和创建/编辑按网段 CIDR 与租户校验。
- IP 定位使用统一 IPAM 页面外壳，原有 URL 保留。
- 保留用户已有的 `EnterpriseWorkflowPanel` 移除改动。

## 主要文件

- `src/components/AppSidebar/navConfig.ts`
- `src/components/ModuleSubNav.tsx`
- `src/components/AppSidebar/index.tsx`
- `src/pages/IPAMManagementTab.tsx`
- `src/pages/IPVlan/IPPoolTab.tsx`
- `src/pages/IPVlan/VIPManagementTab.tsx`
- `src/components/AppMainContent.tsx`
- `backend/api/ipam.py`
- `backend/services/ipam_service.py`
- `backend/schemas/schemas.py`
- `src/hooks/usePageTitle.ts`

## 验证结果

- `npm run lint`：通过。
- `node node_modules/vite/bin/vite.js build --outDir .codex-ipam-collapsible-nav-build-20261010`：通过，处理 4319 个模块；输出目录与已有 `dist/` 隔离。
- `python -m compileall -q backend/api/ipam.py backend/services/ipam_service.py backend/schemas/schemas.py`：通过。
- `python scripts/validate_postgresql_only.py`：通过，0 项违规。
- `git diff --check`：通过。
- 未运行测试套件。

## 浏览器预览状态

本地 Vite 前端已启动，但当前开发后端 `127.0.0.1:15310` 未通过健康检查。浏览器因此显示登录页，无法在本轮验证 IPAM 菜单的实际交互；没有启动后端，以避免触发数据库初始化和后台任务。代码构建与类型检查通过。

## 数据与回滚说明

本次未增加数据库迁移。VIP 没有 `prefix_id` 外键，当前范围根据网段 CIDR 与租户推导。恢复页面顶部标签或旧侧栏配置即可回滚导航层变更；接口范围参数为可选参数，不影响不带参数的旧查询。
