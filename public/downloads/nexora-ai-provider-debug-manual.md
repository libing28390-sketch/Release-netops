# Nexora AI 配置与调试手册

> 本手册只说明配置和操作步骤，适用于 `/ai/providers`、`/ai/models`、`/ai/security`、`/ai/copilot`。

## 1. 修改根目录 `.env`

在项目根目录创建或修改 `.env`。没有 `.env` 时，先复制 `.env.example`，再修改下面的配置。

### 1.1 外部 AI 最小可用配置

```dotenv
AI_ENABLED=1
EXTERNAL_AI_ENABLED=1
AI_KILL_SWITCH=0
AI_PROVIDER_ALLOWLIST=deepseek,openai,openai_compatible,azure_openai,ollama,local,qwen
AI_DEV_PASSTHROUGH_ENABLED=0
AI_DEV_PASSTHROUGH_MAX_MINUTES=15
VITE_PORT=5400
```

| 配置项 | 填写说明 |
| --- | --- |
| `AI_ENABLED` | `1` 开启 AI 功能，`0` 关闭。 |
| `EXTERNAL_AI_ENABLED` | `1` 允许调用 DeepSeek 等外部 Provider。 |
| `AI_KILL_SWITCH` | 正常使用必须为 `0`；设为 `1` 会阻断 AI 请求。 |
| `AI_PROVIDER_ALLOWLIST` | 必须包含 Provider 的类型，例如 DeepSeek 使用 `deepseek`。 |
| `AI_DEV_PASSTHROUGH_ENABLED` | 普通使用填 `0`；仅开发环境临时调试时才填 `1`。 |
| `AI_DEV_PASSTHROUGH_MAX_MINUTES` | 开发环境直通模式最长时间，默认 15 分钟。 |
| `VITE_PORT` | 前端端口，当前项目使用 `5400`。 |

### 1.2 保留并检查密钥配置

以下配置必须存在，实际密钥不要提交到 Git，也不要写入前端 `VITE_*` 配置：

```dotenv
SECRET_KEY=请填写部署环境的随机密钥
CREDENTIAL_ENCRYPTION_KEY=请填写32位随机设备凭据加密密钥
DATABASE_URL=保持当前数据库连接地址
ENVIRONMENT=development
LOG_LEVEL=INFO
```

如果项目已经有可用值，保持原值即可。`EXTERNAL_AI_ENABLED=1` 时，`CREDENTIAL_ENCRYPTION_KEY` 不能继续使用 `.env.example` 中的占位值。

API Key 不填入 `.env`，在 Provider 页面录入，系统会按当前项目的加密配置保存。

## 2. 配置 DeepSeek Provider

打开：`http://<项目地址>:5400/ai/providers`

点击“添加 Provider”，填写：

| 页面字段 | 推荐填写 |
| --- | --- |
| 名称 | `deepseek` 或 `DeepSeek 主供应商` |
| Provider 类型 | `DeepSeek` |
| Base URL | `https://api.deepseek.com` |
| API Key | 填写 DeepSeek 控制台生成的真实 Key |
| 数据区域 | 按实际合规要求选择；中国区域通常选择 `cn` |
| 允许的数据分类 | 普通内部数据选择 `INTERNAL`；需要允许更高敏感级别时选择 `CONFIDENTIAL` |
| 启用 | 打开 |

保存后点击“测试连通性”。测试通过后，继续配置模型和安全策略。

## 3. 配置安全策略

打开：`http://<项目地址>:5400/ai/security`

确认并保存：

- 外部 AI：开启。
- Kill Switch：关闭。
- 允许的 Provider 类型包含 `deepseek`。
- 允许的数据区域包含 Provider 中填写的区域，例如 `cn`。
- 允许的数据分类至少包含 Copilot 要发送的数据级别；使用 `INTERNAL` 时，策略中也要允许 `INTERNAL`。

修改后点击页面的保存按钮。数据库中已经保存的安全策略优先于只修改 `.env` 后的预期，因此页面保存后要刷新确认。

## 4. 配置模型

打开：`http://<项目地址>:5400/ai/models`

点击“添加模型”或编辑已有模型：

1. Provider 选择刚创建的 DeepSeek Provider。
2. `model_code` 填写 DeepSeek 接口实际支持的模型代码，例如 `deepseek-chat` 或 `deepseek-reasoner`。
3. 打开“启用”。
4. 需要作为默认模型时，打开“默认”。
5. 保存后确认模型状态为启用。

模型代码要填接口实际代码，不要填写页面展示名称。

## 5. 前端配置

### 5.1 本地前端端口

在根目录 `.env` 中设置：

```dotenv
VITE_PORT=5400
```

### 5.2 前后端不在同一台机器

Vite 代理默认指向 `http://127.0.0.1:5310`。需要修改后端地址时，在启动前设置环境变量。

PowerShell：

```powershell
$env:VITE_API_TARGET="http://后端地址:5310"
npm run dev:frontend
```

Linux/macOS：

```bash
VITE_API_TARGET=http://后端地址:5310 npm run dev:frontend
```

如果前后端都在本机，保持默认值即可。API Key 不要配置为 `VITE_*` 变量，因为前端构建后会暴露给浏览器。

## 6. 重启并验证

修改 `.env` 后必须重启后端；修改 `VITE_PORT` 或 `VITE_API_TARGET` 后必须重启前端。

开发环境可执行：

```powershell
npm run dev
```

然后按顺序验证：

1. `/ai/providers`：Provider 状态为 `healthy`，点击测试连通性成功。
2. `/ai/models`：模型已启用并绑定正确 Provider。
3. `/ai/security`：外部 AI、Provider、区域、分类和 Kill Switch 配置正确。
4. `/ai/copilot`：选择刚配置的模型，发送“今天是几号”或“回复 ok”进行测试。

## 7. 常见配置检查

| 页面提示 | 优先检查 |
| --- | --- |
| `AI request blocked by security policy` | `AI_KILL_SWITCH`、安全策略外部 AI、Provider 白名单、数据区域和数据分类。 |
| `只读数据准备失败` | Copilot 诊断范围、数据库连接、设备数据权限和安全策略。 |
| Provider 测试成功但 Copilot 失败 | 模型是否启用、模型代码是否正确、Copilot 是否选择了正确模型。 |
| 页面接口出现 404 | 前端代理目标是否为正确的后端端口，修改环境变量后是否重启前端。 |
| 修改 `.env` 后没有变化 | 是否重启后端；数据库安全策略是否仍覆盖了当前配置。 |

## 8. 开发环境临时直通

只在本地开发调试时使用：

```dotenv
ENVIRONMENT=development
AI_DEV_PASSTHROUGH_ENABLED=1
AI_DEV_PASSTHROUGH_MAX_MINUTES=15
```

启动后，在 Copilot 页面打开“临时直通”开关。测试结束后关闭开关，并将 `.env` 恢复为：

```dotenv
AI_DEV_PASSTHROUGH_ENABLED=0
```

生产环境不要启用直通模式，也不要把 API Key、密码、SNMP community、私钥或完整设备配置粘贴到 Copilot。
