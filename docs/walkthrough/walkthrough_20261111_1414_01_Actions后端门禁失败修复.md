# GitHub Actions 后端门禁失败修复走查

## 完成摘要

GitHub Actions `Build and Sync to Release Repo` #774 的后端 pytest release gate 有 11 项失败、4134 项通过、2 项跳过。浏览器页与用户提供日志一致。失败均为测试调用契约、轻量 PostgreSQL 测试 schema 或期望数据未跟上现有代码；未改生产业务逻辑。

## 根因与处理

- IP 定位 trace 测试的 `_load_trace_port_identity` mock 仍只接受 3 个参数，当前服务会传入 VLAN。异常被终端证据读取层转为“证据不足”，使断言中的 LLDP 保护 mock 被触发。扩展 mock 签名，保留“不应查询 LLDP”的断言。
- 当前终端 API 测试直接调用 FastAPI 函数，省略新增的 `endpoint_class` 参数时拿到的是 `Query` 默认对象。每个直接调用现在显式传入 `endpoint_class='all'`。
- 权限范围测试的 `get_current_discovered_endpoint` mock 不接受新增 `visible_scopes` 参数。mock 现在允许该关键字参数，原 404 权限断言保留。
- IPAM inventory 的轻量 PostgreSQL schema 缺少 `prefixes.address_space_id` 和 `sites.tenant_id`。补齐 fixture 字段，并将 current-only observation 查询固定为空，使 legacy-only 用例不依赖未创建的 current observation 表。旧 `network_endpoints` 记录没有 canonical address-space 证据，测试现明确验证它不会仅凭 IP/站点匹配被并入正式 Prefix。
- CMDB CLI 接口地址返回值新增 `context_source`、`context_type`、`local_context_key`、`local_context_name`。更新对应精确断言，不移除任何字段校验。

## 实际修改文件

- `backend/tests/ip_locator/test_trace_service.py`
- `backend/tests/ipam/test_ipam_current_endpoint_api.py`
- `backend/tests/ipam/test_ipam_read_scope_matrix.py`
- `backend/tests/test_ipam_capacity_and_reconciliation.py`
- `backend/tests/vendor_audit/test_cmdb_cli_collection.py`
- `docs/plans/plan_20261111_1414_01_Actions后端门禁失败修复.md`
- 本 walkthrough 与 `docs/fixes/fix_*.md`

## 验证命令与结果

- 聚焦失败用例：上述五文件对应 9 个节点，参数化展开后 **11 passed**（61.27s）。
- 受影响完整测试文件：`pytest -q backend/tests/ip_locator/test_trace_service.py backend/tests/ipam/test_ipam_current_endpoint_api.py backend/tests/ipam/test_ipam_read_scope_matrix.py backend/tests/test_ipam_capacity_and_reconciliation.py backend/tests/vendor_audit/test_cmdb_cli_collection.py`：**76 passed**（104.16s）。
- `python scripts/validate_postgresql_only.py`：**0 violation(s)**，通过。
- `git diff --check`：通过。

## 未执行验证与剩余风险

- 本地未重跑完整后端 4,000+ 测试套件；推送后的 GitHub Actions 全量 release gate 是最终确认。
- 未运行前端测试（本批只有后端测试契约/fixture 改动），未运行数据库迁移或部署，未连接真实网络设备。
- 最新修复提交的 Actions 结果待推送后核验。若新 run 仍失败，需按该 SHA 的具体 job 日志继续处理，不把局部 76 项通过等同于全量 CI 成功。