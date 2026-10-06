# Grafana Nginx 加载优化

## 现象与目的
嵌入式 Grafana 看板加载偏慢；远端 TLS 协商仅为 HTTP/1.1。代码中的认证子请求没有显式配置上游 keepalive 所需的 HTTP/1.1 与空 Connection 头。

## 根因与方案
HTTPS server 启用 HTTP/2；认证子请求使用 HTTP/1.1 且清除 Connection；Grafana 代理按是否存在 Upgrade 条件发送 Connection，保留 WebSocket 行为。未加入认证缓存。

## 实际修改文件
- `nginx/nginx.conf`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- 配对 `20261006_1130` 计划与 walkthrough。

## 验证
- 部署契约测试 7 项通过。
- 官方 Nginx 1.27.5 隔离实测：连续两次认证的 TCP 连接从 2 条降至 1 条，认证仍逐请求进行；HTTP/2 并发请求、HTTP/1.1 兼容、401/403、身份头及 cookie 隔离、gzip、Grafana/PAM WebSocket 回显均通过。
- 测试仅使用 loopback mock 服务与测试证书；没有修改远端服务。`git diff --check` 通过。

## 未验证、风险与回滚
远端尚未应用，实际页面提速尚未测量；设备模拟器的大量序列与 Grafana 变量级联仍产生负荷。部署和回滚说明见配对 walkthrough；回滚仅恢复 Nginx 配置后语法检查并 reload。
