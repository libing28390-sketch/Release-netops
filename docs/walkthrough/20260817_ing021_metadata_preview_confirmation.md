# ING-021 导入前 Metadata 预览与人工确认

## 目标

导入文件或粘贴文档时，先由服务端执行与实际入库一致的 Front Matter 解析、目录一致性校验和规范化，再由操作者确认，最后才进入既有文档/Chunk 事务。

## 实现

- `backend/ai/services/metadata_confirmation_service.py`
  - 解析 `parse_markdown_document` 和 `validate_metadata`；
  - 输出脱敏的规范化 Metadata、解析状态、警告和内容摘要哈希；
  - 生成 15 分钟 HMAC-SHA256 确认令牌；
  - 令牌绑定租户、当前操作者、原始内容哈希、Metadata 和导入选项；
  - 拒绝身份、租户、ACL、权限和凭据字段。
- `backend/ai/api/assistant.py`
  - 新增 `POST /api/ai/assistant/documents/metadata-preview`；
  - `POST /api/ai/assistant/documents` 接受 `metadata_confirmation_token` 与 `metadata_confirmed` 两个增量字段；
  - 令牌失效、篡改、跨租户或内容变化时，在任何数据库写入前返回稳定错误码。
- `src/api/ai.ts`
  - 增加预览类型、API 客户端和确认字段。
- `src/pages/ai/Knowledge/KnowledgeManagementTab.tsx`
  - 批量上传、目录快捷导入和粘贴导入均先请求服务端预览；
  - 展示最多 8 条规范化摘要及警告数量；
  - 用户取消确认时不提交任何文档；
  - 确认后携带服务端令牌入库。

## 验证命令与结果

PowerShell:

    $env:PYTHONPATH='backend'
    .venv\Scripts\pytest.exe backend/tests/ai/test_ing021_metadata_confirmation.py -q -p no:cacheprovider
    # 5 passed

    .venv\Scripts\pytest.exe backend/tests/ai -q -p no:cacheprovider
    # 267 passed

    .venv\Scripts\pytest.exe backend/tests/catalog -q -p no:cacheprovider
    # 192 passed in 317.34s

    npm.cmd run test:frontend -- --run
    # 22 files / 104 tests passed

    npm.cmd run lint
    # PASS

    npm.cmd run build
    # PASS; existing large-chunk warning only

## 异常路径

- 无 Front Matter：沿用兼容路径，但在预览中明确显示 `metadata_front_matter_missing_legacy_path`；
- malformed YAML、目录/厂商或目录/分类冲突：预览失败，不生成可用确认令牌；
- 修改正文、Metadata、厂商、平台或导入选项：返回 `METADATA_CONFIRMATION_STALE`；
- 过期/篡改/跨租户令牌：分别返回稳定的 expired/invalid/scope 错误；
- 凭据或身份字段：预览直接拒绝，不把值回显到响应。

## 权限、数据库与回滚

- 预览和导入仍使用 `ai.knowledge.manage` 权限；
- 本任务不新增 DDL，实际 PostgreSQL 文档/Chunk 写入仍由既有事务服务负责；
- 老 V1 客户端不发送新增字段时保持兼容；
- 回滚只需撤回前端预览调用/新增字段，服务端增量路由无需数据库回滚。

## 当前限制

浏览器可见验证仍需要用户在本地服务中登录；本轮没有绕过认证或读取凭据。自动化和构建验证已完成。
