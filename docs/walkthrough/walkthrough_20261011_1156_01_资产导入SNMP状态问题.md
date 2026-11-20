# 资产导入 SNMP 主机名与状态展示

## 完成摘要

- 资产导入后的 hostname 同步现支持 SNMPv2c 和 SNMPv3；新资产和重复导入均进入同步队列。
- 在线/离线系统标签只在状态明确为 `online` 或 `offline` 时显示。`pending`、空值及其他未知状态会移除状态标签，不再伪装成离线。
- 周期监控现先用已配置的 SNMPv2c/v3 profile 查询 `sysUpTime.0`：有响应即判在线并跳过 ICMP；SNMP 失败或超时后才使用 ICMP/管理端口兜底。只有 SNMP 与兜底都失败才判离线。
- 快速状态巡检与慢速采集巡检共用该探测流程；慢速路径复用 SNMP 探测结果，不再额外重复查询 `sysUpTime.0`。SNMP 采集失败告警仍与设备在线状态分开维护。
- 离线告警文案改为“网络可达性探测未响应”，不再把状态判定错误描述为单独 Ping 超时。
- 已只读查看用户给出的容器页面，未修改远程数据、未部署。

## 实际修改文件

- `backend/api/assets.py`
- `backend/services/tag_service.py`
- `backend/services/background_monitor_service.py`
- `docs/plans/plan_20261011_1156_01_资产导入SNMP状态问题.md`
- `docs/walkthrough/walkthrough_20261011_1156_01_资产导入SNMP状态问题.md`

## 关键实现说明

- 移除了新资产与重复导入的 SNMPv3 hostname 队列排除逻辑。
- hostname 同步按已解析的 SNMP 配置选择 v2c community GET 或 v3 profile GET，并继续调用现有 `sync_device_hostname_metadata`，事务性更新设备、资产、拓扑观察及 `sys_name`。凭据不进入响应或日志。
- `sync_device_status_tag` 对未知/等待状态移除已有系统状态标签；确定在线/离线时仍按原逻辑维护标签。
- 新增 `_probe_device_reachability_snmp_first`，仅对设备行已配置 SNMP profile 或 community 的设备尝试 SNMP；通过 `resolve_collector_credentials` 读取凭据，使用标准 `sysUpTime.0` 做有限时探测，支持 v2c 与 v3。
- SNMP 成功时跳过 ICMP/TCP；SNMP 无响应、超时或配置读取异常时仍走现有 ICMP 与管理端口探测。SNMP 失败本身不会写入离线状态。
- SNMP 凭据解析放入线程池，避免新增的同步数据库读取阻塞快速巡检事件循环。
- 快速巡检将 collector source/transport 记录为实际成功方式，并记录是否尝试 SNMP 及是否使用 fallback；慢速巡检复用同次 SNMP 探测结果，SNMP 失败且 ICMP/TCP 成功时继续将 SNMP 失败作为独立采集告警处理。
- 如果 SNMP 端等待到 1.5 秒超时，才会开始 ICMP/TCP 兜底；SNMP 正常响应时会省去 ICMP 与 TCP 探测。

## 验证命令与结果

- `git diff --check -- backend/services/background_monitor_service.py docs/plans/plan_20261011_1156_01_资产导入SNMP状态问题.md`：通过，没有空白错误；Git 提示后台服务文件后续会规范化为 CRLF。
- Python AST 解析 `backend/services/background_monitor_service.py`：通过，语法有效。
- 人工调用链审查：新建/重复导入 → 凭据解析 → v2c/v3 sysName GET → hostname 同事务写回 → `hostname_sync` 响应摘要。
- 人工状态链审查：`process_device_fast` 与 `_process_device_raw` 均调用 SNMP-first helper；SNMP 响应直接更新在线状态，SNMP 失败转入 ICMP/TCP，双重失败才更新离线状态。
- 人工凭据链审查：使用 `resolve_collector_credentials`，v2c 与 v3 均只把凭据传给既有 SNMP GET；新增日志仅包含 IP 和异常类型，不包含凭据。
- 远程页面 `https://192.168.204.128/assets/network-devices` 显示 15 台设备：1 台“在线”、14 台“等待中”；等待中的设备还带“离线”自动标签，证实标签将 `pending` 错误折叠成 `offline`。

## 未执行验证及原因

- 未运行测试或部署远程容器。当前请求未要求测试或部署；静态语法和 diff 检查已完成。
- 远程页面只读浏览；没有发起资产导入，因此没有对真实 SNMP 凭据或设备进行探测。

## 剩余风险与后续建议

- 若现场继续使用 SNMPv2c，原实现已有 v2c 同步路径；如仍不同步，应查看导入 API 的 `hostname_sync.failed_items` 和凭据绑定，而不要仅根据列表页面判断。
- 当前运行的容器仍是已有部署状态；需要部署本次涉及的资产标签与 SNMP-first 探测代码后，等待/未知设备的错误“离线”标签才会被启动同步清除，SNMP 响应也才会参与状态判定。
