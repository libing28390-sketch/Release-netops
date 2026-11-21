# YunShan Docker 模板迁移启动故障

## 目标

修复 Docker 部署中数据库迁移 0275 找不到 Huawei YunShan TextFSM 模板、导致 FastAPI 启动失败的问题，并给部署路径添加回归覆盖。

## 现状与问题

`Dockerfile` 将发布模板复制到 `/app/release-textfsm-templates`，而 `/app/data` 是持久卷。迁移 `m0275_huawei_yunshan_platform` 当前只从源码目录 `/app/data/textfsm_templates` 读取文件，因此容器启动时会报缺少 `huawei_yunshan_display_version.textfsm`，迁移未完成，数据库初始化随后使应用退出。迁移执行器在当前版本失败时回滚该迁移事务。

## 影响范围

- Huawei YunShan 系统平台、模板、发布动作及识别规则的首次数据库注册。
- Docker 发布镜像与开发源码运行时的模板查找路径。
- 不改既有数据库结构或持久化卷内容。

## 拟修改文件

- `backend/database/migrations/m0275_huawei_yunshan_platform.py`
- `backend/tests/database/test_m0275_huawei_yunshan_platform.py`
- 本计划和对应 walkthrough。

## 实施步骤

1. 为迁移增加模板根目录解析：优先选择包含全部必需模板的镜像只读发布目录，再兼容开发源码目录；在迁移写库前验证所有必需文件。
2. 添加回归用例，模拟 Docker 中源码数据目录为空、只读发布目录存在模板的情形，并保留现有 PostgreSQL 注册/幂等测试。
3. 执行迁移测试、关联的 YunShan TextFSM 检查及 PostgreSQL-only 代码扫描；若 Docker 可用，再验证构建上下文或镜像模板路径。
4. 记录结果及远程 Linux 主机升级步骤。此任务不包含直接登录或部署远程主机。

## 验证计划

- `pytest backend/tests/database/test_m0275_huawei_yunshan_platform.py`
- `pytest backend/tests/vendor_audit/test_huawei_yunshan_textfsm.py`
- `python scripts/validate_postgresql_only.py`
- 检查 Dockerfile 发布路径与迁移 resolver 的契约；Docker 构建可用时构建镜像并确认模板位置。

## 风险与回滚

迁移失败会回滚当前 PostgreSQL 事务，不应遗留 0275 的部分注册数据。修复只调整迁移读取模板的来源；若新镜像启动仍有问题，可回滚应用镜像至上一版本。无需删除或重建数据库卷。
