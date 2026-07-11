# 实施计划 - H3C 邻居解析与拓扑展示修复

## 1. H3C 邻居获取缺失与拓扑展示失败问题

* **问题分析**：
  1. H3C Comware 设备的自动发现命令为 `display lldp neighbor-information verbose`。
  2. 社区标准的 TextFSM 模板（`hp_comware_display_lldp_neighbor-information_verbose.textfsm`）在匹配记录行时，使用了硬编码的末尾标志：`^\s+Maximum\s+frame\s+size -> Record Start`。
  3. 如果 H3C 设备连接的是 **Cisco** 或 **Juniper** 设备，其上报的邻居明细中并不包含 `Maximum frame size` 这一行；只有连接到华为（VRP）或其它 H3C（Comware）的邻居才会带此字段。
  4. 这导致 TextFSM 在扫描时，Cisco 邻居的属性被不断地在内存状态中重写覆盖，但**绝不触发写入记录 (Record)**。整机解析完后，只有最后一台邻居（因为触发了 EOF）和极个别带 `Maximum frame size` 属性的邻居才会被提取出来（例如 7 个邻居只解析出 2 个，漏掉了 5 个）。
  5. 只要 TextFSM 返回了包含这 2 个结果的 List，Scrapli 和 Netmiko 驱动就会默认解析成功，跳过 Regex 正则兜底解析，导致其余 5 个邻居完全丢失，拓扑链路无法完整展示。
* **解决方案**：
  * 对 `topology_service.py` 中的 Scrapli 与 Netmiko 连接提取逻辑进行针对性改进：
    * 当识别到当前发现设备平台为 `comware` (H3C) 时，**主动绕过容易漏条目的 TextFSM 引擎**，直接回退并执行系统内编写的高精 `_regex_parse_lldp_detail` 正则解析器。
    * 经本地测试验证，正则解析器可以 100% 正确捕获并导出所有 7 个包含不同厂商类型的邻居信息，解决了 H3C 多厂商混连拓扑缺失的隐蔽缺陷。
