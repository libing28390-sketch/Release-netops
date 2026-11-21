# Docker 前端依赖安装失败

## 完成摘要

定位并修复 Docker 前端构建依赖安装失败。原始日志中 `npm ci --include=dev` 安装了开发工具 Promptfoo，其依赖树包含原生模块 `better-sqlite3`。预编译包下载超时后，`node-gyp` 尝试本地编译；Node Alpine 阶段没有 Python，导致 `npm ci` 退出。Python 运行时阶段的 `python3-dev` 属于另一独立构建阶段，不能被前面的 Node 阶段使用。

复查今天的提交记录后，确认今天 Dockerfile 的变更只涉及 Python 阶段新增 `git`、容器健康检查地址和启动宽限时间，没有改动前端依赖安装命令，因此这些提交不是本次失败的直接原因。失败发生在 `COPY . .` 之前，今天的前端源码尚未进入镜像构建。

## 实际修改文件

- `Dockerfile`
- `docs/plans/plan_20260924_2031_01_Docker前端依赖安装失败.md`
- `docs/walkthrough/walkthrough_20260924_2031_01_Docker前端依赖安装失败.md`

## 关键实现说明

Node 阶段现在使用 `npm ci --omit=dev`，不再安装 Promptfoo 和其 `better-sqlite3`。Vite 及 `@vitejs/plugin-react`、`@tailwindcss/vite` 均保留在生产依赖树中；Tailwind 插件本身依赖 `tailwindcss`。构建命令直接调用 Vite CLI，并保留原有 4 GB Node 堆上限，避免依赖 dev-only 的 `cross-env`。

PostgreSQL 运行配置和 Python 运行镜像没有改变。

## 验证命令与结果

- 在临时目录执行 `npm ci --omit=dev`：通过，安装 546 个包。
- 检查临时生产依赖树：`vite`、`@vitejs/plugin-react`、`@tailwindcss/vite`、`tailwindcss` 均可解析；`better-sqlite3` 不存在。
- 执行 Vite CLI 生产构建并输出到临时目录：通过，4292 个模块转换，42.92 秒完成。
- 执行 `git diff --check`：通过。
- 复查 `git log`、`git show` 与 Dockerfile：确认今天的提交没有修改前端 `npm ci` 阶段。

## 未执行验证及原因

- 未运行 `docker compose build`：当前工作环境没有 Docker CLI，无法本地构建 `node:22.22.2-alpine` 镜像。依赖树检查与 Vite 构建通过，但仍需在 Docker 主机重新构建确认 Alpine 镜像结果。

## 剩余风险与后续建议

- 提供的 Docker 输出还包含 `/root/.docker/config.json` JSON 格式警告。它与 `npm ci` 的 `node-gyp` 错误相互独立；日志显示 Docker 继续执行了构建，但应在部署主机单独校验并修正该配置。
- 当前主机无法复现用户服务器上的预编译下载超时；本次变更通过排除该 SQLite 开发依赖，避免其触发本地编译。
- 回滚方式是恢复 Dockerfile 中原来的 `npm ci --include=dev` 和 `npm run build` 两行。
