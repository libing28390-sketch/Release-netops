# RackVision 资产可用性 CI 一致性走查

## 完成摘要

已修复 GitHub Actions 干净检出环境中三个 RackVision 资产解析测试失败的问题。资产解析器现在按前端真实可访问的发布位置检查已批准 GLB，兼容源码态的 `public/` 与生产构建态的 `dist/`，不再依赖被 Git 忽略的 `assets/build/` 本机构建残留。

## 根因

- 注册表中的 `glb_path` 指向 `assets/build/glb/*.glb`。
- `.gitignore` 的 `build/` 规则排除了该目录，因此 Actions 干净检出中不存在这些文件。
- 对应成品已由 Git 跟踪在 `public/assets/3d/*.glb`，且 API 返回的 `asset_url` 也来自 `public_path`。
- 原 `_available()` 只检查 `glb_path`，导致匹配结果正确但 `available` 被误报为 `False`。

## 实际修改文件

- `backend/services/rack_asset_resolver.py`
- `backend/tests/rackvision/test_asset_resolver.py`
- `docs/plans/plan_20260909_2346_01_RackVision资产可用性CI一致性.md`
- `docs/walkthrough/walkthrough_20260909_2346_01_RackVision资产可用性CI一致性.md`

## 关键实现说明

- `_available()` 仍要求资产状态为 `approved`。
- 使用 `public_path` 映射并检查仓库的 `public/` 或构建输出的 `dist/`，与浏览器实际请求 URL 保持一致。
- 每个候选路径都必须位于对应发布根目录内部，路径逃逸会被拒绝。
- 新增隔离回归测试，不读取本机 `assets/build/`，直接复现 Actions 的干净检出条件。
- 新增路径逃逸测试，验证安全边界未因路径映射放宽。

## 验证命令与结果

- `.\.venv\Scripts\python.exe -m pytest -q backend/tests/rackvision/test_asset_resolver.py`
  - 结果：`8 passed in 27.43s`
- `.\.venv\Scripts\python.exe -m pytest -q backend/tests/rackvision`
  - 结果：`47 passed in 82.82s`
- `.\.venv\Scripts\python.exe backend/scripts/validate_rackvision_catalog.py`
  - 结果：`valid: true`，120 个网络设备映射、91 个注册表条目和 120 个型号映射通过校验。
- `.\.venv\Scripts\python.exe scripts/validate_postgresql_only.py`
  - 结果：`0 violation(s)`，PostgreSQL-only 策略通过。
- `git diff --check`
  - 结果：通过；仅有当前 Windows 工作树的 LF/CRLF 提示，无空白错误。

## 未执行验证及原因

- 未重复运行完整 `backend/tests`：本次改动只涉及 RackVision 只读文件可用性判断，已覆盖具体失败文件和完整 RackVision 目录；用户提供的失败运行中其余 1889 项已通过。
- 未运行前端 lint/build：没有修改前端代码、静态资源内容或 API 字段契约。

## 剩余风险 / 后续建议

- 运行环境必须包含 `public/`（开发/源码运行）或 `dist/`（生产构建）中的发布资产；两者都缺失时会正确降级为不可用。
- 当前目录校验脚本只验证已批准条目具有 `glb_path`，尚未校验 `public_path` 成品是否存在；本次回归测试已覆盖故障行为，可在未来强化目录生成门禁时一并扩展。
- 回滚仅需恢复 `_available()` 的旧路径判断并移除两项新增测试；不涉及数据库或外部系统。
