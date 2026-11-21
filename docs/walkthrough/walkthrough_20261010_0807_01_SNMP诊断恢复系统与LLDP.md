# SNMP 诊断与拓扑 LLDP 完整读取 walkthrough

## 目标与根因

恢复 `/monitor/snmp-walk` 的系统信息与 LLDP 邻居视图，并确保 `/monitor/topology` 的 LLDP walk 和图数据读取不会因默认行数上限截断。`5145245c` 将旧系统/LLDP 诊断视图替换为 LibreNMS 硬件规则探测；拓扑 SNMP collector 仍默认每个 LLDP MIB 列最多 10,000 行，拓扑 links/graph 前端还固定请求 5,000 行，后端缺省同样返回 5,000、上限 20,000。

## 实施

- `backend/api/devices.py` 新增 `POST /api/platform-registry/snmp-system-lldp-test`：只接收 `{device_id}`，复用现有租户/设备 scope 和服务端绑定凭据，读取固定 MIB-2 系统 scalar 与标准 LLDP-MIB；不接受自定义 OID 或凭据输入。
- `backend/services/snmp_service.py` 让 `_snmp_walk` 和 `collect_snmp_lldp_neighbors` 支持 `max_rows=None`。仅显式传入数字时才按行数截断，未改变其他调用的既有默认值。
- 诊断 endpoint 与 `backend/services/topology_service.py` 的拓扑 SNMP 路径都显式传 `max_rows=None`。拓扑每个 LLDP 列 walk timeout 为 30 秒；9 列并发。SNMP UDP transport 配置为每次 1 秒、最多重试 2 次。全局 SNMP semaphore 默认并发 30；等待 semaphore 的时间不包含在单列 walk 的 30 秒里，但包含在设备任务外层时限内。
- 拓扑设备任务默认 timeout 300 秒，可通过 `TOPOLOGY_DISCOVERY_TIMEOUT_SECONDS` 配置为 30–3600 秒；设备并发默认 6。没有拓扑整轮 wall-clock deadline，run lease 通过 heartbeat 续租。SNMP 超时或列级失败会保留可用数据并标记 `partial`；没有可用邻居时按既有策略尝试 SSH CLI fallback。设备外层 timeout 会明确结束为失败，不会把超时结果标成完整快照。
- `backend/api/topology.py` 与 `backend/services/topology_graph_service.py` 在 links/graph 请求未提供 `limit` 时不附加 SQL `LIMIT`；显式传 limit 的旧调用仍兼容并保留 20,000 的上限。
- `src/hooks/useTopology.ts` 的 `/monitor/topology` links 和 graph 请求不再发送 `limit=5000`。诊断 UI 默认展示系统信息与 LLDP，硬件规则/已采样硬件样本保留在次级页签；邻居列表没有前端切片。

## 验证

- `npm run lint`：通过（`tsc --noEmit`）。
- `npm run build -- --outDir ...`：通过。仓库 `scripts/build-frontend.mjs` 未把附加参数传给 Vite，实际写到 `dist/`；构建后已将此前干净的受跟踪 `dist/index.html` 还原。构建产生的 `dist/assets/` 属于忽略目录。
- `python -m py_compile backend/api/devices.py backend/services/snmp_service.py backend/services/topology_service.py backend/api/topology.py backend/services/topology_graph_service.py`：通过。
- `python scripts/validate_postgresql_only.py`：通过，0 项违规。
- `git diff --check`：通过；只有工作树既有的 LF/CRLF 转换提醒。
- 未运行测试套件。未通过浏览器访问线上页面：用户提供的 HTTPS 地址返回证书颁发机构错误；没有绕过浏览器安全提示。未部署或向真实设备发起采集。

## 边界与剩余风险

- SNMP walk 不设 LLDP 行数上限，但 30 秒单列 deadline 与 300 秒默认单设备 deadline 仍是保护边界；超大表、慢设备或全局 semaphore 排队可能返回 partial/failed。需要看状态字段，不能把 partial 当作全量邻居。
- `/monitor/topology` 默认读取全部已授权 links/graph 数据；大型拓扑会增加响应体、服务端内存和前端渲染开销。非页面调用方仍可显式传 `limit`，上限为 20,000。
- 当前只完成仓库代码与静态构建核验；等待部署后再在目标环境确认 LLDP 展示与真实设备数据完整性。
