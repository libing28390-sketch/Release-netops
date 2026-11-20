# Grafana 子路径重复与自动登录排查完成记录

## 完成摘要

已定位到 Grafana 404 的直接表现：Chrome 中 Nexora 创建的 iframe 起始地址只有一段 `/grafana`，随后 iframe 自行跳转到重复数十次 `/grafana/grafana/...` 的地址。已将本地 Compose 与 Nginx 配置恢复为单一子路径处理模式：Nginx 剥离 `/grafana/`，Grafana 内部按根路径服务，`root_url` 继续负责浏览器侧子路径链接。

Grafana `/api/user/auth-tokens/rotate` 的 `user token not found` 401 与页面路径 404 分开处理。本次没有改登录桥接、令牌或 Grafana 数据库逻辑；路径修复部署后若 401 仍出现，再单独检查 token/session 生命周期。

## 实际修改文件

- `docker-compose.yml`
- `nginx/nginx.conf`
- `docs/deploy/docker.md`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- `docs/plans/plan_20260924_2314_01_Grafana子路径重复与自动登录排查.md`
- `docs/walkthrough/walkthrough_20260924_2314_01_Grafana子路径重复与自动登录排查.md`

## 关键实现

- Grafana 设置恢复为 `GF_SERVER_SERVE_FROM_SUB_PATH=false`；外部 `GRAFANA_ROOT_URL` 仍包含 `/grafana/`。
- Nginx 恢复 `proxy_pass http://grafana_backend/;`，由 URI 替换规则剥离请求中的 `/grafana/` 前缀；保留 `/grafana` 转发前缀头供外部 URL 识别。
- 部署文档明确要求不要让 Nginx 与 Grafana 同时处理相同子路径。
- 新增部署契约，校验 Grafana 子路径开关、外部 root URL、Nginx 前缀剥离和转发头保持一致。
- Chrome 只读检查确认 iframe 源地址正常、最终页面 URL 异常重复子路径。没有修改浏览器数据或运行中的服务器。

## 验证命令与结果

- `.venv\Scripts\pytest.exe --confcutdir=backend/tests/monitoring -q backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：通过，5 passed。
- `git diff --check -- docker-compose.yml nginx/nginx.conf docs/deploy/docker.md backend/tests/monitoring/test_monitoring_v1_deployment_contract.py docs/plans/plan_20260924_2314_01_Grafana子路径重复与自动登录排查.md`：通过。
- `.venv\Scripts\python.exe -c "import yaml; d=yaml.safe_load(open('docker-compose.yml', encoding='utf-8')); print(len(d['services']))"`：通过，Compose YAML 可解析，共 9 个服务。

## 未执行验证及原因

- 未执行 `docker compose config` 或 `nginx -t`：本机没有 Docker CLI，也没有 Nginx CLI。
- 首次直接运行该 pytest 文件时，仓库级 `backend/tests/conftest.py` 自动触发 PostgreSQL session fixture 并等待数据库；本配置契约不依赖数据库，因此在 `--confcutdir=backend/tests/monitoring` 下重跑，5 项测试全部通过。
- 未在远端重建 Grafana/Nginx，也未对浏览器当前站点做新部署后的验证；本次只修改本地仓库。远端仍运行旧配置，因此当前已打开页面继续报错是预期状态。

## 剩余风险与后续建议

- 将本次 `docker-compose.yml` 与 `nginx/nginx.conf` 同步到服务器并重建 Grafana、Nginx 后，再确认 iframe 最终 URL 为单一 `/grafana/d/...` 且仪表盘返回 200。
- 部署后若 token rotate 仍返回 `user token not found`，检查新的 Grafana 会话是否只由 Auth Proxy 建立、浏览器是否仍携带旧 `grafana_session`；不要通过删除 Grafana 数据卷处理。
- GitHub Actions 及未知插件 `404/Unknown Plugin` 日志不是本次子路径路由修复范围。
