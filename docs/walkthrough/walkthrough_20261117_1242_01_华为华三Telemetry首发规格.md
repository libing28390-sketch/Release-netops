# 华为华三 Telemetry 首发规格核查结果

## 完成摘要

按用户要求查询华为/华三中国官网资料，形成`docs/plans/Telemetry首发开发规格_华为华三_20261117.md`。首发改为两厂商私有gRPC Dial-out JSON接收，H3C二层/三层区分，gNMI主动订阅按后续协议批次验证。其余采用用户接受的独立采集器/独立agent、50台/25000序列/5000samples/s首期准入及前后端完整闭环范围。

## 证据与实现边界

- 华三：中国站S6812/S6813 R6628Pxx手册、S6520X等R68xx手册、S6805等Release66xx命令参考。确认私有Dial-out与gNMI模式不同，H3C gNMI示例有Login/token_id。R66xx的32传感器组/10订阅上限不外推到其它版本。
- 华为：中国站S5735-S-V2与S6730-H-V2产品页确认Telemetry；中文官方gRPC资料确认私有Dial-out RPC/JSON。部分中文产品文档返回403，进一步从华为官方发布页提取并下载e-file英文V600R024C10配置指南核实正文；不以第三方副本作为官网核实依据。具体链接均写入规格。
- 华为官方PDF正文核对补充：该版本英文附件未提供具体硬件SKU表，支持结论保持系列级，不从第三方中文镜像推导SKU白名单；Dial-in默认57400与Dial-out示例10001明确区分，10000ms示例不是最小周期。
- 数据库/API仅为开发契约，未新增真实表、路由或业务功能；官网文档支持状态不等于设备已验收。
- 现有monitoring_collectors、collector_artifact_service、CMDB同步、凭据服务和监控管理页作为复用边界；Telemetry不塞入SNMP module_variant_id，也不另建不互通的通用collector控制面。

## 文件

- 新增：本计划配对的plan、首发开发规格、本walkthrough。
- 更新：原`Telemetry整改建议书_20261117.md`的首发协议决策及规格指向。
- 无业务代码、数据库、Compose或生产配置修改；保留用户现有未提交变更；不读取skills、不连接设备、不执行推送或部署。

## 分工

主Agent负责H3C官网、华为中国产品页与官方PDF下载来源、现有代码复用、数据库/API/前端边界及最终文档；`huawei_official`执行者只读核实华为官方产品版本资料和PDF正文，无代码文件修改、无下级Agent。

## 验证

- 对已使用官网URL核对域名、标题、产品版本及相应协议描述；访问失败和目录级证据单独标注。
- 核查当前`backend/main.py`挂载与`monitoring_v1.py`路由：现有控制面是`/api/monitoring`；新契约采用`/api/monitoring/telemetry`。
- 首发规格结构/关键对象/行末空白检查通过。
- `git diff --check -- docs/plans docs/walkthrough`通过。
- 未运行业务测试：本次仅文档规格，未改业务代码。未运行设备测试/生产压测：无实际设备操作，本机无Docker；不宣称首期准入数字已经认证。

## 剩余事项

后续按规格实施迁移/接口、协议回放、前端与指标告警接入、隔离压测和实机验收。版本proto、字段单位、最小周期或型号范围不足的项目标未验证，开发时不能伪造已支持；这不要求用户再选择数据库表名或技术协议字段。新增文档可撤回，无业务回滚。
