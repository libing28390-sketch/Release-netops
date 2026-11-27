"""Documented catalog routes for the supported mainland China API presets."""

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DomesticCatalog:
    kind: str
    path: str | None = None
    items: tuple[dict[str, str], ...] = ()


def _chat_candidates(*codes: str) -> tuple[dict[str, str], ...]:
    return tuple({"model_code": code, "name": code, "model_type": "chat"} for code in codes)


# These lists come from official chat compatibility docs. They describe the
# public API and do not imply that an individual account has model access.
_PUBLIC = {
    # https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope
    "dashscope": _chat_candidates("qwen3.8-max", "qwen3.7-plus", "qwen-plus", "qwen-flash"),
    # https://cloud.tencent.com/document/product/1729/104753
    "hunyuan": _chat_candidates("hunyuan-a13b", "hunyuan-translation", "hunyuan-vision-1.5-instruct", "hunyuan-t1-vision-20250916"),
    # https://docs.bigmodel.cn/cn/guide/start/quick-start
    "zhipu": _chat_candidates("glm-5.3", "glm-5.3-flash", "glm-5.2"),
    # https://platform.minimax.cn/docs/api-reference/text-openai-api
    "minimax": _chat_candidates("MiniMax-M3.1-Flash", "MiniMax-M3"),
}

_CHAT_TYPES = {"chat", "text", "textgeneration", "text-generation", "llm"}
_EMBED_TYPES = {"embedding", "embeddings", "text-embedding", "textembedding"}
_OTHER_TYPES = {"image", "image-generation", "video", "audio", "tts", "asr"}


def get_domestic_catalog(base_url: str) -> DomesticCatalog | None:
    try:
        url = urlsplit(base_url)
        port = url.port
    except ValueError:
        return None
    if url.scheme != "https" or not url.hostname or url.username is not None or port not in (None, 443):
        return None
    host = url.hostname
    base = url.path.rstrip("/").removesuffix("/chat/completions")

    if host == "api.deepseek.com" and base in {"", "/v1"}:
        return DomesticCatalog("deepseek", f"{base}/models")
    if host == "ark.cn-beijing.volces.com" and base == "/api/v3":
        return DomesticCatalog("ark", "/api/v3/models")
    if host == "qianfan.baidubce.com" and base == "/v2":
        return DomesticCatalog("qianfan", "/v2/models")
    if host == "api.moonshot.cn" and base == "/v1":
        return DomesticCatalog("kimi", "/v1/models")
    if host == "api.siliconflow.cn" and base == "/v1":
        return DomesticCatalog("siliconflow", "/v1/models")
    if host in {"tokenhub.tencentcloudmaas.com", "tokenhub-intl.tencentcloudmaas.com", "tokenhub-us.tencentcloudmaas.tech"} and base == "/v1":
        return DomesticCatalog("tokenhub", "/v1/models")
    if base == "/compatible-mode/v1":
        if host == "dashscope-us.aliyuncs.com" or re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com", host):
            return DomesticCatalog("dashscope", "/api/v1/models")
        if host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com"}:
            return DomesticCatalog("dashscope", items=_PUBLIC["dashscope"])
    public_kind = {
        ("api.hunyuan.cloud.tencent.com", "/v1"): "hunyuan",
        ("open.bigmodel.cn", "/api/paas/v4"): "zhipu",
        ("api.minimax.cn", "/v1"): "minimax",
    }.get((host, base))
    return DomesticCatalog(public_kind, items=_PUBLIC[public_kind]) if public_kind else None


def _compatible_type(kind: str, item: dict[str, Any]) -> str | None:
    if kind in {"deepseek", "kimi"}:
        return "chat"
    if kind == "dashscope":
        values = item.get("capabilities")
        capabilities = {str(value).lower() for value in values} if isinstance(values, list) else set()
        if "tg" in capabilities:
            return "chat"
        if "tr" in capabilities:
            return "embedding"
        return None

    status = str(item.get("status") or "").lower()
    if status in {"offline", "disabled", "retired"} or (kind == "tokenhub" and status != "online"):
        return None
    if kind == "tokenhub":
        return "chat"
    declared_type = str(item.get("sub_type") or item.get("type") or "").lower()
    if declared_type in _EMBED_TYPES:
        return "embedding"
    if declared_type in {"rerank", "reranker"}:
        return "rerank"
    if declared_type in _OTHER_TYPES:
        return None
    if declared_type in _CHAT_TYPES:
        return "chat"
    endpoints = item.get("endpoints")
    if kind == "qianfan" and isinstance(endpoints, (str, list)) and "/v2/chat/completions" in endpoints:
        return "chat"
    return "unknown"


def parse_domestic_catalog_page(kind: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    if kind == "dashscope":
        output = payload.get("output")
        rows = output.get("models") if isinstance(output, dict) and payload.get("success") is not False else None
    else:
        rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("Invalid domestic provider model catalog")
    items = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        code = item.get("model" if kind == "dashscope" else "id")
        if not isinstance(code, str) or not (code := code.strip()) or len(code) > 256:
            continue
        model_type = _compatible_type(kind, item)
        if model_type is None:
            continue
        name = item.get("model_name") or item.get("name")
        display_name = name.strip() if isinstance(name, str) else ""
        items.append({"model_code": code, "name": (display_name or code)[:256], "model_type": model_type})
    return items
