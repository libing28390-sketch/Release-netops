# 别再手写脚本了！如何用 Docker 5 分钟搭建一套高颜值的网络运维自动化平台 Nexora？

作为网络工程师，你是否每天还在重复以下枯燥且高压的工作：
- 🔌 **逐台登录交换机**，手动执行 `display current-configuration` 或 `show running-config` 备份配置，复制粘贴到本地文件夹？
- 🚨 **遇到突发网络故障**，满头大汗地打开多个 SSH 终端敲命令，挨个排查 CPU、内存、端口流量和路由状态？
- 💻 **写了一堆零散的 Python/Netmiko 脚本**，却因为缺少统一的 Web 可视化界面和权限管控，团队其他同事无法协同使用，只能你一个人帮忙跑脚本？

今天为大家安利一款专为现代网络工程师打造的**高颜值、零门槛、极简部署**的网络运维自动化平台 —— **Nexora NetOps**。平台集成了多厂商设备接入、自动化运维引擎、配置版本对比（Diff）、SNMP 实时遥测和一键诊断等核心功能，更拥有基于 **React 19 + TypeScript** 打造的现代化丝滑网页终端。

---

## 🌟 核心亮点一览

1. **🚀 极简容器化部署**
   全栈容器化架构，**宿主机无需安装任何 Node.js、npm、Python 或数据库依赖**。前端在 Docker 构建时自动在容器内编译完成，配合内置的自动化部署脚本，真正实现一键开箱即用。
2. **🌐 深度多厂商驱动适配**
   内置智能化多厂商适配引擎，深度支持**华为（Huawei VRP）、华三（H3C Comware）、思科（Cisco IOS）**等主流平台，自动隔离不同厂商的 CLI 语法与解析差异。
3. **📜 配置版本控制与智能比对（Diff）**
   自动执行定时或手动配置备份，记录历史版本基线，直观高亮展示任意两次配置之间增删改差异，快速锁定变更根因，“甩锅排障”必备利器。
4. **🔒 生产级安全防护**
   敏感凭据（登录密码、Enable 密码、SNMP Community）在 PostgreSQL 18 数据库中全量加密存储（AES/ChaCha20 级加解密），支持自签名或自定义 HTTPS 双向安全闭环。

---

## 🏗️ 系统架构与服务构成

一套标准 Docker Compose 环境由三个核心容器精简编排而成，资源占用低，稳定性极强：

| 容器服务 | 镜像与来源 | 内部/对外端口 | 挂载卷（Volume）与作用 |
| :--- | :--- | :--- | :--- |
| **`db`** | 本地 `docker/postgres/Dockerfile` 构建的 `nexora-postgres:latest`（pgvector + pg_trgm） | 内部 `5432` | `nexora-pgdata`：生产级关系数据库持久化存储 |
| **`netops`** | 本地 `Dockerfile` 编译构建 | 内部 `8003` | `nexora-data`（运行数据）、`nexora-backup`（配置备份）、`nexora-dist`（构建产物导出） |
| **`nginx`** | `nginx:1.27-alpine` | 对外 `80` / `443` | 挂载 `nexora-dist` 静态网页与 `./nginx/ssl` 证书目录，提供反向代理与 HTTPS |

---

## 🛠️ Docker 5 分钟一键部署教程

我们为您提供了两个代码托管地址，部署时任选其一即可：

- **Gitee 地址**：`https://gitee.com/leerbon/netops.git`
- **GitHub 地址**：`https://github.com/libing28390-sketch/Release-netops.git`

### 第一步：准备 Linux 主机与拉取代码

在您的 Linux 宿主机终端执行以下命令拉取项目：

```bash
# 二选一：选择当前环境可以访问的代码仓库
git clone https://gitee.com/leerbon/netops.git nexora-automation
# 或者使用 GitHub
# git clone https://github.com/libing28390-sketch/Release-netops.git nexora-automation

cd nexora-automation
```

---

### 第二步：一键构建与启动服务

为照顾不同使用习惯，项目提供了两套部署方式，推荐使用官方自动化部署工具脚本。

#### 推荐方式 A：使用内置自动化部署脚本（最省心）
项目自带了智能部署工具 `scripts/deploy-docker.sh`，会自动帮您完成环境检查、从 `.env.example` 生成配置、使用 `openssl` 自动生成 **32 字节高强度密钥**与**随机数据库密码**，并构建拉起容器：

```bash
# 自动初始化环境变量、构建镜像并后台拉起容器
bash scripts/deploy-docker.sh install
```

> 💡 **后续维护命令（基于 deploy-docker.sh 工具）：**
> - **平滑升级项目**：`bash scripts/deploy-docker.sh update`（自动比对源码变更并安全重建，不丢失数据库与备份）
> - **彻底重置环境**：`bash scripts/deploy-docker.sh reset-data`（清空容器与数据卷，谨慎操作）

#### 方式 B：使用原生 Docker Compose 手动控制
如果您熟悉或希望完全掌控各项参数配置：

```bash
# 1. 复制环境配置模板
cp .env.example .env

# 2. 编辑 .env 文件（重点修改以下安全参数）
# - POSTGRES_PASSWORD=您的数据库高强度密码
# - SECRET_KEY=由 openssl rand -hex 32 生成的随机字符串
# - CREDENTIAL_ENCRYPTION_KEY=由 openssl rand -hex 32 生成的随机字符串
# - DATABASE_URL=postgresql://postgres:您的密码@db:5432/netops

# 3. 触发 Docker Compose 编译与后台启动
docker compose up -d --build
```

> 💡 **构建提示**：首次启动会拉取 pgvector/PostgreSQL 和 Nginx 基础镜像，并在后端镜像构建阶段编译 React 前端代码。如果生产服务器无法访问镜像仓库，请先在联网构建机执行 `bash scripts/deploy-docker.sh save-images <archive-path>`，再在目标服务器执行 `load-images` 和 `start-offline`。

---

### 第三步：访问系统与开局初始化

当终端提示所有容器（`nexora-db`、`nexora-netops`、`nexora-nginx`）状态为 `Healthy` 或 `Up` 后，在浏览器中访问系统：

- **访问地址**：`https://<您的服务器IP>`（或 `http://localhost`）
  *(注：默认 Nginx 会生成高安全系数的自签名 SSL 证书，浏览器提示证书不可信时选择“继续访问”即可；或将您企业持有的合法证书替换至 `./nginx/ssl/` 目录)*
- **默认管理员账号**：`admin`
- **默认管理员密码**：`admin`

🎉 **恭喜！您已成功开局！** 首次登录后，强烈建议立即进入【系统设置 / 用户管理】修改默认密码，并在设备管理页面添加您的第一台核心交换机，体验极速命令下发与自动化巡检。

---

## 🩺 常用运维与日志排障命令

所有日常操作均可在仓库根目录下执行，无需指定 compose 文件：

```bash
# 查看各个容器运行状态与健康检查(Health Check)结果
docker compose ps

# 实时追踪后端 API 与执行引擎日志
docker compose logs -f netops

# 查看 Nginx 前端请求访问日志与 HTTPS 握手日志
docker compose logs -f nginx

# 单独重启后端服务（修改部分环境变量配置后生效）
docker compose restart netops

# 停止并安全销毁本次 Compose 容器实例（保留数据卷与备份文件）
docker compose down
```

---

## 🎁 读者福利与技术交流

- **关注公众号**：微信搜索关注 **“小网工爱运维”**，回复 **“试用”** 或 **“交流”** 获取最新运维自动化实践案例与行业精选干货。
- **开源共建与打赏**：如果本项目让您的网络运维工作获得了极大解脱，欢迎在 Gitee / GitHub 点亮 **Star ⭐️** 或打赏一杯咖啡 ☕️！
- **反馈与技术讨论**：在部署或使用过程中遇到任何 Bug、设备兼容性问题或新功能建议，欢迎前往仓库提交 **Issue**，开源团队将第一时间跟进解决；同时也欢迎通过公众号联系作者加入专业技术群交流沟通！
