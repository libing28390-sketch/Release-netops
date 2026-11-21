# Nexora IPAM 模块使用手册

## 功能入口

前缀管理 `/ipam/prefixes`、IP 地址 `/ipam/ips`、地址池 `/ipam/pools`、VIP `/ipam/vips`、DHCP `/ipam/dhcp`、利用率 `/ipam/utilization`、IP 对账 `/ipam/reconciliation`。

## 使用流程

先维护前缀和 VRF，再查看 IP 地址使用状态；地址池和 VIP 用于登记可分配范围及虚拟地址；DHCP 页面用于租约追踪；利用率页面按 Site/前缀统计；对账页面用于比较采集结果与台账。

## 异常处理

接口缺少前缀长度时，检查设备接口命令输出和掩码字段，修正后重新同步。数量较多时使用搜索和分页，不建议一次展开全部网段。

