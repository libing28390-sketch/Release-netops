# SNMP 诊断 LLDP 本地端口映射

## 完成摘要

修复了 SNMP 诊断弹窗里 LLDP 邻居有名称和对端端口、但本地端口显示“未识别端口（索引 N）”的问题。

用户日志中的后台拓扑记录显示同一批设备已通过 SNMP 发现 LLDP/CDP 邻居，拓扑图也显示了本地接口名，证明网络设备 LLDP 数据和后台拓扑采集正常。问题在诊断弹窗的独立探测链路：它把父 OID `.1.0.8802.1.1.2.1.4` 当普通 WALK，因此没有读取 `.3` 下的本地 LLDP 端口表，也没有用 IF-MIB 的 `ifName` 补齐索引。解析器缺少节点实例后缀时还会先按用户父 OID 截取，可能把列号混进索引。

## 实际修改文件

- `src/components/SnmpMib/components/LiveWalkInspector.tsx`
- `docs/plans/plan_20260924_2123_01_SNMP诊断LLDP本地端口映射.md`
- `docs/walkthrough/walkthrough_20260924_2123_01_SNMP诊断LLDP本地端口映射.md`

## 关键实现说明

- 将 LLDP 远端表父 OID `.4` 和其下所有子 OID 识别为 LLDP 专项探测。
- 专项探测除邻居表字段外，也会读取 `lldpLocPortId`、`lldpLocPortDesc` 和 IF-MIB `ifName`，按远端表的 `localPortNum` 映射本地接口名称。
- 优先采用后端 MIB 解析得到的实例后缀；缺失时先按具体列 OID 根提取，再回退到用户选择的 WALK 根。
- 后台拓扑采集服务没有修改。

## 验证命令与结果

- `npm run lint`：通过。
- `$buildOut = Join-Path $env:TEMP 'netsops-lldp-local-port-build-20260924'; npm run build -- --outDir "$buildOut"`：通过，4292 个模块转换，64 秒完成；未覆盖仓库 `dist`。
- `git diff --check`：通过。

## 未执行验证及原因

- 没有向真实 H3C 设备发起 SNMP 请求；设备现场验证需要部署该前端更新后重新以 `.1.0.8802.1.1.2.1.4` 探测。
- 没有新增或运行测试。

## 剩余风险与后续建议

- 如果目标设备的 SNMP View 同时屏蔽 `lldpLocPortId`、`lldpLocPortDesc` 和 IF-MIB `ifName`，诊断界面仍会显示本地端口索引；这时检查设备侧只读视图权限。用户提供的同一设备拓扑记录目前已经映射出接口名，预期新增查询会覆盖该路径。
