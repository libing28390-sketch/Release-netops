# 公有仓库 README 更新走查

## 完成摘要

已根据当前前端导航、后端路由与服务、部署文档和 GitHub Actions 公有同步规则重写根目录 `README.md`。新版 README 以当前产品能力为准，补齐终端/PAM、告警、NSOT/NPA、深度 CMDB、工单、AI/知识引擎、服务器与出口监控等模块，并修正数据库、部署分支、安全默认值和 Roadmap 的过期表述。

## 实际修改文件

- `README.md`
- `docs/plans/plan_20260910_0014_01_公有仓库README更新.md`
- `docs/walkthrough/walkthrough_20260910_0014_01_公有仓库README更新.md`

## 关键实现说明

- 将旧版 7 类功能说明重组为覆盖当前导航与后端能力的 13 类模块矩阵。
- AI Copilot、Provider、模型路由、知识库、安全网关等从历史 Roadmap 移入当前能力，并明确外部 AI 默认关闭。
- 增加版本授权、RBAC、功能开关和高风险写操作边界，避免对所有部署承诺全部功能默认开放。
- 将数据库说明统一为 PostgreSQL 17，并说明 `vector`、`pg_trgm` 扩展要求；移除 SQLite 发布回退表述。
- 明确公开仓库 `main` 与 `windows` 分支用途，以及 Docker、Ubuntu、Windows 三种部署入口。
- 增加安全检查清单、常用环境变量、备份/更新命令和多厂商适配边界。
- 移除发布时会被清理的 `docs/images/*` 截图引用和 `docs/walkthrough/` 用户手册链接；所有保留的本地链接均指向公有发布树中的文件。
- Roadmap 仅保留尚未作为当前核心能力交付的方向，不再把 AI Copilot 标记为开发中。

## 验证命令与结果

执行文档级 PowerShell 校验：

```powershell
# 检查 Markdown 代码围栏成对、相对链接存在且位于 release.yml 保留路径；
# 检查 README 引用的环境变量均存在于 .env.example。
```

结果：

- 14 个本地链接全部存在。
- 14 个 Markdown 代码围栏成对。
- README 中列出的环境变量均能在 `.env.example` 中找到。
- README 未再引用发布时删除的 `docs/images` 或 `docs/walkthrough`。
- `git diff --check` 通过，无空白错误；仅提示 Windows 工作区的 LF/CRLF 自动转换预警。
- 功能表已交叉核对 `src/components/AppSidebar/navConfig.ts`、`src/components/AppMainContent.tsx`、`backend/main.py` 和相关 API/service 文件。

## 未执行验证及原因

- 未运行 `npm run lint`、前端构建或 pytest：本次只修改 Markdown 文档，不改变前后端代码、API 合约、路由、部署脚本或构建产物，按风险门禁无需执行无关业务回归。
- 未触发 `release.yml`、未推送公有仓库：用户请求仅授权本地更新 README，发布和推送需要另行明确授权。

## 剩余风险 / 后续建议

- 公开仓库只有在私有仓库 `main` 的变更被提交并推送、且 `release.yml` 成功后才会显示新版 README。
- 功能可用性仍受版本授权、角色权限、环境配置、设备厂商/型号和功能开关影响；README 已加入相应边界说明。
- Docker 部署子文档中仍有 `http://localhost` 的旧访问示例，本次按用户要求未扩展修改；后续可单独统一全部公开部署文档的 HTTPS 表述。
