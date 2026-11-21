# Monitoring V1 P0 落地记录

## 目标

按 `Nexora_Monitoring_V1_详细架构与落地实施方案.md` 的 P0-T01～P0-T20 建立第一条可编译、可回滚、可切换 Provider 的控制面闭环。文档中的 H3C/Huawei/Cisco 真实设备与 VictoriaMetrics 中断恢复属于部署环境 Gate，仓库测试不能伪造为已通过。

## 变更

- P0-T01/T02：`docs/monitoring/current_architecture.md` 审计当前 Native 链路并记录迁移边界。
- P0-T03/T16/T17/T20：`backend/services/metric_provider.py` 提供 Native、VictoriaMetrics、Shadow Provider、Counter Wrap 和 Shadow Compare 持久化契约。
- P0-T04～T07：`docker-compose.yml` 与 `monitoring/` 加入固定版本 VictoriaMetrics、vmagent、snmp_exporter 和 Generic IF-MIB PoC。
- P0-T08～T15：`m0232_monitoring_v1_control_plane.py`、`models/monitoring.py` 和 `monitoring_compiler.py` 建立 Collector、Module、Variant、Plan、Assignment、MetricDefinition、Target Snapshot、Config Version、Auth Alias、冲突/超时校验和回滚数据结构。
- P0-T14/T15：`collector_artifact_service.py` 增加 Collector 侧版本目录、原子复制、Last Known Good、Previous 和回滚校验；编译产物会在 Apply 前验证 Manifest、checksums、YAML 和 Auth Artifact。
- P0-T18/T19：`api/monitoring_v1.py` 接入控制面、Metrics Query、Collection Health；`NetworkMonitoring.tsx` 提供 Native/Shadow/VictoriaMetrics Provider 切换。
- 前端管理页面：`MonitoringManagementPage.tsx` 已接入 `/monitor/collection-plans`、`/monitor/modules`、`/monitor/collectors`、`/monitor/collection-health`，支持 Module/Variant 创建与发布、Plan 编译测试、Collector 编译/校验/发布/回滚和健康表格。

## 验证

```text
python -m py_compile <changed backend files>       PASS
pytest -q backend/tests -k "monitor or snmp or alert or probe"  PASS (162 passed, 2112 deselected)
pytest -q backend/tests/database -k "migration or db019 or db020 or db021"  PASS (54 passed)
pytest -q backend/tests/snmp/test_snmp_metric_semantics.py backend/tests/snmp/test_snmp_transport.py  PASS (34 passed)
pytest -q backend/tests/monitoring/test_monitoring_v1_compiler.py  PASS (7 passed)
pytest -q backend/tests/monitoring/test_collector_artifact_service.py PASS (2 passed)
pytest -q backend/tests/monitoring/test_monitoring_v1_deployment_contract.py PASS (2 passed)
python scripts/monitoring_poc_preflight.py         PASS (static; Docker runtime warning)
npm run lint                                      PASS
npm run build                                     PASS
npx vitest run --config vitest.config.ts src/utils/routeContext.test.ts PASS (8 passed)
pytest -q backend/tests/database/test_m0232_monitoring_v1.py      PASS (1 passed)
pytest -q backend/tests/vendor_audit/test_collection_plan_service.py backend/tests/vendor_audit/test_collection_plan_bulk_api.py PASS (46 passed)
python + PyYAML docker-compose.yml parse          PASS (Docker CLI not installed on this host)
scripts/validate_postgresql_only.py               PASS (0 violations)
```

## 尚需现场 Gate

聚焦套件最终结果为 `162 passed, 2112 deselected`；迁移测试 `10 passed`，P0 migration + SNMPv3 测试 `1 passed`，Compiler/Provider 测试 `7 passed`，Collection Plan 回归 `46 passed`。真实设备矩阵、错误 Community 分类、Collector Last Known Good、vmagent Queue 补传、Credential Rotation、ifIndex 变化、300 台压测及告警 Flapping 仍应在 PoC 环境执行方案中的 GATE-01～GATE-18；默认 Provider 保持 `native`，在这些 Gate 通过后再设置 `MONITORING_METRIC_BACKEND=shadow` 或 `victoriametrics`。
