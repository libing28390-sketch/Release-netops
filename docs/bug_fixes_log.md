# Nexora 项目 Bug 修复与问题记录报告 (内存记录)

## 2026-04-28 ~ 2026-04-29 修复记录

### 1. 资产设备数量统计不准确
- **问题描述**: 资产管理页面中，设备数量未将“网络设备”和“服务器设备”汇总。
- **根本原因**: 前端 `App.tsx` 中的状态提取或后端资产汇总接口未正确包含这两类设备类型的合计逻辑。
- **修复方案**: 修正了数量统计逻辑，确保资产总数等于网络设备与服务器设备的准确总和。

### 2. 自动化模块 extractVars 引用报错
- **问题描述**: 自动化逻辑从 `App.tsx` 迁移到 `useAutomation.ts` 后，部分组件报错 `extractVars is not defined`。
- **根本原因**: 重构期间未正确导出或作用域暴露工具函数 `extractVars`。
- **修复方案**: 将 `extractVars` 工具函数单独提取并对外导出，恢复了 `PlatformSettingsTab.tsx` 等组件的正常调用。

### 3. Inspection Metrics 表结构迁移报错
- **问题描述**:  inspection_items 触发 `sqlite3.OperationalError`。
- **根本原因**: 数据库缺乏 `method` 和 `command` 字段，且 SQLite 对列的修改支持有限。
- **修复方案**: 执行了安全的 Schema 迁移，补全了相关字段，避免了数据丢失并提升了巡检模块的健壮性。

### 4. License 上传接口 `405 Method Not Allowed`
- **问题描述**: 前端在平台设置 -> 授权管理页面上传 License 时，接口返回 HTTP 405 错误，阻断了授权的激活。
- **根本原因**: 新增的 `license_router` 未被热重载进程正确捕获（FastAPI 的 `StaticFiles` 拦截了未识别的 POST 请求并返回 405）。
- **修复方案**: 
  - 手动杀死后台死锁的 Uvicorn 进程并重启 `npm run dev:backend`。
  - 确认了 `python-multipart` 依赖的存在并验证了路由绑定，修复后可正常实现本地离线验证上传。

### 5. License 安全与权限控制完善 (API 细粒度拦截)
- **问题描述**: 授权管理模块只在 UI 层隐藏了菜单，且审计日志仅保存在内存中（重启丢失）。
- **根本原因**: `upload_license` 路由缺乏 `Depends` 的服务器鉴权，`LicenseAuditLog` 的写操作未持久化。
- **修复方案**:
  - 在 `upload_license` 接口中加入了严格的 Bearer Token 解析和 `Administrator` 角色验证。
  - 在 `LicenseAuditLog.log` 方法中接入异步线程（避免阻塞），将关键的 License 上传、拒绝日志写入 `audit_events` 数据库表中持久化。

### 6. License 上传 "Administrator permissions required" 误报
- **问题描述**: 在使用管理员账号上传 License 时，后端抛出 `Administrator permissions required`。
- **根本原因**: 前端 `LicenseAdminTab.tsx` 中的 `fetch` 请求未携带 `Authorization: Bearer <token>` 请求头，导致后端解析身份为空。
- **修复方案**: 在前端上传请求的 headers 中主动附加了 `localStorage` 中提取的 `netops_token`。

### 7. License 授权设备统计未包含服务器并需独立授权
- **问题描述**: 之前设备配额仅统计了网络设备 (`devices` 表)，未统计服务器 (`physical_assets` 表)，且逻辑上混合计算容易导致业务混淆。
- **根本原因**: `models.py` 与 `generator.py` 中只有单一的 `device_limit` 字段，且 `_get_device_count` 只查询了网络设备。
- **修复方案**: 
  - 修改 `LicensePayload` 结构，新增独立的 `server_limit` 参数并支持在 License 生成工具中配置。
  - 修改后端统计逻辑，新增 `_get_server_count` 专门查询 `physical_assets` 中 `asset_type='server'` 的资产数量。
  - 更新前端 `LicenseAdminTab.tsx` UI，将设备授权环形图由 1 个独立拆分为 2 个（“网络设备”和“服务器”），并在卡片布局上升级为 5 列自适应布局，更加直观。

### 8. License Issuer 日期选择器重构 — 匹配主站 DateTimePicker 风格
- **问题描述**: Issuer 工具页面原来使用纯文本输入或浏览器原生日期控件，不支持精确时间选择，且与主站 DateTimePicker 风格不一致。
- **修复方案**:
  - 实现了白底浮层日历 + 右侧双列滚动时间选择器的复合组件，完全复刻了主站 `DateTimePicker.tsx` 的视觉风格和交互模式。
  - 保留了 `3天 / 7天 / 30天 / 1年` 快捷按钮与日历的联动。
  - 增加了"现在"按钮快速定位到当前时间、点击外部自动关闭、打开时自动滚动到选中时间位置。

### 9. License Issuer 签发工具增加登录验证门禁
- **问题描述**: Issuer 工具页面之前是无门槛开放的，任何人访问 `localhost:9900` 即可操作私钥签发 License，存在安全隐患。
- **修复方案**:
  - 后端新增 `/api/login` 接口和 `check_auth` 中间件，所有 API 端点（features / history / issue / verify / download）均要求 Bearer Token 认证。
  - 前端新增全屏登录遮罩层（login-overlay-gate），未登录时屏蔽所有操作，登录成功后 token 缓存在 `sessionStorage` 中支持会话持久化。
  - 文件下载链接通过 `?token=` 查询参数透传认证，兼容 `window.open` 场景。
  - 支持 Enter 键快速登录。

### 10. License Issuer 签发历史搜索与分页
- **问题描述**: 签发历史记录没有搜索和分页功能，当记录量增大后难以定位特定记录。
- **修复方案**:
  - 增加全局实时搜索框，支持按公司名称、备注、签发时间、到期时间模糊匹配。
  - 实现纯前端分页（每页 10 条），包含上一页/下一页控件和页码指示器。

---
> *此文档作为项目内存记录，将跟随每次 Bug 修复持续更新。*
