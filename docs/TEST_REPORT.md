# Nexora 全量整改测试报告

> 日期：2026-07-28
>
> 分支：`main`
>
> 提交：未创建（按用户要求）
>
> 生产数据库：PostgreSQL

## 1. 最终结论

本次整改的后端全量测试、前端类型检查、前端生产构建、Python 编译、PostgreSQL 运行核验和 62 页面真实浏览器验收均通过。Docker CLI 未安装，因此未执行 `docker compose config`；本轮也没有修改或回退用户开始前已有的 Docker 部署改动。

## 2. PostgreSQL 核验

| 检查 | 结果 |
| --- | --- |
| 运行引擎 | PostgreSQL 18.4 on x86_64-windows |
| 当前数据库 | `netops` |
| NCM `config_snapshots` 新增元数据字段 | 9/9 存在 |
| 新增字段 | `raw_hash`、`normalized_hash`、`line_count`、`section_count`、`integrity_status`、`lifecycle_status`、`normalizer_version`、`collected_at`、`task_id` |
| MySQL 方案 | 未采用 |

验证使用实际应用环境变量建立连接，只输出引擎、数据库名和字段结果，没有输出连接串或密码。

## 3. 后端测试

### 3.1 全量测试

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

最终结果：

```text
640 passed, 1 warning, 25 subtests passed in 335.51s
```

唯一警告来自 FastAPI `TestClient` 依赖中的 Starlette/httpx 第三方弃用提示，不是本次代码错误。

### 3.2 回归修复过程

首次全量执行结果为 617 通过、23 失败。失败被分为两类并全部处理：

1. Change Center 新增 PostgreSQL MFA 门禁与仓库旧 SQLite 隔离测试契约冲突：保留生产 PostgreSQL 强制 MFA，只为 SQLite 隔离测试后端提供兼容路径；相关 4 个测试文件 39/39 通过。
2. 旧测试仍断言已被当前产品规则替代的行为：空凭据占位、旧导入返回结构、自由文本机房、CDP 回退、5 分钟拓扑周期和旧 H3C BGP 命令；测试契约按当前安全、站点规范化、LLDP-only、24 小时周期和明确地址族命令更新。

同时修复了真实兼容问题：

- 双账号资产不会再被旧通用凭据覆盖；
- 普通账号轮换不会覆盖管理员凭据；
- 旧单账号设备仍可被只读拓扑采集；
- 离线设备先返回离线状态，不会被缺失平台字段遮蔽。

### 3.3 Python 编译

命令：

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend
```

结果：通过。

## 4. 前端验证

| 命令 | 结果 |
| --- | --- |
| `npm run lint` | 通过，TypeScript `tsc --noEmit` 无错误 |
| `npm run build` | 通过，Vite 6.4.1 转换 3368 个模块 |

生产构建存在 Vite 的大 chunk 优化建议，属于性能提示，不阻断构建。本轮新增与整改页面均成功进入产物。

## 5. 浏览器验收

| 指标 | 结果 |
| --- | ---: |
| 一级模块 | 11 |
| 二级页面 | 62 |
| 成功页面 | 62 |
| 真实截图 | 62 |
| 应用错误页 | 0 |
| 登录页误截 | 0 |
| 未完成加载 | 0 |
| 页面级横向溢出 | 0 |

完整过程见 [`BROWSER_VALIDATION.md`](./BROWSER_VALIDATION.md)，逐页面文档与截图映射见 [`MODULES_OVERVIEW.md`](./MODULES_OVERVIEW.md)。

## 6. 文档完整性

| 文档项 | 数量 | 结果 |
| --- | ---: | --- |
| 一级模块 README | 11 | 完成 |
| 二级功能介绍 | 62 | 完成 |
| 二级使用指南 | 62 | 完成 |
| 模块文档总数 | 136 | 完成 |
| 二级页面截图 | 62 | 完成 |

## 7. 差异与部署检查

| 检查 | 结果 |
| --- | --- |
| `git diff --check` | 通过；仅 Git 行尾转换提示 |
| Docker Compose 配置 | 未执行：当前系统未安装 `docker` CLI |
| Git 分支 | `main` |
| Git 提交 | 未创建 |
| 用户既有 Docker 改动 | 保留，未回退 |

## 8. 未执行的高风险测试

没有对真实网络设备执行配置下发、密码轮换、会话强制终止、恢复配置或工单实施。此类动作需要独立维护窗口、目标设备清单、回退确认和动态 MFA，不能仅凭页面验收授权推断为可执行。
