# 资产导入与 SNMP 探测解耦记录

## 完成摘要

资产管理表格导入现在按有效行分别提交。单行校验或落库失败只回滚该行；启用 `atomic=true` 时仍整批回滚。资产提交后，SNMP 主机名同步、SNMP 设备识别和 LibreNMS 纳管在 HTTP 响应后继续执行，网络超时不再阻塞导入列表刷新。

## 实际修改

- `backend/api/assets.py`
  - 接入 FastAPI `BackgroundTasks`。
  - 详细且非原子导入每行成功后提交；失败行通过 savepoint 隔离。
  - 网络补全任务在响应后运行，并在响应中标出 `enrichment_pending`。
- `src/pages/AssetManagement/index.tsx`
  - 请求 `detailed=true`，即时展示失败行和失败数量。
  - 有后台补全时提示稍后刷新查看已同步的设备名称。
- `backend/tests/rackvision/test_asset_import_contract.py`
  - 验证前一行已提交时，后续行仍可独立失败。
  - 验证资产已保存且 SNMP 补全任务排队后立即返回。

## 验证

- `.venv/Scripts/python.exe -m pytest backend/tests/rackvision/test_asset_import_contract.py -k "asset_import_detailed_row_failure_and_atomic_rollback or asset_import_queues_snmp_enrichment_after_committing_asset" -q -x`：2 passed，1 deselected，67.40s。
- `.venv/Scripts/python.exe -m py_compile backend/api/assets.py backend/tests/rackvision/test_asset_import_contract.py`：通过。
- `git diff --check`：通过；Git 对工作区换行符给出 CRLF 规范化提示，没有空白错误。
- `npm run lint`：通过。
- 未执行实际浏览器导入或真实设备 SNMP 探测，避免向用户当前资产库写入测试设备；没有运行全量后端测试。

## 剩余风险

- FastAPI 后台任务保存在应用进程内，进程在任务完成前重启可能中断补全；已提交资产不会回滚。
- 后台任务完成状态不持久化到 API。页面会提示稍后手动刷新以显示 SNMP 更新后的主机名。
- 本次没有数据库迁移，也未部署或推送代码。
