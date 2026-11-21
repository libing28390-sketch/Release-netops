# MIB 引导缓存与拓扑 SNMP 降级

## 结果

LibreNMS MIB 导入增加跨进程缓存判据。新进程核对 manifest、全部候选文件 SHA256、source/import run 状态、parser 版本、规则来源/契约版本及实际节点记录总数。全部匹配时跳过符号依赖索引和逐文件解析；文件、规则、解析器或数据库记录完整性改变时仍走原导入流程。PostgreSQL advisory lock 串行多个 worker 的首次导入。

缓存命中仍枚举并哈希候选 MIB 文件，以发现本地文件改动。进一步现场核对发现，原来的文件大小比较和“所有 OID 均已解析”门槛让缓存永远无法命中；本次已修正。相同输入与解析器产生的未解析节点继续显示在 MIB 详情，不再作为每次启动重导理由。现场只读 marker 和新进程启动日志均已确认命中。

拓扑发现开始时会先删除本轮目标设备的旧 LLDP 观测和对应物理图投影，再开始并发采集；因此失败设备保留 CMDB 设备节点、原图标和 SNMP/SSH 异常角标，但旧邻居不会继续被画成本轮拓扑。只有本轮有效采集到的邻居会生成边；例如 `.3/.4` 采集失败且没有其他设备本轮报告 `.5/.6` 时，不会从旧观测推导 `.5/.6` 的关系。已登记在 CMDB 的 `.5/.6` 仍作为各自资产节点显示。SNMP 返回有效行但部分 MIB walk 失败时会保存有效行并标记快照不完整；SNMP 失败后 SSH 成功时，SSH 结果写入当前快照，同时任务标记为部分异常。协议错误元数据保留脱敏后的 SNMP、SSH 状态与详情。

身份规则已由最新现场修正收敛：LLDP 报出 IP 时先匹配 CMDB 管理地址，再匹配同租户、同一发现 run、当前代次的设备自身接口 IP 事实；IP 仍未确认或有冲突时不回退名称猜测。SNMP 与 CLI 采集完成后统一重匹配，设备名称不一致仍按既定规则显示 IP。画布只包含纳管资产，因此 WH-DC-02 始终为 8 个设备图标。完整证据见配对的最新拓扑身份冲突诊断 walkthrough。

拓扑提取器兼容 `neighbor_management_ip`、`neighbor_ip_address`、`neighbor_chassis_id` 及已标准化的端口/名称字段；当前有效行缺少索引字段时仍会从原始 JSON 恢复。匹配索引读取设备/资产各自的 IP 与序列号，以及设备 `sys_name`、资产主机名和标签。发现开始时清理目标设备的旧观测后，这些兼容逻辑只处理当前保留的观测，不会让上轮名字/IP 再次造出节点。发生 IP/序列号冲突或无法唯一匹配的本轮观测继续隔离为未匹配节点，不用型号、楼层或相似名称猜测合并。

拓扑 API 将持久化采集异常按设备 ID 返回。画布保留原有厂商/设备图标，在同一节点角落叠加琥珀色或红色 `!` 角标；悬浮卡和右侧设备面板分别显示 SNMP、SSH 结果与错误详情。发现进度卡在任务运行时显示百分比（未到终态时最多 99%），终态显示实际完成百分比和任务状态；成功设备只计入汇总，结果区只列失败、部分异常或取消项。

## 关键实现

- `backend/services/librenms_mib_service.py`：通过 manifest 和数据库持久状态验证是否可以跳过昂贵的 MIB 建索引/解析过程，并使用 PostgreSQL session advisory lock 避免多 worker 同时导入。
- `backend/tests/snmp/test_librenms_mib_cache.py`：隔离 PostgreSQL 覆盖 CRLF 文本大小差异、稳定未解析节点、节点丢失，以及源码/hash/parser/规则来源及契约变化。
- `backend/services/topology_service.py`：处理 per-protocol 结果、完整与部分快照边界、标准/旧版 LLDP 身份字段兼容、设备/资产身份别名索引、身份归并和持久采集异常读取。
- `backend/services/topology_service.py`：每轮开始清理目标设备的旧 LLDP 行和受影响物理链接投影，并刷新图模型后再并发采集。
- `backend/api/topology.py`：在链接响应中返回当前授权设备范围内的拓扑采集异常。
- `src/hooks/useTopology.ts`：把异常状态按现有 CMDB 设备 ID 合并到画布设备数据。
- `src/components/TopologyGraph.tsx`、`src/components/TopologyInspectorPanel.tsx`：保留原设备图标并叠加状态角标，提供悬浮与选中详情。
- `src/pages/TopologyPage.tsx`：状态匹配进度百分比，成功项从最终结果列表中收敛。

## 验证与限制

- `python -m py_compile` 覆盖本次修改的拓扑、SNMP、MIB 服务和拓扑 API 文件：通过。
- `git diff --check`：通过；仅提示工作区中既有 `dist/index.html` 和平台绑定测试文件的 LF/CRLF 转换警告。
- `npm run lint`（`tsc --noEmit`）：通过。
- 用户映射、分隔符碰撞、本轮观测及链接投影清理、未选设备数据保留和清理先于并发采集的聚焦 pytest：30 passed。
- 上述为早期检查；本次已补充本机 PostgreSQL、只读设备采集和新发现 run 验证，结果见下文。最终浏览器截图因 CDP 连接超时未完成，未声称视觉验收通过。

## 2026-10-01 最新现场缓存修正与验证

- 原缓存比较文件系统原始 `st_size` 与数据库规范化、解码后文本的 UTF-8 大小，217 个文件均不相等；但全部文件 SHA256 已一致，因此移除这个冗余且口径不同的大小条件，保留完整内容哈希。
- 161 个文件含当前解析器稳定产生的未解析 OID，共 42042 个节点。原条件只统计数值 OID，导致每个新进程重新导入这 161 个文件；现改为核对实际数据库节点记录总数。217 个文件的 `node_count` 均与实际记录一致，总计 67612 个节点。
- 未解析节点仍保留并可查看；输入、parser、规则依赖变化或数据库节点丢失时仍重新导入。没有数据库迁移，没有强制执行额外 MIB 导入。
- `cd backend; ..\.venv\Scripts\python.exe -m pytest tests/snmp/test_librenms_mib_cache.py tests/snmp/test_mib_repository_import.py -q`：7 passed，覆盖缓存条件与现有导入回归。
- PostgreSQL-only 扫描：0 violations；相关 Python 编译与 diff 检查通过。
- 现场只读缓存判定命中 `mib-run-40a202303a214784`。16:07 新后端进程日志确认：`Reusing completed LibreNMS MIB snapshot mib-run-40a202303a214784 (217 files, parser mib-regex-v2)`，本次启动复用已有快照。
- 本机新拓扑 run `59982723-fd37-4dee-8a01-427b2abf1575`：8/8 成功、34 条观测全部匹配、11 条双向确认链路、0 待确认邻居。拓扑范围 61 个不同测试、前端 lint 与 Vite 构建通过；详情见最新拓扑报告。
- 未运行全量发布回归，没有提交、推送或部署。

## 回滚范围

回滚本次拓扑状态 API、身份归并、每轮 LLDP 历史清理和渲染/进度改动，以及 MIB persistent-cache 判据即可恢复旧行为。无需数据库迁移。每轮删除旧来源观测是用户明确要求的运行行为；保留工作区中既有平台绑定、`dist/index.html` 及其他用户文件变更。
