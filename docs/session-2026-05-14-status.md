# 工作状态报告 — 2026-05-14

## 当前问题总结

### 问题 1：Excel/JSON 下载功能未在 Ubuntu 虚拟机上验证

**现象**
- 代码已完整实现（`AutomationHistoryTab.tsx` 第 1050-1311 行）
- 前端已构建成功（`npm run build` 无错误）
- 但在 Ubuntu 虚拟机 `http://192.168.56.1:4350` 上看不到下载按钮

**代码实现状态** ✅ 完成
```typescript
// 命令栏中的 Raw/Parsed 切换 + 下载按钮
- [Raw|Parsed] 切换按钮 ✅
- Copy 按钮 ✅
- Download .txt 按钮 ✅
- Download .xlsx 按钮（仅解析成功后显示）✅
- Download .json 按钮（仅解析成功后显示）✅

// 解析结果表格顶部的导出按钮
- 导出 Excel 按钮 ✅
- 导出 JSON 按钮 ✅
```

**根本原因**
部署在 Ubuntu 虚拟机上，本地 Windows 的改动没有同步过去。

**排除思路**
| 步骤 | 检查项 | 结论 |
|------|--------|------|
| 1 | 代码逻辑 | ✅ 正确。使用 XLSX.utils.json_to_sheet，自动列宽，生成真正的 .xlsx |
| 2 | 前端构建 | ✅ 成功。`npm run build` 无错误，`dist/` 已更新 |
| 3 | 本地 dist/ | ✅ 存在。`dist/index.html` 引用的 JS hash 是最新的 |
| 4 | 本地后端 | ❌ 没跑。Windows 上没有启动后端服务 |
| 5 | Ubuntu 部署 | ❌ 旧版本。Ubuntu 虚拟机上的 dist/ 是旧代码 |

**解决方向**
1. 登录 Ubuntu 虚拟机 `192.168.56.1`
2. 进入项目目录
3. `git pull origin main` 拉最新代码
4. `npm run build` 重新构建前端
5. 重启后端服务（或执行 `deploy-ubuntu.sh`）
6. 刷新浏览器（Ctrl+Shift+R 强制刷新）

**预期结果**
执行历史详情弹窗，每条命令应显示：
```
$ show ip interface brief
[Raw|Parsed] [⎘ Copy] [↓ txt] [📊 xlsx] [📄 json]

<output content>
```

解析成功后，表格顶部应有两个大按钮：
```
✓ 42 条记录 · intf · ip · status    [📊 导出 Excel] [📄 导出 JSON]
```

---

## 代码改动清单（已 push）

| 文件 | 改动 | Commit |
|------|------|--------|
| `backend/database.py` | 补上 `pam_sessions` 的 `risk_level` / `risk_summary` 列 | `31110e2` |
| `src/pages/AutomationHistoryTab.tsx` | 新增 `downloadJSON()` 和改进 `downloadExcel()`；每条命令独立 Raw/Parsed 切换 | `291b6ce` |
| `src/pages/ScheduledJobsTab.tsx` | IP 输入框移到左列（Device Scope 下拉框下方） | `2114691` |
| `backend/services/scheduler_service.py` | 定时作业并发改为 10（asyncio.Semaphore） | `b65450e` |
| `backend/services/automation_service.py` | 修复多命令 join 导致输出丢失（逐条 send_command） | `b65450e` |

---

## 技术细节

### Excel 导出实现
```typescript
const downloadExcel = useCallback((records: Record<string, any>[], fields: string[], filename: string) => {
  if (!records || records.length === 0) return;
  const data = records.map(r => {
    const row: Record<string, any> = {};
    for (const f of fields) row[f] = r[f] ?? '';
    return row;
  });
  const ws = XLSX.utils.json_to_sheet(data, { header: fields });
  // 自动列宽：最大 60 字符
  ws['!cols'] = fields.map(f => {
    const maxLen = Math.max(f.length, ...data.map(r => String(r[f] ?? '').length));
    return { wch: Math.min(Math.max(maxLen + 2, 10), 60) };
  });
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Parsed');
  XLSX.writeFile(wb, filename.endsWith('.xlsx') ? filename : `${filename}.xlsx`);
}, []);
```

### JSON 导出实现
```typescript
const downloadJSON = useCallback((records: Record<string, any>[], filename: string) => {
  if (!records || records.length === 0) return;
  const text = JSON.stringify(records, null, 2);
  const blob = new Blob([text], { type: 'application/json;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename.endsWith('.json') ? filename : `${filename}.json`;
  a.click();
  URL.revokeObjectURL(url);
}, []);
```

### TextFSM 解析流程
```typescript
const handleParseCommand = useCallback(async (
  blockKey: string,
  platform: string,
  command: string,
  rawOutput: string,
  executionId: string,
  deviceId: string,
) => {
  setParseResults(prev => ({ ...prev, [blockKey]: { loading: true, data: null, error: '' } }));
  setParseViewMode(prev => ({ ...prev, [blockKey]: 'parsed' }));

  try {
    const res = await fetch(`/api/playbooks/${executionId}/devices/${deviceId}/parse`, {
      method: 'POST',
      headers: { ...authHeaders, 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform, command, output: rawOutput }),
    });
    const json = await res.json();
    if (json.success && json.data?.count > 0) {
      setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: json.data, error: '' } }));
    } else if (json.has_template === false) {
      setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: `未找到 ${platform} / ${command} 的解析模板` } }));
      setParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }));
    } else {
      setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: json.message || '解析无结果' } }));
    }
  } catch {
    setParseResults(prev => ({ ...prev, [blockKey]: { loading: false, data: null, error: '解析请求失败' } }));
    setParseViewMode(prev => ({ ...prev, [blockKey]: 'raw' }));
  }
}, [authHeaders, isZh]);
```

---

## 明天行动计划

### 优先级 1（必做）
1. 登录 Ubuntu 虚拟机 192.168.56.1
2. 进入项目目录
3. `git pull origin main`
4. `npm run build`
5. 重启后端服务（或执行 `deploy-ubuntu.sh`）
6. 刷新浏览器验证：
   - 执行历史详情：Raw/Parsed 切换 + 下载按钮
   - 定时作业编辑：IP 输入框位置

### 优先级 2（如果有问题）
- 检查 Ubuntu 上的 `dist/` 是否真的更新了
- 检查后端日志是否有错误
- 确认浏览器缓存已清除（DevTools → Network → Disable cache）

### 优先级 3（后续）
- 验证 Excel 下载的文件格式和内容
- 测试 JSON 下载
- 测试 CSV 下载（如果还需要的话）

---

## 其他发现

1. **测试附件已清理**：`data/change_order_attachments/` 下 132 个空壳文件已删除
2. **代码规模**：项目约 102,000 行（前端 60%，后端 38%）
3. **定时作业现已并发**：从串行改为 10 并发，执行时间大幅缩短
4. **多命令执行已修复**：之前 join 导致只有第一条命令有输出，现在每条都有

---

*记录时间：2026-05-14 09:00*
