# IPAM 对账证据与时效重建及发现终端

状态：实现及本地自动化验证完成，待本次 main 提交对应 Actions 验证。

## 完成摘要与实际文件

- 新增迁移 backend/database/migrations/m0301_ipam_discovery_evidence.py，独立保存快照、观察及人工范围确认，不修改共享采集表。
- 新增 backend/services/ipam_discovery_service.py，只读已有 ARP/MAC、采集状态及目录，保留来源、真实观察时间、范围与代次。未知 VRF、失败/超期数据不能证明完整覆盖或终端离线；源版本不变时重复投影不新增观察。
- backend/main.py 仅新增每60秒的 IPAM 数据库投影任务，不访问设备、不调整监控或 ARP/MAC 采集周期。
- backend/api/ipam.py、backend/schemas/schemas.py、backend/services/ipam_service.py 提供发现记录、详情、六类对账、显式范围登记及带版本保护的 MAC 校准。终端不自动绑定网关设备，不校准未知主机名、不自动释放地址。
- .env.example 提供独立保留期和时间窗口配置。长期未发现需7天及至少3次独立、完整、覆盖所有责任来源的成功采集，失败和重复投影不累计。
- 新增 src/pages/IPVlan/DiscoveredEndpointsTab.tsx、ipamDiscoveryPresentation.ts，接入 IPAMManagementTab、导航、标题及路由。支持筛选、分页、详情与完整筛选结果导出。
- IPReconciliationTab.tsx 及域内 presentation/export helpers 呈现六类差异，页面使用简短提示，详情提供证据。IPAddressTab.tsx 使用 ipAddressQuery.ts 的 registered_only，正式台账不混入采集观察。
- 新增 backend/tests/ipam/test_ipam_discovery_evidence.py，并更新既有 IPAM 与页面/helper 测试。
- 同次提交包含本会话前序已授权的接口采集联动 VLAN、用途去重/批量修改/设备候选、IPAM 导航及接口进度组件；分别见同日1208、1224、1227、1301、1417、1440计划及对应 walkthrough。

## 验证命令与结果

- 隔离 PostgreSQL runner：发现证据、台账范围、来源计数、容量对账、批量用途/设备候选、CMDB快照、跨站复用，共48项通过；追加4项边界补测通过。隔离库运行后删除。
- npm run test:frontend -- --run --maxWorkers=2：182文件806项通过。初次资源竞争造成一项超时，该文件独立10项及后续全量均通过，未修改无关模块。
- 最新重点回归7文件39项通过，覆盖发现、对账、登记查询、时间展示及六类导出。
- npm run lint：通过（tsc --noEmit退出0）。直接 Vite 隔离构建通过，输出在系统临时目录，未提交生成物。
- python scripts/validate_postgresql_only.py：0违规；Python3.11 AST兼容检查通过；git diff --check通过。
- 本地应用库只运行迁移0301与数据库投影：90条已有ARP进入发现清单，正式登记地址0条，重复投影新增0条。历史/未知范围没有被包装成在线或核对通过。
- 投影前后 arp_table、mac_table、network_endpoints、interfaces、ip_inventory、ip_addresses 行数及 SHA256一致；监控、驱动、共享访问限制文件无修改。
- 本机日志位于未入库 backend/artifacts/ipam_validation/，认证凭据不落盘。

## 未执行验证及原因

- 实际浏览器截图/交互验收未完成。Computer Use捕获Chrome时因无法可靠识别URL被自动安全检查阻止，已停止操作。组件测试、HTTP或数据库验证不能替代浏览器验收。
- 未运行真实设备采集、不修改设备配置；未知的源VRF/完整代次不能由软件补造。
- 本次SHA的远端Actions及部署状态在推送后单独核验，起点提交成功不代表本次通过。

## 风险与回滚

独立历史从上线开始累计，不能追补过去完整缺席次数。迁移仅新增IPAM表及索引，保留期默认90天，仅清理IPAM自有旧历史且保留最新源快照。回滚应用提交可恢复旧入口并停止投影，保留新表避免证据丢失，不删除共享采集或台账数据。人工登记/校准恢复应核对审计旧值。
