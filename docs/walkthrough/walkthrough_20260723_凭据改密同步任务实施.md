# 凭据改密同步任务实施记录

## 完成内容

本次将凭据中心的密码修改改造成“设备先改密并验证，中心后提交”的任务流程：

- 新增旧密码和旧 Enable 密码的服务端校验；
- 新增凭据改密任务、凭据级互斥锁和设备级加密快照；
- 复用现有 `jobs`、`job_targets`、`job_events` 任务体系；
- 单任务默认最多 5 台设备并行，继续受全局 SSH 限流器和单设备并发 1 约束；
- Driver 支持改密任务专用连接/命令读取超时；
- 设备端改密完成后使用新密码重新连接验证；
- 所有关联设备验证成功后才更新 `credentials` 表；
- 部分失败时保持凭据中心旧密码，并尝试回滚已成功设备；
- 回滚失败会进入人工介入状态；
- 前端编辑凭据时显示旧密码输入框，并轮询任务进度。

## 关键接口行为

### 有关联设备

`PUT /api/credentials/{id}` 在密码发生变化且存在关联设备时返回 HTTP `202`，响应包含：

```json
{
  "success": true,
  "job_id": "job-...",
  "device_count": 5,
  "message": "Credential change accepted; hardware synchronization is running"
}
```

此时凭据中心仍保留旧密码。前端通过 `/api/jobs/{job_id}` 查询状态。

### 无关联设备

旧密码验证通过后直接更新凭据中心，不创建硬件任务。

### 失败处理

- 预检查失败：不连接设备，不更新中心；
- 设备认证/命令/超时失败：记录设备级失败结果；
- 全部设备失败：中心旧密码保持不变；
- 部分成功：尝试回滚已经成功的设备；
- 回滚失败：中心旧密码保持不变，任务标记需要人工介入。

## 配置项

默认值已写入 `backend/core/config.py`，并同步到 `.env` 与 `.env.example`：

- `PASSWORD_SYNC_MAX_WORKERS=5`
- `PASSWORD_SYNC_DEVICE_TIMEOUT_SECONDS=240`
- `PASSWORD_SYNC_CONNECT_TIMEOUT_SECONDS=20`
- `PASSWORD_SYNC_COMMAND_READ_TIMEOUT_SECONDS=60`
- `PASSWORD_SYNC_RETRY_LIMIT=1`

## 验证记录

已执行：

```text
pytest backend/tests/test_credential_management_sync.py backend/tests/vendor_audit/test_network_access_limiter.py -q
13 passed

pytest backend/tests -q
150 passed, 1 warning, 25 subtests passed

npm run lint
passed

npm run build
passed
```

另使用内存 SQLite 验证了 `m0029_credential_password_sync_jobs` 新迁移可以创建三张任务表和索引。

## 尚未执行

本次没有连接真实交换机，也没有执行真实密码修改。上线前应先使用 Cisco、Huawei、H3C 各一台测试设备，验证改密、保存、新密码重连、失败回滚和人工介入流程。
