# Nexora 真实浏览器验收记录

> 验收日期：2026-07-28
>
> 环境：本地前端 `http://127.0.0.1:5400`，本地后端端口 `5010`
>
> 数据库：PostgreSQL 18.4 / `netops`
>
> 账号：使用用户授权的管理员账号；密码未写入本文件、源码、截图或日志。

## 验收结果

| 指标 | 结果 |
| --- | ---: |
| 一级模块 | 11 |
| 二级页面 | 62 |
| 成功进入业务页面 | 62 |
| 真实截图 | 62 |
| 应用错误页 | 0 |
| 登录页误截 | 0 |
| 未完成加载 | 0 |
| 页面级横向溢出 | 0 |

## 分模块结果

| 模块 | 页面数 | 结果 | 截图目录 |
| --- | ---: | --- | --- |
| 实时监控 | 6 | 6/6 通过 | [`images/realtime`](./images/realtime/) |
| 终端接入 | 2 | 2/2 通过 | [`images/terminal-access`](./images/terminal-access/) |
| 告警处置 | 4 | 4/4 通过 | [`images/alerts`](./images/alerts/) |
| 资产与配置 | 7 | 7/7 通过 | [`images/assets-config`](./images/assets-config/) |
| CMDB 基础数据 | 10 | 10/10 通过 | [`images/cmdb-group`](./images/cmdb-group/) |
| IPAM | 7 | 7/7 通过 | [`images/ipam-group`](./images/ipam-group/) |
| 配置管理 | 5 | 5/5 通过 | [`images/config-mgmt`](./images/config-mgmt/) |
| 自动化 | 9 | 9/9 通过 | [`images/automation`](./images/automation/) |
| 工单管理 | 7 | 7/7 通过 | [`images/tickets`](./images/tickets/) |
| 容量与报表 | 2 | 2/2 通过 | [`images/capacity`](./images/capacity/) |
| 平台管理 | 3 | 3/3 通过 | [`images/management`](./images/management/) |

62 个页面的路由、功能文档、用户指南和逐页截图一一对应关系见 [`MODULES_OVERVIEW.md`](./MODULES_OVERVIEW.md)。

## 验收方法

1. 在真实本地页面输入授权账号并完成登录；
2. 按 `navConfig.ts` 的 62 个真实路由逐页直达；
3. 等待页面主标题、数据区和异步面板完成渲染；
4. 检查当前 URL、页面标题、主标题、登录态、错误页、加载状态和文档宽度；
5. 在确认页面处于业务态后保存浏览器视口截图。

拓扑页面和 Prefix、IP 地址、利用率三个 IPAM 页面存在较长的异步初始化，首次截图未计入结果；验收时延长等待并在主标题与数据面板完成加载后重新截图。

## 真实性与边界

- 截图来自实际运行页面，不是设计稿、合成图或静态占位图；
- 未触发批量改密、设备配置下发、工单实施等高风险写操作；
- 页面出现“无数据”时保留真实空状态，不伪造业务记录；
- 登录密码未进入仓库或报告；
- 浏览器验收不替代后端测试、生产构建和 PostgreSQL 校验，完整质量结论见 [`TEST_REPORT.md`](./TEST_REPORT.md)。
