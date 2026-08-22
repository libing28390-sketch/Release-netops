# Nexora AI 快速配置手册

> 适用于 `/ai/providers`、`/ai/models`、`/ai/security`、`/ai/copilot`。

## 0. 先确认部署方式和访问入口

AI 页面路径相同，但访问协议、主机和端口取决于部署方式。`5400` 只用于本地前端开发，不要用于 Docker 或正式生产环境。

| 部署方式 | 平台基础地址 | Provider | Models | Security | Copilot |
| --- | --- | --- | --- | --- | --- |
| Docker Compose 生产部署 | `https://<Docker服务器IP>`（Nginx 默认 443；HTTP 会跳转 HTTPS） | `/ai/providers` | `/ai/models` | `/ai/security` | `/ai/copilot` |
| Ubuntu/物理机部署 | `http://<服务器IP>:<Nginx端口>`（脚本默认 80） | `/ai/providers` | `/ai/models` | `/ai/security` | `/ai/copilot` |
| Windows 桌面部署 | `http://127.0.0.1:5010` | `/ai/providers` | `/ai/models` | `/ai/security` | `/ai/copilot` |
| 本地前端开发 | `http://127.0.0.1:5400` | `/ai/providers` | `/ai/models` | `/ai/security` | `/ai/copilot` |

例如 Docker 服务器地址为 `192.168.204.128` 时，应访问：

```text
https://192.168.204.128/ai/copilot
```

同一部署下的其他页面为：

```text
https://192.168.204.128/ai/providers
https://192.168.204.128/ai/models
https://192.168.204.128/ai/security
```

Docker 首次启动可能使用自签名证书，浏览器会提示证书风险；生产环境应替换 `nginx/ssl/` 下的证书。Ubuntu 如果把 Nginx 改为其他端口，例如 `8080`，则使用 `http://<服务器IP>:8080/ai/copilot`。Windows 需要局域网访问时，将 `127.0.0.1` 替换为 Windows 主机 IP，并按防火墙策略放行 5010。

下面步骤中的 `<平台基础地址>`，请替换为上表对应的地址。例如 Docker 环境使用 `https://192.168.204.128`，不要再固定使用 `http://<项目地址>:5400`。

## 1. `.env` 最小配置

正式 Docker 环境保持 `production`，不需要改成 `development`：

```dotenv
ENVIRONMENT=production
AI_ENABLED=1
EXTERNAL_AI_ENABLED=1
AI_KILL_SWITCH=0
AI_PROVIDER_ALLOWLIST=deepseek,openai,openai_compatible,azure_openai,ollama,local,qwen
```

API Key 不要写入 `.env`、前端 `VITE_*` 变量或 Git，在 Provider 页面填写。
`.env` 中同一个变量只保留一行，重复定义可能以后出现的值为准。

## 2. Docker 部署后更新

Compose 会把部署目录中的 `.env` 自动加载到 `netops` 容器。修改 `.env` 后只需重新创建容器，不需要重新 build；代码更新才需要 build：

```bash
# 只修改 .env
docker compose up -d --force-recreate netops nginx

# 拉取代码或修改代码
git pull origin main
docker compose up -d --build --force-recreate netops nginx
```

Docker 内部会自动使用生产环境标识和数据库容器地址，不要为了开启 AI 临时测试模式修改 `ENVIRONMENT`。

以后开启或关闭 AI 临时测试模式，不需要修改 `.env`，也不需要重新 build。

检查容器是否读到配置：

```bash
docker compose exec netops sh -lc 'printf "ENVIRONMENT=%s\nAI_ENABLED=%s\nEXTERNAL_AI_ENABLED=%s\nAI_KILL_SWITCH=%s\n" "$ENVIRONMENT" "$AI_ENABLED" "$EXTERNAL_AI_ENABLED" "$AI_KILL_SWITCH"'
```

## 3. 配置 DeepSeek

打开 `<平台基础地址>/ai/providers`，新增 Provider：

| 字段 | 填写值 |
| --- | --- |
| 类型 | `DeepSeek` |
| Base URL | `https://api.deepseek.com` |
| API Key | DeepSeek 控制台生成的 Key |
| 数据区域 | 按实际要求选择，例如 `cn` |
| 允许的数据分类 | 通常选择 `INTERNAL` |
| 启用 | 打开 |

保存后点击“测试连通性”。

## 4. 配置安全策略和模型

打开 `<平台基础地址>/ai/security`，确认：

- 外部 AI 已开启。
- Kill Switch 已关闭。
- Provider 白名单包含 `deepseek`。
- 数据区域和数据分类符合 Provider 配置。

打开 `<平台基础地址>/ai/models`，确认模型已绑定 DeepSeek、模型代码正确并已启用。

## 5. AI 临时测试模式

打开 `<平台基础地址>/ai/security`，在“AI 临时测试模式”卡片中点击开关。

- 仅管理员可以操作。
- 最多开启 15 分钟，到期自动关闭。
- 容器重启后自动关闭。
- 不需要修改 `ENVIRONMENT`，不需要修改 `.env`。
- 仍然拦截 API Key、密码、私钥、JWT、Cookie、SNMP community 和危险工具。

测试结束后可以手动关闭开关。

## 6. 常见问题

| 现象 | 检查项 |
| --- | --- |
| 看不到临时测试模式 | 是否访问 `/ai/security`；容器是否已用最新代码重新 build。 |
| Provider 测试成功但 Copilot 失败 | 检查 `/ai/security` 的外部 AI、Kill Switch、区域和分类。 |
| 修改 `.env` 后不生效 | 使用 `docker compose up -d --force-recreate netops nginx`，不要只执行 `restart`。 |
| 页面仍是旧版本 | 浏览器执行 `Ctrl+F5`，并确认 `netops`、`nginx` 都已重建。 |

本模式用于受控调试，不等于关闭安全网关。
