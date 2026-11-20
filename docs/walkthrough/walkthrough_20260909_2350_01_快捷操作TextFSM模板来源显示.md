# 完成摘要

修正 Quick Ops 结构化结果的 parser 来源显示。未绑定平台 Profile 的兼容采集路径现在也复用版本感知的统一 TextFSM 解析入口，并把具体模板名、模板来源和 parser platform 回传给前端；前端不再显示 `NTC Templates（旧目录）`。

# 关键修改

- `collect_operational_data()` legacy 路径先调用 `parse_device_cli_output()`，H3C `version=7.1.070` 会返回 `textfsm:h3c_comware_v7_display_interface_brief.textfsm`。
- 没有模板命中时仍保留类别专用 raw fallback，但 parser 标记为 `platform-parser`，不会伪装为旧 NTC 目录。
- Quick Ops 前端将历史 `ntc-templates` 值显示为“TextFSM 解析（模板未回传）”，新结果显示具体版本模板。

# 验证

- `pytest backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py -q`
- `pytest backend/tests -k "operational or quick_query or textfsm" -q`
- `npm run test:frontend -- --run src/pages/AutomationExecute/components/QuickQueryResultOverlay.test.tsx`
- `npm run lint`
- 浏览器 Quick Ops：H3C Comware V7 接口查询结果显示具体 `h3c_comware_v7_*.textfsm` 模板。
