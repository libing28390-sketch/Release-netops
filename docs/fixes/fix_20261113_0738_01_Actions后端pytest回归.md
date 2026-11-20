# Actions 后端 pytest 回归修正

## 现象

首次推送的 Actions workflow `43328406081` 在 `Run backend pytest release gate` 失败。全量测试收集 4154 项，失败 3 项；前置 PostgreSQL 启动和依赖安装均成功。

## 根因与处理

1. `test_v2c_raw_global_alias_context_key_is_not_overwritten` 仍断言“SNMPv2c 没有任何 VRF/路由上下文时归属未知”。当前实现按已确认规则把无 VRF 的默认 SNMPv2c ARP 表标为 Global；测试更新为验证 Global 上下文和保留 `global` 键。
2. `test_current_endpoint_routes_use_only_current_observations_and_explicit_writes` 的测试设备没有接入/AP角色，终端投影按角色过滤后结果为空。测试夹具改为明确标注 `access`，继续检查当前快照读取和显式登记契约。
3. `test_arp_sweep_device_selection_uses_bounded_cursor_batch` 把五个候选都标为 `router`，与现行只采集接入交换机/AP的过滤条件冲突。测试增加一个 `router` 负例，其余标为 `access`，并验证游标仍选中正确的两个接入设备。

## 修改文件

- `backend/tests/ip_locator/test_arp_current_snapshot_collector.py`
- `backend/tests/ipam/test_ipam_current_endpoint_api.py`
- `backend/tests/vendor_audit/test_ip_locator_arp_contract.py`

未修改业务代码；调整的是与当前已确定行为不一致的测试断言和夹具。

## 验证

- 首次 Actions 全量 pytest：4154 项收集，3 项失败，失败名与原因见上。
- 本机 PostgreSQL 测试不运行：没有可确认隔离且可丢弃的 `DATABASE_URL`；pytest fixture 会先初始化 source DB。
- 第二次 Actions 将运行隔离 PostgreSQL 的全量 pytest 与后续发布门禁；最终结论以新 SHA 的 Actions 为准。
- 提交前执行三份 Python 测试文件 AST 解析和 `git diff --check`。

## 风险与回滚

该提交只同步既有角色与 Global 归属行为的测试预期，不修改采集或 IPAM 数据逻辑。若全量门禁仍发现差异，按新日志继续修复；不回滚用户现场数据，也不重写已有提交。
