# 接口采集联动 VLAN

## 完成摘要

实际任务 job-4a4bbe29dafd 成功 14 台、失败 1 台；成功目标的 cli_categories 只有 interfaces/interface_description，数据库没有 VLAN snapshot/observation。原因是两层采集策略门控都把默认关闭的 VLAN 排除。

## 修改文件及行为

- backend/services/cmdb_cli_collection_service.py：手动接口采集附带 VLAN；显式 VLAN-only 调用同样可采集。使用同一个 PlatformActionSession。
- backend/services/read_only_collection_adapter.py：透传已有 policy_override_categories；CMDB 调用仅覆盖 vlan。默认调用保留原策略。
- backend/tests/vendor_audit/test_cmdb_cli_collection.py：覆盖 VLAN 默认关闭时同会话双域写入、VLAN-only，以及覆盖参数穿过适配器进入实际类别选择。

没有修改监控代码、全局调度策略、命令映射或解析模板逻辑。

## 验证

- `.venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests/vendor_audit/test_cmdb_cli_collection.py`：最终 31 passed in 135.33s；临时 PostgreSQL 数据库已删除。
- scripts/validate_postgresql_only.py：0 violations。
- git diff --check：通过。
- 实机 S6850_1（CLI）：接口快照 59 条，VLAN 快照 2 条，端口成员 3 条；数据库 observation count=2，list_vlans(page=1) total=2。
- 浏览器重新加载 http://192.168.56.1:5400/cmdb/vlans 后实际显示 VLAN 100/112，共 2 个 VLAN 域、4 条设备展示行（S6850_1/S6850-2），3 条端口成员；空列表已恢复。
- 本机服务启动使用 `node scripts/dev-internal.mjs`，终端会话 57533；已恢复后端与前端，未修改启动脚本。
- 本次补丁尚未提交或推送，未运行全量回归；变更范围为手动 CMDB 类别选择及适配器可选参数，已完成聚焦验证和单设备实机验证。

## 边界与风险

实机验证覆盖一台 H3C 交换机，未批量重采全部设备；新增 VLAN 只读命令仍沿用现有平台动作和解析完整性校验，设备不支持时会报告错误并保留旧成功快照。回滚三个实现/测试文件的本次补丁即可。
