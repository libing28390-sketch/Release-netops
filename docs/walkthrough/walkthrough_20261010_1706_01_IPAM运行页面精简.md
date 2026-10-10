# IPAM 运行页面精简与 ARP 周期采集走查

## 变更

- ARP 工具栏复用公共 `IconInputField` 与 `ActionButton`，保留搜索、刷新、立即采集及运行状态。
- IP 对账页保留“IPAM 台账为基准、设备发现缓存用于对比”的含义，移除重复说明。
- 利用率页收紧 KPI、Top 5 网段和站点卡片的布局；无趋势样本时显示紧凑空状态。
- APScheduler 注册 ARP 周期采集，间隔沿用 `ARP_SWEEP_INTERVAL_SECONDS`，默认 600 秒、最小 300 秒；复用 `collector_sweep_state`，不新增采集配置表。
- `run_arp_sweep` 使用现有 `scheduler_locks` 数据库租约，协调 scheduler、手动采集与 NSOT 入口；手动采集遇到重叠会返回说明。

## NSOT 协议现状

统一 NSOT 流程目前不能视为全 SNMP：ARP 是 SNMP 优先；LLDP 是 SNMP 优先并在失败或数据不完整时结合 SSH；IF-MIB 用于接口快照，但接口同步仍会读取 CLI 补充字段。MAC 表、路由表、动态路由邻居、BGP 路由仍通过平台动作或 CLI 采集。接口与前缀数据的规范化、投影及落库是服务端处理。

标准 MIB 提供了一部分迁移基础：IF-MIB（RFC 2863）、IP-FORWARD-MIB（RFC 4292）、Q-BRIDGE-MIB（RFC 4363）、BGP4-MIB（RFC 4273）和 OSPFv2-MIB（RFC 4750）。具体设备是否开放对应表、VRF 覆盖和字段是否满足当前数据模型，需要按型号核验；BGP4-MIB 的路径属性表与经本地策略处理后的最终路由也不完全等价。建议分数据域采用 SNMP，并保留 CLI 回退直到影子对比达到覆盖要求。

## 验证与限制

- 本轮仅做源码静态审查与 `git diff --check`；未运行测试、构建或浏览器验证。
- 未执行提交、推送或部署。
