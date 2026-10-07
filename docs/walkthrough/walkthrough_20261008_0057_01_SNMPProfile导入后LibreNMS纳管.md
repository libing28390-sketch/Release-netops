# SNMP Profile 导入后 LibreNMS 纳管：执行记录

## 完成摘要

修复资产导入与 LibreNMS 之间断开的纳管链路：使用导入资产实际保存的管理 IP 和 SNMP Profile 调用 LibreNMS 官方设备 API，精确确认原生设备后建立本地 binding。远端纳管在 CMDB 提交后执行，逐行报告结果，失败不会回滚资产。

同时补齐 SNMPv2/v3 资产 Profile 校验与表单/模板、原生硬件诊断反馈和 Grafana CPU/内存/温度原生样本覆盖，并抑制 cAdvisor 对无用 smaps 指标的重复读取告警。

## 关键实现

- `librenms_enrollment_service` 按设备读取已保存凭据并在服务端解密；v2c/v3 参数使用受控字段映射发送到 LibreNMS。无效 Profile 不会回退到旧 Community。
- 已存在设备按唯一管理 IP 查找并更新 SNMP Profile；未存在时在唯一健康 LibreNMS 实例上调用 Add Device API。仅在原生 ID 与目标管理 IP 精确核对后写入本地关联。
- 资产事务提交后最多并行纳管 5 台设备；重复行会去重并映射回每个导入行。权限、配置、冲突、超时等结果均返回安全的状态和说明。
- SNMPv3 Profile 可在资产编辑/导入中选择；诊断服务显示 LibreNMS 原生采集结果与缺少绑定的说明。Grafana 硬件面板以原生硬件样本统计设备覆盖。
- Compose 的 cAdvisor 指标禁用项增加 `referenced_memory`。

## 实际修改文件

代码与测试文件详见同批次修复记录 `docs/fixes/fix_20261008_0057_01_SNMPProfile导入后LibreNMS纳管.md`；实施方案为 `docs/plans/plan_20261007_2329_01_LibreNMS自动关联与诊断反馈.md`。

## 验证命令与结果

- `.venv\Scripts\python.exe -m pytest backend/tests/monitoring/test_librenms_runtime_client.py backend/tests/monitoring/test_librenms_enrollment_service.py -q -p no:cacheprovider`：55 passed。
- LibreNMS 诊断、资产导入、导入模板、Grafana 查询和部署契约定向组合：99 passed。
- `npm run test:frontend`：124 个文件、476 项通过。
- `npm run lint`：通过。
- `npm run build`：通过。
- `python scripts/validate_postgresql_only.py`：0 项违规。
- Compose YAML、修改模块 `compileall` 与 `git diff --check`：通过。
- `.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider`：退出码 0，3453 passed、0 failed、1 skipped、26 subtests passed，耗时 5239.83 秒。

## 未执行验证与剩余风险

- 暂未在真实 LibreNMS/HCL 设备上验证 API Token 权限、SNMP Profile 应用及实际硬件数据；用户此前将设备级验证留待代码推送后执行。
- Add Device 超时后如果 LibreNMS 尚未完成 Discovery，地址可能暂不可读；结果提示等待一轮 Discovery 后重试，以降低远端重复添加风险。
- 从远端 API 预检到本地 binding 提交之间仍存在并发竞争窗口；唯一约束会阻止覆盖已有 binding，但两个同时到达的调用可能需要人工复核冲突。
- 远端 GitHub Actions 结果待推送后核对。
- 全量后端唯一跳过项为 `backend/tests/ip_locator/test_topology_lldp_snapshot_service.py:246`，因测试需要明确授权 Redis 中的短期密钥；与本次变更无关。
