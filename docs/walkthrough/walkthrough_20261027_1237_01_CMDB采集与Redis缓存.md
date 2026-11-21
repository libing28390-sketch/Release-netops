# CMDB采集与Redis缓存：实施记录

- 时间：2026-10-27（Asia/Shanghai）。
- 对应方案：`docs/plans/plan_20261027_1237_01_CMDB采集与Redis缓存.md`。
- 状态：本次约定范围的实现及发布门禁已完成。代码提交 `0aa1136293f2d3bdc11972fe96b2561c60a51ae0` 已推送到 `origin/main`，对应 Actions run `40535628669` 为 success。未验证项仍单独列明；这不代表额外平台覆盖、Redis现场验收或原生Network面板已通过。
- 用户硬约束：严禁修改监控相关代码。本轮监控保护文件、配置和共享接口采集器均保持原样。

## 已实施

- `backend/services/cmdb_service.py`：移除接口GET里的DELETE/commit；修复未分配站点匹配、ARP/MAC-only设备展开和VLAN搜索字段；业务绑定增加可选搜索、筛选和分页，旧数组契约保留；相关CMDB写事务递增read revision。VLAN站点、prefix/IP、接口、ARP/MAC计数和业务绑定改为批量查询；`include_details=false`列表省略完整端口/端点数组，详情和导出保留旧字段；修复轻量模式下SVI掩码回退。
- `backend/api/cmdb.py`：三个列表走一致性只读快照和版本化Redis缓存；新增Viewer鉴权的VLAN设备明细GET，键含版本、角色、VLAN/site/device；VLAN列表`include_details`默认false并进入query key；接口监控阈值仍从数据库动态读取；手动CMDB接口任务写入显式`cmdb_cli_only`作用域，只复用同作用域活动任务。
- 新增`backend/services/cmdb_cli_collection_service.py`：仅手动CMDB任务走CLI；复用只读证据适配器、已发布平台action、单SSH会话及共享SSH全局/单设备租约；完整性不成立时保留上次成功快照；明确标注平台不支持的描述字段；不写`collection_status_service`，不调用SNMP或全局`sync_observed_vlans`。
- `backend/services/cmdb_cli_collection_service.py`：沿用既有同命令/同profile-version精确模板重解析、action缺失时的精确action元数据解析和List字段校验；本次未修改共享TextFSM目录扫描、parser、resolver或模板选择逻辑。无地址记录在校验接口名之前跳过，有地址记录仍校验接口与前缀，防止无IP管理口导致整批失败。
- `scripts/dev-internal.mjs`：开发前后端服务增加5秒健康检查、启动最长120秒宽限和1s到30s上限退避重试；健康异常连续3次后重启被本监督器管理的子进程，服务停止/重用时不杀无所有权进程。
- `backend/services/job_worker.py`：只有任务`scope_json`明确设置`cmdb_cli_only=true`时分流到CMDB专用service；其他接口任务继续原调用。
- `backend/services/read_only_collection_adapter.py`：增加可选的action session参数，让同一只读CLI会话服务于分类命令和IP接口action。
- `backend/services/cmdb_snapshot_service.py`、`cmdb_version_service.py`、`cmdb_cache_service.py`、`cmdb_cache_runtime.py`及迁移m0298：提供generation fencing、设备VLAN观察、read revision、Redis缓存/fail-open。
- `src/pages/CmdbManagementTab.tsx`：三类列表服务端分页、搜索提交、取消旧请求、按需加载VLAN目录；VLAN弹窗点击后才取当前VLAN/设备详情，支持请求取消、旧响应丢弃、成功缓存、加载/错误/重试/空态；只有显式用户导出请求带`include_details=true`。

## 监控边界检查

- `backend/services/interface_collection_service.py`已恢复到任务前版本，没有CMDB专用参数或分支。4个SNMP专用函数与HEAD的AST一致。
- 以下保护文件对HEAD均无差异：`backend/api/monitoring.py`、`backend/services/snmp_service.py`、`backend/services/ip_locator_service.py`、`backend/services/scheduler_service.py`、`backend/services/collection_status_service.py`、限流/平台action服务、配置和Compose文件。
- M0最初发现writer会更改共享事实；M0299现已改为CMDB独立接口/VLAN端口观察，writer不写interfaces/vlans/ip_inventory，prefix共享投影跳过。读者按successful_generation显示last-good；共享ID/监控阈值和拓扑计数只读补充。
- NSOT/Network Reality原有批量采集入口未切换协议，保持其原SNMP优先行为；本轮只改CMDB手动任务路径。

## 2026-10-27 最新集成与现场错误排查

- M0299及`cmdb_interface_snapshot_service.py`：CMDB独立观察表、generation事务、共享事实零写入；对应迁移/CLI组合20 passed（88.44s，早前writer验证）。
- `cmdb_service.py`：接口paged/unpaged、VLAN列表/详情/导出接入成功快照；纯CLI行稳定观察ID，失败attempt不覆盖last-good；未成功设备沿用legacy只读数据。接口IP筛选以CLI地址为准，空描述不回填共享旧值。CLI VLAN端口保留mode/tagging，未知不推断。
- `cmdb.py`：VLAN列表/详情缓存generation加入interfaces revision。
- UI：CLI-only接口无共享ID时隐藏profile编辑，CLI-only VLAN保留明细并隐藏共享目录编辑/删除；14/14组件测试通过。
- 服务投影组合：`python -m pytest backend/tests/vendor_audit/test_cmdb_cli_projection.py backend/tests/vendor_audit/test_vlan_discovery_contract.py backend/tests/vendor_audit/test_interface_alias_consolidation.py -q`：22 passed（217.44s）。前几轮失败涉及最小PG fixture字段、schema兼容和legacy精确响应形状，最终组合已完整通过。
- 现场SSH错误根因：CMDB外层`limiter.ssh`与PlatformActionSession内BaseDriver重复申请相同非重入设备锁；即使单次触发也会等待120秒超时。仅删除CMDB外层锁，底层驱动/共享限流/监控代码不改。新增真实NetworkAccessLimiter+模拟BaseDriver测试，验证并发1、连续两次调用及异常释放；完整`test_cmdb_cli_collection.py`：20 passed（69.39s）。
- 16:41任务的Profile错误发生时三个设备profile_id为空；后续只读审计确认S6850-5已手动绑定system-profile-h3c_comware，设备7.1.070，resolver选择h3c_comware_v7。不得继续把早前NULL状态作为当前值。
- H3C V7精确IP命令缺口已补齐：共享目录新增`data/textfsm_templates/h3c_comware_v7_display_ip_interface_brief.textfsm`，通过原有catalog/resolver解析`display ip interface brief`输出。组合测试确认CIDR、严格表头及坏行失败关闭；S6850-5现场采集成功，metadata记录模板、action和命令，无IP行不再因接口名白名单被误拒。没有创建CMDB私有解析器或更改共享parser逻辑。
- 单目标S6850-5 CMDB只读接口采集成功：`interface_inventory` generation 9，57条CMDB观察记录；地址action metadata的模板为`h3c_comware_v7_display_ip_interface_brief.textfsm`，来源`custom`。数据写入CMDB观察快照，没有SNMP调用。
- 本轮诊断时发现监督器与前后端进程均未运行，使用隐藏的`dev-internal.mjs`监督器自动恢复；后端健康检查和`192.168.56.1:5400/cmdb/interfaces`页面均恢复HTTP 200。监督器进程已启动，恢复范围为当前Windows登录会话。
- 最新公共验证：共享parser/runtime/catalog与CMDB采集定向组合92 passed；PostgreSQL-only scanner 0 violations；`git diff --check`通过。此前py_compile、TypeScript lint和隔离Vite构建4347 modules、exit0也已通过。监控/共享驱动/限流保护文件diff为空。
- 最近9台接口任务`job-d0f2b48c2ae5`结果4成功/5失败。job_target错误分成两类：AC_11、F1090-10、F1090-9为IP action `unmatched`；S6850-3、S6850-4为有效接口名校验失败。平台action审计显示相关CLI传输均成功，失败点在解析/CMDB验证，不是SSH连接或设备profile未绑定。
- 只读输出检查确认AC_11的brief表头只有`IP Address`且只有1个裸IPv4。现对这个特定maskless表头回退到已发布`get_interfaces` action；要求详细action有CIDR且其IP集合与brief原始输出完全相同。AC_11详细action的1个CIDR地址与brief的接口/IP匹配后，单设备完整CMDB采集generation 10成功、30条观察记录。
- F1090-10尾部提示符`RBM_S<F1090-10.`经共享V7模板匹配；S6850-3的`RAGG34`由CMDB本地名称守卫接受。随后串行重跑原5台失败设备的CMDB单目标service，F1090-9/-10各25条、S6850-3/-4各57条，均成功。加上原4台成功设备，9台当前接口快照全部success；原job仍保留4/5的历史状态，未重跑整批job。全程使用CLI-only路径，没有SNMP调用。
- 解析器核心、通用resolver与模板选择机制未改；监控、SNMP和共享接口采集器未修改。AC_11使用的详细接口数据来自现有发布action，不新增私有parser或设备命令。
- 会话边界只读审计：工作台PAM在`api/pam.py`直接建独立AsyncSSH会话，不占后台SSH gate；自动化registry与CMDB各建独立driver连接，但共用BaseDriver设备gate，当前会互相排队。业务通道优先级/预留人工容量尚未实施；设备总VTY容量仍共享。不得把重复锁修复报成跨业务互不阻塞已实现。
- 本节为最新状态，优先于下文历史验证快照。未完成的Redis跨worker/TTL、浏览器DOM/Network、真实设备完整字段对账与性能A-B仍保留。

## 2026-10-27 M3参考目录revision复核

- 发现未分页站点列表仍使用进程内30秒缓存；原缓存键没有共享数据库revision，另一个worker写站点后，当前worker可能在TTL内继续返回旧列表。
- `backend/api/cmdb.py`：未分页站点列表在PostgreSQL只读一致性快照中读取`sites` revision，并把版本加入缓存键。已有旧revision缓存不会命中新版本请求；分页列表仍直接查询数据库。
- `backend/services/cmdb_service.py`：站点写入递增`sites`，VRF写入递增`vrfs`，同时保留接口/VLAN/业务绑定投影需要的共享revision。审计确认仓库服务/API中站点与VRF各3个SQL写入口，均调用此事务内版本函数。
- 参考列表覆盖复核：VLAN与业务绑定缓存分别使用`vlans`/`bindings`版本，写入路径同事务递增；VRF列表直接读PostgreSQL，不依赖缓存版本；tenants列表/写接口在单组织模式下禁用。隔离PostgreSQL已有CRUD版本回归覆盖VLAN/binding与site/VRF事务递增。
- `backend/tests/configuration/test_cmdb_sites_import_export.py`：新增真实隔离PostgreSQL跨worker回归，先缓存空列表，再通过service模拟另一worker写站点且不清理本地cache，随后列表请求能读取新站点。`backend/tests/test_cmdb_phase3_crud.py`同时校验站点/VRF revision值。
- 验证：`.venv\\Scripts\\python.exe -m pytest backend/tests/test_cmdb_phase3_crud.py backend/tests/configuration/test_cmdb_sites_import_export.py -q`：13 passed；`.venv\\Scripts\\python.exe scripts\\validate_postgresql_only.py`：0 violations；`git diff --check`通过。监控/SNMP/共享接口采集保护路径无diff。
- 没有连接或写入配置的远程Redis。隔离Redis并发、恢复、TTL和容量验证，以及受保护写入路径的ARP/MAC/IPAM外部新鲜度承诺仍未完成。

## 2026-10-27 M2 VLAN缺名失败保护回归

- 共享CMDB writer在解析投影阶段发现缺少`VLAN_NAME`时先报错，之后才删除上一代观察；`_persist_vlan_snapshot`捕获异常并回滚事务。外层采集器把attempt记为failed，因此可保留上一代last-good事实。
- 新增隔离PostgreSQL回归：先提交命名完整的VLAN generation，再提交缺名称attempt；断言attempt失败、`successful_generation`/`last_success_at`不变、原`cmdb_device_vlan_observations`仍保留，且失败attempt不递增read revision。
- 验证：`.venv\\Scripts\\python.exe -m pytest backend/tests/vendor_audit/test_cmdb_cli_projection.py -q -k vlan_snapshot_without_name`：1 passed，3 deselected；PostgreSQL-only扫描0违规，`git diff --check`通过。没有改共享TextFSM模板、解析器/模板选择逻辑或监控代码。
- 这证明当前契约对缺名记录失败关闭，不证明Huawei VRP无名VLAN输出应被接受。仍需对应VRP脱敏输出和action字段契约，才能决定是否合成名称并进入last-good快照。

## 2026-10-27 M2平台 action/parser 覆盖审计

- 审计范围：源码中的`SYSTEM_PROFILES`、已定义action/命令、共享TextFSM模板、CLI fixtures及对应测试。只读审计未读取运行数据库中的published release，因此不把源码默认映射等同于当前部署设备映射；未执行设备命令，也未改模板。
- Cisco IOS：`get_vlan_table`命令已定义，但仓库没有Cisco IOS VLAN模板/fixture；现有Cisco相关手工记录测试不证明CLI解析能力。
- Huawei VRP V5/V8：`display ip interface brief` action已定义，但缺少VRP地址/掩码模板和输出fixture。`display vlan`模板含有名与无名语法分支；VRP8有官方文档fixture但当前未被对应parser测试引用。CMDB快照对缺名记录失败关闭；无名输出是否应支持仍需脱敏设备样本与action字段契约确认。
- H3C Comware V5：IP/VLAN命令和版本profile已定义；VLAN模板要求名称但缺版本fixture，V5 IP模板/fixture缺失。
- H3C Comware V9：有VLAN模板和官方文档样例测试，证明该文档形状的多词名称解析；缺V9 IP模板/fixture。V7解析器不能跨版本复用，现有resolver测试会拒绝V7模板用于V9。
- 后续边界：先取得脱敏的对应版本输出，再补版本专属共享模板与fixture；不从H3C V7或YunShan样本推断VRP/V5/V9覆盖。相关细节见`backend/services/platform_registry_service.py`、`backend/core/textfsm.py`、`data/textfsm_templates/`及`backend/tests/vendor_audit/test_cmdb_cli_ip_parser.py`。

## 2026-10-27 服务自动恢复与浏览器状态

- 首次服务恢复时启动了隐藏监督器PID 21324；之后日志显示`backend/tests/vendor_audit/test_cmdb_cli_projection.py`变更触发Uvicorn热重载，进程树随后退出，导致端口再次关闭。`backend/main.py`现在仅在开发模式把`backend/tests`和`backend/artifacts`排除出`reload_excludes`，运行时源码目录仍受监视。用当前venv的Uvicorn `FileFilter`验证：测试/生成目录路径不触发、`backend/services`源码仍触发；`py_compile`通过。
- 按用户此前要求再次自动启动隐藏监督器PID 17572；复核时后端health=healthy/database=connected、前端`/cmdb/interfaces`返回HTTP 200。监督器仍在当前登录会话内运行，没有配置Windows开机任务。
- 后端正常启动会恢复现有scheduler/background monitor；启动日志记录到既有BGP采集先走SNMP、失败后CLI fallback。这是应用启动的自动行为，不是本轮手动触发；没有修改监控代码或调度配置。后续验收不再触发设备采集。
- Chrome扩展调试器未能附着，原生窗口访问因URL策略未提供DOM；随后IAB页面成功呈现Nexora登录表单（用户字段已脱敏），证明页面壳可渲染但不是已认证CMDB内容。本轮没有输入密码、登录、改数据或提交操作，因此接口列表/筛选/详情/Network验收仍未完成。
- 本机没有Redis server/cli命令或6379监听；未连接配置的远程Redis。隔离Redis验证仍需专用本机服务。

## 2026-10-27 M1 CMDB列表性能基准与名称归一化

- 新增`backend/tests/vendor_audit/test_cmdb_list_performance.py`：opt-in隔离PostgreSQL基准，挂载CMDB router到FastAPI `TestClient`，创建100台设备、10,000接口、2,000条设备VLAN观察和500条业务绑定；统计HTTP状态/total/响应字节/耗时、SQL执行数与累计耗时、归一化fingerprint。测试注入Redis-disabled adapter，未连接任何Redis；每个请求均验证`cache_state=bypass`和正确分页，无性能硬断言。
- 手动命令：PowerShell设置`NETOPS_RUN_CMDB_LIST_PERFORMANCE=1`后运行`.venv\\Scripts\\python.exe -m pytest -s backend/tests/vendor_audit/test_cmdb_list_performance.py`，随后清除该变量。优化前基准`1 passed/68.23s`；加入名称memoization后同数据集复测`1 passed/60.84s`。样本条件、时间点不同且每条请求只采一次，不能当作P95、生产值或前后版本的正式收益门槛。
- 加速实现：`backend/services/cmdb_service.py`增加8192项有界LRU，仅缓存对原`core.interface_utils.normalize_interface_name`的纯函数调用；接口名/别名规则、SQL筛选、IP回退、分页顺序和解析模板均未改。
- 同数据集优化前/后代表单次HTTP结果（全为bypass）：接口首屏`821.190ms -> 411.267ms`（SQL数15，SQL合计`119.196ms -> 89.635ms`）；接口搜索首屏`113.593ms -> 77.400ms`；VLAN首屏`487.885ms -> 303.988ms`（SQL数22，SQL合计`98.114ms -> 79.385ms`）；VLAN搜索1/2/3页`499.911/520.246/515.607ms -> 345.444/305.798/288.100ms`；业务绑定首屏`7.770ms -> 5.688ms`（SQL数5）。这表明在该合成数据集和单次采样中，归一化缓存减少了端到端耗时，数据库查询次数没有改变。
- 验证：`.venv\\Scripts\\python.exe -m pytest backend/tests/vendor_audit/test_cmdb_cli_projection.py backend/tests/vendor_audit/test_interface_alias_consolidation.py backend/tests/vendor_audit/test_vlan_discovery_contract.py -q`：23 passed；性能基准opt-in：1 passed（60.84s）；`py_compile`、PostgreSQL-only扫描（0违规）、`git diff --check`均通过。监控保护路径无diff。
- 未完成：没有实施候选身份的SQL下推；缺少重复采样的P95以及原始CMDB改造前基线；Redis冷/热、容量和真实部署性能尚未验证。性能基准不是浏览器或生产证据。

## 当前验证证据

- `.venv\Scripts\python.exe -m pytest backend/tests/vendor_audit/test_interface_alias_consolidation.py backend/tests/vendor_audit/test_cmdb_cli_collection.py backend/tests/vendor_audit/test_vlan_discovery_contract.py backend/tests/vendor_audit/test_cmdb_cache_service.py backend/tests/vendor_audit/test_cmdb_snapshot_service.py`：在本轮fallback类别收窄前50 passed（259.63s），覆盖接口候选分页/别名归并、IP inventory回退、CLI任务分流、IP List字段、VLAN详情/轻量列表、缓存和快照。
- 历史验证快照：`test_interface_alias_consolidation.py`曾5 passed；早前`test_cmdb_cli_collection.py`曾18 passed（62.96s），IP action子集8 passed。当前真实共享resolver、模板解析和CMDB复用原始输出由`test_cmdb_cli_ip_parser.py`与CMDB集成测试覆盖，最新四文件组合87 passed；其他profile/version选择仍待覆盖。
- `node --check scripts/dev-internal.mjs`、`py_compile`、相关路径`git diff --check`均通过；PostgreSQL-only扫描此前报告0违规。
- `node_modules\.bin\vitest.cmd --config vitest.config.ts --run src/pages/CmdbManagementTab.test.tsx`：12 passed。
- `npm run lint`：通过；隔离目录Vite生产构建：4347 modules，55.16s，exit 0；Python `py_compile` 通过；`scripts/validate_postgresql_only.py`报告0违规；本轮相关路径`git diff --check`通过。
- `http://192.168.56.1:5400/` 与 `/cmdb/vlans`：HTTP 200；未带登录态的接口、VLAN、业务绑定三个列表API均返回预期401；`http://127.0.0.1:15310/api/health`：HTTP 200，status=healthy、database=connected。浏览器自动化因无法以足够置信度识别Chrome当前URL被安全拦截，没有页面DOM/登录态/Network/交互证据。
- 监控专用文件diff检查为空；共享接口采集文件diff检查为空。
- 早前开发库快照曾显示17台设备均无 `platform_profile_id`，该快照已过期；本轮确认S6850-5已绑定H3C系统profile并成功采集。不能据此推断其他设备profile/action可用。`PlatformActionSession`缺发布release时会拒绝，CMDB CLI将失败关闭。当前 `REDIS_URL` 是非本机目标；未连接该实例，且本机无Redis进程/二进制供隔离验收。
- `scripts/dev-internal.mjs`、前端5400和后端15310当前均在运行。隔离验证中只终止了5410测试Vite子进程，监督器在第2次HTTP检查恢复；随后旧开发启动器退出时，隐藏恢复进程自动重新启动前端，5400和15310均恢复200/healthy。发现旧守护进程对复用中的后端瞬时探测超时有重复拉起尝试，源代码现已改为需连续3次失败才尝试恢复，`node --check`通过；运行中的隐藏守护进程仍加载旧版本。尝试安全换代时，执行环境策略拒绝了对该后台进程发信号/替换的命令，因此保持原守护进程和服务运行，未做强制终止。当前恢复进程仅服务本次登录会话，没有安装开机任务。未启动设备采集或修改监控调度。
- 本轮只对S6850-5执行一次已授权的只读CMDB接口采集；未提交、推送、部署或更改设备配置。

## 尚未完成

- M0：同一数据集性能已有单次HTTP/SQL样本，但重复采样P95与冷/热Redis A-B未完成；其他设备profile/action/parser覆盖矩阵及除S6850-5 H3C V7外的真实只读对账仍缺证据。`PLATFORM_ACTION_COMMANDS`未为Cisco/Huawei静态映射`get_interface_description`，但`COMMAND_CATALOG`含相应只读命令，Registry缺action时还可能通过同版本精确TextFSM fallback；每个published profile是否具备可用action/parser仍需逐个核验。
- M1：VLAN summary/tree已使用轻量全局候选，完整字段与端点只物化当前页；接口唯一候选的无搜索路径已增加SQL窗口统计与分页。别名重复/搜索/快照/IP库存回退继续原Python路径；轻量身份预检仍需读取全体匹配键，避免改动共享归一化语义。
- M2：H3C Comware V7九台目标CMDB接口快照成功，AC_11通过现有`get_interfaces` action补足前缀；Huawei VRP V5/V8和H3C Comware V5/V9仍缺覆盖证据。Cisco VLAN模板/action兼容与Huawei VLAN无名称分支还需验证；同接口多IP继续失败并保留旧快照，合法空表/分页截断fixture不足；其他profile/version矩阵和NSOT入口仍待验证。
- M3：用户于2026-10-27要求忽略本机Redis验收；本机没有Redis服务，未连接配置地址。ARP/MAC/IPAM写入水位的只读审计已完成，但缓存绕过无可信水位的动态字段策略仍未实施。
- M4：HTTP可达/后端健康已核验，隔离构建已通过；浏览器完整交互、Network证据、冷/热/禁缓存性能对比和最终回滚验收仍未完成。

## 2026-10-27 M1 接口列表候选 SQL 分页

- `backend/services/cmdb_service.py`：对无搜索、无CMDB快照候选、无会影响结果的IP库存回退场景，先读取轻量候选键并调用原共享Python规范化器检查身份是否唯一；唯一时由带窗口统计的SQL直接返回总数、汇总和当前页ID。has_ip排序字段不满足ASCII安全排序条件时回退原逻辑。重复别名、搜索、快照及有效IP库存回退不走快路径，保持现有Python代表行、合并、筛选和排序语义。详情和关联字段仍只为当前页查询。
- 新增隔离PostgreSQL用例验证SQL分页/统计、`has_ip=true`、越界页汇总；既有用例验证重复别名去重、IP库存回退、scope/search/只读语义。定向命令：`.venv\Scripts\python.exe -m pytest backend/tests/vendor_audit/test_interface_alias_consolidation.py -q -k "unique_interface_candidates or pagination_deduplicates_aliases or paged_ip_inventory_fallback"`：3 passed，3 deselected；`py_compile`通过。
- opt-in性能样本：100设备/10000接口/2000 VLAN观察/500 bindings，隔离PostgreSQL、Redis disabled、cache bypass。接口无搜索首屏206.791ms、19条SQL、SQL累计74.989ms；接口搜索首屏88.274ms、18条SQL、SQL累计79.812ms。此样本在最后跳过快路径空inventory查询前采集；当前无搜索快路径少一条无结果查询，但该微调后未重跑性能基准。此前memoization单样本同路由为411.267ms/SQL累计89.635ms；所有请求均为独立单次采样，波动明显，不能视作P95、SLA或生产结论。搜索继续旧路径，没有宣称搜索优化。
- 这一实现没有把Python别名表复制到SQL；窄预检仍会扫描过滤后的候选身份键，但接口详情、全局统计和分页不再构造完整候选对象。监控、SNMP、解析模板和共享归一化规则无修改；没有连接Redis或设备。

## 2026-10-27 M3/M4 外部水位及接口页现状

- 按用户要求忽略本机Redis验收：Windows PATH/服务及6379/6380未发现Redis/Valkey/Memurai或监听；唯一WSL发行版无法启动实例。本轮未安装/启动服务，未读取或连接有效`REDIS_URL`，未接触告警Redis。隔离Redis跨worker、租约、冷启动、故障恢复与容量仍是未验收项，不记为通过。
- 只读追踪发现：ARP行有`last_updated`，完整sweep有部分`device_collection_status`，但状态先于事实表写入且其它写入源不一致；MAC writer不写对应设备级成功状态；`ip_inventory`仅有行级`last_seen`且由多个writer写入；IPAM prefix有`source_type/last_observed_at`，但CMDB VLAN reader不选这些字段。CMDB `dependency_watermark`是全局15秒时间桶，`stale_domains`当前固定为空，不是外部采集成功水位。审计结论是动态事实没有一致的来源成功水位；对应代码缓存策略未在本轮更改。
- 已认证Chrome中的`/cmdb/interfaces`初始DOM显示0台设备/0接口。健康端点为healthy/database connected，device_total=17。随后一个只读PostgreSQL `REPEATABLE READ READ ONLY`快照下，CMDB service无scope查询返回total=426、has_ip=true total=33。成功快照共18条，其中9条设备已不存在；M0298的snapshot表没有device外键，因此这9条旧元数据保留了reported record_count=426，但不参与读路径。其余9条live snapshot的reported record_count与当前generation的426条观察事实完全相符。初始空页与后续DB视图时间不同；没有重载页面/Network证据，不能据此判定当前API仍返回0或认定live事实缺失。
- 尚未重新加载浏览器页或触发设备CLI采集；当前Chrome页缺实际Network交互证据。9条孤儿snapshot元数据未删除，因其不影响当前设备读路径且计划没有授权清理。Redis依用户要求忽略，本机未启动/连接任何实例。未修改监控、SNMP、解析模板，也未执行数据库清理。

## 2026-10-27 当前设备 profile/action 只读复核

- 对当前开发PostgreSQL只读汇总：17台设备中9台H3C绑定`h3c_comware` profile，其current release为1且状态PUBLISHED；该release含接口brief、接口description、IP接口、VLAN四类CMDB所需action。另8台设备无`platform_profile_id`，所以不能据H3C发布映射推断它们可采集。
- CMDB CLI调用`PlatformActionSession.send_command`，沿发布release执行当前命令；全仓`get_cached_command/set_cached_command`仅在IP Locator legacy命令路径调用，未发现CMDB action输出缓存。因此本次源代码/当前绑定映射没有命令结果缓存导致旧CLI输出的证据。没有发设备命令。
- 用户要求本轮不处理解析模板；VRP V5/V8、H3C V5/V9、Cisco action/parser的fixture和现场覆盖仍未验收。

## 2026-10-27 M1 孤立 IP inventory dry-run 设计

- 只完成设计，没有新增清理函数、执行入口或数据库写入。孤立候选分为 `device_id` 为空/空白，以及非空但无法关联 `devices.id` 两类；计数分开呈现，避免重复统计。
- dry-run 契约规定使用 PostgreSQL 只读重复读快照，返回两类/合计数量和最多20条脱敏样例；样例隐藏 IP、掩码、设备ID和接口名。该操作不得挂到页面 GET、定时任务或采集链路，不连接设备、不清缓存。
- `ip_inventory` 被 IPAM、接口采集和拓扑等路径共享，表定义没有设备外键；本计划不执行删除。未来若要 apply，必须另行授权并重新核对消费者与候选集合。
- 已更新计划第7节及M1检查项；没有修改监控相关代码、解析模板或数据库记录。

## 2026-10-27 动态事实直接读取与浏览器复核

- `backend/api/cmdb.py`的接口、VLAN列表和VLAN详情投影含无统一成功水位的共享依赖，现提前绕过缓存，直接读取本请求的PostgreSQL快照；不会调用Redis客户端工厂。移除15秒`external_bucket`及伪水位，保留`dependency_watermark`字段但值为null。VLAN业务的事务revision缓存仍沿用原逻辑。
- 定向回归新增三个资源在revision不变、源数据变化时读取新值，并断言没有访问Redis；元数据回归断言旧时间桶不能产生成功水位。此次没有设备连接、数据库清理或迁移变更。
- Chrome中新开的已认证接口页实际显示33个有IP接口、首屏10条、共4页，warn/error日志为空。搜索框已成功输入；源码确认按Enter应用搜索。提交Enter后的状态获取超时，因此搜索、翻页及Network仍未验收，不将浏览器扩展超时报告为应用故障。
- 未添加snapshot设备外键：现存已删除设备的快照元数据未影响当前设备读路径；删除/保留语义没有在本次变更中扩展。CMDB与自动化仍共用设备SSH gate，可能排队；独立容量预留尚未实施。
- Redis现场验证依用户要求排除；解析模板覆盖不扩展。监控、SNMP及共享驱动保护路径本轮无diff。
- 验证：`.venv/Scripts/python.exe -m pytest backend/tests/vendor_audit/test_cmdb_cli_collection.py backend/tests/vendor_audit/test_cmdb_cache_service.py -q`：40 passed（107.79s）；`npm run lint`通过；`scripts/validate_postgresql_only.py`：0 violations。

## 2026-10-27 用户授权SSH容量隔离及剩余验收（最新状态）

- 用户明确允许仅增加CMDB专用SSH容量池，更新原方案共享基础设施禁改边界。`network_access_lease_service.py`新增受限capacity class，CMDB以`cmdb_cli`purpose独立领取global/device租约，容量硬限制3/1；claim/renew/release均按purpose/owner/token定位。复用既有表，无迁移。
- `network_access_limiter.py`为CMDB增加独立global/per-device信号量与计数；`drivers/base.py`和`PlatformActionSession`只在明确传入时选择新池，CMDB service显式选择该池，job并发同步改为3。原默认`network_ssh`池及SNMP/probe逻辑保持原有策略。PAM本来独立；设备物理VTY容量仍共享，默认后台20之外CMDB最多额外3条，不承诺设备端无限会话。
- 定向验证：`.venv/Scripts/python.exe -m pytest backend/tests/database/test_m0224_network_global_ssh_slots.py backend/tests/vendor_audit/test_network_access_limiter.py backend/tests/platform_registry/test_platform_action_session.py backend/tests/vendor_audit/test_cmdb_cli_collection.py -q`：52 passed（267.27s）。覆盖同设备跨池共存、CMDB同设备互斥、global3上限、失败释放、purpose/token fencing和跨进程租约。未对真实设备运行并发登录测试。
- 前端按全文搜索范围调整接口搜索提示；`npm run lint`通过，`npx vitest run src/pages/CmdbManagementTab.test.tsx --config vitest.config.ts`：14 passed。隔离Vite构建`.codex-build-validation-cmdb-final-20261027-ssh`通过（50.88s）。PostgreSQL-only扫描0 violations，diff check通过（仅既有换行警告）。
- 浏览器真实读取：接口33条；搜索S6850-2返回7条（包含接口描述匹配），清除恢复33；第二页10条、末页3条且边界按钮禁用；每页20条后total保持33并回到第一页；无匹配搜索返回0及明确空态。VLAN列表13条/2页；S6850-2 VLAN100详情返回网段、网关、SVI及4条ARP；VLAN业务当前0条，空状态正常。没有点击采集、写入或删除操作。接口和VLAN详情截图位于`backend/artifacts/cmdb_validation/cmdb-interfaces-final-20261027.jpg`、`cmdb-vlan-details-final-20261027.jpg`。
- 验收时发现5400/15310均无监听，浏览器此前保留旧页面。已按用户已有授权自动启动隐藏监督器PID30008，日志`logs/dev-internal-cmdb-final-20261027_220259.stdout.log`及`.stderr.log`；服务恢复后重新加载，已看到新搜索提示和正确分页。启动会恢复应用既有后台任务，未修改监控调度。
- 性能：通过安全runner创建test-only空源库并调用共享隔离fixture，bypass基准1 passed（106.59s），10类请求×10次，共100次。接口列表median157.429ms/P95288.005ms；报告`backend/artifacts/cmdb_list_performance_20261027T141217388896Z.json`。n=10最近秩P95等于max；当前本机合成样本，不代表生产SLA/改造前改善。Redis未访问。
- runner自身临时源库已删除；只读清理检查发现4个无活动连接的历史test-only残留库，无法确认归属，未删除。完整backend回归另用`backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests`运行，日志`cmdb_full_backend_20261027.log`，仍待最终结果。
- 原生Network面板验收未完成：浏览器工具在切换至Windows窗口检查时因无法可靠确定当前URL而停止本轮Computer Use；未换通道规避。既有页面DOM和截图证据保留，原生Network不可记为通过。Redis现场验证及用户排除的解析模板扩展保持不做。

## 2026-10-27 全量本地回归中断复核及发布准备

- 全量日志 `backend/artifacts/cmdb_validation/cmdb_full_backend_20261027.log` 记录运行到约36%，2个失败、1个跳过后以退出码1结束，没有pytest最终汇总或失败traceback；全量测试没有通过结论。
- 根据同一轮实际收集顺序定位两项：`test_async_scheduler_releases_real_pg_lease_when_job_is_cancelled` 与 `test_session_pool_reuses_connection_and_releases_slot_after_idle`。使用临时PostgreSQL源库定向复跑：2 passed in 104.08s。它们未复现失败；这不足以替代完整backend gate，main push后以Actions结果为最终证据。
- 完整回归期间未收集开发库连接；隔离runner创建的测试源由finally清理。此前已知的4个无活动连接历史测试库归属不明，未删除。
- Git credential helper错误源于用户级 `.gitconfig` 指向不存在的WorkBuddy PortableGit路径；仅在此仓库 `.git/config` 覆盖为系统Git Credential Manager，`git ls-remote origin refs/heads/main`成功，远端main与本地基线当前相同。未更改全局Git配置或输出令牌。
- 浏览器Network面板仍未完成；浏览器工具报当前Windows浏览器URL无法充分确认后本轮停止了Computer Use。已保存的接口/VLAN详情截图、页面DOM交互证据及性能报告仍在`backend/artifacts/`，不会纳入源码提交。

## 2026-10-28 交付状态复核

- 当前 `main` 与 `origin/main` 均指向代码提交 `0aa1136293f2d3bdc11972fe96b2561c60a51ae0`。对应 `Build and Sync to Release Repo` push run `40535628669` 已完成且结论为 `success`。
- 该 run 的后端完整 pytest、前端 lint/测试/build、Docker发布输入校验、后端 compileall、发布树提交和Linux发布包打包均成功。Knowledge Engine评估仅在tag或workflow_dispatch触发，故本次main push为skipped；百度网盘上传和公开GitHub Release同样为skipped，不是失败。
- 当前本机监听正常：`127.0.0.1:15310/api/health` 返回HTTP 200；`127.0.0.1:5400/cmdb/interfaces` 返回HTTP 200。本次无需重启服务。
- 最近一次Git状态复核未发现未提交业务源码；仍有私有 `.agents/`、`handoff.md` 改动及本地构建、日志、截图/性能等产物，均保留且未纳入main提交。
- 本次复核重新尝试读取Chrome页面时，Computer Use因无法可靠确定Windows浏览器当前URL而停止；遵守工具要求后没有继续UI输入或换通道规避。因此原生Network面板仍未验收。Redis运行验收按用户要求忽略；额外平台/profile/parser覆盖与更大样本性能对比仍未声称完成。
