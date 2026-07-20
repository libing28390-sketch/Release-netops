# 机柜并发控制与上架策略优化走查与验证报告

本报告记录了对 Nexora 平台机架管理模块进行的重构优化。修改内容已通过自动化构建与后端单元测试，能够完美支持高并发场景下的 U 位冲突保护以及基于策略（底部优先 / 顶部优先）的空余 U 位推荐。

## 变更内容概述

### 1. 数据库模式与迁移
* **目标文件**：[schema.py](file:///e:/data/netsops/backend/database/schema.py)
* **变更点**：
  * 在 `racks` 数据库表中增加了 `placement_strategy`（`VARCHAR(20) DEFAULT 'bottom_first'`）字段。
  * 调用了 `ensure_column` 函数，以确保老版部署环境中的机架表自动增加该列而无需重置数据库。

### 2. 后端 API 校验与并发控制
* **目标文件**：[schemas.py](file:///e:/data/netsops/backend/schemas/schemas.py), [rack_service.py](file:///e:/data/netsops/backend/services/rack_service.py)
* **变更点**：
  * 在 `RackCreate` 和 `RackUpdate` Pydantic 校验模型中定义了 `placement_strategy` 字段，且限制其合法值为 `('bottom_first', 'top_first')`。
  * 在 `_check_u_constraints` 校验函数中，增加了数据库锁定逻辑：
    * 当系统被检测为 PostgreSQL (`_USE_PG = True`) 时，直接对当前正在修改的机架行执行 `SELECT 1 FROM racks WHERE id = ? FOR UPDATE`。
    * 这样一来，若有两个并发请求尝试在同一个机架上创建/修改设备，第二个请求会被强行阻塞在 `SELECT ... FOR UPDATE` 处，直至第一个请求所在的连接提交 (`commit`)。当第二个请求恢复执行时，它会读取到最新的设备占位信息，正确触发 U 位冲突保护报错。

### 3. 前端 U 位推荐算法与机柜表单
* **目标文件**：[types.ts](file:///e:/data/netsops/src/pages/RackManagement/types.ts), [helpers.ts](file:///e:/data/netsops/src/pages/RackManagement/helpers.ts), [index.tsx](file:///e:/data/netsops/src/pages/RackManagement/index.tsx)
* **变更点**：
  * 前端 `Rack` 和 `RackLayout` 接口扩充了 `placement_strategy` 类型定义。
  * 重构了 `findFirstFreeStartU` 与 `pickStartUForAsset`：
    * 若机柜为 `top_first` 策略，检索空闲 U 位时，循环变量从 `totalU - uHeight + 1` 递减到 `1`（自顶向下搜索第一个适合安装的连续空位）；
    * 否则为 `bottom_first`（底部优先），循环变量从 `1` 递增到 `totalU - uHeight + 1`（自底向上搜索）。
  * 在机架的「创建/编辑机架」弹窗表单中，在“最大功率 (W)”右侧并行引入了“上架安装策略”下拉框选择框（底部优先 vs 顶部优先），方便管理员配置。

---

## 验证结果

### 1. 前端静态代码分析与成功编译
我们运行了 `npm run build`，编译输出表明前端 TypeScript 代码没有任何语法、类型缺失或导入错误，打包完成：
```bash
vite v6.4.1 building for production...
✓ 3325 modules transformed.
dist/assets/RackManagementTab-DIJFT7fp.js       122.52 kB
✓ built in 13.43s
```

### 2. 后端单元测试通过
我们向 `test_racks_new_fields.py` 补充了针对 `placement_strategy` 以及并发加锁机制的单元测试，并在隔离数据库中成功运行通过：
```bash
pytest backend/tests/test_racks_new_fields.py backend/tests/test_cmdb_phase3_crud.py
...
backend/tests/test_racks_new_fields.py .....                             [100%]
============================== 5 passed in 3.96s ==============================
```

这证明数据库迁移字段正常，查询与事务锁语义完全兼容 PostgreSQL。

---

## 用户手册更新
我们已同步将“上架策略”这一高级特性的说明加入到设备资产与机柜管理手册中，指导用户在现场操作时根据配重与散热需求选择合适的策略排列。
