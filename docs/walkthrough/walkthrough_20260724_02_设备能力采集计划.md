# 设备能力采集计划落地 walkthrough

## 目标

将 ARP、MAC、VLAN、LLDP、路由和动态路由协议采集从“所有设备统一执行”改为“按设备角色默认值 + 设备级覆盖值”执行，降低设备 SSH 会话和后台数据写入压力。

## 本次落地内容

1. 新增统一的 `collection_plan_service`，集中解析角色默认值和 `collection_policy_json` 覆盖值。
2. 新增 `devices.collection_policy_json` 数据字段及第 34 号幂等迁移。
3. 新增 `/api/collection-plans` 查询、修改和恢复默认计划接口。
4. ARP、MAC、终端定位、路由、LLDP、接口/IP 采集入口接入能力过滤。
5. `poll_endpoints_job` 改为缓存投影，不再重复对设备执行 ARP/MAC 采集。
6. BGP、OSPF、BFD 默认关闭；只有显式开启的设备才进入协议采集。
7. 巡检页面增加“设备采集计划”操作区。
8. 保持 Cisco 邻居发现 LLDP-only，复用 Automation Playbook/TextFSM。

## 推荐上线顺序

1. 发布后让数据库初始化流程执行 migration 034。
2. 检查设备角色字段，至少区分 router、core/distribution、access、server。
3. 在巡检页面抽查每类设备的默认计划。
4. 对实际运行 BGP/OSPF/BFD 的设备逐台开启对应开关。
5. 手工运行一次全网巡检，观察命令、耗时、失败率和 Prefix 投影。
6. 确认无误后再启用定时巡检和批量任务。

## 验证结果

- 专项后端回归：106 passed。
- 已覆盖角色默认值、设备级覆盖、非法策略校验、Cisco/H3C 采集兼容性、ARP、LLDP 和系统任务契约。
- 完成后应继续执行完整后端测试、前端 lint/build，并核对生产环境迁移日志。
