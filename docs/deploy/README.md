# Nexora 部署指南 · 总览

本目录按**部署方式**拆分，方便你直接定位到自己的场景。所有实际的部署文件仍在仓库根目录（这样 `curl | bash`、`docker compose up`、双击兼容入口 `NetOps.exe` 等命令保持不变），这里只是导航和说明。

## 选哪种？

| 部署方式 | 适合场景 | 入口文件（仓库根目录） | 详细指南 |
|---------|---------|----------------------|---------|
| **Nexora Windows 一键图形化** | 纯 Windows 环境、个人/小团队、本地实验，不想碰命令行 | `NetOps.exe` / `start.bat`（兼容入口） | [windows.md](./windows.md) |
| **Docker Compose** | Linux 服务器、生产环境，已有 Docker 经验 | `docker-compose.yml` / `Dockerfile` | [docker.md](./docker.md) |
| **Ubuntu 一键脚本** | Ubuntu 裸机 / Codespaces，想要 systemd + Nginx 的原生部署 | `deploy-ubuntu.sh` | [ubuntu.md](./ubuntu.md) |

三种方式功能完全一致，区别只在运行环境和安装门槛。

## 一句话速览

- **Windows**：克隆 `windows` 分支或解压发布包 → 双击 `NetOps.exe` → Nexora 向导自动准备 PostgreSQL 17.6、匹配的 `pgvector`、`pg_trgm`、完整 Node.js 和 Python 运行时 → 浏览器开 `http://127.0.0.1:5010`。
- **Docker 在线**：克隆仓库 → 配好 `.env` → 根目录 `docker compose up -d --build` → 访问 `http://localhost`。
- **Docker 完全离线**：联网机器执行 `bash scripts/deploy-docker.sh save-images <archive-path>`，目标服务器执行 `load-images` 后再执行 `start-offline`；详见 [Docker Compose 部署](docker.md#完全离线部署)。
- **Docker 交付手册**：镜像归档、离线升级、数据卷和故障排查详见 [Docker 部署与离线交付手册](docker-release-manual.md)。
- **Ubuntu**：一条 `curl ... | bash` 或 `./deploy-ubuntu.sh`，自动装依赖 + systemd + Nginx。

> 完整的安全加固清单、HTTPS 配置、备份与日志轮转等内容见仓库根目录的 [README.md](../../README.md) 和 [DEPLOY.md](../../DEPLOY.md)。
