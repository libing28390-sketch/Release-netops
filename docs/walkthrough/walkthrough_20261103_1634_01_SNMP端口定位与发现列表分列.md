# SNMP端口定位与发现列表分列走查

## 完成摘要

172.16.5.10经真实SNMP采集、接口属性入库、发现投影和浏览器确认，已显示S6850-5/GigabitEthernet1/0/2；16:46自动周期也曾显示172.16.6.10/S6850-6/GigabitEthernet1/0/2。目标设备FDB随后若为空或证据不再满足时限，端口留空，不把来源设备充作接入设备。

页面IP、MAC、站点、VRF、接入设备、接入端口均为独立列，导出同步。缺失字段及推断VRF留空。时间列继续为“上一次时间”，使用北京时间。筛选框、搜索框和三个按钮实测均13px公共字体、约36px高、底边相同。

## 后端修改

- snmp_service.py：桥映射可多于PVID条目；保留有PVID且映射/成员关系完整的端口，PVID引用未知桥端口仍拒绝。缺PVID的端口不输出属性。
- ip_locator_service.py：SNMP FDB成功后同步读取QBRIDGE端口成员关系并保存接口属性，属性读取/持久化失败不丢已成功FDB。记录endpoint_port_attributes成功代次及本次明确access的端口名；失败状态阻止复用旧代次。
- ipam_discovery_service.py：新增同设备/站点/VLAN/MAC的物理位置证据关联，要求唯一且为明确access口、access VLAN相同，成功属性代次包含端口；ARP与FDB、属性与FDB时间差均不超过5分钟。上联/聚合/多候选继续排除。
- 物理位置关联保持原始VRF unknown、scope_pending、登记/对账限制。未知VRF不会跨设备借MAC，不会因显示物理位置自动确认三层地址空间。

## 前端修改与分工

frontend_worker Luna仅负责DiscoveredEndpointsTab.tsx与测试；主agent负责后端、集成和文档。

- 公共字体及高度token，筛选grid/form底部对齐；统计卡统一高度和数字样式。
- 站点、VRF、接入设备、接入端口独立列；colSpan=11；导出对应字段独立。
- 不显示缺失字段的横杠、未定位、来源叠加和推断VRF提示。
- 已有精简详情、刷新、北京时间显示保留。

## 验证结果

- 后端初始发现证据/QBRIDGE回归：27 passed。
- ARP/FDB合同和端点站点隔离：74 passed。
- QBRIDGE专项（额外桥端口、无映射PVID、属性失败保留FDB）：4 passed。
- 最终物理位置边界复测：13 passed，17 deselected，覆盖匹配、其他设备、错误VLAN、旧FDB、trunk、多端口、旧属性、无接口、显式MAC范围、缺属性代次、代次遗漏端口及原有隔离断言。期间测试夹具遗漏updated_at，修正后重跑通过。
- 前端两个发现测试文件：14 passed，覆盖列/导出拆分、空值、推断VRF空白及原有加载/权限等。
- npm run lint：通过。隔离Vite构建：通过（40.97秒），输出.codex-build-validation-ipam-port-fix-20261103，未覆盖dist。
- PostgreSQL-only扫描：0 violations；Python语法编译和git diff --check通过。

## 运行与浏览器证据

- 用户授权的定向SNMP刷新S6850-5后，源表及发现投影均显示GigabitEthernet1/0/2，接口属性为access/VLAN7。无设备配置及凭据变更。
- 本机页面服务停止时，启动原有scripts/dev-internal.mjs用于验收；最后自动重载退出后，代码稳定时再次启动本地开发入口。日志output/ipam-port-final.stdout.log及.stderr.log。不是远程部署或发布。
- 浏览器实际显示独立列、空白VRF和两台设备端口；控件几何与字体读取确认选择框、搜索框和按钮底边相同，字号13px、相同公共sans字体。
- 浏览器截图接口两次超时，采用实际页面AX/DOM、字号与坐标证据完成验收，未声称截图文件已保存。

## 剩余边界与回滚

低频FDB仍可能漏掉300秒老化窗口中的短时终端；没有当前可靠证据时留空。原VRF不会被虚构为全局。回滚本次后端/页面变更可恢复原行为，现有真实采集事实仍保留，不删除工单或设备数据。
