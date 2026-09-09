# RackVision 资产可用性 CI 一致性计划

## 任务目标

修复 GitHub Actions 干净检出环境中 RackVision 已批准 GLB 资产被误判为不可用的问题，使解析结果与实际发布到 `public/assets/3d/` 的前端静态资源一致。

## 现状 / 问题

- `asset_registry.json` 同时记录 Blender 构建产物路径 `glb_path` 与前端公开路径 `public_path`。
- `rack_asset_resolver._available()` 当前只检查 `assets/build/glb/` 下的构建产物。
- `assets/build/` 被 `.gitignore` 排除，本机存在残留构建文件，但 GitHub Actions 的干净检出没有这些文件。
- 已批准成品实际已由 Git 跟踪在 `public/assets/3d/`，因此 CI 中三个可用性断言失败。

## 影响范围

- RackVision 后端资产解析服务的只读可用性判断。
- RackVision 资产解析单元测试。
- 不改变资产匹配顺序、API 响应字段或前端 URL 契约。

## 拟修改文件

- `backend/services/rack_asset_resolver.py`
- `backend/tests/rackvision/test_asset_resolver.py`
- `docs/walkthrough/walkthrough_20260909_2346_01_RackVision资产可用性CI一致性.md`

## 实施步骤

1. 将已批准资产的可用性校验对齐到 `public_path` 对应的仓库公开目录，同时保留严格的仓库根目录边界检查。
2. 增加隔离回归测试，证明只有公开成品存在、构建中间文件不存在时仍可正确判定可用。
3. 增加非法公开路径的边界测试，防止路径逃逸被当作有效资产。
4. 运行 RackVision 资产解析定向测试及相关目录级测试。

## 验证计划

- `pytest -q backend/tests/rackvision/test_asset_resolver.py`
- `pytest -q backend/tests/rackvision`
- 检查 `git diff --check` 与最终差异。

## 风险与回滚思路

- 风险：旧注册项若仅有构建中间文件但没有公开成品，将不应被报告为前端可用；这是与运行时 URL 契约一致的预期收紧。
- 回滚：恢复 `_available()` 原有的 `glb_path` 检查并移除新增回归测试即可；不涉及数据库、外部设备或持久化数据变更。

## Agent 分工

- 主 Agent：方案、代码与测试修改、集成验证、计划及 walkthrough。
- Explorer：只读核对失败共同根因与最小修复建议，不修改共享文件。
