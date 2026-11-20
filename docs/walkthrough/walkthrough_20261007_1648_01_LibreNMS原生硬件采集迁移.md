# LibreNMS 原生硬件采集迁移实施与验证记录

## 当前状态

P1 核查及 P2–P6 代码实现已完成。产品代码 commit `669f0f67` 和验收状态文档 commit `a51ab887` 均已推送到 `main`。代码提交对应 GitHub Actions run 681 全量门禁成功；文档提交对应 [run `37636816427`](https://github.com/chaojifeixia-007/netsops/actions/runs/37636816427) 也成功，包含后端 pytest、前端/Docker 构建、净化发布树同步和归档，并生成净化发布树提交 `a2dd6bc6`。前端全量 476 项、Grafana 相关后端 68 项、Docker capacity 17 项、根目录定向后端回归 128 项和当前样本时间 PostgreSQL 测试 5 项均通过。首次全量 pytest 从 `backend` 子目录误启动，其 24 个失败已拆分并由正确根目录的 CI 全量结果覆盖。Compose 容器运行时和 HCL/真实设备验证未执行；后者按用户要求留待现场验证，因此真实部署问题根因仍未确认。

## 实现结果

- 新增 LibreNMS 专用运行环境配置、镜像锁定、MariaDB/Redis 隔离、Web/API 与 dispatcher 服务，以及 PostgreSQL 实例和设备绑定迁移。后台原生同步循环按显式绑定读取 LibreNMS 样本。
- LibreNMS API 客户端读取设备、标准传感器、processor/mempool 当前行、无线传感器和光模块元数据；投影保留原生设备/实体 ID 与上游样本时间。缺失时间或缺失样本不会伪造 0 或使用本地请求时间充当采样时间。
- CPU 和内存百分比进入现有硬件库存和 `nexora_hw_cpu_usage_percent` / `nexora_hw_memory_usage_percent` Prometheus 指标出口。导出只包含 `librenms_native` 来源，沿用设备 Grafana 看板已有指标名称与租户/资产标签契约。
- `/monitor/snmp-walk` 的硬件诊断读取当前 LibreNMS 原生快照，分开展示引擎连接、设备识别、CPU/内存/传感器/无线/光模块当前行及样本时间。原始 SNMP WALK、MIB 浏览、系统身份检查和 IF-MIB 接口验证仍保留为独立工具。
- 删除旧 Python 厂商硬件探测/归一化服务及其测试，移除后台、模板验证、设备测试、发现结果和编译器中调用旧硬件 OID 的生产入口与回退。SNMP 协议、身份识别、接口 IF-MIB 和非硬件用途不随旧 producer 一起删除。
- 同一工作区已有的 Docker 容量测试任务修改也纳入本次推送范围；其独立验证为 17 项通过。

## 验证

- Grafana 无线看板新增“LibreNMS 原生无线传感器”表格，保留原生数值/单位及可用标签，不臆造 AP 或 Radio 归属；相关面板总数为 263（非 row 面板 208）。

- 前端完整测试：`npm run test:frontend -- --run`，**124 个文件、476 项测试通过**。
- TypeScript：`npm run lint`（`tsc --noEmit`），退出码 **0**。
- 前端生产构建：`node node_modules/vite/bin/vite.js build --outDir .codex-build-validation-libre-hardware-20261007`，退出码 **0**。
- 容量测试：`.venv\Scripts\python.exe -m pytest -q scripts/docker_capacity/test_runner.py`，**17 passed**。
- PostgreSQL-only：`.venv\Scripts\python.exe scripts/validate_postgresql_only.py`，**0 violation(s)**。
- 发布配置：test knowledge config、backend `compileall`、RackVision catalog、AI/RAG release config 和前后端版本一致性检查均通过。
- `docker-compose.yml` 的 PyYAML 静态解析和原生 profile/service/network 断言通过（15 个服务）。当前工作区没有 Docker/Podman CLI，未运行 `docker compose config` 或启动容器。
- `git diff --check` 退出码 **0**；仅有 Git 关于 LF/CRLF 将转换的提示，没有空白错误。
- 首次错误 cwd 的全量 `.venv\Scripts\python.exe -m pytest -q`：3382 passed、24 failed、1 skipped（1:39:24）；根目录相对路径测试误判，另有迁移后已删除的 legacy 重试测试、厂商前缀定义、光模块旧 adapter 测试和未初始化 `last_sample_at` 的 fixture。以上问题/测试边界已处理并针对性验证。
- 根目录后端专项命令覆盖上述失败项和原生采集链路：**128 passed**；`backend/tests/snmp/test_snmp_hardware_sample_batch.py` 使用补齐 `last_sample_at` 的当前 fixture 单独复跑：**5 passed**。
- GitHub Actions run 681（commit `669f0f67`）的完整根目录 pytest/release gate：**success**。后端 pytest、前端/Docker 构建、移除私有/开发文件、净化发布树 commit/push 和归档均成功；Knowledge Engine 评估、百度上传和 GitHub Release 按本次 `main` push 条件跳过。
- 文档状态回填 commit `a51ab887` 的 GitHub Actions run `37636816427`：**success**。后端 pytest、前端/Docker 构建、移除私有/开发文件、净化发布树 commit/push 和归档均成功；Knowledge Engine 评估、百度上传、GitHub Release 和 Windows Workstation Agent 按本次 push 条件跳过。发布仓库 `main` 现为 `a2dd6bc65e3a2c8531ebfab566c85259052bc7f3`。

## 未验证项与风险

- 本机没有 Docker/Podman CLI，未验证 Compose 最终展开、镜像拉取、容器启动、原生 discovery/poller、dispatcher 网络、LibreNMS Influx v1 到 VictoriaMetrics 写入及 Grafana 现场查询。
- 未访问 HCL 或真实设备；按用户要求留给 push 后的现场验证。因此没有确认真实设备故障的首个失败层，不能宣称现场根因已修复。
- 代码级测试证明请求、数据契约、库存投影和指标名称，不证明锁定镜像的实际 API 字段、设备支持项或 VictoriaMetrics 协议兼容。
- 无线/光模块在隔离环境下尚无原生样本对照；其既有 Grafana 实体分类、明细覆盖及时间序列要在 P7 使用目标设备验证。缺乏上游实体证据的值不能靠 Python 私有 OID 兜底。
- 旧硬件本地轮询停止后，现场需要按绑定契约启用 LibreNMS；生产切换与写入设备配置不属于本次 push，仍按计划单独审批。

## 变更范围

本次提交按显式清单纳入后端 API/服务/迁移/测试、`docker-compose.yml`、`.env.example`、`monitoring/librenms/`、SNMP 诊断前端和回归测试、容量测试脚本/测试/说明，以及本计划和 walkthrough。任务前 `main`/`origin/main` 均为 `d510c59b`，无远端领先或落后提交。

未纳入 `.agents/`、`handoff.md`、`.codex-build-*`、`dist-*`、`logs/`、`backend/vendor/librenms/mibs/cisco/TEST-MIB-*`；它们分别是内部协作资料或生成/测试产物。代码提交与 Actions 门禁已完成；P7 现场运行时验证仍待用户执行，P8 生产切换需单独授权。
