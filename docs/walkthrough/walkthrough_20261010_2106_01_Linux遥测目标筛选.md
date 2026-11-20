# Linux 遥测目标筛选走查

## 完成摘要

周期遥测只选择 platform 明确匹配 Linux allowlist 的在线设备。设备分类中的通用 `server` 不再作为目标兜底，因此 Windows 和未知平台不会进入 `insp_linux_full` SSH 脚本。

## 实际修改

- `backend/services/telemetry_service.py`：按 Linux 平台 allowlist 筛选目标，并说明脚本只支持 Bash/Linux。
- `docs/plans/plan_20261010_2106_01_Linux遥测目标筛选.md`
- `docs/walkthrough/walkthrough_20261010_2106_01_Linux遥测目标筛选.md`
- `docs/fixes/fix_20261010_2106_01_遥测任务误连Windows.md`

## 验证

- `python -m py_compile backend/services/telemetry_service.py`：通过。
- `git diff --check`：通过。
- 静态检查目标条件：只依据 `linux`、`ubuntu`、`centos`、`debian`、`redhat` 平台值；Windows/未知值跳过。

## 未执行与剩余风险

- 按当前工作区规则未新增或运行测试。
- 未连接真实设备；部署后可观察下一轮 `device_telemetry_sampler`，确认 `web-srv-02` 不再出现 SSH 尝试。
- Linux 平台别名必须在 allowlist 中；新平台别名需确认脚本兼容后再加入。
- 本次只修筛选逻辑，不部署。
