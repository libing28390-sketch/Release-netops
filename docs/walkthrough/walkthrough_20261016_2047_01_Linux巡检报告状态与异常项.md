# Linux 巡检报告状态与异常项

## 完成摘要

- Linux 报告状态由脚本实际检查结果决定，不再通过健康评分计算。
- 用户提供的结果现解析为：严重异常 1 项、告警 0 项、未采集 3 项；严重异常明细为 SSH 认证失败次数达到严重阈值。
- `[ERROR] 8. ...` 这样的编号行按检查章节处理，报告明细使用其下方的具体异常说明，避免把章节标题当成异常原因。
- HTML、PDF、Excel、JSON 报告字段已统一中文并移除评分；HTML 改为白底黑字。Excel 与 JSON 同时列出未采集项。
- 执行历史和作业详情中的状态标签改为“正常 / 异常 / 部分异常”等中文状态。

## 实际修改文件

- `backend/api/inspections.py`
- `backend/core/report_generator.py`
- `backend/templates/inspection_report.html.j2`
- `backend/templates/inspection_report_pdf.html.j2`
- `src/pages/ExecutionSchedule/components/ExecutionDetail.tsx`
- `src/pages/ExecutionSchedule/components/HistoryList.tsx`
- `src/pages/ExecutionSchedule/types.ts`
- `docs/plans/plan_20261016_2047_01_Linux巡检报告状态与异常项.md`

## 关键实现

- 新增 Linux 综合巡检输出解析，使用脚本汇总行、`[ERROR]` / `[WARNING]` 明细和 `*_status` 指标提取严重异常、告警及未采集项。
- 报告将脚本异常映射为“异常”，成功映射为“正常”，有未采集数据但无异常时映射为“部分采集”。
- 删除 HTML/PDF/Excel/JSON 输出中的单项评分、平均评分和评分字段；JSON 导出使用中文字段名。
- Excel 增加“未采集明细”页，列出 DNS、NTP 时间偏差和进程级文件句柄检查的采集情况。
- 非 Linux Playbook 的历史失败仍保留异常原因，不由报告评分重新判定。

## 验证命令与结果

- `npm run lint`：通过（`tsc --noEmit`）。
- `python -m py_compile core/report_generator.py api/inspections.py`：通过。
- 对用户提供的实际输出执行解析和导出检查：通过，结果为 1 项严重异常、0 项告警、3 项未采集；检查章节、具体异常文本、Excel/JSON 中文状态和无评分字段均匹配。
- `git diff --check`：通过；Git 提示当前工作区既有 LF/CRLF 转换警告，无空白错误。
- 未运行 pytest。HTML/PDF 模板未在本地 Python 环境渲染：当前解释器缺少 Jinja2、xhtml2pdf 和 ReportLab；模板已静态检查，Excel 和 JSON 导出已实际生成并核对。

## 未完成事项与风险

- 本次修改仅在本地工作区，未部署至 `192.168.96.1` 或其他服务实例。
- 历史数据表中的评分列保留以兼容旧记录；报告和执行历史界面不再展示或依赖评分。
- 部署环境仍需使用其后端依赖实际生成 HTML/PDF，确认字体与分页布局。

## 后续修正：加密阶段输出与耗时

### 根因与处理

- Playbook 阶段输出已加密保存在 `execution_device_results.phases_encrypted`，而报告导出路径只读取 `phases_json`。新记录的 `phases_json` 是 `{}` 占位符，因此报告未解析到 Linux 脚本的真实错误和未采集状态。
- 导出现在复用 Playbook 执行范围校验、受保护输出解密和输出读取审计；解密后的阶段输出只用于当前报告生成，不写回明文存储。
- 定时作业设备结果完成时现在写入单调时钟测得的 `duration_ms`。对历史默认值 0 的记录，报告会用设备开始/完成时间回算；无法回算时显示“—”，不再显示误导性的 0 毫秒。
- 对 `ntp_offset_ms_status: UNCHECKED` 的结果补上未采集说明，报告会分别呈现 NTP 同步状态和时间偏差数据状态。
- SSH 安全审计异常会把脚本附近的失败总数、关注/严重阈值和来源 IP 汇总到异常说明中，避免只显示“达到严重阈值”。

### 本轮验证

- `python -m py_compile backend/api/inspections.py backend/core/report_generator.py backend/services/scheduler_service.py`：通过。
- `git diff --check`：通过；Git 对工作区既有文件提示 LF/CRLF 转换警告，没有空白错误。
- 本轮未运行 pytest 或动态报告导出；本轮改动的加密解密、审计及耗时回算尚未在运行中的服务实例验证。
- 当前修改只在本地工作区，未部署到生成该 HTML 报告的服务实例；需部署后重新导出报告才能看到修正。

## TCP 未采集项归类修正

- 用户报告中“TCP 连接状态监控”行的说明实际来自脚本的 TCP 重传率采样分支；`tcp_retrans` 是 `tcp_retrans_pct` 的兼容别名，不代表重传包数量。
- 报告解析按 `[未采集]` 原因识别 TCP 连接状态和重传率，并将两个重传状态别名合并为“TCP 重传率”，避免一条采样原因产生三行。
- DNS 未配置探测域名、进程 FD 权限读取失败、NTP 偏差数值不可用仍保留为未采集，因为脚本确实无法基于当前配置/权限/工具得到这些指标；NTP 同步状态与偏差状态单独呈现。
- 本轮只做代码与空白静态检查，未执行脚本或模板动态测试，也未部署。

## 报告下载格式

- 用户截图中的下载菜单来自 `HistoryList`，之前改为只含 HTML、Excel；后续按用户要求将其改为两个行内图标，并从预览详情移除下载按钮。
- 未更改其他独立的 JSON 数据下载入口或后端格式接口。
- `npm run lint`：通过。
- 历史列表每条记录直接展示 Excel 和 HTML 图标按钮，点击即导出；预览详情头部不提供报告下载按钮。
- HTML 与 Excel 下载统一命名为“系统名_报告类型_作业名_开始时间_记录短ID.扩展名”，例如 `Nexora_自动化作业_linux_20261016_213200_7542764a.xlsx`；文件名中的 Windows 非法字符和空白会转换为下划线。
- 本轮修改后 `npm run lint` 和隔离 Vite 构建均通过；构建目录为 `.codex-build-validation-report-download-formats-20261016`，未覆盖 `dist/`。

## 导出模板错误修正

- HTML/PDF 渲染报 `builtin_function_or_method` 的原因是模板写 `device.items`，Jinja 优先解析为字典的 `items()` 方法。
- 两个模板均改为 `device['items']` 显式读取字段，并搜索确认报告模板中没有其他 `.items`、`.keys` 或 `.values` 属性访问冲突。
- 未运行模板渲染或测试；该模板修正尚待在具备项目依赖的后端环境中重新导出 HTML 和 PDF 验证。
