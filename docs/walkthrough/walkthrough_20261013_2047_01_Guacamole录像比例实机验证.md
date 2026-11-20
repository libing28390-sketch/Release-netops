# Guacamole 录像画幅实机验证

## 本次结果
RDP 初始分辨率修改已在 Ubuntu 实际部署，新建 RDP 录像与 VNC 录像的源画幅均为 1920×1080（16:9）。播放器完整适配与按宽度放大两种模式可用；画面保持比例。

## 发布与部署
- 提交 126d84be：fix(pam): request widescreen RDP initial resolution
- GitHub Actions #728：https://github.com/chaojifeixia-007/netsops/actions/runs/38396735476 成功，Ubuntu/Linux 发布作业用时 13 分 54 秒。
- 在 Ubuntu 192.168.204.128 执行 bash scripts/deploy-docker.sh update，成功同步发布源 0a23696 并重建服务。
- nexora-netops、nexora-guacamole、nexora-guacd、nexora-db、Redis、Nginx、SeaweedFS、VictoriaMetrics、Grafana 及其他容器运行；带健康检查的容器均为 healthy。https://127.0.0.1/ 返回 HTTP 200。

## 真实录像核对
- RDP：通过 Nexora 发起 LEERBON 普通凭据会话。显示 Windows 登录界面及其它用户已登录提示，连接过程确认目标画面为 16:9；回放播放器标注源画面 1920 × 1080 · 16:9。会话由用户手动结束；Gateway 521 是手动关闭后的状态。
- VNC：播放 LEERBON 最新 VNC 录像，播放器标注源画面 1920 × 1080 · 16:9。完整适配与按宽度放大控件均可用。
- 旧 RDP 录像依旧是 1024 × 768 · 4:3；不修改历史文件。使用按宽度放大模式可等比放大，画面超出高度时纵向滚动。

## 代码验证
- .venv\Scripts\python.exe -m pytest backend/tests/pam/test_remote_desktop_guacamole_service.py -q：9 passed。
- GitHub Actions #728 成功，包含完整后端发布门禁、前端 TypeScript lint/build 与知识引擎评估。
- 更新脚本报告 .env、持久卷和 nginx/ssl 已保留。
