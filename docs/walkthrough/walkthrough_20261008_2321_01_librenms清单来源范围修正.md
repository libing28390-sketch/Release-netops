# LibreNMS 清单来源范围修正执行记录

## 完成摘要

- 将 MIB 条目的 `vendor_scope` 更名为 `platform_vendor_scope`，明确它只表示 Nexora 的离线索引分组；新增清单 schema 版本及字段契约，说明设备硬件规则仍由 LibreNMS OS detection/discovery YAML 选择。
- 在 `mib_scope_mappings` 中登记上游 `mibs/hp` → Nexora Aruba（98 个文件，`procurve` / HP ProCurve）和上游 `mibs/fs` → Nexora Ruijie（79 个文件，`fs-ruijie` / Fiberstore）映射。其余 Nokia、Nortel、Radlan 等既有共享目录映射仍在清单说明中列出。
- 固定 LibreNMS MIB 包只导入清单列出的文件；本地多余文件被忽略。清单列出的文件若缺失，则在连接数据库前拒绝导入，避免不完整导入影响已有索引。
- 未删除或改写 MIB 文件；此前已有的工作区更改继续保留。

## 实际修改文件

- `backend/vendor/librenms/source-manifest.json`
- `backend/vendor/librenms/README.md`
- `backend/services/librenms_mib_service.py`
- `backend/tests/snmp/test_librenms_mib_cache.py`
- `backend/tests/snmp/test_librenms_bundle_manifest.py`
- 本计划与本 walkthrough。

## 关键实现

- 清单保留每条记录的精确 `upstream_path` 和本地 `bundle_path`，并把 Nexora 分组放入 `platform_vendor_scope`。后端 MIB 导入器按本地目录进行索引，不使用该字段挑选硬件采集规则。
- 仅固定 `backend/vendor/librenms/mibs` 路径执行 manifest 白名单；传入的外部/手动 MIB 目录仍按原有递归扫描流程处理。
- 如果固定包缺少 manifest 声明的任意文件，导入器直接返回错误，不打开数据库连接。

## 验证命令与结果

- `.\.venv\Scripts\python.exe -m pytest --confcutdir=backend/tests/snmp backend/tests/snmp/test_librenms_mib_cache.py -k 'manifest_whitelist or incomplete_pinned_bundle' -q`：2 passed。
- `.\.venv\Scripts\python.exe -m pytest --confcutdir=backend/tests/snmp backend/tests/snmp/test_librenms_bundle_manifest.py -q`：2 passed。
- `py -3.11 -m py_compile backend/services/librenms_mib_service.py backend/tests/snmp/test_librenms_mib_cache.py backend/tests/snmp/test_librenms_bundle_manifest.py`：通过。
- 对 manifest 中全部 2,357 条 MIB 记录逐项核对路径、大小和 SHA-256：缺失 0，大小或哈希不符 0；记录覆盖 2,357 个本地 bundle 路径和 2,356 个不同上游路径。目录中另有 12 个未列入清单的本地文件，按设计不导入。
- `git diff --check`：通过；Git 仅提示工作区已有 LF/CRLF 转换提示，没有空白错误。
- 用户提供的启动日志显示本次进程实际处理 2,357 个清单 MIB 文件、0 个失败。该启动任务是 MIB 符号索引/本地目录导入，不是对设备执行 SNMP 采样。

## 未执行验证及剩余风险

- 未运行依赖真实隔离 PostgreSQL 的完整 MIB 缓存测试集；本次聚焦回归覆盖清单白名单、缺文件拒绝导入和映射契约。
- 12 个未列入清单的本地文件保留在工作区，导入器会忽略它们；本次没有删除用户已有文件。
- 未推送、部署或修改 Ubuntu 主机。

## 回滚

若后续发现导入兼容性问题，可回滚本次 manifest schema/映射字段、README、导入器白名单分支及对应测试；无需回滚或删除 MIB 内容。
