# Nexora 全量整改与模块文档 Walkthrough

## 任务结果

已按任务 PDF 和 8 份专项文档完成全部任务，不以 P0/P1 为交付边界。所有工作直接在 `main` 分支完成，未创建 Git 提交；运行和持久化环境使用 PostgreSQL。

## 功能整改

### Smart NPA

- 删除固定 IP 和伪造诊断结果；
- 使用真实采集步骤生成证据；
- 明确 `UNKNOWN`、`CONFLICT`、证据缺口和置信度封顶；
- 增加正向/回程路径、逐跳入/出接口、ACL 方向与来源时间；
- 前端不再预填演示地址，展示回程路径和证据不足提示。

### 标签管理

- API 返回逐标签分配数和总数/已使用/未使用/已标记设备统计；
- 页面改为左侧分类、紧凑表格、搜索和组合筛选；
- 使用状态和启用状态可独立筛选。

### IPAM

- 利用率排除点到点、主机路由和容器前缀；
- Prefix 状态、分类、生命周期、来源和容量口径可读；
- IP 地址支持层级 Prefix 选择，`/32` 独立呈现；
- 对账显示设备名称、证据、置信度和风险；
- 无趋势样本时显示真实空状态。

### 网络总览与网络监控

- 空值、未采集和采集失败不再显示正常；
- 未配置、无邻居和未知使用中性状态；
- 风扇、电源等硬件数据的 `0`、`null` 和空值不被误判。

### PAM 与凭据轮换

- 会话审计补齐筛选、详情、录像/回放、终止、完成时间、风险和 CSV 导出；
- 轮换页面去除重复统计，支持状态/目标筛选、单台和批量轮换；
- 修复双账号资产被旧通用凭据覆盖；
- 修复普通账号轮换覆盖管理员凭据；
- 保留旧单账号设备的只读采集兼容性。

### Change Center

- 多厂商命令静态扫描；
- 不可逆命令阻断和高风险命令升级；
- 审批快照哈希与审批后变更检测；
- PostgreSQL 运行环境实施前强制 MFA；
- 一次性执行令牌元数据和敏感审计字段过滤。

### NCM

- 配置快照新增 9 个 PostgreSQL 元数据字段；
- 备份执行原始/规范化哈希和完整性判断；
- 内容读取时校验原始哈希；
- 恢复计划校验设备归属、快照完整性、变更工单、MFA、预备份和回滚计时；
- 完整配置不允许直接执行恢复。

## 文档交付

- [`PROJECT_ANALYSIS.md`](../PROJECT_ANALYSIS.md)
- [`TASK_REMEDIATION.md`](../TASK_REMEDIATION.md)
- [`EXECUTION_LOG.md`](../EXECUTION_LOG.md)
- [`TEST_REPORT.md`](../TEST_REPORT.md)
- [`MODULES_OVERVIEW.md`](../MODULES_OVERVIEW.md)
- [`BROWSER_VALIDATION.md`](../BROWSER_VALIDATION.md)
- [`modules/README.md`](../modules/README.md)

模块文档统计：

| 类型 | 数量 |
| --- | ---: |
| 一级模块 README | 11 |
| 子功能介绍 | 62 |
| 子功能使用指南 | 62 |
| 合计 | 136 |

## 真实浏览器验收

在本地实际运行环境完成登录并逐页打开 62 个真实路由。每页确认业务主标题、登录态、错误状态、加载完成和页面宽度后保存截图。

| 指标 | 结果 |
| --- | ---: |
| 页面 | 62/62 |
| 截图 | 62 |
| 应用错误 | 0 |
| 登录页误截 | 0 |
| 未完成加载 | 0 |
| 横向溢出 | 0 |

拓扑和 3 个 IPAM 页面首次异步加载较慢，已等待数据面板完成后重新验收和截图。逐页面映射见 [`MODULES_OVERVIEW.md`](../MODULES_OVERVIEW.md)。

## PostgreSQL

实际连接结果：

```text
engine=PostgreSQL
database=netops
version=PostgreSQL 18.4 on x86_64-windows
config_snapshots_metadata_columns=9/9
missing=none
```

没有采用 NCM 文档中的 MySQL 方案。SQLite 仅存在于仓库原有的隔离单元测试兼容层，不是运行数据库。

## 最终质量门禁

| 检查 | 结果 |
| --- | --- |
| 后端全量测试 | 640 passed，25 个子测试通过，1 条第三方弃用警告 |
| Python 编译 | 通过 |
| TypeScript | 通过 |
| Vite 生产构建 | 通过 |
| 浏览器页面 | 62/62 通过 |
| PostgreSQL | 通过 |
| `git diff --check` | 通过，仅行尾提示 |
| Docker Compose | 未执行，本机无 Docker CLI |

## 安全边界

- 登录密码未写入源码、文档或报告；
- 未执行真实设备配置下发、批量改密、会话强制终止或配置恢复；
- 用户开始前已有的 Dockerfile、部署脚本和部署文档改动均保留；
- 未创建提交、未暂存文件、未切换离开 `main`。
