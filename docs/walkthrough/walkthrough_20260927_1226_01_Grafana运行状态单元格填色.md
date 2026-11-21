# Grafana 运行状态单元格填色

## 完成摘要

04 接口流量与健康仪表盘的“接口运行状态”表格现在使用映射色作为单元格背景：`Up` 为绿色、`down` 为红色。状态映射和查询逻辑未变。

## 实际修改文件

- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-network-interface.json`
- `docs/plans/plan_20260927_1226_01_Grafana运行状态单元格填色.md`
- 本 walkthrough。

## 关键实现

表格生成 helper 新增 `mapped_cell_mode` 参数，默认仍为 `color-text`，因此其它使用映射色的表格行为不变；04 仪表盘运行状态面板单独设置为 `color-background`。生成器预期写出 9 份仪表盘 JSON，复核后只有接口仪表盘 JSON 产生差异。

## 验证命令与结果

- `python monitoring/grafana/generate_dashboards.py`：成功，生成器完成 9 个仪表盘文件。
- Python JSON 解析：成功解析 `monitoring/grafana/dashboards/` 下 9 个 JSON 文件。
- `git diff --check -- monitoring/grafana/generate_dashboards.py monitoring/grafana/dashboards/nexora-network-interface.json`：通过。
- 完整差异复核：只变更目标面板的单元格类型和生成器参数，状态值映射保持 `Up` 绿色、`down` 红色。

## 未执行验证与原因

- 未运行测试套件，用户请求的是面板配色调整，且项目指令要求不要在用户未要求时运行测试。
- 未打开或写入 live Grafana，因此没有验证当前运行实例的实际渲染或 provisioning reload。

## 剩余风险与后续建议

本次验证确认了 Grafana 12.1.0 仪表盘 JSON 结构和生成器输出；运行实例需要读取更新后的 provisioned dashboard 后才会显示背景填色。若实际渲染效果不符预期，可将该面板模式恢复为 `color-text`。
