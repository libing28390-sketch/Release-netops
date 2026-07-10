# Walkthrough: 机柜批量导入导出与输入框逻辑修复

我们已成功完成了该任务的所有变更。下面是详细的设计走查与测试验证报告。

## 1. 问题修复与功能实现

### 输入框逻辑修复 (Power & U-height Input Fix)
- **修复前**：用户在“新建/编辑机柜”弹窗中修改“最大功率”或“总 U 位”时，若清空输入框进行重新输入，触发的 `onChange` 事件会被 `parseInt("") || 0`（或 `|| 42`）立即将状态重置为 `0` 或 `42`，导致无法流畅删除旧数字并键入新数值。
- **修复后**：在 [index.tsx](file:///e:/data/netsops/src/pages/RackManagement/index.tsx) 的输入框逻辑中，允许临时存在空字符串 `''`。仅在用户点击“保存”提交时，在 `saveRack` 函数内才对其进行格式转换和默认值保底填充（`total_u || 42`、`power_capacity_watts || 0`）。这样保证了用户交互的自然顺畅。

### Excel 导入/导出/模板功能
- **前端处理**：利用前端已安装的 `xlsx` (SheetJS) 库直接在客户端实现 Excel 读取和写入，不仅避免了服务器代理网络的 Python 依赖报错，还提高了批量处理的瞬时性能。
- **模板下载**：在机柜管理页首部添加了“下载导入模板”按钮，可将包含示例行及中英文表头的 [机柜导入模板.xlsx] 导出给用户。
- **批量导入**：添加了“导入机柜”按钮。读取用户上传的 Excel，自动根据 `COL_MAP` 将中英文映射为后端所需字段，数据解析完成之后调用后端新增的批量接口 `/api/racks/batch` 提交给数据库。
- **列表导出**：添加了“导出机柜”按钮，将当前列表过滤下的所有机柜及其布局占用（已用 U 位、可用 U 位等）整合成 Excel 文件一键下载。

---

## 2. 代码接口调整

- **后端新增接口**：
  - `POST /api/racks/batch` (位于 [backend/api/racks.py](file:///e:/data/netsops/backend/api/racks.py))，支持传入 `List[RackCreate]` 并按序创建机柜，具备原子报错定位功能。

- **前端新增操作项**：
  - “下载导入模板” (`FileText` 按钮)
  - “导入机柜” (`Upload` 按钮)
  - “导出机柜” (`Download` 按钮)

---

## 3. 测试验证与结果

### 自动化单元测试
在 [backend/tests/test_racks_new_fields.py](file:///e:/data/netsops/backend/tests/test_racks_new_fields.py) 中新增了 `test_api_batch_create_racks_endpoint` 自动化测试用例，覆盖了：
1. 成功导入多个机柜并校验数据落库是否正确。
2. 异常捕获（如发生 rack_code 重复冲突时，能够抛出精准的第几行导入失败错误）。

运行测试结果如下：
```powershell
.\.venv\Scripts\pytest backend\tests\test_racks_new_fields.py
```
**输出**：
```
collected 4 items

backend\tests\test_racks_new_fields.py ....                              [100%]

============================== 4 passed in 3.18s ==============================
```

同时，我们执行了完整的后端单元测试套件，没有发现任何回归问题：
```powershell
.\.venv\Scripts\pytest
```
**输出**：
```
======================= 349 passed in 164.52s (0:02:44) =======================
```

### 前端 TypeScript 编译校验修复 (TypeScript compilation fix)
在推送后，GitHub Actions 的 `frontend-build-check` 执行 `tsc --noEmit` 时报错：
* `Property 'power_capacity_watts' does not exist on type 'Rack'`
* `Property 'remarks' does not exist on type 'Rack'`

**修复方案**：
在 [types.ts](file:///e:/data/netsops/src/pages/RackManagement/types.ts) 中，将这些新同步的数据库属性字段加入到了前端的 `Rack` 接口定义中。重新运行 `npx tsc --noEmit` 校验，无任何报错，构建成功通过。
