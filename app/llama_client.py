"""
llama.cpp HTTP 客户端。

负责 FastAPI 与 llama.cpp OpenAI-compatible API 之间的通信。

支持：
1. 后端健康检查
2. 获取模型列表
3. 非流式推理
4. 流式推理
5. 异常日志记录

预期后端地址：
http://host.docker.internal:8081/v1

实际 API：
GET  /v1/models
POST /v1/chat/completions
"""

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings


logger = logging.getLogger(__name__)


class LlamaClient:
    """封装 FastAPI 到 llama.cpp OpenAI-compatible API 的 HTTP 通信。"""

    def __init__(self) -> None:
        # 地址需要包含 /v1。
        # 例如：http://host.docker.internal:8081/v1
        self.base_url = settings.llama_base_url.rstrip("/")
        self.timeout = settings.request_timeout

        logger.info(
            "LlamaClient initialized: base_url=%s, timeout=%s",
            self.base_url,
            self.timeout,
        )

    async def health(self) -> bool:
        """
        检查 llama.cpp 的模型 API 是否可访问。

        Returns:
            True: 后端可访问。
            False: 后端不可访问。
        """
        url = f"{self.base_url}/models"

        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                trust_env=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

            return True

        except (httpx.HTTPError, OSError) as exc:
            logger.warning(
                "llama.cpp health check failed: url=%s, error=%s",
                url,
                exc,
                exc_info=True,
            )
            return False

    async def list_models(self) -> dict[str, Any]:
        """
        获取 llama.cpp 支持的模型列表。

        Returns:
            后端返回的 JSON 对象。

        Raises:
            httpx.HTTPError: HTTP 请求失败或返回非成功状态码。
            ValueError: 响应 JSON 无法解析。
        """
        url = f"{self.base_url}/models"

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                trust_env=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()

        except Exception:
            logger.exception(
                "llama.cpp list_models failed: url=%s",
                url,
            )
            raise

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        执行非流式推理。

        Args:
            model: 模型名称，例如 qwen2:0.5b。
            messages: OpenAI-compatible 消息列表。

        Returns:
            llama.cpp 返回的推理结果 JSON。

        Raises:
            请求、HTTP 状态码或 JSON 解析相关异常。
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                trust_env=False,
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                )
                response.raise_for_status()
                return response.json()

        except Exception:
            logger.exception(
                "llama.cpp chat failed: url=%s, model=%s",
                url,
                model,
            )
            raise

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        """
        执行流式推理。

        逐行返回 llama.cpp 的 SSE 响应内容。
        上层路由负责将这些内容转发给客户端。

        Args:
            model: 模型名称。
            messages: OpenAI-compatible 消息列表。

        Yields:
            SSE 响应中的非空行。

        Raises:
            请求或 HTTP 状态码相关异常。
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            # 让 llama.cpp 在结束 chunk 中返回 Token 用量，以便统计流式 Token 速率和 TPOT。
            "stream_options": {"include_usage": True},
        }

        try:
            async with httpx.AsyncClient(
                timeout=None,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line:
                            yield line

        except Exception:
            logger.exception(
                "llama.cpp stream failed: url=%s, model=%s",
                url,
                model,
            )
            raise
