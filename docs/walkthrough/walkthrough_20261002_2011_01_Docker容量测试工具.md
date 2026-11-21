# Docker 容量测试工具执行记录

## 完成摘要

交付了部署机可运行的 Docker 容量测试工具。入口保留为 `scripts/stress-test-docker.sh`；默认 dry-run 不访问 Docker，显式传入 `--run` 后，工具读取当前源容器镜像和限额，创建带唯一标签的临时隔离测试栈，运行真实协议与业务合成负载，采集资源数据并生成报告。旧连通性预检查通过 `--probe` 保留。

测试范围为 11 个场景：PostgreSQL、NetOps API、Redis、VictoriaMetrics、SNMP exporter、vmagent、Docker socket proxy、cAdvisor、Grafana、Nginx、SeaweedFS。默认每场景依次尝试 5/20/50 RPS，每档测量 120 秒，并在测量前预热与预检查。选择子集时会补齐服务依赖。

临时服务使用源容器对应的本地镜像 ID 和 CPU、内存、PID 限额。所有临时容器、网络和数据卷均带运行标签；测试数据只写入本次新建的数据库、缓存、时序存储、对象存储与应用卷。测试网络设为 internal，SNMP 目标由本地模拟器提供。资源采集器记录 Docker 原始计数器差分和 Linux 主机指标；升压结果与清理状态写入 JSON/Markdown 报告。

## 实际修改文件

- `scripts/stress-test-docker.sh`：容量测试 CLI 入口。
- `scripts/stress-test-docker-probe.sh`：保留已有轻量连通性预检查。
- `scripts/docker_capacity/main.py`：参数校验、阶段编排、SLO 判断、报告与清理控制。
- `scripts/docker_capacity/lab.py`：本地镜像/限额发现、隔离 Docker 栈和标签所有权清理。
- `scripts/docker_capacity/metrics.py`：Unix socket stats/events、容器与宿主机 CSV、原始指标和阶段汇总。
- `scripts/docker_capacity/runner.py`：数据准备、协议检查、11 种场景工作负载、有界 open-loop 调度。
- `scripts/docker_capacity/snmp_simulator.py`：支持 GET、GETNEXT、GETBULK 与 EndOfMibView 的 SNMPv2c 模拟器。
- `scripts/docker_capacity/test_main.py`、`test_metrics.py`、`test_runner.py`：本地编排、指标、协议与工作负载回归。
- `docs/README_DOCKER_CAPACITY_TEST.md`：部署、参数、场景和结果解释。
- 本任务计划：`docs/plans/plan_20261002_2011_01_Docker容量测试工具.md`。

## 验证命令与结果

- `python -m unittest discover -s scripts/docker_capacity -p 'test_*.py' -v`：38 项通过；包含模拟 Docker 的完整编排、失败后清理、指标可用性/增量、真实 loopback HTTP 和 SNMP BER 请求、请求调度及错误语义。
- `bash -n scripts/stress-test-docker.sh scripts/stress-test-docker-probe.sh`：通过。
- `bash scripts/stress-test-docker.sh --dry-run`：通过；显示 11 个场景和默认数据/档位，没有 Docker 访问。
- `python -m py_compile scripts/docker_capacity/main.py scripts/docker_capacity/lab.py scripts/docker_capacity/metrics.py scripts/docker_capacity/runner.py scripts/docker_capacity/snmp_simulator.py`：通过。
- `git diff --check`：通过；其余提示只涉及工作区已有的 `dist/index.html` 和当日提交文档换行符。
- 已生成并检查 `artifacts/nexora-docker-capacity-test.zip`：压缩包校验通过，包含入口、旧预检查、运行模块、聚焦测试与中文部署说明。

## 用户提供的部署机首轮报告

`report.json` 的状态为 `aborted`，诊断是 `TEST_NETOPS_STARTUP_FAILED` 和临时 NetOps 容器异常退出；`stages` 为空，说明未进入任何正式压测档位。清理完成。测试机 2 个 CPU，最低可用内存约 61.6%；测试 NetOps 峰值约 204 MiB / 2 GiB，报告未见 OOM 或重启。因此首轮报告不能说明容器限额够不够。

报告 CPU 指标全部为空，是因为采集器请求 Docker `one-shot` stats，却只使用响应中 `precpu_stats` 计算 CPU。依据 Docker API 对 one-shot 的定义，这类请求返回单次统计，不等待两轮采样；更新为采集器保存相邻累计 CPU/system 计数差分，遇到重启或计数器回退时重设基线。

检查 NetOps 启动代码后，找到与报告相符的确定性配置遗漏：测试容器没有传 `POSTGRES_USER`。应用根据该变量及容器标记识别 Compose 环境；识别失败会把数据库 URL 中的 `db` 主机替换为 `localhost`，而 NetOps 在启动阶段立即连接数据库。测试环境现传入本次生成的数据库用户名。旧报告没有应用日志，无法确认是否还存在其它启动错误；新版本会在清理前记录失败容器的退出码和有限脱敏日志。

最终聚焦验证：`python -m unittest discover -s scripts/docker_capacity -p 'test_*.py' -v`：45 项通过，覆盖 one-shot CPU 差分、NetOps 环境契约、日志脱敏与清理、关键/辅助指标缺失分类、11 场景协议和调度。Linux Docker 实际启动和压测仍未验证。

后续版本：工具版本 1.1.2。v1.1.1 部署报告显示数据准备成功，但 preflight runner 抛出通用错误且没有 OOM/重启；为定位该 runner 错误，v1.1.2 在异常时新增脱敏异常类型及代码位置，不包含异常消息或秘密。依用户要求不生成压缩包，直接交付 `runner.py` 和 `main.py` 两个单文件。报告中的 SNMP exporter `block_io` 缺项仍归入辅助指标，不影响 CPU/内存等关键指标完整时的容量结论。

v1.1.2 验证：聚焦单测 46 项通过；Python 编译、Bash 语法、版本命令和 dry-run 均通过。部署机错误位置落在 runner 的 VictoriaMetrics 预检汇总：布尔结果被当成字典调用 `.get()`。v1.1.3 将 VictoriaMetrics 检查结果规范化，并增加成功/失败分支用例。聚焦单测现为 48 项通过；Python 编译、Bash 语法、版本命令和 dry-run 均通过。未在本机连接部署 Docker；部署机直接替换 `runner.py` 和 `main.py` 后重跑相同低档 NetOps 场景。

## v1.1.3 部署机报告与 v1.1.4 诊断改进

用户提供的 `report (5).json` 对应 run ID `97c33b26cab548ea99474e0200294ece`。v1.1.3 preflight 成功；stage-5 配置为 5 RPS、30 秒，但 runner 在 5.416 秒时因 `/api/login` 超时退出，NetOps 场景 `scheduled=0`、`completed=0`、`successful=0`，没有进入正式请求调度。`check-final` 再次在相同登录步骤约 6.8 秒后超时。故 `NO_SUCCESSFUL_REQUESTS`、100% 错误率和 p95=0 是未启动负载的结果，不能代表 5 RPS 容量。

报告期间无 OOM、重启、关键指标缺失或 CPU throttle；宿主最低可用内存约 63.1%。隔离 NetOps 内存峰值约 258 MB / 2 GiB，CPU 约 50.2%。限额不是本报告可证明的瓶颈。preflight 单请求 p95=263.51 ms、计算得出的 73297 RPS 也不是有效吞吐。报告未包含仍运行的测试应用/DB日志，所以目前不能在客户端超时之外确定服务端原因。

v1.1.4 的改动文件：

- `scripts/docker_capacity/runner.py`：NetOps 登录请求超时输出 `api_login_timeout`，不包含异常消息、凭据或响应体。
- `scripts/docker_capacity/main.py`：将每档 warmup 结果写入 `warmups`；失败后停止，不进入正式阶段。
- `scripts/docker_capacity/lab.py`：失败清理前收集本次测试 NetOps、DB、Redis 的脱敏日志尾部。
- `scripts/docker_capacity/test_runner.py`、`test_main.py`：补充登录超时分类、warmup 停止及运行容器日志捕获回归。
- `docs/README_DOCKER_CAPACITY_TEST.md`：更新版本与失败报告读取方法。

验证：`python -m unittest discover -s scripts/docker_capacity -p 'test_*.py' -v`：51 项通过；`python -m py_compile ...`：通过；Git Bash `-n` 检查两个入口脚本通过；`--version` 输出 1.1.4；`--dry-run` 通过。当前 Windows 工作区没有 Docker，未做实际容器复测。用户在 Linux 部署机替换三个核心 Python 文件后，应核对版本 1.1.4 并重跑同一低档命令，重点查看 `warmups`、`diagnostics` 与 `container_diagnostics.netops/db`。

## 未执行验证及原因

当前工作区运行在 Windows，未部署 Docker；因此无法验证 Linux Docker daemon、现有部署镜像和其运行时配置能否全部成功启动，也没有实测真实容器性能。本地检查覆盖的是隔离容器构造、协议、指标算法与控制流程。将工具放到 Linux 部署机后应先执行 dry-run，再选较低 RPS 做第一次实际运行；完整结果以该机生成的 `report.md`、`report.json` 和资源 CSV 为准。

## 剩余风险与建议

- 测试实例和生产实例共享宿主机资源，测试会改变宿主机负载；工具在主机余量过低、测试容器内存接近限制、OOM 或服务异常退出时停止。
- 生产数据量、请求比例、Grafana 查询复杂度、保留期以及设备响应差异，需要按现场情况匹配测试参数。模拟 SNMP 不代表真实网络丢包、SNMPv3 或厂商设备性能。
- 容量结论只适用于报告记录的数据集、流量、阶段时长和阈值；工具不自动调整容器 limits。长期内存增长应通过更长持续时间和符合实际规模的数据集单独测试。
- SIGKILL、断电或 Docker daemon 故障可能中断清理；发生时使用报告中的 run ID 和资源前缀人工定位，仅核对并清理同一完整运行标签对应的临时资源。
