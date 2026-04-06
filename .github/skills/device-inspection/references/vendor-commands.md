# 多厂商巡检命令对照表

## 接口状态

| 用途 | Cisco IOS/IOS-XE | Cisco NX-OS | Huawei VRP | H3C Comware | Arista EOS | Juniper JunOS |
|------|------------------|-------------|------------|-------------|------------|---------------|
| 接口摘要 | `show ip interface brief` | `show interface brief` | `display interface brief` | `display interface brief` | `show ip interface brief` | `show interfaces terse` |
| 接口详情 | `show interface {intf}` | `show interface {intf}` | `display interface {intf}` | `display interface {intf}` | `show interface {intf}` | `show interfaces {intf} extensive` |
| 接口计数器 | `show interface {intf} counters errors` | `show interface {intf} counters errors` | `display interface {intf}` | `display interface {intf}` | `show interfaces counters errors` | `show interfaces {intf} statistics` |
| 接口描述 | `show interface description` | `show interface description` | `display interface description` | `display interface description` | `show interfaces description` | `show interfaces descriptions` |

## CPU / 内存

| 用途 | Cisco IOS/IOS-XE | Cisco NX-OS | Huawei VRP | H3C Comware | Arista EOS | Juniper JunOS |
|------|------------------|-------------|------------|-------------|------------|---------------|
| CPU 利用率 | `show processes cpu sorted` | `show processes cpu sort` | `display cpu-usage` | `display cpu-usage` | `show processes top once` | `show chassis routing-engine` |
| 内存使用 | `show memory summary` | `show system resources` | `display memory-usage` | `display memory` | `show memory` | `show chassis routing-engine` |
| 进程列表 | `show processes cpu sorted` | `show processes cpu sort` | `display cpu-usage process` | `display process cpu` | `show processes top once` | `show system processes extensive` |

## 硬件环境

| 用途 | Cisco IOS/IOS-XE | Cisco NX-OS | Huawei VRP | H3C Comware | Arista EOS | Juniper JunOS |
|------|------------------|-------------|------------|-------------|------------|---------------|
| 温度 | `show environment temperature` | `show environment temperature` | `display environment` | `display environment` | `show environment temperature` | `show chassis environment` |
| 电源 | `show environment power` | `show environment power` | `display power` | `display power` | `show environment power` | `show chassis power` |
| 风扇 | `show environment fan` | `show environment fan` | `display fan` | `display fan` | `show environment cooling` | `show chassis fan` |
| 版本/型号 | `show version` | `show version` | `display version` | `display version` | `show version` | `show version` |

## 路由协议

| 用途 | Cisco IOS/IOS-XE | Cisco NX-OS | Huawei VRP | H3C Comware | Arista EOS | Juniper JunOS |
|------|------------------|-------------|------------|-------------|------------|---------------|
| 路由表 | `show ip route` | `show ip route` | `display ip routing-table` | `display ip routing-table` | `show ip route` | `show route` |
| BGP 邻居 | `show bgp summary` | `show bgp ipv4 unicast summary` | `display bgp peer` | `display bgp peer` | `show bgp summary` | `show bgp summary` |
| OSPF 邻居 | `show ip ospf neighbor` | `show ip ospf neighbors` | `display ospf peer brief` | `display ospf peer` | `show ip ospf neighbor` | `show ospf neighbor` |
| BFD 会话 | `show bfd neighbors` | `show bfd neighbors` | `display bfd session all` | `display bfd session` | `show bfd peers` | `show bfd session` |

## 二层 / 邻居

| 用途 | Cisco IOS/IOS-XE | Cisco NX-OS | Huawei VRP | H3C Comware | Arista EOS | Juniper JunOS |
|------|------------------|-------------|------------|-------------|------------|---------------|
| LLDP 邻居 | `show lldp neighbors detail` | `show lldp neighbors detail` | `display lldp neighbor brief` | `display lldp neighbor-information` | `show lldp neighbors detail` | `show lldp neighbors` |
| CDP 邻居 | `show cdp neighbors detail` | `show cdp neighbors detail` | N/A | N/A | `show lldp neighbors detail` | N/A |
| ARP 表 | `show arp` | `show ip arp` | `display arp` | `display arp` | `show arp` | `show arp` |
| MAC 地址表 | `show mac address-table` | `show mac address-table` | `display mac-address` | `display mac-address` | `show mac address-table` | `show ethernet-switching table` |
| STP 状态 | `show spanning-tree` | `show spanning-tree` | `display stp brief` | `display stp brief` | `show spanning-tree` | `show spanning-tree bridge` |

## 日志与配置

| 用途 | Cisco IOS/IOS-XE | Cisco NX-OS | Huawei VRP | H3C Comware | Arista EOS | Juniper JunOS |
|------|------------------|-------------|------------|-------------|------------|---------------|
| 日志 | `show logging` | `show logging last 50` | `display logbuffer` | `display logbuffer` | `show logging last 50` | `show log messages` |
| 运行配置 | `show running-config` | `show running-config` | `display current-configuration` | `display current-configuration` | `show running-config` | `show configuration` |
| NTP 状态 | `show ntp status` | `show ntp peers` | `display ntp-service status` | `display ntp-service status` | `show ntp status` | `show ntp associations` |
