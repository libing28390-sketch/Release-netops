# 登录后页面尺寸跳变整改记录

## 完成摘要

登录页根容器宽度由视口单位 `w-screen` 改为父容器单位 `w-full`，与登录后的应用壳保持一致，避免切换认证界面时因视口宽度计算差异产生横向尺寸跳变。

## 实际修改文件

- `src/components/LoginScreen.tsx`
- `docs/plans/plan_20261011_2009_01_login_layout_shift.md`
- `docs/walkthrough/walkthrough_20261011_2009_01_login_layout_shift.md`

## 关键实现说明

- 保留 `h-screen`、内边距、背景和表单布局，仅将根容器宽度改为 `w-full`。
- 登录成功仍由现有认证状态与路由流程切换到主应用，不改变登录接口或会话行为。

## 验证命令与结果

- 静态检查了登录根容器、应用壳及全局视口设置；`index.html` 使用 `width=device-width, initial-scale=1.0`，未发现程序化浏览器缩放逻辑。
- 已在浏览器确认登录成功并进入 `/dashboard`；当前仪表盘显示 221 台设备。
- 未运行测试、lint 或构建；用户未要求执行验证命令。

## 剩余风险与建议

- `w-full` 消除登录页与应用壳之间的宽度单位差异。实际显示器上的闪动幅度可能受浏览器滚动条样式影响，需由用户在本机重新登录后确认。
