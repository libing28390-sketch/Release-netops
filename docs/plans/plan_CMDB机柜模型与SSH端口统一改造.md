# CMDB 机柜模型与 SSH 端口统一改造计划

## 任务目标

本计划用于承接两个生产级 CMDB/NetOps 基础能力整改需求：

1. 机柜模型不能写死为 42U，需要支持不同高度、不同类型、不同安装规则的生产机柜。
2. 所有涉及 SSH 登录设备的代码，都必须支持自定义 SSH 端口；默认端口为 22，并允许用户在资产管理页面维护该端口。

## 当前需求确认

### 1. 机柜模型需求

当前问题：

- 机柜高度如果写死 42U，只适合 demo 或少量标准机柜。
- 生产环境中常见机柜高度和类型差异很大，例如：
  - 24U
  - 32U
  - 37U
  - 42U
  - 45U
  - 47U
  - 48U
  - 52U
  - 壁挂机柜
  - 网络配线柜
  - ODF / 光纤配线架
  - 电源柜 / PDU 柜
- 不同机柜类型对正反面安装、深度、承重、功耗容量、U 位规则的要求不同。

目标模型：

```text
Rack Type / Cabinet Type
        ↓
Rack Instance
        ↓
Rack Unit Occupancy
        ↓
Mounted Asset / Device
```

核心要求：

- 机柜实例必须支持动态 `total_u`，不能再由前端或后端写死 42。
- 机柜类型需要抽象出来，用于描述默认高度、宽度、深度、承重、功率容量、是否允许正反面挂载等规则。
- 设备上架、拖拽、U 位冲突校验必须读取机柜实例的真实 `total_u`。
- 正反面挂载能力不应全局写死，应由机柜类型或机柜实例决定。

### 2. SSH 自定义端口需求

当前原则：

- 所有 SSH 登录设备的代码都必须支持自定义端口。
- 默认端口为 22。
- 用户应能在资产管理页面修改设备的默认 SSH 管理端口。
- 该端口应统一写入设备/资产模型，并被所有 SSH 连接链路读取。

需要覆盖的 SSH 场景包括但不限于：

- 设备连接测试
- 自动化任务 `/api/execute`
- Playbook 自动化执行
- 快捷查询 / parsed-command / operational-data
- 配置备份
- 配置快照 / 回滚
- 巡检
- 拓扑发现 / LLDP 采集
- IP 定位 / 路径追踪中需要登录设备的查询
- PAM / 操作工作台 / 本地终端拉起
- 密码轮换 / 凭据验证
- 其他 Netmiko、Scrapli、Paramiko、AsyncSSH 连接入口

统一规则：

```text
ssh_port = device.management_port or device.port or asset.management_port or 22
```

最终建议收敛为：

```text
devices.management_port
physical_assets.management_port
```

其中：

- `management_port` 为空时默认 22。
- 前端展示和编辑使用 `management_port`。
- 后端连接统一通过 helper 解析，不允许各处散落 `port=22`。

## 影响范围

### 数据库 / 模型层

- `backend/database/schema.py`
- `racks`
- `rack_devices`
- `device_types`
- 可能新增 `rack_types`
- `devices.management_port`
- `physical_assets.management_port`

### 后端 API / Service

- `backend/api/racks.py`
- `backend/services/rack_service.py`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/api/automation.py`
- `backend/api/playbooks/engine.py`
- `backend/api/configs.py`
- `backend/services/automation_service.py`
- `backend/services/operational_data_service.py`
- `backend/services/inspection_service.py`
- `backend/services/topology_service.py`
- `backend/services/ip_locator_service.py`
- `backend/services/password_rotation_service.py`
- `backend/api/pam.py`
- `backend/api/system.py`
- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`
- `backend/drivers/scrapli_driver.py`
- 其他通过 `ConnectHandler`、`Scrapli`、`paramiko`、`asyncssh` 建立 SSH 的代码

### 前端页面

- 资产管理页面：支持编辑默认 SSH 管理端口
- 设备管理页面：如存在设备编辑弹窗，也应支持端口
- 机柜管理页面：支持动态 U 高度渲染
- 机柜/资产导入模板：支持机柜类型、机柜高度、管理端口
- 自动化/连接测试页面：展示连接目标端口或至少确保使用后台端口配置

## 拟修改文件

第一阶段重点文件：

- `backend/database/schema.py`
- `backend/services/rack_service.py`
- `backend/api/racks.py`
- `src/pages/RackManagement/index.tsx`
- `src/pages/RackManagement/components/RackElevation.tsx`
- `src/pages/AssetManagement/index.tsx`
- `src/pages/AssetManagement/components/AssetModal.tsx`
- `src/pages/AssetManagement/constants.ts`
- `backend/api/assets.py`
- `backend/api/devices.py`
- `backend/services/vault_service.py`（如需统一凭据/端口 helper，可引用但不应混放职责）

第二阶段全链路 SSH 端口收敛文件：

- `backend/drivers/netmiko_driver.py`
- `backend/engine/drivers/netmiko_driver.py`
- `backend/drivers/scrapli_driver.py`
- `backend/services/operational_data_service.py`
- `backend/services/automation_service.py`
- `backend/api/automation.py`
- `backend/api/playbooks/engine.py`
- `backend/api/configs.py`
- `backend/services/inspection_service.py`
- `backend/services/topology_service.py`
- `backend/services/ip_locator_service.py`
- `backend/services/connectivity_service.py`
- `backend/api/pam.py`
- `backend/api/system.py`
- `backend/services/password_rotation_service.py`

## 实施阶段

### Phase 1：机柜高度动态化

目标：先去掉 42U 写死。

实施项：

1. 检查当前 `racks` 表是否已有 `total_u` / `u_height` 等字段。
2. 若没有，则新增 `total_u INTEGER DEFAULT 42`。
3. 所有机柜查询 API 返回 `total_u`。
4. 前端机柜视图使用 `rack.total_u` 渲染 U 位。
5. 设备上架、拖拽、移动、编辑时的边界校验使用 `rack.total_u`。
6. 兼容旧数据：旧机柜没有高度时按 42U 回填或运行时默认 42。

验收标准：

- 42U、45U、47U、24U 机柜都能正确渲染。
- 拖拽到超过实际 U 高度的位置会被拒绝。
- 旧数据不崩溃。

### Phase 2：机柜类型基础模型

目标：引入 `rack_types`，支持不同机柜类型。

建议字段：

```text
rack_types
- id
- name
- category
- default_u_height
- width_mm
- depth_mm
- max_power_w
- max_weight_kg
- allow_front_rear_mount
- description
- created_at
- updated_at
```

`racks` 建议增加：

```text
- rack_type_id
- total_u
- width_mm
- depth_mm
- max_power_w
- max_weight_kg
- allow_front_rear_mount
```

规则：

- 新建机柜时可选择机柜类型。
- 选择类型后自动带出默认高度和规格。
- 实例层允许覆盖高度、功率、承重等参数。
- 正反面挂载校验优先看机柜实例，实例为空时看机柜类型。

验收标准：

- 可维护机柜类型。
- 新建机柜可继承类型默认值。
- 不同类型机柜的 front/rear 规则可不同。

### Phase 3：资产管理支持 SSH 管理端口

目标：用户可在资产管理页面维护设备默认 SSH 端口。

实施项：

1. 检查 `devices.management_port` 和 `physical_assets.management_port` 是否已存在。
2. 如缺失则新增，默认 22。
3. 资产创建/编辑弹窗增加“SSH 管理端口”字段。
4. 资产导入模板增加管理端口列。
5. 资产到设备同步时同步 `management_port`。
6. 设备列表/详情可展示管理端口。

验收标准：

- 用户可将某设备 SSH 端口改为非 22，如 2222。
- 保存后设备连接测试、自动化、备份等后续阶段能读取该端口。

### Phase 4：SSH 端口解析 helper 统一

目标：所有 SSH 连接入口不再散落写死 `22`。

建议新增统一 helper：

```python
def resolve_ssh_port(device: dict, default: int = 22) -> int:
    raw = (
        device.get("management_port")
        or device.get("port")
        or device.get("ssh_port")
        or default
    )
    try:
        port = int(raw)
    except Exception:
        port = default
    if port < 1 or port > 65535:
        return default
    return port
```

建议位置：

- `backend/services/device_connection_profile.py`

或：

- `backend/core/device_connection.py`

避免把端口解析散落在各个 API 或 driver 中。

验收标准：

- 全局搜索 `port=22`、`get('port', 22)`、`or 22` 后，所有 SSH 连接场景都改为统一 helper 或明确合理保留。
- 非 SSH 场景不受影响。

### Phase 5：所有 SSH 链路接入自定义端口

需要逐个确认并接入：

```text
设备连接测试
自动化任务
Playbook 执行
快捷查询
配置备份
配置快照 / 回滚
巡检
拓扑发现
IP 定位 / 路径追踪
PAM / 操作工作台
本地终端拉起
密码轮换
凭据验证
```

每个入口需要确认：

- 是否读取 `management_port`
- 是否 fallback 到 22
- 是否传给 Netmiko/Scrapli/Paramiko/AsyncSSH
- 日志是否只记录端口，不记录密码
- 前端错误提示是否显示目标端口

验收标准：

- 将测试设备端口配置为 2222 后，各 SSH 功能都连接 2222。
- 未配置端口的设备仍默认连接 22。

### Phase 6：测试与回归

后端测试：

- 机柜动态高度：
  - 24U / 42U / 47U 渲染数据
  - U 位越界拒绝
  - front/rear 规则
- SSH 端口：
  - 默认 22
  - 自定义 2222
  - 非法端口回退或拒绝
  - 各 driver 参数包含正确端口

前端验证：

- 资产管理页面可编辑端口。
- 机柜页面按真实高度显示。
- 拖拽校验符合机柜高度。

命令建议：

```powershell
python -m py_compile ...
.\.venv\Scripts\python.exe -m pytest backend\tests\... -q
npm run lint
npm run build
git diff --check
```

## 风险与注意事项

### 1. 数据兼容风险

旧数据可能没有 `total_u` 或 `management_port`。

处理策略：

- `total_u` 默认 42。
- `management_port` 默认 22。
- 迁移脚本必须幂等。

### 2. 连接链路遗漏风险

SSH 连接入口很多，最容易漏。

处理策略：

- 使用 `rg` 全局扫描：

```powershell
rg -n "ConnectHandler|Scrapli|paramiko|asyncssh|management_port|get\\('port'|port.*22|:22|ssh://" backend src
```

- 每个入口建立 checklist。

### 3. 前端和后端字段不一致风险

资产、设备、连接测试、自动化可能使用不同字段名。

处理策略：

- 前端统一展示 `management_port`。
- 后端兼容读取 `management_port`、`port`、`ssh_port`，但写入统一收敛到 `management_port`。

### 4. 机柜类型过度设计风险

第一阶段不建议一次做完整容量管理。

处理策略：

- 先完成动态 U 高度和基础 rack_type。
- 功耗、承重、散热、容量预测作为后续增强。

## 最终确认的需求摘要

当前确认需求如下：

1. 机柜高度不能写死 42U。
2. 需要支持不同机柜类型。
3. 机柜实例应支持动态 `total_u`。
4. 机柜类型应定义默认高度、深度、功率、承重、是否支持正反面挂载。
5. 设备上架、拖拽、U 位冲突校验必须基于真实机柜高度。
6. 所有 SSH 登录设备的代码必须支持自定义端口。
7. SSH 默认端口为 22。
8. 用户可以在资产管理页面修改设备默认 SSH 端口。
9. 自动化、备份、巡检、拓扑、PAM、连接测试等所有 SSH 链路都必须读取该端口。
10. 后续实现时需配套测试和回归验证。
