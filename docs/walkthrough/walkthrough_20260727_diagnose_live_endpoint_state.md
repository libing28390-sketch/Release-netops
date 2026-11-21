# 诊断末端接口实时状态修复

## 变更目标

修复源设备 `10.253.0.2` 到目标 `10.253.10.10` 的诊断误判：目标接入交换机端口已经 shutdown/down 时，历史路由、ARP/MAC 或拓扑定位缓存不能继续把目标显示为可达。

## 实现结果

- ICMP P8 改为优先从源设备执行设备侧 Ping，并保留源地址。
- 命中 `network_endpoints` 后，诊断通过现有 operational-data/TextFSM 接口采集链路重新检查终端接入交换机端口。
- 实时接口状态为 down 时，P5 路径标记为中断，报告明确指出最后一跳设备和端口，不再显示“物理路径正常但目标端未响应”。
- 即使历史路径仍返回 reachable，只要 P8 探测失败，目标 hop 也会降级为 timeout；前端不会继续绘制绿色目标节点。
- 接口名称比较统一使用 `core.interface_utils.normalize_interface_name`，兼容 `GE0/0/1` 与 `GigabitEthernet0/0/1`。

## 验证

- `py -3.11 -m py_compile backend/services/diagnose_service.py backend/services/connectivity_service.py backend/tests/vendor_audit/test_diagnose_endpoint_state.py`：通过。
- `npx tsc --noEmit --pretty false`：通过。
- `npm run lint`：通过。
- `npm run build`：通过。
- `py -3.11 -m pytest backend/tests`：未执行，当前 Python 环境未安装 pytest；新增回归用例已放置在 `backend/tests/vendor_audit/test_diagnose_endpoint_state.py`。

## 现场复测

在 LSW6 的 PC1 上联接口保持 shutdown 后重新执行诊断，预期结果为：

1. P8 ICMP 丢包率 100%，状态为 failed；
2. 路径最后一跳显示 LSW6 对应接入口 DOWN；
3. 目标主机显示 timeout/unreachable，不再显示绿色“目标主机”或“物理路径正常”；
4. 恢复接口后再次执行诊断，只有实时接口状态与源设备 Ping 均成功时，才显示 reachable。
