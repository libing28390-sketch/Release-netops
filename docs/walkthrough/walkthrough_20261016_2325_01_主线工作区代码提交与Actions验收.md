# 主线工作区代码提交与 Actions 验收走查

## 结果

- 源码仓库 `main` 已推送提交 `f07975d8568a34685dd85879f50b97559b4dce82`（`fix: synchronize accumulated workspace changes`）；推送前后远端 `origin/main` 与本地 `main` 对齐。
- GitHub Actions 运行 [#738](https://github.com/chaojifeixia-007/netsops/actions/runs/38926417551) 通过，浏览器显示 Linux 发布作业成功，耗时约 14 分 22 秒。
- 后端 PostgreSQL 发布门禁收集并通过 3303 项测试；前端检查/测试/构建、Knowledge Engine 发布门禁、清理发布树和 Linux Docker 发布包均成功。
- 本次分支推送没有创建标签，因此 Windows 工作站发布、百度网盘上传和 GitHub Release 创建按工作流条件跳过；这不影响主线门禁和 Ubuntu 发布包成功。
- 现有工作流将清理后的发布树同步至公开仓库 `libing28390-sketch/Release-netops`。目标机部署日志读取到发布树提交 `e214a65`。

## 目标机更新

- 已按授权执行：`cd /data/nexora-automation/ && bash scripts/deploy-docker.sh update`。
- 部署命令退出码为 `0`；Docker 镜像构建以 `56/56 FINISHED` 完成，Compose 更新完成。
- 部署脚本创建 `.env.backup.20261016235952`，并在 `../netops-release-backups/release-20261016-235952` 生成 PostgreSQL dump、源清单、部署配置和配置快照备份。
- `docker compose ps` 显示项目容器均处于运行状态。数据库、Redis、告警 Redis、cAdvisor、Grafana、VictoriaMetrics、vmagent、SNMP exporter、NetOps 主应用和 Nginx 的健康检查通过；随后 `guacd` 也转为 `healthy`。
- `nexora-guacd` 日志确认守护进程已监听 TCP 4822，容器内 `nc -z 127.0.0.1 4822` 探测通过；最终只读 `docker inspect` 显示 `nexora-guacd`、`nexora-netops`、`nexora-nginx` 均为 `running healthy`。
- 本机 HTTP 入口 `http://127.0.0.1/` 返回 `301`，符合跳转 HTTPS 的预期。
- SSH 会话已正常退出。

## 工作区保留项

- 本次源码提交包含 62 个有意保留的源码、测试、迁移、配置及修复记录文件。
- 本地 `dist/index.html` 修改未提交：它是生成清单，引用的 bundle 是本地忽略/未跟踪构建产物；Linux 发布工作流会在 CI 中重新构建前端并生成发布树。
- `.codex-build-*`、`dist-*`、`logs/` 和未纳入提交的内部计划/走查文档均保留在本机，没有推送到源码仓库。

## 遗留风险记录

- 提交前曾启动本地后端 pytest；仓库的 autouse fixture 会在隔离测试模板创建前调用配置源库的 `database.init_db()`。本机数据库并非 test/ci/eval 命名，安静模式没有迁移写入明细，不能据此确认本机源库是否发生迁移。已停止进一步本地数据库测试；本次完整后端门禁在 GitHub Actions 的独立 PostgreSQL 服务上通过。
- GitHub Actions 的 npm 安装日志报告 51 个依赖审计项（3 low、14 moderate、30 high、4 critical），但该项没有阻断本次工作流。本次任务未擅自升级依赖。
