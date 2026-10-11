
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class OllamaClient:
    """封装 FastAPI 到 llama.cpp OpenAI-compatible API 的 HTTP 通信。"""

    def __init__(self) -> None:
        # 例如：http://llm-serving-llama:8080/v1
        self.base_url = settings.llama_base_url.rstrip("/")
        self.timeout = settings.request_timeout

    async def health(self) -> bool:
        """检查 llama.cpp 服务是否可访问。"""
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=False,
            ) as client:
                response = await client.get(
                    f"{self.base_url}/models"
                )
                response.raise_for_status()
                return True

        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "llama.cpp health check failed: %s",
                exc,
                exc_info=True,
            )
            return False

    async def list_models(self) -> dict:
        """获取 llama.cpp 提供的模型列表。"""
        async with httpx.AsyncClient(
            timeout=10.0,
            trust_env=False,
        ) as client:
            response = await client.get(
                f"{self.base_url}/models"
            )
            response.raise_for_status()
            return response.json()

    async def chat(self, model: str, messages: list[dict]) -> dict:
        """发送非流式对话请求，返回 OpenAI 兼容格式。"""
        async with httpx.AsyncClient(
            timeout=self.timeout,
            trust_env=False,
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
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
        """发送流式请求，逐行返回 OpenAI SSE 数据。"""
        async with httpx.AsyncClient(
            timeout=None,
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line:
                        yield line
