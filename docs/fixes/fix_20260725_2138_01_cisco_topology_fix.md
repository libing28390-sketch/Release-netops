# Git 提交修复记录

* **修复编号**：fix_20260725_2138_01_cisco_topology_fix
* **问题描述**：修复思科设备 LLDP 发现由于拦截器 TypeError 导致全站拓扑失效，以及华三（`hp_comware`）在 BGP 路由收集时使用不完整命令导致路由表缺失的问题。
* **修改时间**：2026-07-25 21:38:00

## 1. 问题现象与根因

1. **思科设备无 links 显示**：
   - *现象*：已确认思科设备上有 LLDP 邻居关系，且“立即发现”无显式连接报错，但前台拓扑图 links 仍显示为 0。
   - *根因*：在 `backend/drivers/ssh_compat.py` 的全局 `_patched_send_command` 拦截器中，当开启 `use_textfsm=True` 且成功匹配时，底层 Netmiko 返回了已解析的列表（`list`）。然而，拦截器在执行后没有做类型校验就直接调用了 `drain_paged_output`；`drain_paged_output` 内在处理 `contains_paging_prompt(output)` 时强行将该 `list` 作为字符串处理，引发了 `TypeError: expected string or bytes-like object, got 'list'` 崩溃。该异常被 observations 收集层的 `except Exception` 静默吞没并返回 `None`（0条邻居），导致思科拓扑链路全部失效并变为陈旧的 stale 状态。

2. **华三 BGP 路由表缺失**：
   - *现象*：华三设备在 `routing_neighbors` 表中已经正常同步了 BGP 邻居，但 `bgp_route_table`（BGP 路由表）里却没有任何华三路由数据。
   - *根因*：在 `backend/services/operational_data_service.py` 中，针对 `hp_comware` 平台（华三 Comware 平台），配置的 BGP 路由收集命令是 `display bgp routing-table`。而在现代 Comware 设备上，该命令是不完整的，直接执行会报错 `% Incomplete command found at '^' position.`，必须指定地址族（如 `ipv4`）。同时，系统中对应的解析 TextFSM 模板也是以 `display_bgp_routing_table_ipv4` 命名的，导致获取为空。

## 2. 解决方案

1. **思科 LLDP 修复**：
   - 修改 [ssh_compat.py](file:///d:/netops/netsops-main/backend/drivers/ssh_compat.py)，在执行 `_orig_send_command` 拿到 output 后，先对 output 进行 `isinstance(output, str)` 校验。只有当 output 为 `str` 时才对其调用 `drain_paged_output` 过滤分页符。
2. **华三 BGP 收集命令修复**：
   - 修改 [operational_data_service.py](file:///d:/netops/netsops-main/backend/services/operational_data_service.py)，将 `hp_comware` 的 `bgp_routes` 命令变更为 `['display bgp routing-table ipv4']`，对齐 `h3c_comware` 的命令格式，使其既能通过设备验证，又能正常加载 TextFSM 模板进行解析。

## 3. 实际修改文件

* [backend/drivers/ssh_compat.py](file:///d:/netops/netsops-main/backend/drivers/ssh_compat.py)
* [backend/services/operational_data_service.py](file:///d:/netops/netsops-main/backend/services/operational_data_service.py)

## 4. 验证命令与结果

* 独立测试：在虚拟环境下运行测试脚本，`show lldp neighbors` 在 `use_textfsm=True` 下正常输出解析列表，无任何崩溃异常。
* 发现测试：针对设备 `R1` 单独跑 `discover_device_neighbors` 逻辑，成功收集到 2 个 LLDP observations，且在数据库里匹配关联成功。
* BGP 发现：修改命令后，华三设备执行 BGP 收集不再提示不完整命令，可通过 `display bgp routing-table ipv4` 得到正确回显并存入 `bgp_route_table` 表中。

## 5. 风险与回滚方式

* **风险**：无。修改安全且完全独立。
* **回滚方式**：`git checkout -- backend/drivers/ssh_compat.py backend/services/operational_data_service.py` 或 `git revert`。
