# Grafana 接口描述与 S3 内部代理排查走查记录

## 完成摘要

- 更正 Grafana 字段语义：设备 CLI `description` 映射为 IF-MIB `ifAlias`，`ifName` 作为“接口全称”。
- 确认线上 04“接口实时状态清单”仍直接查询不存在的 `ifDescr{...}`，导致结果为空；同一接口 helper 影响的表格与图表也因此没有数据。
- 更新 Grafana 生成器，按 `(instance, ifIndex)` 从接口名行关联 `ifAlias`；接口流量/出向查询分别对接口名和别名使用正确 selector，并隐藏 `ifDescr` 列。
- 为 `netops` Compose 服务把 `seaweedfs` 与 `nexora-seaweedfs` 加入大小写代理绕过列表，保留现有代理配置供外部 S3 兼容 endpoint 使用。

## 实际修改文件

- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-network-device.json`
- `monitoring/grafana/dashboards/nexora-network-interface.json`
- `monitoring/grafana/dashboards/nexora-network-outbound.json`
- `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- `docker-compose.yml`
- `docs/deploy/docker.md`
- `docs/plans/plan_20260925_2152_01_Grafana接口描述与S3内部代理排查.md`

## 关键实现与调查证据

### Grafana 接口描述

- IF-MIB OID `.1.3.6.1.2.1.31.1.1.1.18` (`ifAlias`) 对应接口 alias/设备配置 description；OID `.1.3.6.1.2.1.31.1.1.1.1` (`ifName`) 对应接口全称。
- 用户在 Linux 部署服务器上 walk 到的 `ifAlias` 包含 `TO-F1090_9`、`TO-S6850_3`、`TO-S6850_4`、`TO-S6850-2`、`ROUTER-ID`、`FIREWALL-INSIDE` 等人工设置描述；默认 alias 字符串也按设备返回值原样呈现。
- 线上 Grafana 04 panel 10 的编辑视图显示查询仍直接引用 `ifDescr{job=...,site_name=...,vendor=...,role=...,hostname=...}`，而不是从 `ifOperStatus` 标签或独立 alias 指标取值。当前指标合同没有独立 `ifDescr` 时序，所以该查询为空。
- 线上 Explore 查询 `ifHCInOctets{job="network_snmp"}` 返回 475 条时序；以 `F1090-9` 过滤的同类接口状态关联查询返回 27 条。空结果根因是 dashboard 请求 `ifDescr{...}`，不是采集缺少接口流量。
- 线上 Explore 查询 `ifAlias{job="network_snmp"}` 返回 27 条 F1090-9 时序样例，label 含 `ifIndex` 和 `ifAlias`。服务端 walk 则可见完整索引，包括用户配置的高编号接口别名；Grafana 后续按相同 `ifIndex` 与 `ifName` 行匹配。
- `ifAlias` 不带 `ifName` label，因此接口变量条件仅应用于 `ifName` 侧；别名 metric 使用去掉 `ifName` matcher 的设备 selector，再按 `(instance, ifIndex)` 合并。若 alias 未上报，保留接口行并让描述为空。

### S3

- 浏览器在 `/management/storage` 对默认 `Environment` profile（endpoint `http://seaweedfs:8333`、bucket `nexora`）执行测试，页面返回 `S3 storage check failed: 502 (HTTP 502)`。
- 非默认 `test` profile 另保存有 `http://seaweedfs:8333/conf` endpoint；本次未改动它或线上任何 profile。它与默认 profile 不同，不能解释默认 profile 测试返回 502。
- S3 测试执行 `list_objects_v2(Bucket, MaxKeys=1)`，是只读列举操作；后端将失败信息放入 `{ok:false,message}`，管理页显示这个 message。因此文案中的 `HTTP 502` 是 boto3 收到的响应状态，不能单凭它认定浏览器到 Nexora API 返回了 502；代理和 S3 服务端响应都可能给出此状态。
- `netops` 容器没有清理从 `.env` 继承的代理变量；boto3 会采用进程代理配置。Compose 已让大写、小写 `NO_PROXY` 都包含 `seaweedfs` 和 `nexora-seaweedfs`。如果 endpoint host 是 `seaweedfs`，且部署端重建容器加载了新配置，这一改动应绕过代理；但它只覆盖代理路径，不能证明 502 的来源，也不能修复 URL 路径、签名、Bucket 或权限问题。
- 子 Agent 独立追踪确认：`Environment` profile 的 signing region 固定为 `us-east-1`，所以移除 `.env` 的 `S3_REGION` 不会导致 SDK 缺少 region。另一个 profile 的 `/conf` 路径是独立配置问题；带路径的 endpoint 会把该路径并入 path-style 请求，可能造成路由或签名问题。
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py` 已断言 netops 两种 `NO_PROXY` 都包含两个 SeaweedFS 主机名。仍没有部署容器运行时证据：本机没有 Docker CLI，未能比较代理请求与强制直连请求；Compose 修改也未部署，所以 S3 根因尚未定案。

## 验证命令与结果

- `.venv\Scripts\python.exe -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`：11 passed（40.32s）。
- `.venv\Scripts\python.exe monitoring/grafana/generate_dashboards.py`：成功重新生成 8 份 Dashboard JSON；相关查询与列映射契约测试通过。
- Python + PyYAML 解析 `docker-compose.yml`：YAML valid；`netops.environment` 的 `NO_PROXY` 和 `no_proxy` 都包含 `seaweedfs`、`nexora-seaweedfs`。
- `git diff --check`：通过。
- Grafana live Explore / panel editor：线上现有 04 panel 10 仍是旧的 `ifDescr{...}` 查询；基础流量时序 475 条，按 ifIndex 将 F1090-9 的 ifName/ifAlias 关联后为 27 条。用新 alias join 的 Top 10 流量查询返回 10 条时序，当前窗口值为 0；这表示查询不为空，但当前采样窗口没有计数增长。线上 Dashboard 的 provisioning JSON 未随本地生成结果更新。
- SNMP walk 与 live Explore 都确认 `ifIndex=1` 的 `ifName=GigabitEthernet1/0/0`、`ifAlias=TO-S6850-1`，可分别用于“接口全称”和设备配置的 `description`。
- 用户在部署服务器运行 SNMP walk：OID `.1.3.6.1.2.1.31.1.1.1.18` 返回接口配置 alias/description。

## 未执行验证与限制

- `docker compose config --quiet` 和 `docker exec ...`：本地环境未安装 Docker CLI。
- 未重新部署或推送修改；当前线上 Grafana/S3 行为不会因本地工作树变更而改变。
- 线上 Grafana 未更新为本地生成的 JSON，现场 Dashboard 是否恢复要等用户部署后确认；本次没有 push/deploy。
- S3 代理路径尚未在部署容器复现，NO_PROXY 修复尚未部署。要定案，需在重建后的 `netops` 容器里比较默认代理与强制直连访问 `http://seaweedfs:8333/` 的状态，再重测 Environment profile；不要回传完整环境变量、S3 响应正文或凭据。

## 后续建议

- 生成 dashboard JSON 后，在发布的 Grafana dashboard 版本中确认 04 status table 与流量 panel恢复数据，并核对某个配置了 `description` 的端口同时显示 `ifName` 和 `ifAlias`。
- 部署端重建 `netops` 容器后重测默认 Environment profile。若仍 502，在容器内比较默认代理路径与 `ProxyHandler({})` 直连路径，并只回报变量名、bypass 命中和 HTTP 状态，避免泄露凭据。
