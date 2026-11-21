# 标签体系全新模型与自动化目标筛选改造 Walkthrough

> 日期：2026-07-22  
> 范围：统一标签体系、设备/资产标签查询、标签中心、定时自动化目标筛选

## 1. 本次改造决策

本次按全新模型直接切换，不保留旧设备标签数据和旧 `device_tags` 兼容读取逻辑。

清理范围限定为：

- 旧 `tag_definitions`。
- 旧 `device_tags`。
- 旧标签相关数据和索引。

未清理设备、资产、凭据、用户、自动化作业等其他业务数据。

## 2. 新数据模型

```text
tag_categories
  业务、环境、网络区域、运维、安全、项目、生命周期、系统自动

tag_definitions
  id / category / code / label / label_zh / color / resource_types
  exclusive_group / priority / source_type / is_system / is_active

tag_assignments
  resource_type / resource_id / tag_id / source_type / rule_id
  inherited_from / expires_at / created_by / created_at

tag_assignment_history
  add / remove / replace 等绑定变更历史
```

标签使用稳定 `code`，例如：

- `env.production`
- `zone.core`
- `ops.change-freeze`
- `security.no-auto-change`
- `system.status.online`

## 3. 核心行为

- 系统在线/离线标签归入 `system_auto`，由系统自动维护，不能人工绑定、修改或删除。
- 环境和生命周期标签支持互斥组校验。
- 使用中的普通标签不能直接删除，应先停用。
- 普通标签绑定、解绑和替换写入绑定历史。
- 设备、站点、机柜、接口、VLAN、VRF、链路预留统一资源标签能力；当前设备页面通过统一 assignment 表读取。
- 标签中心使用标签代码，不再使用旧的分类和值字段。

## 4. 自动化目标筛选

自动化和定时任务统一解析以下条件：

```json
{
  "groups": [
    { "tag_ids": ["production"] },
    { "tag_ids": ["core", "aggregation"] }
  ],
  "exclude_tag_ids": ["change-freeze"]
}
```

语义为：

```text
(production) AND (core OR aggregation) AND NOT change-freeze
```

前端配置预览、标签目标 API 和调度器实际执行均调用同一目标解析逻辑，避免页面命中设备与实际执行设备不一致。

新增接口：

```text
GET  /api/tags/categories
POST /api/tags/resolve-devices
```

标签查询接口也支持 `exclude_tag_ids`。

## 5. 已修改的模块

- `backend/database/schema.py`：新建统一标签表和索引，并在发现旧标签结构时清理旧标签表。
- `backend/services/tag_service.py`：重写标签目录、绑定、互斥校验、历史记录、状态同步、目标解析和统计。
- `backend/api/tags.py`：新增分类和目标解析接口，创建标签改用稳定 code。
- `backend/api/devices.py`、`backend/api/assets.py`、`backend/api/cmdb.py`：改用通用标签 assignment 查询。
- `backend/services/scheduler_service.py`：按完整标签条件解析自动化目标。
- `src/pages/TagManagementTab.tsx`、`src/types.ts` 和标签选择器：切换到新分类和 code 字段。
- `backend/tests/test_tag_system.py`：增加新目录、互斥、包含/排除解析和统计测试。

## 6. 验证结果

### 通过

- 标签专项测试：4 passed。
- TypeScript：`npm exec tsc -- --noEmit --pretty false` 通过。
- 前端 lint：`npm run lint` 通过。
- 前端生产构建：`npm run build` 通过。
- 数据库初始化：PostgreSQL 新模型建表、分类播种和 21 个内置标签播种成功。

### 既有问题

全量后端测试结果：134 passed，2 个既有测试因缺少 `isolated_db` fixture 报错：

- `backend/tests/scheduled_jobs/test_outbound_expected_ip.py::test_consecutive_confirmation_mismatch`
- `backend/tests/scheduled_jobs/test_outbound_expected_ip.py::test_status_severity_and_affect_health`

该错误发生在测试 fixture 初始化阶段，与本次标签模型改造无关。

### 浏览器验证

本次尝试读取本地页面时被当前浏览器 URL 安全策略拦截，因此未绕过策略执行浏览器操作。前端行为已通过 TypeScript、lint 和生产构建完成代码级验证。

