# Grafana Auth Proxy 网络动态分配完成记录

## 完成摘要

Compose 现由 Docker IPAM 动态分配 Grafana 与 Nginx 在 `grafana_auth` 网络上的地址；Grafana Auth Proxy 白名单与该网络共用 `GRAFANA_AUTH_PROXY_SUBNET`。部署说明和 Nginx 注释都明确标注该子网的信任边界。

## 实际修改文件

- `docker-compose.yml`
- `nginx/nginx.conf`
- `.env.example`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260924_2110_01_Grafana代理网络动态分配.md`
- `docs/walkthrough/walkthrough_20260924_2110_01_Grafana代理网络动态分配.md`

## 关键实现

- Grafana `GF_AUTH_PROXY_WHITELIST` 使用 `GRAFANA_AUTH_PROXY_SUBNET`。
- Nginx 保留 `default` 与 `grafana_auth` 网络连接，但删除固定 `ipv4_address`。
- Nginx 配置注释同步说明 Grafana 信任专用网络 CIDR，避免误称仅信任 Nginx 单个 IP。
- `.env.example` 移除 `GRAFANA_AUTH_PROXY_NGINX_IP`，并说明 `grafana_auth` 只连接 Grafana 与 Nginx。
- Docker 部署文档同步说明动态分配、CIDR 信任范围和旧变量清理方式。
- 对“Grafana 页面刷新后显示 Page not found”做只读排查：今天的 Compose 差异不修改 `GF_SERVER_ROOT_URL`、`GF_SERVER_SERVE_FROM_SUB_PATH`、Nginx `/grafana/` 路由或前端仪表盘 URL；当前截图不足以判断服务器实际 URL/重定向链或仪表盘 provision 状态。
- 未修改实际服务器 `/data/nexora-automation`，未重启容器。

## 验证命令与结果

- `py -3 -c "import yaml; d=yaml.safe_load(open('docker-compose.yml', encoding='utf-8')); g=d['services']['grafana']; n=d['services']['nginx']; net=d['networks']['grafana_auth']; wl=[x for x in g['environment'] if str(x).startswith('GF_AUTH_PROXY_WHITELIST=')]; subnet=net['ipam']['config'][0]['subnet']; assert len(wl)==1 and 'GRAFANA_AUTH_PROXY_SUBNET' in wl[0] and '172.30.254.0/29' in wl[0]; assert 'ipv4_address' not in n['networks']['grafana_auth']; assert n['networks']['grafana_auth']=={}; assert net.get('internal') is True; assert 'GRAFANA_AUTH_PROXY_SUBNET' in subnet; assert 'grafana-auth' in g['networks']['grafana_auth']['aliases']; example=open('.env.example', encoding='utf-8').read(); assert 'GRAFANA_AUTH_PROXY_SUBNET=172.30.254.0/29' in example; assert 'GRAFANA_AUTH_PROXY_NGINX_IP=' not in example; print('Compose YAML parsed; subnet and whitelist share GRAFANA_AUTH_PROXY_SUBNET; Nginx IP is dynamic; auth network remains internal; example env matches.')"`：通过。Compose YAML 可解析；白名单与网络子网引用同一变量；Nginx 未配置固定地址；Auth 网络仍为 internal；示例环境变量匹配默认子网。
- `git diff --check -- docker-compose.yml .env.example docs/deploy/docker.md`：通过。
- 搜索配置引用：`GRAFANA_AUTH_PROXY_NGINX_IP` 不再被 Compose 或 `.env.example` 消费；仅部署说明提到旧变量可删除。
- 代码路径审阅：前端默认 `refresh=30s` 是 Grafana 仪表盘刷新参数；无法解释 Grafana UI 的 `Page not found`。Nginx 仍代理 `/grafana/` 到 Grafana 内部根路径。

## 未执行验证及原因

- 未执行 `docker compose config`：当前工作区没有 Docker CLI。
- 未执行容器重建或服务器验证：本次只修改本地仓库文件，没有连接或修改用户的 Linux 服务器。
- 未运行应用测试套件：变更仅涉及 Compose、环境示例和文档。

## 剩余风险与后续建议

- 白名单从 Nginx 单 IP 扩大到整个专用 `/29` 子网。必须保持该内部网络只连接 Grafana 和 Nginx。
- 对 Grafana `Page not found` 的根因尚未通过远端浏览器 URL、Grafana/Nginx 日志和有效 Compose 配置确认；需要这些运行时证据才能区分路径/根 URL 与 dashboard provision 问题。
- 将更新后的 `docker-compose.yml` 同步到服务器后，可执行 `docker compose up -d --no-deps --force-recreate grafana nginx`，再检查两容器在 `nexora_grafana_auth` 上分配到不同地址。
- 服务器已有 `.env` 中的 `GRAFANA_AUTH_PROXY_NGINX_IP` 目前会成为未使用变量，可在确认新 Compose 生效后删除；未设置 `GRAFANA_AUTH_PROXY_SUBNET` 时使用默认 `172.30.254.0/29`。
