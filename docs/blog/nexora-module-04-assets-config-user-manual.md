# Nexora 资产与配置模块使用手册

## 功能入口

资产管理 `/assets/dashboard`、网络设备 `/assets/devices`、服务器 `/assets/servers`、路径诊断 `/assets/diagnose`、网络事实库 `/assets/nsot`、IP 工具 `/assets/toolbox`、标签管理 `/assets/tags`。

## 使用流程

先在资产管理中导入或维护设备、Site、平台和凭据，再在网络事实库执行同步。同步结果按分页展示，可查看接口、路由、OSPF/BGP 和邻居信息。路径诊断用于输入源/目的地址并查看逐跳结果；标签页用于批量归类和过滤资产。

## 厂商兼容

H3C 默认平台使用 `h3c_comware`；明确配置为 V5 的旧设备可使用 `hp_comware` 解析器命名空间。导入后建议执行一次接口和路由同步验证。

