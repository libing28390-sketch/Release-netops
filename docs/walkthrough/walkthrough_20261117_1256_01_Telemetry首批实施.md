# Telemetry 首批实施走查

## 交付范围

- 增加 PostgreSQL-only 迁移321-325。新增协议档、订阅模板、TLS配置引用、独立`telemetry_collectors`、设备配置、订阅、运行态和发布任务表；Telemetry采集器身份与SNMP的`monitoring_collectors`分离，迁移在SQLite路径会明确失败。m0324加入可选设备上送源IP和H3C S6850 R6717 v2/v3档案（DOCUMENTED）；m0325加入Huawei CE6800 / V200R005C10 gRPC JSON协议档和各现有租户的起始模板。
- 管理API前缀为 `/api/monitoring/telemetry`，继续使用项目RBAC、租户设备范围和审计事件。数据库不保存证书或私钥内容；TLS API仅返回名称、状态和证书指纹，不返回密钥库引用。
- 添加独立 `telemetry-collector` 和 `telemetry-vmagent` Compose profile。接收器只接收华为/华三 gRPC Dial-out JSON；设备身份从客户端证书指纹与允许来源IP校验，忽略payload中的设备名和tenant标签。
- 添加 Telemetry 管理入口 `/monitor/telemetry-management`：设备支持按资产编号、主机名、管理IP、型号搜索；可维护模板草稿、登记TLS引用、登记订阅并查看容量/运行状态，以及启停和重试。页面展示设备可达接收端点、配置兼容性和H3C v2/v3周期采样命令预览，但不会向设备下发配置命令。
- 资产导入下载模板增加“Telemetry采集”工作表。每行对应一个订阅，通过资产编号关联网络设备；资产提交后，导入请求同步调用Telemetry PG服务登记设备配置和订阅，新订阅默认停用，完全相同的重复导入会复用原订阅并保留其启停状态。出错时保留资产并在逐行结果中报告Telemetry登记失败。带Telemetry字段的请求不接受 `atomic=true`，避免声称跨资产与Telemetry服务的原子事务。
- 对已存在资产，导入仍遵守原有“重复资产不改CMDB字段”规则；Telemetry配置可单独绑定，但必须通过非空且相同的资产编号和管理IP匹配原设备。管理IP不匹配时会逐行报告失败。SNMP端口/Profile不会用于Telemetry绑定判断。软删除订阅后可重新使用相同订阅名称。
- 批量配置入口在 Telemetry 页面跳转到资产导入；“Telemetry采集”工作表一行配置一个订阅，允许逐设备设置TLS、设备上送源IP和接收端白名单。接收端白名单必填，NAT下可以和设备上送源IP不同；同一设备的多行订阅需保持连接身份参数一致。
- CE6800起始模板包含设备提交的两个sensor path，默认周期为10秒。CPU和接口JSON字段是候选映射，状态为`UNKNOWN`；页面提供草稿编辑入口，真实样本核实字段前不能发布。
- 资产编辑页允许Operator对已投产设备手工修正型号和管理IP。后端仅对`production`资产放开这两个字段；管理IP仍需为有效地址且不能与其他资产重复，并同步到关联设备记录。业务IP此前已可编辑。

## 容量与 64 MiB 抓取限制

首发准入限制为每个本机接收器最多50台设备、25,000活跃序列、5,000样本/秒。设备单条 gRPC 消息和JSON payload均限制为4 MiB；collector向专用vmagent提交文本样本时每批最多1 MiB。超过持续样本速率或序列数的样本会被拒绝并计入订阅运行状态。

Telemetry业务样本走推送链路：设备 → 独立collector → `telemetry-vmagent`导入接口 → VictoriaMetrics；它不经过现有vmagent的64 MiB HTTP抓取响应上限。Telemetry vmagent只抓取collector自身的小型健康指标。远写磁盘队列默认上限16 GiB，实际值由 `TELEMETRY_VMAGENT_MAX_DISK_USAGE` 决定。

控制页会显示容量上限、数据库预留量和运行态观测值。最大消息大小和远写队列占用当前未写入PostgreSQL，因此“实测”列显示“—”，不会把未采集的占用伪报成0。

## 启用前配置

1. 确认服务已经应用PostgreSQL迁移321至325；本轮没有访问数据库或运行迁移。
2. 在 `.env` 设置 `TELEMETRY_CERTS_DIR`，目录中提供 `server.crt`、`server.key`、`client-ca.crt`；目录只读挂入collector。服务启动时要求三项同时存在，未配置时会安全失败。
3. 设置 `TELEMETRY_GRPC_BIND_IP` 为主机实际监听的设备管理接口IP（或`0.0.0.0`），设置 `TELEMETRY_DEVICE_TARGET_ADDRESS` 为设备实际访问的采集器地址，`TELEMETRY_GRPC_BIND_PORT` 为发布端口。端点未配置、目标地址不可达或仍绑定loopback时，允许保存停用草稿，但不能启用订阅。
4. 在“Telemetry采集”页面登记TLS密钥库引用与客户端证书SHA-256指纹，创建包含逐路径证据的模板并发布。
5. 搜索选择华为/华三设备，选择与型号/软件版本相符的协议档、`telemetry-collector-local`、TLS配置和接收端观察到的来源IP；可选填设备本地上送源IP。型号/版本待识别时允许保存停用草稿，已知不匹配则保存时拒绝；启用阶段仍会严格校验。按厂商手册配置设备并确认连接后，再在订阅列表启用；平台不会修改设备配置。

## 已实现的状态保护

- 设备时间偏差超过5分钟时拒收该消息并报告 `CLOCK_SKEW`。
- 接收器运行期间按时间戳丢弃每个序列的乱序样本。模板声明 `counter_bits` 时，对接近计数器上限后回绕的样本补齐模数；设备重启归零仍保留Prometheus counter reset语义。
- H3C v3分片总缓冲限制为32 MiB，gRPC并发流限制为64；单消息归一化最多生成10,000个样本点。
- 序列、计数器回绕和乱序缓存保存在collector进程内。重启会重置这些缓存，但不会删除VictoriaMetrics历史样本；远写未发送数据由vmagent的持久队列承接。
- 每个TLS协议档要求显式来源IP allowlist；接收器同时校验客户端证书指纹与来源IP。导入工作表也要求填写允许来源IP。
- 已启用订阅的设备配置发生变化时生成PostgreSQL发布job，接收器配置通过原子文件替换发布到共享volume。资产导入只创建停用订阅，因此不会自动生成设备配置发布动作。
- 容量硬上限作用于独立的 `telemetry-collector-local`；Telemetry页面读取 `/api/monitoring/telemetry/collectors`，不会使用SNMP采集器API或容量池。

## 未验证事项

- 协议档的支持状态是 `DOCUMENTED`，没有华为或华三实机连接、厂商配置下发或有效样本证据；UI明确显示这一点。S6850 R6717 v2/v3档以官方配置指南和现有接收适配器为依据，仍未实机验证。
- CE6800模板范围按设备输出的`V200R005C10SPC607B607`归到`V200R005C10`系列档案；迁移新增的模板保持DRAFT，JSON source_field候选值需先由实收样本核对，不能当作已验证模板。模板只有在应用325迁移后才会出现在页面中。
- 用户在 192.168.96.103 上应用华为 JSON/gRPC Dial-out、`no-tls` 配置后，本机只读连通检查显示设备 IP 可 ping 通；接收地址 192.168.96.1 的 TCP 50050 和默认 10051 均不可连接，未收到 Telemetry 数据。当前 Windows 环境没有 Docker CLI，项目 `.env` 未配置 Telemetry bind/target 端点；没有连接设备 CLI 或修改设备。
- 即使启动现有 Compose 接收器，设备 `no-tls` 与其预设双向 TLS 不兼容：Compose 为 receiver 提供 server cert/key/client CA，服务端要求 client certificate；Huawei `device_configured` profile 启用时也要求活动 TLS profile。需要先对齐 TLS，再做端到端数据验证。
- 用户后续截图显示设备已采用搜索框选择；CE6800起始模板需在迁移325应用后才会列入模板草稿区，本轮未执行迁移或重载运行服务。
- 本轮未运行测试、类型检查、Python编译检查、Compose解析或部署。未连接真实设备、生产数据库或部署主机。
- 容量值是首发准入线，需在隔离PostgreSQL和目标Linux/设备环境中压测后再校准；队列实际占用指标尚未接入控制页。

## 回滚

关闭Compose `telemetry` profile或停用订阅即可停止接收新数据。配置表和订阅软删除历史保留；不要删除VictoriaMetrics数据卷或手工回滚PostgreSQL表。代码回滚不自动移除数据库迁移。
