# ADR / BLOCKER：MIG-007 迁移范围与首批官方目录不一致

状态：BLOCKED，等待 NET/ARCH/PM 对范围作出明确决策

## 背景

MIG-007 只能对通过 MIG-006 官方来源、Source Registry/Version 和 reviewed catalog snapshot 校验的文档执行 Parse → Chunk → Embed → Index。当前 CAT-001 冻结的首批官方范围是：

- Huawei CloudEngine 6800 / VRP8；
- Cisco Catalyst 9300 / IOS-XE。

PostgreSQL `BEGIN READ ONLY` 统计显示，当前 `tenant-default` 有 154 条旧文档，全部标记为 Huawei；主要产品族为 S5700（109）、S6700（19）和 `CloudEngine 58&68&78&88&98`（10），没有能够与 CAT-001 的 `CloudEngine 6800` 精确匹配的已审核目录实体。历史 Metadata 虽有 92 个唯一来源 URL 声明，但没有 active/valid 的官方 Source Registry/Version 绑定；DB-006/DB-007 目录表也尚未进入物理 schema。

## 决策边界

不得把 S 系列、模糊 CloudEngine 族或历史 `metadata_json.sources` 声明静默提升为 CloudEngine 6800 官方实体。不得修改 CAT-001、创建 Source Registry、改写 V1 Metadata 或启动 Provider/Chunk/Index 写入来绕过该阻断。

## 可选路径

### A（首选，不改变既定架构）

补充属于 CAT-001 首批范围的 CloudEngine 6800/VRP8 或 Cisco C9300 文档，并为每条文档提供同租户 active/valid Source Registry、Source Version、内容哈希和 reviewed catalog snapshot。MIG-006 重新验证产生 `verified` 后，MIG-007 才能执行。

### B（需要人工批准的架构变更）

通过新的 ADR/PM 范围评审扩展 CAT-001 到 S5700/S6700 等 S 系列，新增对应官方 host/path allowlist、产品/OS/版本 catalog、Source Registry/Version 和安全回归。该路径会改变首批范围，当前不自动执行。

### C（保持 V1 兼容）

将现有 S 系列旧文档继续保留为 V1 兼容数据，仅允许 V1 读取；不进入 V2 verified corpus，不生成 V2 Shadow 样本。

## 解除条件

1. NET/ARCH/PM 书面选择 A、B 或 C；
2. 若选择 A，提供首批范围内的官方来源和 reviewed catalog snapshot；
3. 若选择 B，完成新的 ADR、allowlist 和目录评审，并通过 CAT-004 安全门禁；
4. MIG-006 PostgreSQL 只读校验产生非零 `verified`；
5. MIG-007 重建门禁确认 eligible rows、阶段顺序、Provider 维度和回滚证据后，才能 apply。

## 安全与回滚

- 当前仅执行 PostgreSQL READ ONLY 查询，未修改 V1 文档、Chunk、Embedding 或索引。
- 在决策完成前保持 V1 默认读取路径，V2 重建 worker 不启动。
- 任何范围扩展失败时，撤销新增候选目录/来源记录并关闭 V2 migration wave，不删除既有 V1 数据。

## 证据

- `docs/knowledge-engine/evidence/MIG-007.md`
- `docs/knowledge-engine/eval/mig-006-official-entity-validation-report-v1.json`
- `docs/knowledge-engine/eval/mig-007-rebuild-gate-report-v1.json`
- `docs/knowledge-engine/architecture/CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml`

## A 路径复核补充（2026-08-18）

官方 Huawei 页面检索和只读 `basic` 元数据接口已经确认 `CE6885-48YS8CQ` 位于
CloudEngine 6800 的 V300R024C10/C11 文档适用范围内，并返回带签名标记的 ZIP 文件
元数据。经过 CAT-001/CAT-004 的受控评审后，新增了一个仅限这两份 EDOC、精确 query
和 `partNo=6001` 的 server-owned artifact endpoint；普通 canonical URL、redirect 和
跨主机规则没有放宽。当前已在内存中取得并校验 ZIP magic、大小、哈希和 PDF 适用型号，
但没有把正文写入仓库或数据库。

因此 A 路径目前从“缺合法正文证据”推进为“官方正文 artifact 可验证、待登记 source
version 和目录 owner review”。`MIG-006 verified=0` 和 `MIG-007
BLOCKED_NO_VERIFIED_SOURCE_ENTITIES` 仍保持不变，因为当前 legacy rows 的 `source`
仍为 `upload`，不能静默改写为新 Source Registry；正式同租户 source/version seed
及目录激活仍需通过 MIG-006 的只读门禁。

对应的受控实现和哈希证据见：

- `docs/knowledge-engine/evidence/CAT-004-HUAWEI-ARTIFACT.md`
- `docs/knowledge-engine/catalog/CAT-005-HUAWEI-CE6800-OFFICIAL-SOURCE-SNAPSHOT-20260818.yaml`

最终结论：MIG-007 保持 `BLOCKED_NO_VERIFIED_SOURCE_ENTITIES`，不得勾选完成。
