# Walkthrough：资产标签接入与网络技术平台内置标签

## 变更目标

本次变更解决资产新增/编辑和资产导入模板无法绑定统一标签的问题，并为网络设备提供厂商与平台差异的内置标签。

## 用户可见结果

1. 资产新增/编辑窗口新增“标签”区域，可搜索、选择和移除标签。
2. 选择网络设备厂商或平台时，系统自动推荐对应的技术平台标签；环境、区域、项目等标签仍可手工选择。
3. “标签管理”分类新增“技术平台”，内置 Cisco、Huawei、H3C、Arista、Juniper、Ruijie、Fortinet、Palo Alto、ZTE、Maipu 等厂商标签，以及 IOS、NX-OS、IOS-XE、VRP、Comware、EOS、JunOS 等平台标签。
4. 资产导入模板的服务器和网络设备工作表新增“标签代码”列，多个代码使用英文逗号分隔。

## 绑定与校验逻辑

```text
资产表单 / 导入模板
        ↓
tag_ids（表单）或 tag_codes（导入）
        ↓
后端按稳定 code 解析并校验
        ↓
统一 tag_assignments（设备资源）
        ↓
资产列表、标签筛选、自动化目标解析共同读取
```

- 系统自动标签（例如在线/离线）不会被表单覆盖。
- 厂商标签组 `technology.vendor` 和平台标签组 `technology.platform` 各自互斥。
- `vendor`、`platform` 结构化字段仍然是事实来源，标签是筛选和自动化使用的规范化入口。

## 验证记录

- `backend/tests/test_tag_system.py`：4 passed。
- `npm run lint`：通过。
- `backend/api/assets.py`、`backend/schemas/schemas.py`、`backend/services/tag_service.py`：Python 编译通过。
- `public/templates/asset_import_template.xlsx`：服务器模板、网络设备模板和参数参考工作表均已验证包含“标签代码”。

## 测试夹具修复

补充 `backend/tests/conftest.py` 的 `isolated_db` 夹具，用于出口探测测试：

- 测试前初始化数据库并清理测试节点事件。
- 测试后删除新增的探测结果、运行记录、样本和出口事件。
- 恢复 `platform-server` 的 `last_seen_at`、`updated_at`，避免污染开发数据。

完整后端测试结果：`137 passed, 25 subtests passed`。

## 本轮问题修复

- 资产表单标签选择器按 `exclusive_group` 实时互斥；同一互斥组内再次选择会自动替换旧标签，后端仍会再次校验。
- 选择器增加“一键清除”“应用选择”和“保存资产”操作，清除或选择后的结果会写回资产表单。
- 导入的“标签代码”单元格支持多个标签，兼容英文逗号、中文逗号和分号；模板示例已覆盖服务器多标签和网络设备厂商/平台多标签。
- 新增厂商互斥和平台互斥的后端回归测试。
