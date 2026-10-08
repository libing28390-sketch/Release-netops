# 全量 SNMP 采集流程文档与主线交付

## 完成摘要

- 新增 [SNMP 硬件采集全流程与代码索引](../architecture/SNMP采集全流程与代码索引.md)，覆盖资产导入、LibreNMS YAML 识别与发现、采样周期、关系库与 VictoriaMetrics 存储、API/Grafana 展示和诊断入口。
- 校正 LibreNMS bundle manifest 的范围说明：26 个资产厂商名、25 个有 OS profile 的厂商、136 个 OS profile、122 份 discovery YAML；上游 MIB 35 个来源目录映射到本地 23 个厂商 scope 目录及 `standard`。
- 为固定 LibreNMS YAML/MIB 加入 `.gitattributes -text`，避免 Windows `core.autocrlf` 改写提交对象并让来源哈希在 Linux 部署时失配。
- 按本地解析器重算后，122 份 discovery YAML 中有 31 份未解析出 processors/mempools/sensors 定义，91 份至少解析出一种硬件定义。
- 代码审阅确认通用接口 SNMP exporter 是独立于硬件 YAML 的路径。由于当前没有通过固定 LibreNMS 来源校验的 exporter module，旧手工 OID module 与旧接口轮询段已停用；文档明确记录了接口指标当前不会产生新采样的缺口。

## 实际修改文件

- `docs/architecture/SNMP采集全流程与代码索引.md`
- `backend/vendor/librenms/README.md`
- `backend/vendor/librenms/source-manifest.json`
- `backend/tests/snmp/test_librenms_bundle_manifest.py`
- `docs/plans/plan_20261008_2008_01_多厂商规则与采集周期审计.md` 及对应 walkthrough
- `docs/plans/plan_20261008_2321_01_librenms清单来源范围修正.md` 及对应 walkthrough
- `docs/plans/plan_20261008_2346_01_全量SNMP采集流程文档与主线交付.md`
- 本 walkthrough
- 与 LibreNMS 规则收敛、SNMP 硬件采集、资产导入、Monitoring V1、Grafana 与迁移相关的后端/前端/监控代码和测试；LibreNMS MIB 资源按 manifest 收录。

## 验证

- 完整后端 pytest（修复前基线）：3,508 passed、11 failed、1 skipped、26 subtests passed，耗时 5,927.32 秒。11 个失败涉及过期的 LibreNMS MIB 上传状态变量、旧 profile 注解 mock、旧 Grafana 查询/面板数量断言和迁移序号断言。
- 针对失败修复的复测：Grafana 三个测试文件 71 passed；SNMP MIB 上传与设备健康三个测试文件 21 passed；迁移注册 Postgres 测试 1 passed。修复后没有在本机重跑 98 分钟的完整后端套件；推送后的 release workflow 将执行完整门禁。
- Grafana 生成器：运行通过；Python 编译通过；12 个 dashboard JSON 均可解析。只更新网络总览和无线 dashboard 生成物。
- PostgreSQL-only policy scanner：0 项违规。
- `git diff HEAD --check`（排除按上游字节原样保存的 LibreNMS `mibs/**` 与 `resources/definitions/**`）：通过；保留 Windows 换行提示，不改写上游来源文件。
- 前端 lint：通过。
- 前端 Vitest：122 个测试文件、469 个测试通过。
- Vite 生产构建：通过，输出到独立目录 `dist-validation-codex-20261009`。
- Grafana dashboard 生成：通过。
- LibreNMS manifest 文件完整性：2,357 条记录、2,357 个 bundle 路径、0 项完整性问题。
- 暂存 Git 对象来源检查：2,357 个 MIB 记录与 258 个规则文件共 2,615 个输入，0 项哈希/大小不一致。
- `git diff --cached --check`（排除按上游字节原样保存的 LibreNMS `mibs/**` 与 `resources/definitions/**`）：通过。来源文件本身保留上游 CRLF/空白，不做 whitespace 改写。
- 功能代码提交 `5145245cc28a453d1b66bd68b3aa43d7f5012c77` 已推送到 `origin/main`。对应 GitHub Actions #692 已成功完成（15 分 24 秒）：后端发布门禁通过，Vitest 122 个测试文件/469 个测试通过；清理后的发行树同步步骤随工作流完成。运行记录：<https://github.com/chaojifeixia-007/netsops/actions/runs/37822199572>。
- 本次修订交接文档会产生新的文档提交；该提交对应的 Actions 运行仍需检查。最终关机尚未执行。

## 未执行验证与剩余风险

- 没有在真实网络设备上重新采集，也没有部署或重启 Ubuntu 主机。
- 修复后的完整后端套件已在 GitHub Actions #692 中运行并通过。此前本地完整套件是在修复前运行，曾有 11 项失败；修复后执行的针对性测试通过，完整修复后覆盖以 #692 为准。
- Nexora 使用 Python 执行器解释固定 LibreNMS YAML，没有通过全部厂商与官方 PHP 运行实例的 differential parity 测试，因此不宣称与 LibreNMS PHP 每个边界行为完全等价。
- 14 个 OS profile 没有 discovery YAML；31 个已有 discovery YAML 的 profile 当前未解析出硬件定义；不会用自定义 OID 静默补齐。
- 通用接口 SNMP exporter 当前没有受来源校验的 module，新的接口指标样本不会产生；需单独确定符合 LibreNMS 来源要求的通用接口实现。
- 迁移 `m0279_retire_custom_snmp_metric_profiles` 会清除自定义指标 Profile 绑定并删除 Profile 记录，downgrade 不可恢复。
- 功能提交的主线推送和 Actions #692 已完成；本次文档修订提交的 Actions 尚待验证，最终关机尚未执行。
