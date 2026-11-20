# CMDB 页面布局与接口采集范围走查

## 变更

- CMDB 共用管理页补齐根容器和滚动容器的 `min-width/min-height` 约束；接口表避免内容换行，并将宽表横向滚动限制在表格容器内。
- CMDB 资产页、资源检索页移除依赖 `100vh` 的页面最小高度，改为跟随内容区；补齐网格、筛选区和表格滚动容器的宽度约束。
- 人工“采集接口”入队时仅选择在线网络设备：按资产 `asset_type` 判定，并复用服务器分类器排除服务器、虚拟机等设备；worker 执行前再次核验在线状态和设备分类，防止任务排队后设备类型变化仍被采集。
- 没有符合条件的在线网络设备时，API 返回 409 并说明原因。未改变周期采集范围、设备配置或数据库结构。

## 验证与限制

- `npm run lint`：通过。
- 隔离目录生产构建：`npx vite build --outDir node_modules/.cache/codex-cmdb-arp-final-build-20261010 --emptyOutDir`，通过（4319 modules）。
- `python -m py_compile backend/api/cmdb.py backend/services/interface_collection_service.py backend/services/job_worker.py`：通过。
- `git diff --check`：通过。
- 未运行测试、浏览器视觉验收或真实设备采集；未部署。宽表在小视口下使用表格内横向滚动。
