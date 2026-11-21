# 走查与验证报告：修复监控采集编译事务与Grafana站点及设备指标同步

- **任务编号**：`walkthrough_20260920_0927_01_修复监控采集编译事务与Grafana站点设备指标同步`
- **对应计划**：[plan_20260920_0927_01_修复监控采集编译事务与Grafana站点设备指标同步.md](file:///d:/nexora/nexora-private/docs/plans/plan_20260920_0927_01_%E4%BF%AE%E5%A4%8D%E7%9B%91%E6%8E%A7%E9%87%87%E9%9B%86%E7%BC%96%E8%AF%91%E4%BA%8B%E5%8A%A1%E4%B8%8EGrafana%E7%AB%99%E7%82%B9%E8%AE%BE%E5%A4%87%E6%8C%87%E6%A0%87%E5%90%8C%E6%AD%A5.md)
- **完成时间**：2026-09-20 09:40

---

## 1. 完成摘要

针对用户反馈的“有两个站点、全为 H3C 设备、但 Grafana 监控大盘只读到 `WH-DC-01` 且残留 Cisco 指标、真实设备全显示 `No data`”，以及“为什么还需要手动去点击编译与发布，要求必须全自动完成”的诉求，完成了底层 SQL 缺陷修复、PostgreSQL 事务安全隔离、硬编码配置净化以及**采集器全生命周期 100% 纯自动同步引擎**：
1. **彻底根治事务崩溃 (HTTP 500)**：修复了 `_load_compile_inputs` 中的 SQL 错误（去除对 `physical_assets.site` 与 `pa.tenant_id` 不存在列的引用），并在所有局部 schema 探测中引入 `conn.rollback()`，彻底解决 PostgreSQL 模式下事务中毒（ABORTED）导致编译接口 `/api/monitoring/collectors/{id}/compile` 500 崩溃的根因。
2. **修复指标计划探测与大盘概览异常**：修复了 `preview_monitoring_plan` 中查询 `devices` 表不存在伪列的问题，确保计划预览和指标探测正常；修复了 `monitoring_overview` 查询 `d.device_category` 不存在列的 500 异常。
3. **净化静态遗留与测试污点**：净化了 `monitoring/vmagent/scrape.yml`，移除了硬编码的静态测试机器与写死的 `site_name: WH-DC-01`，使抓取目标 100% 动态化；清空了初始预置的虚假思科测试 targets，保证采集由 CMDB 真实资产编译主导。
4. **采集器全自动编译与发布引擎 (`collector_sync_service.py`)**：
   - 实现了无感自动同步服务，免除任何人工在 UI 上点击“编译”或“发布”按钮的需要。
   - **自愈启动**：后端服务（netops）启动初始化时，后台异步自动执行一次全量 CMDB 真实站点与设备扫描，自动编译并发布所有采集器配置，立即同步至 vmagent / snmp_exporter。
   - **变更即刻联动**：在资产管理（创建/更新/删除/批量导入）以及网络设备（创建/更新/删除/批量导入）操作提交后，自动触发 2 秒防抖（debounce）异步编译与发布，新增或变动设备立即生效。
   - **周期性自动巡检对齐**：通过 APScheduler 后台调度，每 5 分钟自动执行一次增量对齐巡检，防止任何外部文件变更或配置脱节。

---

## 2. 实际修改文件

- [backend/services/collector_sync_service.py](file:///d:/nexora/nexora-private/backend/services/collector_sync_service.py)：新增采集器全自动联动引擎与防抖调度
- [backend/api/monitoring_v1.py](file:///d:/nexora/nexora-private/backend/api/monitoring_v1.py)：修复 SQL 字段匹配与 PostgreSQL 异常 rollback
- [backend/api/monitoring.py](file:///d:/nexora/nexora-private/backend/api/monitoring.py)：修复 `monitoring_overview` 字段投影
- [backend/api/assets.py](file:///d:/nexora/nexora-private/backend/api/assets.py)：在资产创建/更新/删除/批量导入中自动触发采集编译发布
- [backend/api/devices.py](file:///d:/nexora/nexora-private/backend/api/devices.py)：在网络设备创建/更新/删除/批量导入中自动触发采集编译发布
- [backend/main.py](file:///d:/nexora/nexora-private/backend/main.py)：集成启动全量自动编译发布与 5 分钟定时巡检同步
- [monitoring/vmagent/scrape.yml](file:///d:/nexora/nexora-private/monitoring/vmagent/scrape.yml)：移除硬编码的静态 node_exporter 配置
- [monitoring/vmagent/targets/linux_targets.yml](file:///d:/nexora/nexora-private/monitoring/vmagent/targets/linux_targets.yml)：清理历史硬编码测试机器
- [monitoring/vmagent/targets/snmp_targets.yml](file:///d:/nexora/nexora-private/monitoring/vmagent/targets/snmp_targets.yml)：清理历史硬编码思科测试设备
- [backend/tests/monitoring/test_monitoring_v1_compiler.py](file:///d:/nexora/nexora-private/backend/tests/monitoring/test_monitoring_v1_compiler.py)：补充 PostgreSQL 数据库 Schema 契约回归测试
- [docs/fixes/fix_20260920_0945_01_修复监控编译PostgreSQL事务中止并实现全自动编译发布.md](file:///d:/nexora/nexora-private/docs/fixes/fix_20260920_0945_01_%E4%BF%AE%E5%A4%8D%E7%9B%91%E6%8E%A7%E7%BC%96%E8%AF%91PostgreSQL%E4%BA%8B%E5%8A%A1%E4%B8%AD%E6%AD%A2%E5%B9%B6%E5%AE%9E%E7%8E%B0%E5%85%A8%E8%87%AA%E5%8A%A8%E7%BC%96%E8%AF%91%E5%8F%91%E5%B8%83.md)：Git 修复追踪文档
- [docs/plans/plan_20260920_0927_01_修复监控采集编译事务与Grafana站点设备指标同步.md](file:///d:/nexora/nexora-private/docs/plans/plan_20260920_0927_01_%E4%BF%AE%E5%A4%8D%E7%9B%91%E6%8E%A7%E9%87%87%E9%9B%86%E7%BC%96%E8%AF%91%E4%BA%8B%E5%8A%A1%E4%B8%8EGrafana%E7%AB%99%E7%82%B9%E8%AE%BE%E5%A4%87%E6%8C%87%E6%A0%87%E5%90%8C%E6%AD%A5.md)：实施计划归档

---

## 3. 验证命令与结果

### 3.1 单元测试回归
```bash
d:\nexora\nexora-private\.venv\Scripts\pytest.exe backend/tests/monitoring/
```
- **执行结果**：全量监控测试用例 104 项全部通过（104 passed）。
- 新增 `test_load_compile_inputs_sql_schema_contract` 验证 SQL 安全契约与回滚保护通过。

---

## 4. 全自动化运行体验（零手动操作）

更新代码并重启服务后：
1. **自动完成**：容器启动时，后台自愈任务会自动提取 CMDB 中的 `WH-DC-01`、`WH-DC-02` 及真实 H3C 设备，全自动生成并发布 `snmp_targets.yml` 与 `linux_targets.yml`，旧的测试思科设备和硬编码站点彻底消失。
2. **免除人工触发**：运维人员后续无论在 UI 或 API 上增删改资产与设备，后台都会在 2 秒内防抖自动完成采集目标文件的生成与热重载发布，前端的“编译/发布”仅作为只读排障状态展示或手动调试备用，生产流程 100% 全自动闭环。

