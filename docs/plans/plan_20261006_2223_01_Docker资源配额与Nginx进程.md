# Docker 资源配额与 Nginx 进程

## 目标与证据

用户实际Linux容器检查确认只有NetOps（2 CPU / 2GiB）与Nginx（1 CPU / 256MiB）有显式硬限额，其余主要服务memory/NanoCPUs为0。用户授权补齐全部容器资源上限、留适度余量并要求Nginx worker从2个改为1。用户最新授权已覆盖提交、push、Actions 和部署验证；后端 Uvicorn `WORKERS=1` 仍保持不变。

卡顿样本221103已抓到容器内direct live的1931.1ms、5007ms超时和553.3ms，同窗无新增CPU节流或OOM。因此不把增大quota解释为根因修复；数据库/同步阻塞分析与补丁继续沿用2054计划和2148审查。

## 文件边界与实现

主Agent负责 `docker-compose.yml`、`.env.example`、`nginx/Dockerfile`、新增 `nginx/docker-entrypoint.d/40-configure-workers.sh` 与 `backend/tests/release/test_nginx_worker_contract.py`、`docs/deploy/docker.md` 和本计划/走查。第二位Luna验证执行者独立分析两份真实容器日志，不写这些文件。

- 每个Compose服务设置mem_limit、cpus、pids_limit；CPU/内存从环境变量读取并有非零默认值。后端内存从2GiB放宽到2304MiB，CPU和Uvicorn worker不变。
- 默认全部内存cap合计6784MiB，当前7.709GiB主机剩约1.084GiB系统余量。CPU额度是上限而非预留，允许关键服务在宿主机可用时使用2CPU；不把11项CPU相加当实际独占CPU需求。
- Redis内存1GiB，保留原内部512MB数据上限，为AOF/缓冲留空间；不改缓存策略、ACL、密码或数据卷。
- 官方Nginx镜像按文件名顺序执行hook，40脚本在自动调节之后设置主配置worker_processes。默认1，接受1～1024正整数，拒绝无效值及缺失/重复指令；仅改main配置的worker行，保留站点代理、TLS和worker_connections1024。
- 不修改数据库启动参数/扩展、不安装 `pg_stat_statements`，也不更新镜像版本。用户已授权部署现有镜像与配置改动；部署前需备份，部署后核对容器限额和 Nginx 进程数。

## 验证范围

- Compose YAML解析、11项默认CPU/MEM/PID非零、示例变量与默认一致、总内存预算检查。
- Nginx实际hook函数在临时配置上运行，验证默认/显式worker、重复启动稳定、LF/CRLF配置语义保持、非法值拒绝、缺失/重复main指令失败。
- 既有Docker存储/Redis/监控部署契约；这些仅测试文件与shell helper，不触及数据库，可用confcutdir排除无关PostgreSQLbootstrap。
- Bash语法与改动diff检查。Windows没有Docker；实际镜像构建、容器限额生效和 `nginx -t` 由现已获授权的 Linux 部署验收完成，并记录 `docker inspect`/`nginx -T`/进程数证据。
- 同步阻塞修改所需完整后端回归已启动，结果由2054走查统一记录，不再重复全量。

## 风险与回滚

容量建议只覆盖当前2CPU/约8GiB模拟器部署的实际峰值，规模扩大时需调`.env`。到达内存/进程/CPU上限仍可能OOM/拒绝fork/节流，不能保证所有负载都满足默认值；数据持久化和磁盘保留策略不受这些内存限额代替。回滚仅撤销本次Compose/示例/hook差异，保留既有工作区改动和真实凭据、数据卷。
