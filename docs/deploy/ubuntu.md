# Ubuntu 一键脚本部署

适合 Ubuntu 20.04 / 22.04 / 24.04（x86_64 / arm64）裸机或 GitHub Codespaces。脚本自动装依赖、配置 systemd 服务和 Nginx。

## 入口文件（仓库根目录）

| 文件 | 作用 |
|------|------|
| `deploy-ubuntu.sh` | Ubuntu / Codespaces 一键部署脚本 |
| `deploy-ubuntu.gitee.sh` | Gitee 镜像版（国内网络） |

> 脚本是**自包含**的：它会自己克隆仓库再部署，所以可以在任意目录运行。文件保持在根目录，是为了让下面那条公开的 `curl` 一键安装链接保持有效。

## 方式一：远程一键安装（推荐）

```bash
# 推荐：先下载再执行，便于排查
curl -fsSL -o /tmp/deploy.sh https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh
chmod +x /tmp/deploy.sh
bash /tmp/deploy.sh
```

或直接管道执行：

```bash
curl -fsSL https://raw.githubusercontent.com/libing28390-sketch/Release-netops/main/deploy-ubuntu.sh | bash
```

## 方式二：克隆后本地运行

```bash
git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation
cd nexora-automation
chmod +x deploy-ubuntu.sh
./deploy-ubuntu.sh
```

## 脚本做了什么

- 安装 Node.js 22、Python 3.10+ 及系统依赖
- 全新部署时自动生成 `.env`（含随机 `SECRET_KEY` / `CREDENTIAL_ENCRYPTION_KEY` / 数据库密码）
- 配置 systemd 服务（后端绑定 `127.0.0.1`，外部流量经 Nginx）
- 容器环境（无 systemd）自动降级用 `service` + `nohup` 启动

## 部署后建议

- 安装每日备份：`sudo bash scripts/install-daily-backup.sh`
- 安装日志轮转（容器 / 裸机模式）：`sudo cp scripts/netops.logrotate /etc/logrotate.d/netops`
- 启用 HTTPS：`sudo certbot --nginx -d <你的域名>`

> 完整安全加固清单见根目录 [README.md](../../README.md) 与 [DEPLOY.md](../../DEPLOY.md)。
