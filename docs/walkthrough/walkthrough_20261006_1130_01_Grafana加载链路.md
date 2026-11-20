# Grafana 加载链路排查与 Nginx 调整

## 完成摘要
用户确认设备均为模拟器，并明确允许从 Nginx 配置优化。本轮已完成远端只读采样、前后端加载路径审查，以及本地 Nginx 的 HTTP/2 和上游连接复用调整。远端服务尚未修改；实际整页提速须应用配置后复测。

## 实际发现

| 层级 | 证据 | 判断与边界 |
| --- | --- | --- |
| 浏览器到入口代理 | 远端无凭证 TLS 协商：TLSv1.3，ALPN `http/1.1` | HTTP/2 尚未协商，可减少大量资源请求受浏览器 HTTP/1.1 连接并发限制的影响。未读取远端容器有效配置。 |
| Nginx 到认证服务 | 本地 `/_grafana_auth` 原未指定 HTTP/1.1，也未清空默认 Connection；真实 Nginx 隔离测试中两请求创建两条 TCP 连接 | 修正后两请求使用一条连接，仍执行两次认证。属于实际验证的连接复用改善，不能换算为远端加载秒数。 |
| Nginx 到 Grafana | 普通请求原恒发 `Connection: upgrade` | 按请求是否有 Upgrade 条件发送；旧配置在 mock 测试中已经复用主连接，因此不能声称此头部是主要耗时来源。 |
| 页面引导 | 页面 `POST session → GET health → iframe` 串行；冷启动 `useAuth` 另发一次 session bridge | 确定存在重复桥接与启动等待，本轮收敛到 Nginx，不修改前端。直接取消健康门槛会让错误 SPA 回退脚本运行，需单独设计。 |
| Grafana 变量 | 远端 JSON 模型有八个 query 变量，均在加载时刷新；最长链为 site→vendor→role→asset_id→hardware_group→sensor_name→component_class（七层） | 每次完整 iframe 导航会重走变量初始化；查询级联是启动成本。未取得每个变量实际耗时，不将层数乘面板耗时估算总时间。 |
| 模拟数据 | 功率图 518 条曲线、20,362 点，请求 2.28/2.48s；CPU 图一条曲线、39 点，请求 886ms | 大量序列会增加数据量和绘图负荷；259 条占位符名称和重复 Slot 1 与模拟数据有关，不能认定真实设备采集错误，本轮不改采集、不删除序列、不以 Top N 掩盖数据。 |
| 压缩与权限 | 本地已启用代理 gzip（JS/JSON，1KB 阈值、级别6）；所有 Grafana 请求经 auth_request 和数据库会话校验 | 不重复添加压缩，也不缓存权限校验。代码可见的数据库固定成本未取得生产时序，不能把端到端延迟全归因于数据库。 |

面板 Stats 的 `Total request time` 是 Grafana 观察到的请求耗时；`Data processing time` 是数据帧处理时间，**不是 VictoriaMetrics 引擎执行时间**。浏览器可用工具没有网络瀑布/资源 timing 接口，本轮用 Query Inspector 与 TLS ALPN 提供有限但可复核的实测。

## 实际修改文件
- `nginx/nginx.conf`：HTTPS server 添加 `http2 on;`；认证子请求显式 HTTP/1.1、清空 Connection；Grafana 专用 Upgrade map，无升级时不发送 Connection，升级时保留 `upgrade`。
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：现有部署契约追加协议、条件升级、权限校验与身份头隔离断言。
- 本计划及 walkthrough。前端、采集器、看板查询、数据库、超时、连接池数量和缓存策略没有本轮新增变更。

## 分工与集成
frontend_worker 只读审查 React 引导、iframe 生命周期和全局请求；backend_worker 审查并修改 Nginx 与局部契约测试。主 Agent 负责浏览器/协议采样、变量与模拟数据分析、统一方案、验证和归档。保留之前 Windows 端口、YunShan 和 Grafana 查询/布局的所有未提交变更。

## 验证命令与结果
```powershell
.venv/Scripts/python.exe -m pytest --noconftest -q backend/tests/monitoring/test_monitoring_v1_deployment_contract.py
.venv/Scripts/python.exe artifacts/grafana-nginx-validation-20261006/validate_nginx.py
git diff --check -- nginx/nginx.conf backend/tests/monitoring/test_monitoring_v1_deployment_contract.py
```
- 静态部署契约 **7 passed**；`--noconftest` 避免应用数据库自动初始化。
- 官方 `nginx.org/download/nginx-1.27.5.zip` Windows 二进制，确认包含 auth_request、HTTP/2、SSL 模块。
- 验证脚本使用实际配置的隔离副本，仅替换 Docker 上游地址、loopback listen 端口、测试证书及本地目录；旧/新配置均通过 `nginx -t`。不使用应用数据库和真实凭证。
- 两次连续请求：旧鉴权连接2、新鉴权连接1；两次权限校验均执行。Grafana 主连接旧/新均为1。
- 新配置可信测试证书 TLS 协商 h2；Node 原生 HTTP/2 客户端在同一会话并行请求两次，均200，认证未跳过，伪造 Admin 身份头被覆盖为 Viewer。HTTP/1.1 客户端仍正常。
- 401/403 拦截、internal auth 入口404、Cookie/Authorization 隔离、gzip JSON、Grafana Live 与 PAM 的真实101握手和 WebSocket文本回显均通过。
- 差异空白检查通过。测试 Nginx 与本地 mock 服务已退出，官方二进制/临时证书仅保留在专用 Temp 路径，不纳入更新包。
- [可复核结果 JSON](D:/netops/netsops-main/artifacts/grafana-nginx-validation-20261006/result.json)；隔离脚本和语法日志位于同目录（Git ignored）。

## 未执行项与剩余风险
- 无远端 SSH/Docker 管理会话，且本轮授权为配置优化；未替换远端文件、reload 容器或部署。远端运行时证书、挂载、Linux镜像和实际请求耗时仍待应用后验证。
- 未做前端 lint/build、全量后端回归或真实设备测试：本轮只改 Nginx 配置和无数据库静态契约，不涉及这些业务输出。
- HTTP/2 会增加并发调度能力；大量模拟序列和变量链的实际计算/传输成本仍在，不能承诺页面立即加载或某个百分比提速。
- 如部署后仍慢，优先采集浏览器网络瀑布和代理/认证/数据源的分段耗时，再决定是否合并 session bridge、调整变量依赖或降低模拟器无意义序列数；不先引入认证缓存或扩大数据库连接池。

## 应用与回滚
项目 Compose 将 `nginx/nginx.conf` bind mount 到 `/etc/nginx/conf.d/default.conf`，无需重建前端或 Grafana。将新内容写入原文件以保留挂载 inode，先 `docker compose exec nginx nginx -t`，通过后 `docker compose exec nginx nginx -s reload`。若配置通过原子替换改变了 inode，应重新创建仅 Nginx 容器以更新挂载，不能仅 reload 旧挂载。

应用前备份现有文件并比对远端自定义项；失败时恢复备份，验证通过后 reload。不要覆盖证书、`.env`、数据库或监控卷。更新包只含本轮配置、差异与说明，之前看板 JSON 更新包独立。

[配置更新包](D:/netops/netsops-main/artifacts/grafana-nginx-update-20261006_1130.zip)：4,789 bytes，ZIP CRC 检查通过，SHA256 `1a82300ee3a7be76f1161c32c52d143a3bd3743d6768e0ebd0d04fc52e1df19c`。内容为 `nginx/nginx.conf`、`nginx-config.patch` 和应用/回滚说明；不含凭证、证书、测试二进制或内部协作文件。

## 官方依据
- [Nginx HTTP upstream keepalive](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#keepalive)：旧版本需 HTTP/1.1 和清空 Connection，条件头部必须保留升级语义。
- [Nginx WebSocket proxy](https://nginx.org/en/docs/http/websocket.html)：升级请求需转发 Upgrade/Connection。
- [Nginx HTTP/2](https://nginx.org/en/docs/http/ngx_http_v2_module.html#http2)：`http2 on` 自1.25.1起支持，适用于项目1.27系列。
- [Grafana chained variables](https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/advanced-variables/) 与 [Panel inspector](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/panel-inspector/)：级联变量初始化与 Stats 指标的含义。
