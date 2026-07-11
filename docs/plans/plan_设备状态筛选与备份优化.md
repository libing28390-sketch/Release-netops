# 实施计划 - 设备状态筛选与备份逻辑优化

## 1. 自动化执行页面状态筛选不一致问题

* **问题分析**：
  * 在自动化执行（`/automation/tasks`）页面的左侧“快速筛选”中，当选择 `离线` 状态时，过滤算法在 `src/pages/AutomationExecute/index.tsx` 里的 `filteredDevices` 计算中使用的是严格等于：`d.status === statusFilter`。
  * 而实际上，数据库中表示不可达或未完成初始化的设备，其 status 可能被记录为 `'pending'`（待定）或其它非 `'online'` 的值。
  * 列表渲染和总览栏（例如“共8台，7台在线”）中对 `离线` 设备的渲染规则是：只要 `status !== 'online'` 就视为离线。
  * 这导致 `pending` 状态的设备在列表中呈现为“离线”状态，但在左侧“离线”按钮筛选时，因为 `'pending' !== 'offline'` 而被全部过滤掉，导致匹配数量为 0。
* **解决方案**：
  * 修改 `src/pages/AutomationExecute/index.tsx` 里的状态过滤规则：
    * 当 `statusFilter === 'online'` 时，匹配 `d.status === 'online'`。
    * 当 `statusFilter === 'offline'` 时，匹配 `d.status !== 'online'`。
    * 这样过滤规则与列表渲染和底部摘要展示的判定完全对齐，恢复了一致性。

## 2. 批量配置备份速度优化

* **方案说明**：
  * 后端备份逻辑已经对离线（`offline`）或初始化待定（`pending`）设备进行了数据库级的自动剔除（`WHERE status = 'online'`），从源头上规避了对绝对不通设备的重试耗时。
  * 同时，将 Netmiko 的并发备份处理数提升至 30（基于 `BACKUP_CONCURRENCY` 环境变量，缺省为 30），并使用 50 线程池支撑并发拉取，降低排队积压。
