# ING-010 Metadata 提取、规范化、验证与 UNKNOWN 合同

## 结论

ING-010 使用本地、确定性、无副作用的 Metadata Gate。输入必须已经通过
ING-006 解析、ING-007 清洗和 ING-008 安全扫描。输出只包含规范化 Metadata、
字段来源、UNKNOWN 原因、哈希化审计问题、关系字段投影以及解析/清洗/扫描版本；
不包含正文，不访问网络或文件系统。

## 权威顺序

文档显式 Metadata 优先于 Source Metadata。Source 与文档在 vendor、
document_category、source_type、official_only 上冲突时失败关闭。标题可从一级
标题或文件名提取；目录只能作为提示和冲突检查，不能静默覆盖文档值。tenant、
ACL、用户、角色、凭据、正文和原始内容属于服务端控制面，任何层级出现都拒绝。
source_id、source_version_id、source_url、source_trust_level、classification 和
exclude_from_rag 只能来自 Source 控制面，文档 Front Matter 不得伪造或覆盖。

## 规范化

- Key 使用 Unicode NFKC 后转换为小写 snake_case；规范化后重名直接拒绝。
- 文本执行 NFKC、空白折叠、控制字符和长度检查。
- official_only/exclude_from_rag 使用严格布尔转换。
- vendor 仅规范化为 Huawei、Cisco、H3C、Ruijie 或 all。
- category/source_type/status 使用固定 allowlist；rag_priority 限制为 0～100。
- 数组去重，集合排序，嵌套深度、字段数和总字节数均有上限。
- Metadata Hash 使用排序后的 canonical JSON 计算，重建必须得到相同结果。

## UNKNOWN 规则

缺失或无法识别的字符串字段写为 `UNKNOWN`，布尔等有类型字段写为 `null`，并
单独记录 unknown_fields、reason 和安全的 unresolved value。审计问题只记录
稳定 code、field、source、severity 和短哈希。缺失 status 安全降级为 draft，
不得默认 active。

Product、OS、Software Version、CLI Platform、Vendor 等未知值不会从正文、目录、
driver 或模型记忆中猜测。它们以 REVIEW 状态继续进入 ING-011 Entity Resolution；
UNKNOWN 或 REVIEW 状态不得发布。

## 数据库与兼容性

m0113 已提供 metadata_json、Metadata 标量列、parse status/error、原文和 Hash，
因此本任务没有新增 DDL。Source Registry 和 Source Version 继续由 m0116 管理，
tenant/ACL/身份仍为关系字段和授权边界，不能降级到 Metadata JSON。

V1 `ai.services.knowledge_metadata` 保持不变；新增 AI 命名空间兼容导出指向
`services.document_metadata_extraction`。回滚只需停用新增 Adapter，不删除数据、
不回滚 Schema，也不影响 V1 检索。
