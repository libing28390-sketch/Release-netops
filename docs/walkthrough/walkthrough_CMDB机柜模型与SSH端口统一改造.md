# CMDB 机柜模型与 SSH 端口统一改造执行记录

## 执行时间

2026-07-12

## 本次目标

围绕 CMDB 资产模型和设备登录链路完成两类整改：

1. 机柜不再隐含固定 42U，继续完善动态 `total_u`，并引入可复用的机柜类型模型。
2. 所有涉及 SSH 登录设备的核心路径支持自定义管理端口，字段统一使用 `management_port`，默认值为 22。

## 完成内容

### 1. SSH 管理端口统一解析

新增统一解析入口：

- `backend/services/connection_profile.py`

规则：

- 优先读取 `management_port`
- 兼容 `port`
- 兼容 `ssh_port`
- 兼容 PAM 会话快照字段 `target_port`
- 无效、为空或越界时回退到默认 22

已接入路径：

- `backend/api/assets.py`
  - 资产连通性校验使用资产 `management_port`
  - TCP 探测和 SSH 登录验证使用同一个端口
- `backend/api/pam.py`
  - PAM 会话创建时写入真实 `target_port`
  - PAM WebSocket 实际连接读取会话端口
  - PAM 会话列表返回 `target_port`
- `backend/api/system.py`
  - 本地终端调起审计写入真实端口
  - token exchange 返回真实端口
  - Xshell、PuTTY、SecureCRT、本地 fallback 命令携带端口
- `backend/drivers/base.py`
  - 旧驱动基类使用统一解析
- `backend/engine/drivers/base_driver.py`
  - 新引擎驱动基类使用统一解析
- `backend/engine/pool.py`
  - 连接池 key 使用真实端口，避免不同端口设备误复用连接
- `backend/services/automation_service.py`
  - 自动化连通性检测使用统一端口解析
- `scripts/nexora_handler.py`
  - 桌面协议助手支持 token 返回端口
  - Xshell、PuTTY、SecureCRT、MobaXterm、系统默认 ssh URL 均携带端口
- `src/pages/AccessCenterTab.tsx`
  - 访问中心本地系统 SSH 调起使用设备 `management_port`
- `src/pages/AssetManagement/index.tsx`
  - 资产管理本地系统 SSH 调起使用资产 `management_port`
  - 后端返回端口时以前端端口为准更新调起 URL

### 2. 机柜类型模型

新增后端机柜类型基础能力：

- 数据表：`rack_types`
- 字段：
  - `name`
  - `vendor`
  - `model`
  - `total_u`
  - `width_mm`
  - `depth_mm`
  - `max_weight_kg`
  - `power_capacity_watts`
  - `allow_front_rear_mount`
  - `description`

扩展 `racks` 表：

- `rack_type_id`
- `width_mm`
- `depth_mm`
- `allow_front_rear_mount`

新增 API：

- `GET /api/rack-types`
- `GET /api/rack-types/{rack_type_id}`
- `POST /api/rack-types`
- `PUT /api/rack-types/{rack_type_id}`
- `DELETE /api/rack-types/{rack_type_id}`

删除保护：

- 如果已有机柜引用某个 `rack_type_id`，该机柜类型不能被删除。

### 3. 测试补充

新增测试：

- `backend/tests/test_connection_profile.py`
  - 验证 `management_port` 优先级
  - 验证兼容字段 `port` / `ssh_port` / `target_port`
  - 验证非法端口回退默认 22
- `backend/tests/test_rack_types.py`
  - 验证机柜类型创建
  - 验证机柜引用机柜类型
  - 验证被引用的机柜类型禁止删除

## 验证结果

已执行：

```bash
.\.venv\Scripts\python.exe -m pytest backend/tests/test_connection_profile.py backend/tests/test_rack_types.py backend/tests/test_racks_new_fields.py -q
```

结果：

```text
9 passed
```

已执行：

```bash
npm run lint
```

结果：

```text
tsc --noEmit passed
```

已执行关键残留扫描：

```bash
rg -n "ssh://.*:22|target_port, 22|port=device_config.get\('port', 22\)|get\('port', 22\)|self\.port = int\(device_info.get\('port', 22\)" backend src scripts
```

结果：

```text
未发现关键 SSH 调用残留固定 22 端口。
```

## 说明与后续建议

本次已完成后端机柜类型模型和 SSH 端口统一解析的核心闭环。

建议下一步继续补充：

1. 机柜管理前端增加“机柜类型模板”选择器。
2. 机柜列表展示宽度、深度、承重、功率容量等关键规格。
3. 批量导入机柜时支持按 `rack_type_name` 自动匹配模板。
4. PAM 历史页面展示 `target_ip:target_port`，便于审计确认真实登录端口。
5. 为配置备份、巡检、拓扑发现等批量任务补一组集成测试，验证非 22 端口设备能贯穿执行。
