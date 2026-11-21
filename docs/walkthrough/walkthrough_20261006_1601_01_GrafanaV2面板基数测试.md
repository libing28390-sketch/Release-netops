# Grafana V2 面板基数测试修正记录

## 完成摘要

检查 Actions 附件后，确认全量测试的 2 个失败都来自 dashboard cardinality 测试冻结的旧数字。当前目录已从 253 面板、90 统计卡扩展为 257 面板、92 统计卡；新增项来自 AC 无线统计、终端明细表及分组行。其他 2,872 项通过、1 项跳过。

## 实际修改

- `backend/tests/monitoring/test_grafana_v2_presentation.py`：同步更新面板总数 257、分组行 54、非分组面板 203、统计卡 92，并统一另一个统计卡总数断言。
- `docs/plans/plan_20261006_1601_01_GrafanaV2面板基数测试.md`
- `docs/fixes/fix_20261006_1603_01_GrafanaV2面板基数测试.md`

没有修改运行时代码、Dashboard 配置或 CI workflow。

## 验证命令与结果

- `.venv\Scripts\python.exe -c "from monitoring.grafana.generate_dashboards import build_dashboard_catalog, iter_panels; p=[x for _,d in build_dashboard_catalog() for x in iter_panels(d.get('panels',[]))]; rows=sum(x.get('type')=='row' for x in p); stats=sum(x.get('type')=='stat' for x in p); print(f'panels={len(p)} rows={rows} non_rows={len(p)-rows} stats={stats}')"`：输出 `panels=257 rows=54 non_rows=203 stats=92`。
- `.venv\Scripts\python.exe -m pytest backend/tests/monitoring/test_grafana_v2_presentation.py backend/tests/monitoring/test_grafana_queries.py -q`：54 passed。
- `git diff --check`：通过。

## 未执行验证及剩余风险

- 未在本机重复运行耗时约 5 分 40 秒的全量 pytest；Actions 附件显示其余 2,872 项已通过，针对两个失败模块的复测现为 54 passed。推送提交后 GitHub Actions 会重新执行全量门禁。
- 这是仅更新测试期望基数的改动，不改变运行时行为；以后增加或移除 Dashboard 面板时，需同步维护 V2 基数测试。
