# Docker 资源配额与 Nginx 进程

## 完成内容

`docker-compose.yml` 的11个服务均有CPU、内存、PIDs硬上限；CPU/内存通过`.env`对应变量调整。后端内存2GiB→2304MiB，默认总内存cap6784MiB（6.625GiB），给当前7.709GiB主机约1.084GiB余量。逐项默认值和调节方法见 `docs/deploy/docker.md`。

`nginx/Dockerfile`复制并赋予新hook执行权限；`40-configure-workers.sh`在官方30自动调节hook后设置 `/etc/nginx/nginx.conf` 的worker_processes。默认 `NGINX_WORKER_PROCESSES=1`，重启配置保持幂等，无效整数或缺失/重复main指令会失败退出。站点文件 `/etc/nginx/conf.d/default.conf` 与worker_connections1024保持原行为。

Uvicorn默认仍 `WORKERS=${WORKERS:-1}`。本轮不提交、不push、不部署，不修改生产`.env`或数据卷，不启用pg_stat_statements。此前用户的无线Grafana、首页资产、其他诊断脚本与内部协作材料全部保留。

## 实际修改文件

- `.env.example`、`docker-compose.yml`：可配置CPU/内存及11服务PIDs上限，Nginx worker环境。
- `nginx/Dockerfile`、`nginx/docker-entrypoint.d/40-configure-workers.sh`：发布与执行main配置worker设置。
- `backend/tests/release/test_nginx_worker_contract.py`：临时main配置上的真实shell函数契约。
- `docs/deploy/docker.md` 与本计划/走查：预算、变量、重建要求与只读确认命令。

## 验证结果

1. 11服务默认CPU/MEM/PID与`.env.example`逐项解析校验：通过，总内存6784MiB，后端与Nginxworker默认均1。
2. Bash语法检查新Nginxhook：通过。
3. `python -m pytest backend/tests/release/test_nginx_worker_contract.py backend/tests/release/test_deploy_docker_storage_contract.py backend/tests/release/test_deploy_docker_redis_contract.py backend/tests/monitoring/test_monitoring_v1_deployment_contract.py -q --confcutdir=backend/tests/release`
   - 首轮27 passed、2 failed，8.09秒。两个失败都是本轮新测试比较CRLF字节；Git Bash sed将文件规范化为LF，功能配置正确。修正为比较规范化文本，仍严格断言除worker指令外内容一致，不改已有业务断言。
   - 其中既有部署契约15项通过；新Nginx测试首轮12项通过、2项CRLF比较失败。
4. `python -m pytest backend/tests/release/test_nginx_worker_contract.py -q --confcutdir=backend/tests/release`
   - 修正测试契约后的最终14 passed，4.88秒，exit0。既有15项未受此局部测试文件修正影响，不重复执行。
5. `git diff --check`：本轮配置与文档通过。Docker未安装，不运行本机Docker模拟；未验证实际Docker Compose加载、Linux Nginx `-t`、容器重建后limit/worker生效。

这些配置与shell测试不访问持久化，因此未创建数据库；2054计划所需完整后端回归独立继续运行。

## 卡顿诊断关联

Luna子Agent独立核对221103卡顿样本：direct live超时5秒、Nginx转发0.53～1.25秒，VM/Grafana健康仍≤18ms；MIB/raw新增13/6次序列扫描，后端新增quota throttling与OOM均0。资源上限补齐便于隔离与后续调整，不证明CPU/内存扩大会解决该阻塞。详细证据在2148审查，两份结构化结果在 `logs/validation/perf-container-review-20261006_220737.json` 与 `..._221103.json`。

## 官方依据与剩余边界

- [Docker Compose services](https://docs.docker.com/reference/compose-file/services/)：使用service的mem_limit/cpus/pids_limit，未依赖可选Swarm deploy语义。
- [Nginx官方镜像entrypoint](https://github.com/nginx/docker-nginx/blob/master/entrypoint/docker-entrypoint.sh)：按版本排序执行可执行hook。
- [Nginx worker_processes](https://nginx.org/en/docs/ngx_core_module.html#worker_processes)：main配置上下文中的worker进程设置。

官方入口master资料用于核对hook机制；部署镜像仍固定1.27-alpine，没有升级。需要后续实际Linux镜像启动验证。仅修改.env/restart不足以采用新创建配置；真实部署后才能确认限额与worker，操作尚未执行。
