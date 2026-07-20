# 资产管理 SSH 端口与 Excel 日期导入修复实施计划

本计划旨在解决以下两个问题：
1. 在资产管理页面修改 SSH 端口后，底层驱动仍然使用默认端口 22 的问题。
2. 从 Excel 表格导入资产后，购买日期和保修到期时间格式不正确（显示为 Excel 序列化数字如 45809、46539）的问题。

## Proposed Changes

### 1. 后端：SSH 端口同步与 Fallback

#### [MODIFY] [backend/api/assets.py](file:///d:/netops/netsops-main/backend/api/assets.py)
- 在 `_create_linked_device` 中，将资产 of `management_port` 插入到 `devices` 表的 `management_port` 字段中。
- 在 `_sync_device_from_asset` 中，将资产 of `management_port` 同步更新到 `devices` 表的 `management_port` 字段。

#### [MODIFY] [backend/api/devices.py](file:///d:/netops/netsops-main/backend/api/devices.py)
- 在 `_resolve_connection_target` 中，从传入的 payload (支持 `port` 与 `management_port`) 或存储的设备行数据中解析出管理端口，并赋给 `resolved['port']`。
- 在 `test_device_connection` (即 `/api/devices/connect` 连接测试接口) 中，优先使用 `resolved['port']` 探测连接，不再无条件写死 22。
- 在 `read_devices` 的轻量模式下，将 `d.management_port` 列包含在 SELECT 子句中，以便前端获取。

#### [MODIFY] [backend/services/operational_data_service.py](file:///d:/netops/netsops-main/backend/services/operational_data_service.py)
- 在 `_build_connection_params` 中，当获取连接端口时，支持 fallback 到 `management_port`，即：`int(device_info.get('port') or device_info.get('management_port') or 22)`。

#### [MODIFY] [backend/services/ip_locator_service.py](file:///d:/netops/netsops-main/backend/services/ip_locator_service.py)
- 在 `_build_ssh_params` 和 `_send_command` 及其它获取端口的地方，当获取端口时，支持 fallback 到 `management_port`，即：`int(device_info.get('port') or device_info.get('management_port') or 22)`。

#### [MODIFY] [backend/services/diagnose_service.py](file:///d:/netops/netsops-main/backend/services/diagnose_service.py)
- 在诊断的端口检查和 SSH 属性构建中，支持 fallback 到 `management_port`，即：`int(dev.get('port') or dev.get('management_port') or 22)`。

#### [MODIFY] [backend/services/connectivity_service.py](file:///d:/netops/netsops-main/backend/services/connectivity_service.py)
- 在 `_build_device_info` 中，支持 fallback 到 `management_port`，即：`dev.get('port') or dev.get('management_port') or 22`

---

### 2. 前端：Excel 日期导入格式化与端口字段

#### [MODIFY] [src/types.ts](file:///d:/netops/netsops-main/src/types.ts)
- 在 `Device` 接口中加入可选字段 `management_port?: number;`。

#### [MODIFY] [src/hooks/useDeviceConnectionAndSnmp.ts](file:///d:/netops/netsops-main/src/hooks/useDeviceConnectionAndSnmp.ts)
- 在发起 `/api/devices/connect` 连接测试请求时，增加传入 `management_port: deviceToTest.management_port`，以便测试连接接口使用用户自定义的端口。

#### [MODIFY] [src/pages/AssetManagement/index.tsx](file:///d:/netops/netsops-main/src/pages/AssetManagement/index.tsx)
- 在 `handleImport` 解析 Excel 数据循环中，为购买日期 (`purchase_date`) 和保修到期时间 (`warranty_expiry`) 字段编写日期转换和格式化函数 `formatExcelDate`。
- `formatExcelDate` 将处理：
  1. JS Date 对象（格式化为 `YYYY-MM-DD`）。
  2. Excel 序列号数字（如 45809 转换为 `2025-06-01`，46539 转换为 `2027-06-01`）。
  3. 带 `/` 或 `.` 分割的日期字符串（统一规范化为 `YYYY-MM-DD` 格式）。

## Verification Plan

### Automated Tests
- 运行后端单元测试确保没有破坏现有的测试：
  `pytest` 或 `poetry run pytest`

### Manual Verification
1. **测试 SSH 端口配置**：
   - 在资产管理中，编辑某个设备的 SSH 端口为非 22 端口（例如 2222）。
   - 发起命令执行、配置同步、测试连接或诊断，检查后端连接时使用的端口，验证其已变更为 2222 端口。
2. **测试 Excel 导入日期格式**：
   - 使用包含“购买日期”与“保修到期”列的 Excel 表格进行资产导入。
   - 检查导入后的数据列表及详情页，确认日期格式已正确转换为 `YYYY-MM-DD` 格式。
