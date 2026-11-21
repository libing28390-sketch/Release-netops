# Grafana 子路径循环复查走查记录

## 完成摘要

初期表现像 Grafana 子路径导航问题：Nexora iframe 初始 URL 只有一段 `/grafana`，Nginx 首次返回 200，后续 `/grafana/grafana/d/...` 返回 404；`/grafana/` 和无参数仪表盘也会复现。禁用缓存仍循环，无痕窗口正常；普通窗口删除 `grafana_session` 后恢复，证明 Grafana 原生会话 Cookie 是这次重复跳转的触发因素，而不是 `orgId`、`kiosk` 参数或容器未启动。

用户授权后，服务器已在 2026-09-25 00:11 备份并启用 Grafana 子路径模式，Nginx 原样转发 `/grafana/`。`docker compose config -q` 和 `nginx -t` 成功，Grafana 与 Nginx 已重建，运行配置已核对。普通 Chrome 禁用缓存并强制刷新后仍循环；无痕窗口正常。用户删除普通窗口的 `grafana_session` 后，页面恢复。截图显示浏览器还有 `grafana_session_expiry` 和 Nexora 专用 `nexora_grafana_session`；故障由过期/旧的 Grafana 原生会话 Cookie 与 Auth Proxy 身份冲突触发，Nexora 会话无需清理。

## 实际修改文件

- `docker-compose.yml`
- `nginx/nginx.conf`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260925_0008_01_Grafana子路径循环复查.md`
- 本文件

## 关键实现说明

- Compose 与服务器保持一致：`GF_SERVER_SERVE_FROM_SUB_PATH=true`，Nginx `proxy_pass http://grafana_backend;` 原样转发路径；显式关闭 Auth Proxy 登录令牌 Cookie。
- Nginx 两个代理位置都设置空 `Cookie` 请求头；`/_grafana_auth` 仍从 `$cookie_nexora_grafana_session` 提取 Nexora 会话并作为 Bearer 交由后端 RBAC 校验，Grafana 收到的身份仍由可信 Auth Proxy 头提供。
- 服务器原配置备份时间戳为 `20260925-001156`。新增 Cookie 过滤尚待用户在服务器部署验证。

## 验证命令与结果

- 修改之前，路径配对候选的部署契约曾 5 passed，Compose YAML 解析与 `git diff --check` 曾通过；这些结果不覆盖本次新增的 Cookie 隔离改动。
- 线上只读检查：Grafana、Nginx、NetOps 容器健康；Grafana Auth Proxy 返回 204；Nginx 对首个仪表盘路径返回 200，对重复前缀路径返回 404；未带登录凭据时 Nginx 返回 401，认证边界仍生效。
- 服务器基础子路径试验：`docker compose config -q`、`nginx -t` 通过，容器重建后确认有效环境为 `GF_SERVER_SERVE_FROM_SUB_PATH=true`、有效代理指令为 `proxy_pass http://grafana_backend;`。普通浏览器清除 `grafana_session` 后恢复；无痕浏览器正常（用户报告）。

## 未执行验证及原因

- 本机没有 Docker/Nginx CLI；服务器校验与重建由用户按授权操作。
- 新增的 Nginx Cookie 过滤仍需按部署步骤应用；用户已通过删除单个 Cookie 恢复当前窗口。
- 按当前指令，本轮未运行测试或配置验证；服务器上的 Nginx 校验和重建待用户执行操作命令。

## 剩余风险与后续建议

- 缓存禁用无效、删除 `grafana_session` 即恢复，已由浏览器状态差异定位 Cookie 冲突；不要清除 Nexora 专用 `nexora_grafana_session`。
- 后续在服务器备份当前 Nginx 配置，在两个代理位置设置 `proxy_set_header Cookie "";` 并重建 Nginx；无须重建 Grafana。失败时恢复新增备份。
- 日志中的插件 `Unknown Plugin` 与 `context canceled` 出现在页面不断导航期间，不能据此判断它们是本次循环根因。SNMP exporter 配置重载时的 DNS 临时错误是另一条链路。
- 不删除 Grafana、PostgreSQL 或其他数据卷。回滚时仅恢复这次 Compose/Nginx 配对及文档/契约改动。

## 附加排查：接口流量图断点

- vmagent `/api/v1/targets` 曾报告 R3/R4 的 `generic_ifmib_interface_std` 因 SNMP exporter 请求超时而 HTTP 500；后续对 R3、R4 的接口模块直接探测都返回 HTTP 200，表明 SNMP 可用但有间歇性超时。
- 用户提供的近 30 分钟计数器摘要显示 R3 Et0/3 最大样本间隔 60 秒；R4 最大 120 秒，有两处 120 秒间隔。
- 将面板真实 PromQL 与去掉 `topk(10, ...)` 的表达式对照，结果完全相同：R3 所有接口/入出方向同时在 00:46:30–00:48:00 和 00:50:30–00:52:00 缺样，最大 90 秒；R4 所有接口/入出方向也同步缺样，最大 150 秒，并出现多段 90–150 秒间隔。
- 结论：`topk` 不造成断点，缺样来自目标级 SNMP 采集间断；这与 exporter timeout 证据一致。该间歇超时尚未修复，需另行采集对应时段 vmagent/exporter 错误与设备响应证据，再决定是设备 SNMP 响应、轮询负载还是 timeout 参数问题。
- 本次对照仅查询 VictoriaMetrics，不修改服务器。不要把 Grafana Cookie 隔离变更与 SNMP 采集问题混为同一根因。

## v1.0.9 发布提交与标签

- 发布提交 `0a8a96d3e5a14abf289503cc3510b0a54db7b653` 已推送到 `origin/main`。
- 按用户明确授权，已有的 `v1.0.9` 标签已强制更新。远端 annotated tag 对象为 `de230ddf2ab5c0a67840f96c821469b4f30f7be3`，peeled commit 为 `0a8a96d3e5a14abf289503cc3510b0a54db7b653`。
- `.github/workflows/release.yml` 会在 main/tag 推送时启动；本地只核实了 Git refs，没有检查异步工作流或制品发布结果。
- 发布前后本地未运行测试套件；提交差异的 `git diff --check` 通过。服务器尚未部署本地新增的 Cookie 隔离配置。
