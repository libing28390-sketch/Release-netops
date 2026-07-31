# 修复 ZTE LLDP Brief 测试的 TextFSM 解析异常

## 问题现象
在后台运行测试 `pytest backend/tests/` 时，`test_topology_service.py` 报错 `FAILED backend/tests/test_topology_service.py::test_zte_lldp_table_is_supported_by_topology_parser`，断言 `assert 0 == 2` 失败。

## 根因分析
1. 拓扑采集与解析测试 `test_zte_lldp_table_is_supported_by_topology_parser` 传入的设备命令是 `show lldp neighbor brief`，其回显使用的是简报格式（`Local Interface Scope Chassis ID Port ID Holdtime System Name`）。
2. 在本地 `data/textfsm_templates/` 目录中，模板文件 `zte_zxros_show_lldp_neighbor_brief.textfsm` 错误地使用了非 brief 命令（即 `show lldp neighbor`）所对应的较长列格式进行解析（如含有 `Dest-MAC`、`Capability` 等），导致未能解析出任何行（`matched_rows == 0`）。

## 解决方案
重新编写了 `data/textfsm_templates/zte_zxros_show_lldp_neighbor_brief.textfsm` 模板，使其能够与 `show lldp neighbor brief` 的预处理回显行格式完美契合（支持 `Scope` 列的略过与被预处理逻辑自动合并后的一整行解析）。

## 实际修改文件
- `[MODIFY] data/textfsm_templates/zte_zxros_show_lldp_neighbor_brief.textfsm`

## 验证命令与结果
- 运行 `pytest backend/tests/test_topology_service.py`，全部测试用例均通过。

## 未验证项
- 无。

## 风险与回滚方式
- **风险**: 极低。仅修正了 ZTE 解析 lldp 简报输出的模板匹配模式，没有逻辑层面的大面积改动。
- **回滚方式**: 撤销模板的修改。
