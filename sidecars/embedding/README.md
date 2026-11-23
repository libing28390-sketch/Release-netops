# Embedding sidecar（bge-m3，CPU，离线）

为知识库检索提供中文语义向量。它是一个独立容器，只连接内部网络 `semantic_embedding`，不对外开放端口，运行时不访问外网。

## 1. 导出模型（在能联网的构建机上做一次）

```bash
pip install "optimum[onnxruntime]>=1.21" "transformers>=4.44" onnx onnxruntime
python sidecars/embedding/export_model.py --output sidecars/embedding/models/bge-m3 --revision <固定的 commit hash>
```

产物在 `sidecars/embedding/models/bge-m3/`：`model.onnx`（int8，约 570 MB）、`tokenizer.json`、`manifest.json`（模型名、维度 1024、版本、各文件的 sha256）。该目录已加入 `.gitignore`，不要提交到仓库。

> 换 revision 或去掉量化就是新的向量版本，需要同时修改 `--version` 和 `.env` 中的 `AI_SEMANTIC_EMBEDDING_VERSION`，并重新生成全部向量。

## 2. 构建并分发镜像

```bash
docker compose --profile semantic-embedding build embedding-sidecar
docker save nexora-embedding-sidecar:bge-m3-int8-v1 | gzip > nexora-embedding-sidecar.tar.gz
# 离线主机
docker load < nexora-embedding-sidecar.tar.gz
```

## 3. 启用

`.env`：

```dotenv
AI_SEMANTIC_EMBEDDING_PROVIDER=sidecar
# 可选：共享令牌
AI_EMBEDDING_SIDECAR_TOKEN=<随机字符串>
```

```bash
docker compose --profile semantic-embedding up -d embedding-sidecar
docker compose up -d netops        # 让 backend 加入 semantic_embedding 网络并读取新配置
```

状态检查：`GET /api/ai/models/semantic-embedding/status`（需要 `ai.view` 权限），返回 `ready` / `unavailable` / `disabled`，不包含任何文本或地址。

## 资源

| 项目 | 默认 | 说明 |
| :--- | :--- | :--- |
| 内存上限 | 1536 MB（`EMBEDDING_SIDECAR_MEM_LIMIT`） | 模型约 570 MB，加推理缓冲 |
| CPU | 2 核（`EMBEDDING_SIDECAR_CPUS`、`EMBEDDING_SIDECAR_THREADS`） | |
| 单条最大 token | 512（`EMBEDDING_SIDECAR_MAX_TOKENS`） | chunk 默认约 800 字符，足够 |

## 降级行为

- sidecar 没启动、超时或返回异常时，backend 报 `EmbeddingProviderError`，并在 `AI_EMBEDDING_SIDECAR_COOLDOWN_SECONDS`（默认 30 秒）内直接降级，不再等待超时。检索继续使用全文和模糊匹配。
- sidecar 的模型名、维度或版本和 `.env` 不一致时拒绝使用，避免不同模型的向量混在一起。
- 请求和日志里都不记录原文。

## 接口

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| GET | `/healthz` | 模型加载完成前返回 503 |
| GET | `/v1/info` | 模型契约（model_id、dimensions、version、manifest_sha256） |
| POST | `/v1/embeddings` | `{"input": [...], "kind": "query" \| "document"}`，每批最多 64 条 |
