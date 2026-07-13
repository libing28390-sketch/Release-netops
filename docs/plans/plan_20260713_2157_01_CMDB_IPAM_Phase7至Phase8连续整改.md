# CMDB 与 IPAM 企业级架构整改实施计划 (Phase 7 & Phase 8)

本计划旨在按照 `docs/plans/plan_CMDB_IPAM企业级架构整改.md` 的指引，继续完成 Phase 7（可观测性、部署与高可用）及 Phase 8（性能压测与企业验收）的整改内容，使 Nexora NetOps 具备面向中大型企业的生产可观测性、分布式无状态调度保障、并发冲突量化审计以及核心压测基准。

## User Review Required

> [!IMPORTANT]
> **分布式调度并发限制与锁表设计**
> 为了支持多实例无状态 API 部署，我们在数据库中引入了轻量级的分布式锁 `scheduler_locks` 表，并使用 Python 的 ContextVar 传递上下文。在 PostgreSQL 环境下，过期的锁将由每个节点在尝试获取锁时顺带删除，确保无状态的高可用性。

> [!NOTE]
> **可观测性指标对生产性能无影响**
> 所有统计指标均使用内存中的双端队列 (`collections.deque(maxlen=...)`) 在内存中进行滚动统计或直接执行高速单表 SQL 计数，对数据库读取及 API 响应性能不构成压力。

## Open Questions

目前暂无未决的关键架构设计问题，各项技术指标均已与 Phase 0 至 6 的最佳实践对齐。

---

## Proposed Changes

### Database & Migrations

#### [NEW] [m0009_enterprise_cmdb_ipam_phase7_phase8.py](file:///d:/netops/netsops-main/backend/database/migrations/m0009_enterprise_cmdb_ipam_phase7_phase8.py)
- 新增 `m0009` 迁移脚本，用于在 PostgreSQL 和 SQLite 数据库上创建用于多实例分布式调度的 `scheduler_locks` 锁表。

#### [MODIFY] [schema.py](file:///d:/netops/netsops-main/backend/database/schema.py)
- 在 `_init_db_logic` 函数末尾增加 `scheduler_locks` 表的创建，保证 fresh schema 部署时表结构一致。

---

### Core Components

#### [NEW] [context.py](file:///d:/netops/netsops-main/backend/core/context.py)
- 引入 `request_id_var`、`user_var`、`route_var`（针对 HTTP 请求）以及 `job_id_var`、`target_id_var`、`device_id_var`（针对后台任务）的 `contextvars.ContextVar`，用于跨调用链自动隐式传递可观测上下文。

#### [NEW] [metrics.py](file:///d:/netops/netsops-main/backend/core/metrics.py)
- 实现内存性能指标收集器 `MetricsRegistry`，提供 API 延迟滚动计算、并发 SNMP/SSH 通道执行时长与失败率计算、以及 IPAM 地址冲突审计计算。

#### [NEW] [scheduler_lock.py](file:///d:/netops/netsops-main/backend/core/scheduler_lock.py)
- 基于 `scheduler_locks` 表实现 `synchronized_scheduler_job` 装饰器，支持同步及异步的 APScheduler 定时任务，在多实例高可用部署时防止同一分钟内重复调度。

#### [MODIFY] [logging.py](file:///d:/netops/netsops-main/backend/core/logging.py)
- 修改日志输出的 `LOG_FORMAT`，增加 `[%(context)s]` 占位符。
- 完善 `ContextFilter`，自动读取 ContextVar 中的请求/任务标志并格式化为 `[req:xxx, user:yyy]` 或 `[job:xxx, target:yyy]` 写入日志。

#### [MODIFY] [main.py](file:///d:/netops/netsops-main/backend/main.py)
- 增加 FastAPI HTTP 中间件，自动为每个 API 请求生成唯一 `request_id` 并存入 `ContextVar`，提取 header 中的 Token 完成用户标识回填。
- 捕获中间件中的 HTTP 耗时并写入 API 延迟指标。
- 替换现有 APScheduler 调度注册，使用 `synchronized_scheduler_job` 装饰相关高频及低频定时器，确保分布式调度安全。

---

### Network & Services

#### [MODIFY] [orchestrator.py](file:///d:/netops/netsops-main/backend/engine/orchestrator.py)
- 在 `execute_single` 方法中对驱动执行进行耗时计算，并将 SSH/Telnet 通信状态及耗时记录到 `metrics_registry`。

#### [MODIFY] [background_monitor_service.py](file:///d:/netops/netsops-main/backend/services/background_monitor_service.py)
- 在 `process_device` Telemetry 慢速监控执行循环中记录成功率及耗时，汇总至 SNMP 可观测指标。

#### [MODIFY] [ipam_service.py](file:///d:/netops/netsops-main/backend/services/ipam_service.py)
- 在 `_validate_address_conflicts` 抛出静态 IP/VIP/DHCP 地址冲突异常时，触发并发冲突计数归档。

---

### API Layer

#### [MODIFY] [health.py](file:///d:/netops/netsops-main/backend/api/health.py)
- 重构 `/api/health` 接口，支持详细报告数据库、APScheduler（运行状态）、Worker 线程等系统状态。
- 新设 `/api/health/metrics` 接口（或内置于 `/api/health`），输出 API 平均延迟、锁占用、并发队列长度、Job 成功/失败统计、SNMP 失败率及 IPAM 地址冲突次数，便于 Prometheus 等监控系统对接。

---

### Frontend

#### [MODIFY] [http.ts](file:///d:/netops/netsops-main/src/api/http.ts)
- 从 HTTP 响应 Header 中拦截 `X-Request-ID`，并将该字段保存在 `ApiError` 实例中。
- 当前端显示接口错误弹窗或提示时，若存在 Request ID，将 Request ID 追加到提示信息末尾，方便运维人员排查。

---

## Verification Plan

### Automated Tests
- 执行新编写的单元测试：
  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests/test_enterprise_cmdb_ipam_phase7_phase8.py -v
  ```
- 执行后端全量回归测试：
  ```powershell
  .\.venv\Scripts\python.exe -m pytest backend/tests -q
  ```
- 检查前端代码编译规范：
  ```powershell
  npm run lint
  npm run build
  ```

### Manual Verification
- 访问 `/api/health`，核实返回的 `scheduler` 与 `metrics` 数据。
- 模拟触发一个失败请求，验证前端弹窗错误信息中是否带有所生成的 Request ID。
- 在日志输出中，验证每一行日志的前缀中是否均包含类似 `[req:xxx, user:admin]` 的结构化上下文。
