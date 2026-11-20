# MIB 全量 ZIP 自动上传与后台同步验证与走查报告

## 1. 任务完成摘要

针对用户反馈在 Web 前端页面（`SNMP MIB 知识库管理` 弹窗）中上传包含数千个 MIB 文件的 ZIP 压缩包时报错 `400`、连接重置 `ECONNRESET` 以及需手动解压目录并手动执行脚本的问题，本次变更完成了全链路自动化改造：

1. **前端直接上传与进度联动**：
   - 弹窗右上角增加了“上传 MIB / ZIP”操作入口，支持选择 `.zip`、`.mib`、`.my`、`.txt`、`.asn`、`.smi` 等格式。
   - 前端接收到后台异步响应（`async: true`）后，展示启动提示并无缝联动现有进度条与 3 秒轮询。
   - 监听后台同步完成（`running` 从 `true` 转为 `false`）后自动刷新 MIB 知识库列表及统计卡片，并弹出成功汇总 Toast。
2. **后端安全自动解压与目录规范化**：
   - 服务层增加了 `extract_mib_archive_to_repo`：内置 ZipSlip 路径穿越安全防护，自动去除外层非必要包装目录（如 `mibs/` 或 `librenms-master/mibs/`），将 MIB 文件及厂商子目录规范解压至 `backend/data/librenms_repo/mibs/`。
   - 自动嗅探有效 MIB 文件（含 Linux 常用无后缀标准 MIB 文件如 `IF-MIB`、`SNMPv2-MIB` 等），过滤 macOS 系统元数据和二进制冗余文件。
3. **异步调度与长任务保护**：
   - 上传接口针对大包（文件数 > 10 或多层厂商目录）自动解压后，通过 FastAPI `BackgroundTasks` 在后台启动全量符号索引树构建与入库。
   - HTTP 请求在 1 秒内立即返回 `{"success": True, "async": True, ...}`，彻底消除浏览器与 Vite 代理超时导致的 `ECONNRESET`。
4. **配置项调优**：
   - `SNMP_MIB_UPLOAD_MAX_BYTES` 调大至 150MB（默认 157286400 字节）。
   - `SNMP_MIB_UPLOAD_MAX_FILES` 调大至 20000 个文件。
   - `SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES` 调大至 500MB。
   - 可通过 `.env` 或环境变量动态自定义覆盖。

---

## 2. 修改文件清单

| 文件路径 | 修改类型 | 说明 |
| :--- | :--- | :--- |
| `backend/core/config.py` | 修改 | 调大 MIB 上传体积限制（150MB）、文件数限制（20000）和解压后体积限制（500MB） |
| `backend/services/snmp_mib_service.py` | 修改 | 增加 `.smi` 后缀支持；实现 `extract_mib_archive_to_repo` 与 `is_valid_mib_zip_member`；增强 `parse_and_store_zip` 无后缀 MIB 识别与厂商推断 |
| `backend/api/devices.py` | 修改 | `upload_snmp_mib_file` 升级为支持大文件包后台异步任务调度、解压到 repo 目录与状态同步 |
| `src/components/SnmpMib/MibUploadModal.tsx` | 修改 | 增加上传按钮、文件选择器；支持 `async: true` 异步响应处理；完成后台同步自动刷新 MIB 列表 |
| `backend/tests/snmp/test_snmp_mib_repository.py` | 修改 | 增加大型 ZIP 压缩包上传自动转后台异步索引及解压测试用例 |

---

## 3. 核心功能与代码实现

### 3.1 安全解压与目录规范化 (`backend/services/snmp_mib_service.py`)

```python
def extract_mib_archive_to_repo(
    zip_bytes: bytes,
    target_mibs_dir: Path | str,
    max_files: int = 50000,
    max_uncompressed_bytes: int = 500 * 1024 * 1024,
) -> tuple[int, set[str]]:
    target_mibs_path = Path(target_mibs_dir).resolve()
    target_mibs_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        ...
        for f, norm_name, _ in clean_members:
            # 剥离外层包装目录并校验 ZipSlip 路径穿越安全
            dest_file = (target_mibs_path / rel_path).resolve()
            if not str(dest_file).startswith(str(target_mibs_path)):
                continue
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            dest_file.write_bytes(z.read(f))
            extracted_count += 1
```

### 3.2 异步全量解析调度 (`backend/api/devices.py`)

```python
if is_directory_or_large:
    from scripts.sync_librenms_mibs import MIBS_DIR, import_mibs_from_directory

    extracted_count, detected_vendors = extract_mib_archive_to_repo(
        content,
        target_mibs_dir=MIBS_DIR,
        max_files=settings.SNMP_MIB_UPLOAD_MAX_FILES,
        max_uncompressed_bytes=settings.SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES,
    )
    
    def _archive_sync_worker():
        global _librenms_sync_state
        ...
        result = import_mibs_from_directory(mibs_dir=MIBS_DIR)
        _librenms_sync_state["last_result"] = result
        ...

    background_tasks.add_task(_archive_sync_worker)
    return {
        "success": True,
        "async": True,
        "message": f"Successfully unpacked {extracted_count} MIB files. Full background indexing has started.",
        "extracted": extracted_count,
        "vendors": sorted(list(detected_vendors)),
        "state": _librenms_sync_state,
    }
```

---

## 4. 验证命令与结果

### 4.1 前端类型检查
- **命令**：`npm run lint`
- **结果**：`tsc --noEmit` 耗时 3.5s，0 错误，通过。

### 4.2 前端组件单元测试
- **命令**：`npx vitest run src/components/SnmpMib/MibUploadModal.test.tsx`
- **结果**：`4 passed (4)`，全部通过。

### 4.3 后端 MIB 仓库与上传解析全量 pytest 测试
- **命令**：`.venv\Scripts\pytest.exe backend/tests/snmp/test_snmp_mib_repository.py -v`
- **结果**：`10 passed in 41.87s`，覆盖单文件上传、小 ZIP 同步导入、大 ZIP 自动解压后台异步索引、多厂商搜索、重置与内置 MIB 种子等全部测试。

---

## 5. 限制与配置说明（回答用户关于大小和数量限制）

| 参数名称 | 环境变量键 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| 单压缩包上传大小 | `SNMP_MIB_UPLOAD_MAX_BYTES` | 150MB (157,286,400 字节) | 足够容纳全量 LibreNMS/各大厂商 MIB 归档（通常 30~80MB） |
| 压缩包内文件最大数 | `SNMP_MIB_UPLOAD_MAX_FILES` | 20,000 个 | LibreNMS 全量约 4800~5000 个文件，默认上限充足 |
| 解压后解压总容量 | `SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES` | 500MB (524,288,000 字节) | 防止 ZipBomb 炸弹保护服务器磁盘与内存 |

若需要进一步放宽限制，可在生产部署环境的 `.env` 中指定：
```env
SNMP_MIB_UPLOAD_MAX_BYTES=314572800
SNMP_MIB_UPLOAD_MAX_FILES=50000
SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES=1073741824
```
