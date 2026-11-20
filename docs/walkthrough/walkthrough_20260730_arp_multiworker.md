# ARP 多 Worker 采集验收说明

## 1. 采集链路

后台定时任务不再直接连接设备，而是：

```text
ARP 调度器
    ↓
collector_task_queue
    ↓ 任务租约
ARP Worker 进程/线程
    ↓ 全局 Worker 槽位 + 单设备 SSH 限流
设备采集
    ↓
ARP 快照、采集状态、失败重试
```

手动 ARP 采集和统一 NSoT 同步仍使用即时采集入口，避免调用方拿到尚未完成的异步结果。

## 2. 默认配置

```env
ARP_SWEEP_INTERVAL_SECONDS=600
ARP_MAX_DEVICES_PER_SWEEP=500
ARP_WORKERS_PER_PROCESS=2
ARP_GLOBAL_WORKER_SLOTS=20
ARP_TASK_LEASE_SECONDS=900
ARP_TASK_POLL_SECONDS=1
```

其中：

- `ARP_WORKERS_PER_PROCESS`：每个后端进程启动的 Worker 数量。
- `ARP_GLOBAL_WORKER_SLOTS`：所有后端进程共享的最大 ARP 任务并发数。
- `ARP_TASK_LEASE_SECONDS`：Worker 异常退出后，任务被其他 Worker 回收前的租约时间。
- `ARP_MAX_DEVICES_PER_SWEEP`：调度器每轮最多入队的设备数。

## 3. 重启后检查数据库

启动后执行：

```sql
SELECT version, name
FROM schema_migrations
ORDER BY version DESC
LIMIT 5;

SELECT status, COUNT(*)
FROM collector_task_queue
WHERE collector = 'arp'
GROUP BY status;

SELECT collector, cursor_position, last_eligible, last_selected,
       last_successful, last_failed, last_completed_at
FROM collector_sweep_state
WHERE collector = 'arp';
```

预期：

- 迁移版本包含 `48 collector_task_queue` 和 `49 arp_cache_source_index`。
- 任务会在 `pending`、`running`、`succeeded` 之间变化。
- `collector_worker_slots` 中的 `task_id` 在任务完成后恢复为空。

## 4. 运行时检查

访问现有采集状态接口，查看返回值中的：

```json
{
  "queues": {
    "arp": {
      "pending": 10,
      "running": 2,
      "succeeded": 100,
      "total": 112
    }
  }
}
```

如果设备无法登录，检查 `device_collection_status`：

```sql
SELECT device_id, status, consecutive_failures,
       failure_class, next_retry_at, circuit_state,
       last_success_at
FROM device_collection_status
WHERE collector = 'arp'
ORDER BY updated_at DESC;
```

失败设备应当保留 `last_success_at`，并且 `next_retry_at` 不为空；连续失败达到阈值后 `circuit_state` 为 `open`。

## 5. 多进程验证

开发环境可以临时设置：

```env
ARP_WORKERS_PER_PROCESS=2
ARP_GLOBAL_WORKER_SLOTS=4
```

然后启动两个后端进程。验证重点：

1. 两个进程不会同时领取同一 `collector_task_queue.id`。
2. `collector_worker_slots` 中最多只有 4 个 ARP 任务处于运行状态。
3. 同一 `device_id` 在任意时刻只有一个 `running` 任务。
4. 停止一个进程，等待 `ARP_TASK_LEASE_SECONDS` 到期后，任务会被其他进程重新领取。

## 6. 本地自动化验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/vendor_audit -q
.\.venv\Scripts\python.exe -m py_compile `
  backend/main.py `
  backend/services/ip_locator_service.py `
  backend/services/collector_task_queue_service.py `
  backend/services/collector_worker_service.py
```

当前新增的队列、租约、迁移和 ARP 采集回归测试应全部通过。
