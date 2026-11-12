# 完成摘要

- 按用户澄清后的目标，进入 IPAM 模块时默认落在“IP 地址”，并同时展开“IPAM 工作台”和“地址空间”两个导航分组；用户仍能手动折叠。
- `/ipam` 根入口改为 `/ipam/ips`；路由上下文的默认 IPAM 子页也改为 `ips`。
- 查到顶栏“IPAM地址管理”、首页 IPAM 卡片和命令面板入口此前直接跳到 `/ipam/locate`，绕过了根路径重定向；三处入口已统一改为 `/ipam/ips`。专用“IP 定位”菜单项和带 IP 参数的定位跳转仍保留原路径。
- 撤回了先前误解需求时对终端页“更多筛选”的默认展开改动；该筛选仍保持原来的默认折叠状态。
- IPAM 子导航原本已将“IP 地址”排在第一，未改动菜单顺序。

## 修改文件

- `src/pages/IPVlan/DiscoveredEndpointsTab.tsx`
- `src/App.tsx`
- `src/utils/routeContext.ts`
- `src/components/TopHeader.tsx`
- `src/pages/HomePage.tsx`
- `src/hooks/useCommandPalette.ts`
- `src/components/ModuleSubNav.tsx`
- `src/components/ModuleSubNav.test.tsx`（仅更新已有断言，未运行）
- `docs/plans/plan_20261112_1120_01_终端筛选默认展开与IPAM首页.md`

## 验证

- `npm run lint`（`tsc --noEmit`）：通过。
- `vite build --outDir %TEMP%/netsops-ipam-all-entrypoints-20261112`：通过；未覆盖工作区 `dist/`。
- `git diff --check`：通过；有工作树既有文件的 LF/CRLF 转换提示。
- 浏览器当前显示 `/ipam/ips`，IP 地址页为活动页，“IPAM 工作台”和“地址空间”均展开。
- 未运行 pytest/Vitest，未进行浏览器或部署环境复核。

## 范围说明

只调整 IPAM 导航初始展开状态和根路径默认页。不修改终端筛选默认值、接口请求、业务数据或数据库。未部署；现场服务需在后续部署后才会体现这些改动。
