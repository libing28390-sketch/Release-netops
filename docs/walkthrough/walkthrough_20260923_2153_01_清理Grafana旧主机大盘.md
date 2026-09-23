# 走查报告：清理 Grafana 旧主机大盘

## 完成摘要

- 增加 Docker 部署脚本的 `prune-legacy-dashboard` 命令，定向处理已下线的 UID `nexora-server-metrics`。
- 安装、升级、离线启动和未变更的升级检查都会尝试清理该历史记录；删除前核对 UID 对应标题，仅匹配 `Server & Host Metrics` 才执行删除。目标已不存在时安全通过；认证失败、标题不符或 API 异常会给出失败/告警，不触碰其他大盘。
- 手动清理遇到容器配置凭据失效时会隐藏提示输入 Grafana 管理员账号和密码；凭据仅经 stdin 传入 Grafana 容器，不写入脚本参数或日志。
- 已为 `docs/deploy/docker.md` 补充单独清理命令。

## 实际修改文件

- `scripts/deploy-docker.sh`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260923_2153_01_清理Grafana旧主机大盘.md`
- `docs/walkthrough/walkthrough_20260923_2153_01_清理Grafana旧主机大盘.md`

## 关键实现

部署脚本从 Grafana 容器内部访问 `127.0.0.1:3000`，优先使用容器管理员环境变量；手动清理遇到 401/403 时会隐藏提示输入 Grafana 管理员账号和密码，并把 Basic Authorization 配置经标准输入交给 curl，避免把凭据放入 curl 参数或日志。自动部署路径遇到清理失败会保留服务启动并输出警告；手动命令会以失败状态返回，便于现场排障。

## 验证命令与结果

- `& 'C:\Program Files\Git\bin\bash.exe' -n scripts/deploy-docker.sh`：通过。
- `.\.venv\Scripts\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py -q`：5 项通过。
- `git diff --check`：通过。
- 访问 `https://192.168.204.128/grafana/api/health`：HTTP 200，确认目标 Grafana 存活。
- 未认证请求 Grafana dashboard search：HTTP 401，确认 API 需要认证。
- 通过 `li` SSH 登录并 `sudo -i` 成功；Grafana health endpoint 返回 HTTP 200。
- Grafana dashboard API 使用容器环境凭据及用户提供的 Grafana 凭据均返回 HTTP 401；标题核对未通过，因此本会话没有删除线上记录。

## 未执行验证与剩余风险

- 未运行 pytest；本改动限于 Bash 部署脚本和部署说明。
- 尚未在运行中的 `192.168.204.128` 删除旧 UID。将更新后的脚本同步到部署目录后，执行 `bash scripts/deploy-docker.sh prune-legacy-dashboard` 并在隐藏提示中输入当前有效的 Grafana 管理员凭据；成功日志应为 `Removed retired Grafana dashboard UID nexora-server-metrics`，已不存在时应为 `Legacy Grafana dashboard UID nexora-server-metrics is already absent`。
- Grafana 的保存凭据与容器环境值不一致；不要通过重置 Grafana 管理员密码绕过此问题，使用当前 Grafana 登录凭据完成定向删除。
