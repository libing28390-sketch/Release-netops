# Guacamole RDP 配置请求契约修正

## 问题现象

在资产管理页面保存本机 RDP profile 时，后端返回 `protocol: Extra inputs are not permitted`，配置没有保存。

## 根因

前端把 `protocol` 同时放在请求路径和 JSON body。后端 `RemoteDesktopProfileInput` 使用 `extra="forbid"`，而协议由 URL 路径参数提供，因此拒绝该多余字段。另一个边界契约不一致是空 `rdp_domain` 被序列化为 `null`，后端 schema 要求字符串。

## 解决方案

- 从远程桌面配置 body 类型及序列化结果中移除 `protocol`，继续由路径参数确定协议。
- 把 RDP 域名输入规范化为字符串，未填写时提交空字符串。

## 实际修改文件

- `src/api/pamRemoteDesktop.ts`
- `src/pages/AssetManagement/components/RemoteDesktopProfileEditor.tsx`
- `docs/plans/plan_20261013_0958_01_Guacamole_RDP_VNC纳管.md`
- 本修复记录。

## 验证

- `npm run lint`：通过。
- `node node_modules/vite/bin/vite.js build --outDir $env:TEMP/nexora-guac-rdp-contract-20261013`：通过；构建输出在系统临时目录，没有覆盖仓库 `dist`。
- `git diff --check`：通过。
- GitHub Actions、远端部署和真实 RDP 登录/录像验收：待本次提交后执行。

## 未验证项与风险

真实 RDP 登录及录像仍取决于保存 profile 后目标账号认证成功；这份修复只对齐 API 请求契约，不改变凭据或 Windows 安全设置。VNC 端到端测试还需要用户指定运行 VNC Server 的目标资产。

## 回滚

回退本提交的前端 API 类型和 profile 序列化修改即可。资产站点与已绑定凭据是独立且已成功保存的数据，不受回退影响；此前失败的 profile 请求未写入配置。
