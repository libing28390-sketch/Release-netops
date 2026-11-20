# 资产导入 SNMP 错误提示与同步排查

## 完成摘要

资产导入错误现可说明缺少或无效 SNMP 凭据的原因；成功导入但没有 Community/Profile 的网络设备会提示主机名和型号无法自动同步。对今天 SNMP 不返回主机名和型号的问题，代码对比和真实设备只读计数显示：默认开关没有改变已启用设备的 GET 路径，三台 H3C 收到当前应用 Profile 发出的请求后将其计入 unknown community 并丢弃。

## 代码差异与修改文件

- `backend/api/assets.py`：将详细导入中的已知 SNMP 校验异常映射为安全、明确的错误码及消息，不回传异常原文或凭据。
- `backend/services/snmp_import_identification_service.py`：在可选 ENTITY-MIB 型号 walk 前先使用 sysName 写回主机名。
- `src/pages/AssetManagement/index.tsx`、`importUtils.ts`：按行显示凭据错误；只对成功创建且缺少 SNMP Community/Profile 的网络资产给出同步提示；提示包含“SSH 凭据不能替代 SNMP 凭据”。
- `backend/tests/configuration/test_asset_management_method_import.py`、`src/pages/AssetManagement/index.test.tsx`、`importUtils.test.ts`：补充安全错误提示、主机名写回顺序、导入结果和缺少 SNMP 配置的回归覆盖。
- `docs/plans/plan_20261026_2055_01_资产导入SNMP错误提示.md`：补入实现和诊断结果。

## 关键诊断证据

提交 `e810a4e3`（2026-10-25）新增 `snmp_collection_enabled`，新记录默认为 TRUE；启用状态仍调用既有 SNMP 识别流程，关闭时才跳过。与此前代码对比，`_resolve_probe_settings`、`_read_identity`、`_sync_hostname_from_sys_name` 的函数体未变；`snmp_service.py` 和 `hostname_sync_service.py` 文件内容未变。当前三台设备开关都为启用，绑定的 v2c 凭据记录存在，端口为 161，设备和 Profile 的保存 Community 均有值。

从应用主机对 `.14`、`.11`、`.12` 各发出一次使用绑定 Profile 的 sysName GET。三台请求都超时；各自 H3C 统计的 delivered 和 unknown community 计数均增加 1，accepted GetRequest 维持 0。Ping 正常，设备 SNMP 版本显示 SNMPv2c/v3。应用请求到达设备，但设备未接受当前 Profile 的 Community；这与“缺少凭据条目”不同。排查期间仅执行只读操作，没有修改设备配置。

今天新增型号读取使用 ENTITY-MIB chassis 表，在 sysName 获取和主机名写回后执行。因此它会增加一段型号探测流量，但不能解释当前基础 sysName GET 被记为 unknown community 的现象。下一步需让设备管理员按凭据中心里实际 `snmp-ro` Profile 对照设备端配置，并使只读 Community 一致；不得在日志或聊天中粘贴 Community 明文。

## 验证

- `backend/tests/configuration/test_asset_management_method_import.py::test_detailed_import_explains_missing_snmp_profile_without_echoing_input` 与 `test_batch_import_auto_identifies_device_without_custom_metric_profile_binding`：2 passed。
- `npm run test:frontend -- --run src/pages/AssetManagement/importUtils.test.ts src/pages/AssetManagement/index.test.tsx`：31 passed。
- `npm run lint`：通过。
- `node node_modules/vite/bin/vite.js build --outDir .codex-build-validation-asset-snmp-feedback-20261026`：通过；产物写到隔离目录。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过，只有 Git 对工作区 CRLF/LF 的提示。

## 未执行与剩余事项

- 未将真实 Community 明文读入工具输出，也未修改 H3C 运行配置。
- 未提交、推送、部署或重启服务。
- 修复并验证导入提示，不会修复设备端 Community 不匹配；配置对齐后需重新确认设备计数开始接受 GetRequest，并在新导入/重试后确认主机名和型号同步。
- 当导入路由以 FastAPI 后台任务返回时，响应只包含 pending，当前页面没有查询后台最终识别结果的接口；Community 不匹配这类导入后探测失败不会在原始导入提示中更新。实时设备统计已确认本次失败原因，但异步结果反馈仍是后续改进项。

## 2026-10-27 实时复核

用户确认 15 台设备应共用 `snmp-ro`。

- 最新批次 `asset-import-d134612f319f`（2026-10-27 06:50 Asia/Shanghai）包含 9 行 AC_11–AC_19。`.192.168.56.11` 的输入主机名 AC_12 被 sysName 更新为 F1090-9，`.192.168.56.12` 的 AC_13 更新为 F1090-10；`.192.168.56.14` 返回 AC_11，与导入值相同，因此没有可见改名。`.10.254.0.1-.6` 六行未返回身份信息，hostname 保留为 AC_14–AC_19。更新时间也吻合：前 3 台在导入后约 7 秒更新，六台 `.10.254` 仅有导入时的更新时间。数据库引用符合此策略；实际 SNMP 结果仍为 3/15，不能通过修改凭据中心展示修复其余 12 台。

之前记录的 `.11/.12/.14` SNMP 超时是较早的现场快照。重新检查当前数据库和运行中的导入识别路径后，这三台已能读取 sysName 与 ENTITY-MIB 型号：`.11`、`.12` 返回 `H3C F1060`，`.14` 返回 `H3C WX5540H-HCL`。这次只在内存中运行只读 GET/WALK，没有写回资产。

当前绑定 `snmp-ro` 的 15 台设备全部启用了 SNMP、端口为 161；导入识别同路径测试为 3/15 成功。`.10.254.0.1-.6` 的 H3C 请求在每台设备上都使 unknown-community 计数增加（每次应用 GET 增加 2 或 3），没有返回 sysName；`.10.255.0.1-.6` 的 Cisco Ping 成功，但同路径 SNMP 读不到身份信息。设备与资产表中 Community 字段和凭据库值的一致性只作本地布尔比较，没有输出明文；它不能替代设备 agent 对请求的接受证明。

- 在用户确认 15 台应共用 `snmp-ro` 后复测 `.10.254.0.1`：绑定 Profile 的 sysName GET 无响应；仅用该设备数据库中的本地 Community 做只读 GET 时返回 `S6850_1`。同批 `.10.254.0.2-.6` 的本地字段与 Profile 相同，但仍无响应。当前数据库显示 `.1` 的本地值与共享 Profile 不同，`.2-.6` 相同；未输出任何 Community 明文。
- 为判断是否存在能覆盖全部设备的既存值，用 `.10.254.0.1` 记录中的本地 Community 作只读候选测试：可读 `.10.254.0.1-.6` 和 `.192.168.56.11/.12/.14` 共 9 台；`.10.255.0.1-.6` 均无响应。当前 `snmp-ro` 则只在 `.192.168.56.11/.12/.14` 成功。Cisco `.10.255.0.1` 使用当前 Profile 的 SNMPv1/v2c 探测、系统路由、VMware 源 `192.168.96.1` 和 VirtualBox 源 `192.168.56.1` 均无响应。所有候选值均只在进程内使用，未输出明文或改写 Profile。

进一步的 H3C 只读核验显示：`.10.254.0.1-.6` 都有一条 cipher Community 配置，配置行没有 ACL 引用；配置值没有导出。`display snmp-agent community` 返回空，因为 H3C 命令参考说明该命令只显示明文保存的 Community，空结果并不能证明设备没有 Community，也无法直接比较应用 Profile（[H3C Command Reference](https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Reference_Guides/Command_References/H3C_CR-29161/17/202509/2657618_294551_0.htm)）。

Cisco 网段还发现本机 UDP socket 实际选用 `172.18.0.1`（sing-box TUN）作为源地址；临时绑定 VMware 地址 `192.168.96.1` 的单次 SNMP GET 仍未收到响应。此证据表明 Cisco 网段的本机源路由需要核实，但尚不足以断定其为唯一原因。未改设备配置、Community、ACL 或本机路由。

本轮发现凭据列表的“未绑定”属于单独的 UI 查询漏字段；数据库里 `snmp-ro` 确有 15 条设备引用和对应 15 条资产引用。代码已修复并通过后端、前端测试及构建。SNMP 完整采集验收仍未通过，只有确认所有 15 台都能由导入同路径读取身份与型号后，才可以将整体任务视为完成。
