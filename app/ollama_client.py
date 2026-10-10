import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings


# 记录 Ollama 客户端的连接和请求异常
logger = logging.getLogger(__name__)


class OllamaClient:
    """封装 FastAPI 到 Ollama 的 HTTP 通信。"""

    def __init__(self) -> None:
        # Ollama 服务地址，例如：
        # http://llm-serving-ollama:11434
        self.base_url = settings.ollama_base_url.rstrip("/")

        # 普通推理请求的超时时间
        self.timeout = settings.request_timeout

    async def health(self) -> bool:
        """检查 Ollama API 是否可访问。"""
        try:
            # trust_env=False：不读取 HTTP_PROXY、HTTPS_PROXY 等环境变量，
            # 避免 Kubernetes 内部 Service 请求被外部代理干扰。
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=False,
            ) as client:
                response = await client.get(
                    f"{self.base_url}/api/tags"
                )

                # 非 2xx 状态码会抛出 HTTPStatusError
                response.raise_for_status()

                # 收到成功的 HTTP 响应，说明 Ollama API 可访问
                return True

        except (httpx.HTTPError, OSError) as exc:
            # 记录实际错误，避免只返回 False 而无法定位原因
            logger.warning(
                "Ollama health check failed: %s",
                exc,
                exc_info=True,
            )
            return False

    async def list_models(self) -> dict:
        """获取 Ollama 已登记的模型列表。"""
        async with httpx.AsyncClient(
            timeout=10.0,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{self.base_url}/api/tags"
            )
            response.raise_for_status()

            # 返回 Ollama 原始 JSON 数据
            return response.json()

    async def chat(self, model: str, messages: list[dict]) -> dict:
        """发送非流式对话请求，等待模型生成完整回答。"""
        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                },
            )
            response.raise_for_status()

            return response.json()

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """发送流式对话请求，逐行返回 Ollama 的响应数据。"""
        async with httpx.AsyncClient(
            timeout=None,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                # Ollama 使用逐行 JSON 响应传输生成过程
                async for line in response.aiter_lines():
                    if line:
                        yield line
