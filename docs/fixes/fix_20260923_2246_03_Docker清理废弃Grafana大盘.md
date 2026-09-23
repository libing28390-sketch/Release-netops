# Docker 清理废弃 Grafana 大盘

## 变更目的

部署实例仍可能保留已由 Linux/Windows 专用大盘替代的历史主机大盘 `nexora-server-metrics`，仓库当前配置不再生成该 UID。

## 根因

旧大盘保存在运行中的 Grafana 数据库；仅删除仓库中的 provisioning 文件不会清除已有记录。

## 解决方案

- 增加 `prune-legacy-dashboard` 命令，并在在线安装/升级、离线启动和无变更升级检查后尝试幂等清理。
- 删除前检查固定 UID 和标题；404 视为已清理，鉴权/标题/其他 API 错误报告失败，不触碰其他大盘。
- 手动遇到容器内配置凭据不匹配时，隐藏提示输入 Grafana 管理员凭据；认证头通过标准输入交给 curl，避免将明文密码放进 curl 参数或日志。
- 自动部署清理失败时保留服务启动并给出重试命令；文档提供单独执行步骤。

## 实际修改文件

- `scripts/deploy-docker.sh`
- `docs/deploy/docker.md`
- `backend/tests/release/test_deploy_docker_redis_contract.py`
- `docs/plans/plan_20260923_2153_01_清理Grafana旧主机大盘.md`
- `docs/walkthrough/walkthrough_20260923_2153_01_清理Grafana旧主机大盘.md`

## 验证命令与结果

- `& 'C:\Program Files\Git\bin\bash.exe' -n scripts/deploy-docker.sh`：通过。
- `.\.venv\Scripts\python.exe -m pytest backend/tests/release/test_deploy_docker_redis_contract.py -q`：5 项通过。
- `git diff --check`：通过。

## 未验证项

- 没有在生产 Grafana 执行删除。当前部署实例的管理员凭据未能认证；线上旧 UID 状态仍需部署后用有效管理员凭据确认。
- 未运行全量测试或重建线上 Docker 服务。

## 风险与回滚方式

- 未来 Docker 安装/升级会自动尝试删除固定 UID `nexora-server-metrics`；删除受标题核对保护。手动命令会在密码输入错误或 API 不可用时失败，不删除其他大盘。
- 回滚可恢复脚本与文档，并一并移除此修复记录；若之后已删除旧大盘，需从旧 JSON 或备份重新导入。
