# Nexora AI 快速配置手册

> 适用于 `/ai/providers`、`/ai/models`、`/ai/security`、`/ai/copilot`。

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

打开 `/ai/providers`，新增 Provider：

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

打开 `/ai/security`，确认：

- 外部 AI 已开启。
- Kill Switch 已关闭。
- Provider 白名单包含 `deepseek`。
- 数据区域和数据分类符合 Provider 配置。

打开 `/ai/models`，确认模型已绑定 DeepSeek、模型代码正确并已启用。

## 5. AI 临时测试模式

打开 `/ai/security`，在“AI 临时测试模式”卡片中点击开关。

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
