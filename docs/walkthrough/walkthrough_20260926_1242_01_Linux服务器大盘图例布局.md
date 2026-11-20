# 07 Linux 服务器监控图例布局调整走查

## 完成摘要

将 07 Linux 服务器监控六个时间序列面板的图例从右侧统计表调整为图表底部的简洁列表。曲线可获得更完整的横向空间，图例不再显示 Last、Max、Mean 三列；悬停仍可查看时间点数值。此配置仅应用于 Linux 大盘。

## 实际修改文件

- `monitoring/grafana/generate_dashboards.py`：为时间序列图例添加可选模式、位置和统计项参数，默认值保持原样。
- `monitoring/grafana/dashboards/nexora-linux-metrics.json`：更新面板 7、8、9、10、12、14 的图例配置。
- `docs/plans/plan_20260926_1242_01_Linux服务器大盘图例布局.md`
- 本走查记录。

开始时工作树已有 `handoff.md` 用户改动，本任务未修改该文件。生成器第一次运行后，定向校验发现 CPU 面板参数误落在设备大盘；已在最终生成前纠正。最终工作树不含设备大盘 JSON 的改动。

## 验证命令与结果

- `python monitoring/grafana/generate_dashboards.py`：成功生成 9 份仪表盘 JSON。
- `python -m py_compile monitoring/grafana/generate_dashboards.py`：通过。
- Python JSON 解析与配置断言：9 个 JSON 全部可解析；Linux 面板 7、8、9、10、12、14 均为 bottom/list，且 `calcs` 为空。
- `git diff --check`：通过。
- 检查完整生成差异：仅 Linux 大盘 JSON 有生成差异；其它 8 份仪表盘 JSON 保持不变。

## 未执行验证及原因

- 未将文件部署或写入 Grafana，也未在目标 Grafana 中进行视觉确认；本次授权范围是看板布局修改，没有执行线上发布。
- 未运行业务测试套件；仅对生成器和仪表盘 JSON 做了与改动匹配的结构验证。

## 剩余风险与回滚

- 底部列表会占用少量面板纵向空间；如实际 Grafana 布局拥挤，可只调整图例的位置或恢复汇总项。
- 回滚时恢复 `timeseries_panel` 参数默认配置及 Linux 的图例参数，再运行 `python monitoring/grafana/generate_dashboards.py`。
