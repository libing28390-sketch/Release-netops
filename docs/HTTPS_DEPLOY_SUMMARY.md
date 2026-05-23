# NetOps Automation — HTTPS/SSL 部署与运维总结

本文档总结了 2026 年 5 月 23 日针对 NetOps Automation 平台 Docker 部署实现 HTTPS 支持的完整改动、原理及后续运维指南。

---

## 1. 任务背景
在 Docker 部署环境下，原本的 Nginx 仅监听 80 端口（HTTP），缺乏 HTTPS 安全加密支持。本次任务旨在实现：
- 默认启用 HTTPS，并且所有 HTTP（80 端口）请求自动重定向至 HTTPS（443 端口）。
- 支持开箱即用的自签名证书（有效期 10 年），确保服务可直接拉起。
- 支持用户方便地替换为自定义受信任 CA 证书（如 Let's Encrypt 等）。
- 保证平台核心功能（如 Web SSH 控制台 WebSocket 连接）在 HTTPS（`wss://`）下正常工作。

---

## 2. 核心代码变更说明

### 2.1. Nginx 配置文件更新
*   **修改文件**：`nginx/nginx.conf`
*   **改动详情**：
    *   新增 80 端口监听服务器块，使用 `return 301 https://$host$request_uri;` 强制将所有 HTTP 请求永久重定向至 HTTPS。
    *   新增 443 端口监听服务器块，启用 `ssl` 指令，并配置证书路径为 `/etc/nginx/ssl/netops.crt` 和 `/etc/nginx/ssl/netops.key`。
    *   优化了 SSL 协议版本（仅限 `TLSv1.2` 和 `TLSv1.3`）与加密套件（Ciphers），关闭不安全的旧协议。
    *   配置了 HSTS 响应头 `Strict-Transport-Security`，提升网站安全性。
    *   为 `/api/`、`/api/ws/` 和 `/api/pam/ws/` 代理设置了 `X-Forwarded-Proto $scheme` 头，确保后端 FastAPI 准确识别 HTTPS 协议栈。

### 2.2. Docker Compose 卷挂载
*   **修改文件**：`docker-compose.yml`
*   **改动详情**：
    *   取消了 `nginx` 服务下关于 SSL 证书目录挂载的注释，配置为：`- ./nginx/ssl:/etc/nginx/ssl:ro`。
    *   使得宿主机 `./nginx/ssl/` 下的证书和私钥文件能够安全映射到容器内的 `/etc/nginx/ssl/` 目录中。

### 2.3. 自签名证书生成脚本（开发端）
*   **新建文件**：`scripts/generate_ssl_cert.py`
*   **改动详情**：
    *   基于项目现有的 `cryptography` Python 库，编写了一个跨平台的自签名证书生成脚本。
    *   自动生成一个包含 `localhost` 和 `netops.local` 域名、有效期为 **10 年**（3650 天）的 `netops.crt` 和 `netops.key` 并存入 `nginx/ssl/`。

### 2.4. 前端 WebSocket 兼容
*   **修改文件**：`src/components/access/TerminalWindow.tsx`
*   **改动详情**：
    *   修复了在没有指定 `VITE_API_BASE` 时，WebSocket 基准地址（`WS_BASE`）的构建逻辑。
    *   更新为根据 `window.location` 动态生成。在 HTTPS 环境下，自动使用 `wss://` 加密协议，并继承宿主机 Host。避免了浏览器因相对地址无协议头而抛出语法错误，保证受控终端控制台能够正常连接。

### 2.5. 部署文档更新
*   **修改文件**：`DEPLOY.md`
*   **改动详情**：
    *   更新了中英文的 **启用 HTTPS**（HTTPS / SSL）章节，说明了默认启用自签名证书的设计、如何使用脚本生成证书，以及如何替换成自定义正式证书。

---

## 3. 开发库与发布库的同步机制说明

在开发机上完成修改后，可能会在虚拟机上遇到 "为什么 `git fetch` 没有拉取到包含新提交信息（如日期或特定 Commit Message）的最新提交" 的疑问。

**原理解析**：
- **开发库**（`netsops`）保存完整的 Git 提交历史（我们刚刚修改的文件在开发库中最新提交为 `a2a763b0`）。
- **发布库**（`Release-netops`）是虚拟机（商用部署环境）所指向的仓库。
- **构建同步工作流**：当开发库主分支有代码推送时，会运行 `.github/workflows/release.yml` 自动化任务。该任务会：
    1. 编译不同 Python 版本的核心安全二进制 `.so` 文件。
    2. 清理所有开发及敏感调试文件（包括 `scripts/` 目录）。
    3. **抹除所有 Git 历史并重新初始化**：通过运行 `rm -rf .git && git init`，将全部最新代码打包为**仅包含单个 Commit** 的纯净版本，强制推送至发布库。
    4. 提交信息被固定设为 `"🚀 Release build: Production ready stable release"`。

**结论**：即使发布库的 Commit 消息和以前一样，只要对应的最新 Commit ID 在 GitHub 上已更新完成，并且虚拟机拉取到了该 ID（如本次更新后的 `38caa2b`），就代表代码和证书已经是最新的了。

---

## 4. 后续运维与证书管理指南

自签名证书生成后，后期可能会面临证书过期或需替换为公网受信任证书的情况。

### 4.1. 使用您自己的正式 CA 证书（推荐生产环境）
1.  准备好您的 SSL 证书文件和私钥文件（例如从 Let's Encrypt 或阿里/腾讯云申请的证书）。
2.  分别将证书和私钥文件重命名为 **`netops.crt`** 和 **`netops.key`**。
3.  将这两个文件上传至服务器项目目录下的 **`nginx/ssl/`** 目录中，覆盖原有的自签名文件。
4.  在虚拟机根目录下重启容器生效：
    ```bash
    docker compose down
    docker compose up -d
    ```

### 4.2. 自签名证书过期或重新生成（生产环境快速恢复）
由于发布包中清理了 `scripts/` 目录，在虚拟机（Linux）上，无需使用 Python，可**直接调用系统自带的 `openssl` 命令**一行生成新的 10 年有效期自签名证书：

```bash
# 1. 进入项目根目录并确保目录存在
cd ~/netops-automation
mkdir -p nginx/ssl

# 2. 一键生成 10 年（3650 天）有效期的自签名证书
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout nginx/ssl/netops.key \
  -out nginx/ssl/netops.crt \
  -subj "/C=CN/ST=Beijing/L=Beijing/O=NetOps Automation/CN=netops.local"

# 3. 重启 Nginx 容器使证书生效
docker compose restart nginx
```
