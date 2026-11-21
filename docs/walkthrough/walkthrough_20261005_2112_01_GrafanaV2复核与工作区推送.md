# Grafana V2 复核与工作区推送

## 完成摘要

两个 Luna 6 Max 审查者分别检查 01–06、07–12，主 Agent 汇总后修改配置源并重新生成。V2 skill 是当前规范依据；ZIP 仅作为初始展示来源，发现冲突时按规范纠正。

12 份 JSON 共 253 个面板（53 Row、200 业务面板、90 Stat）。查询、UID、Panel ID、Datasource、变量、Transformations、Options 和布局均保持原有契约。修正 3 处既有 drill-down URL 的字段占位引用，目标看板、筛选参数、时间范围与跳转功能保留。

同时验证此前工作区的首页全量统计、SNMP enum 编译、设备版本列兼容改动。按用户追加授权，将监控默认保留期改为 30 天，VictoriaMetrics 在剩余空间不足 10GiB 时停写，vmagent 重试缓存限制为 1GB。

## 实际修改文件与行为

- `monitoring/grafana/generate_dashboards.py`、`dashboard_presentation_v2.json`、12 份 Dashboard JSON：统一 V2 色板和 No Data、稳定加载 UID/Panel ID 展示配置源；所有生成结果可重复。
- 普通状态表取消冲突的背景色，合并相同 matcher 的重复属性；IF-MIB 保留 Testing、Unknown、Dormant、Not present、Lower layer down 的真实区别，null/nan 为灰色暂无采集数据。
- Interface/Interface Detail 的错误与丢弃类别分别 Amber/Red，精确 0 为 Green；WAN、通知投递与 Outbox 状态颜色覆盖 exporter 实际枚举；无线/Linux/Windows 的字段 override 对齐 organize 后字段名。
- 已有 CMDB 阈值的利用率数值不再使用固定 60/75/90 假定状态；数值和 Gauge 用中性/方向色，Detail 16 保留现有真实 CMDB 阈值状态。单列 Gauge 无法直接应用逐行 CMDB 阈值；本轮保留查询，不声称已实现动态逐接口 Gauge 着色。
- 总览合计吞吐使用 Primary Blue；入向/Receive Cyan、出向/Transmit Blue、Error Amber、Discard Red 统一。
- `backend/api/devices.py`、`src/{App.tsx,types.ts}`、`src/components/AppMainContent.tsx`、`src/pages/HomePage.tsx`：首页使用数据库完整计数，移除首页和资产分页页的共享重型设备轮询；摘要请求按租户过滤、防并发重叠并取消卸载请求。
- `backend/services/monitoring_compiler.py`：runtime exporter YAML 枚举键转换为整数，保存的业务 JSON 保持字符串键，非法配置明确失败。
- `backend/services/platform_identification_service.py`、`backend/database/migrations/m0274_add_device_version_column.py`：避免更新不存在的资产 version 列，幂等补齐 legacy devices.version，并保留已有版本值。
- `docker-compose.yml`、`.env.example`：默认 `30d`、`storage.minFreeDiskSpaceBytes=10737418240`、vmagent `maxDiskUsagePerURL=1GB`；保留原有持久卷。
- 新增相关回归测试和 [服务器存储配置操作说明](../modules/realtime/features/monitoring/存储保留与磁盘保护.md)。配置保护仅约束 VM 新指标写入，其他容器仍可占用同一磁盘；缓存满会丢弃最旧待发送数据。

`.agents/`、`.codex/`、handoff 和临时构建目录按项目要求保留本地；公有提交包含业务文件、测试和允许发布的任务记录。

## 验证命令与结果

1. `python monitoring/grafana/generate_dashboards.py`：12 份输出生成成功。
2. `python .tmp/check_grafana_review_contract.py`：12/12、253 面板、90 Stat、输出与内存生成结果一致；与 HEAD 对比所有 fieldConfig 外字段未变，3 处链接仅修正数据字段引用。
3. 隔离 PostgreSQL wrapper 执行 `test_device_summary_and_version.py`、`test_monitoring_v1_compiler.py`、`test_platform_identification.py -q`：**87 passed**。临时数据库命名、目标限制、连接关闭与强制清理受控，未操作用户应用库。
4. `pytest test_monitoring_storage_config.py --noconftest -q -p no:cacheprovider`：**7 passed**，覆盖 YAML、默认值、环境覆盖、持久卷、LF/CRLF、缺失配置键、重复键和原文件备份。
5. 现有 Dashboard 目录、变量、布局三个指定契约测试：**3 passed**。
6. `node node_modules/typescript/bin/tsc --noEmit --project .tmp/tsconfig.grafana-review.json`：通过。临时配置沿用原 compilerOptions，只明确源码范围并排除历史构建目录。
7. `node node_modules/vite/bin/vite.js build --outDir .tmp/grafana-review-build-20261005-2112`：通过，4329 modules transformed，独立构建约 2 分 12 秒。
8. `python scripts/validate_postgresql_only.py`：**0 violations**。
9. `git diff --check`：通过。
10. `pytest test_grafana_v2_presentation.py --noconftest -q -p no:cacheprovider`：**40 passed**，覆盖最终配置、状态枚举、Gauge/CMDB 优先级、无数据与字段/link 语义。初次 3 条断言发现入向 Gauge 颜色和宽泛状态 regex 残留；修正源配置后通过，未削弱断言。相关定向测试合计 **137 passed**。
11. Staged 白名单/敏感特征与 `git diff --cached --check`：通过；内部/构建/真实 `.env` 未纳入提交。推送完成后以远端 SHA 与本地 HEAD 一致为验收。

## 未执行验证与限制

- 标准 `npm run lint` 因默认 tsconfig 未限定 include、`allowJs=true` 将历史 `.codex-build-validation-*` / dist JS 产物也纳入检查，Node 约 4GB 堆 OOM；未改变业务编译设置，而使用上述同 compilerOptions 的源码范围检查通过。标准命令不能记为成功。
- 未连接 Grafana 实例或真实设备，未验证真实浏览器渲染；JSON/契约验证不等同于线上视觉验收。
- 用户确认 Docker 部署运行在另一台虚机，本机按职责仅做配置源码检查，未在本机执行 Compose 或容器运行验证；PyYAML 和定向配置测试通过，v1.103.0 官方源码确认参数支持。虚机生产容器未更新，旧 `.env` 的 90d/10GB 会覆盖新默认，必须按部署指南更新并重建两个容器。
- 未运行全仓后端回归，本次不是正式发布候选或公共测试基础设施修改。

## 记录的既有问题

- 无线 Panel 3 的离线查询仅统计 deassociated/idle，零值回退集合未涵盖其他已展示状态；可能漏计 down 或在只有 joining 时显示 No Data。本轮按展示任务和 PromQL 保留契约记录，未修改统计口径。
- Windows Panel 11 的 state/Value 均被原 transform 命名为服务状态，可能出现重复表头；本轮未改 transform。
- 日志中的 scheduler max_instances 安全跳过、真实 SNMP 超时/OID 不支持仍需运行时耗时与设备证据；未通过提升并发或隐藏日志处理，也不声称已经消除。

## 风险与回滚

保留现有资产与监控数据卷，不执行生产数据库迁移或设备操作。业务改动可通过新提交回滚；新增 version 可空列可保留。缩短保留期后已清理的数据、缓存满后已丢弃的样本不能通过改回参数恢复；需要长期留存时先备份。30 天是保留策略，不是硬性空间配额，过期数据后台回收不保证立即释放。
