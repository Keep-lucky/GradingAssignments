"""AI 服务设置及可用模型查询。"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


def list_models(provider: str, base_url: str, api_key: str, *, timeout: int = 20) -> list[str]:
    """通过所选协议读取当前 Key 可访问的模型 ID。"""
    provider = provider.strip().lower()
    base_url = base_url.rstrip("/")
    api_key = api_key.strip()
    if provider not in DEFAULT_BASE_URLS:
        raise ValueError("仅支持 OpenAI 或 Anthropic 接口。")
    if not base_url or not api_key:
        raise ValueError("请填写请求地址和 API Key。")
    headers = {"Accept": "application/json"}
    if provider == "openai":
        headers["Authorization"] = f"Bearer {api_key}"
    else:
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    try:
        endpoint = f"{base_url}/models" if provider == "openai" else f"{base_url}/v1/models"
        request = Request(endpoint, headers=headers, method="GET")
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [str(item["id"]) for item in payload.get("data", []) if item.get("id")]
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as error:
        raise RuntimeError("获取模型列表失败，请检查接口地址、API Key 和网络连接。") from error
    if not models:
        raise RuntimeError("接口未返回可用模型。")
    return sorted(set(models))
