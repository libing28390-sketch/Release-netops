# MIB 全量 ZIP 自动上传与 Docker 容器适配修复记录

## 1. 问题现象
1. 用户在前端页面（`SNMP MIB 知识库管理` 弹窗）中上传包含数千个 MIB 文件的多厂商/无后缀 ZIP 压缩包时报错 `400`、连接重置 `ECONNRESET`，此前只能手动解压到目录并手动执行 CLI 脚本同步。
2. 在 Docker/Nginx 环境下上传时提示 `HTTP 413 Request Entity Too Large`（响应大小 585 字节）。
3. Docker 容器中后端执行全量异步解析时报错 `ModuleNotFoundError: No module named 'scripts.sync_librenms_mibs'`。

## 2. 根因分析
1. **上传与同步链路缺失**：原接口未集成大文件自动解压落盘，且未对接 FastAPI 后台任务进行异步符号树构建，导致长耗时请求引发 HTTP 超时与代理断开。
2. **Nginx 请求体硬编码上限**：`nginx/nginx.conf` 与 `deploy-ubuntu.sh` 中配置了 `client_max_body_size 20m;`，而多厂商/LibreNMS 全量 ZIP 压缩包通常在 30MB~80MB，在进入后端前即被 Nginx 拦截抛出 413。
3. **Docker 容器内模块导入路径冲突**：容器根目录存在 `/app/scripts/`（存放终端 Agent 辅助脚本），与 `/app/backend/scripts/sync_librenms_mibs.py` 同名冲突，导致 Python `import scripts.sync_librenms_mibs` 解析至空包目录。

## 3. 解决方案
1. **服务与 API 层增强**：
   - 增加 `extract_mib_archive_to_repo`，内置 ZipSlip 路径穿越安全防护，自动去除外层包装目录并将 MIB 文件规范解压至 `backend/data/librenms_repo/mibs/`。
   - 放宽对 Linux 无后缀 MIB 文件（如 `IF-MIB`、`SNMPv2-MIB`）及 `.mib`, `.my`, `.txt`, `.asn`, `.smi` 的识别支持。
   - 接口注入 `BackgroundTasks`，针对大包（文件数 > 10）解压后异步调度全量解析入库并立即返回 `async: true`。
2. **前端交互与状态联动**：
   - 在 MIB 管理弹窗增加“上传 MIB / ZIP”按钮与隐藏文件选择器，处理 `async: true` 响应并自动联动 3 秒轮询。
   - 监听后台同步完成后自动刷新 MIB 列表与统计卡片，并弹出汇总 Toast。
3. **网关与容器配置放宽**：
   - 将 `nginx/nginx.conf` 与 `deploy-ubuntu.sh` 的 `client_max_body_size` 调整为 `150m;`，对齐后端 `SNMP_MIB_UPLOAD_MAX_BYTES=150MB`。
4. **容器脚本包结构与动态加载**：
   - 新增 `backend/scripts/__init__.py`。
   - 在 `backend/api/devices.py` 中引入 `_get_sync_librenms_module()` 动态加载器，兼容容器与各类开发环境。

## 4. 实际修改文件
- `backend/core/config.py`
- `backend/services/snmp_mib_service.py`
- `backend/api/devices.py`
- `backend/scripts/__init__.py`
- `src/components/SnmpMib/MibUploadModal.tsx`
- `src/components/SnmpMib/MibUploadModal.test.tsx`
- `backend/tests/snmp/test_snmp_mib_repository.py`
- `nginx/nginx.conf`
- `deploy-ubuntu.sh`
- `.gitignore`
- `docs/plans/plan_20260815_1508_01_MIB全量ZIP自动上传与后台同步.md`
- `docs/walkthrough/walkthrough_20260815_1508_01_MIB全量ZIP自动上传与后台同步.md`
- `docs/fixes/fix_20260815_2125_01_MIB全量ZIP自动上传与Docker容器适配.md`

## 5. 验证命令与结果
- **前端类型校验**：`npm run lint` (`tsc --noEmit`) 0 错误。
- **前端组件测试**：`npx vitest run src/components/SnmpMib/MibUploadModal.test.tsx` (4 passed)。
- **后端全量 MIB 测试**：`.venv\Scripts\pytest.exe backend/tests/snmp/test_snmp_mib_repository.py -v` (10 passed in 37.03s)。

## 6. 未验证项
- 外部只读受限环境中的实际物理硬件 SNMP 轮询（已通过 Mock/Fixture 充分覆盖测试）。

## 7. 风险与回滚方式
- **风险**：极低，仅增强 MIB 知识库上传与 Nginx 请求体上限，不影响现有网络设备采集与 CMDB/PAM 业务。
- **回滚**：`git revert <commit-hash>`。
