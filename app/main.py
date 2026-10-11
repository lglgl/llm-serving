
import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models import ChatRequest, ModelInfo, ModelListResponse
from app.ollama_client import OllamaClient


logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Serving API", version="0.1.0")
ollama = OllamaClient()


@app.get("/health")
async def health() -> dict:
    """检查 llama.cpp 后端是否可用。"""
    backend_ok = await ollama.health()

    if not backend_ok:
        raise HTTPException(
            status_code=503,
            detail="llama.cpp unavailable",
        )

    return {
        "status": "ok",
        "service": "llm-serving",
        "backend": "llama.cpp",
    }


@app.get("/v1/models", response_model=ModelListResponse)
async def models() -> ModelListResponse:
    """返回 OpenAI 兼容的模型列表。"""
    try:
        result = await ollama.list_models()
        model_list = result.get("data", [])

        return ModelListResponse(
            data=[
                ModelInfo(id=model["id"])
                for model in model_list
                if model.get("id")
            ]
        )
    except Exception as exc:
        logger.exception("Failed to list llama.cpp models")
        raise HTTPException(
            status_code=503,
            detail="llama.cpp model list unavailable",
        ) from exc


async def _stream_openai(
    model: str,
    messages: list[dict],
) -> AsyncIterator[str]:
    """
    转发 llama.cpp 返回的 OpenAI SSE 数据。
    统一输出 data: ... 格式，并保留 [DONE] 结束标记。
    """
    try:
        async for line in ollama.chat_stream(model, messages):
            # SSE 可能包含注释或空行
            if not line or line.startswith(":"):
                continue

            if not line.startswith("data:"):
                continue

            data_text = line[len("data:"):].strip()

            if data_text == "[DONE]":
                yield "data: [DONE]\n\n"
                return

            try:
                data = json.loads(data_text)
            except json.JSONDecodeError:
                logger.warning("Invalid SSE JSON received from llama.cpp")
                continue

            # llama.cpp 已返回 OpenAI-compatible chunk，
            # 无需再将 Ollama message.content 转换成 delta。
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    except Exception:
        logger.exception("llama.cpp streaming request failed")
        error_event = {
            "error": {
                "message": "LLM streaming request failed",
                "type": "server_error",
            }
        }
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    """提供 OpenAI 兼容的聊天补全接口。"""
    model = request.model or settings.default_model
    messages = [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in request.messages
    ]

    if request.stream:
        return StreamingResponse(
            _stream_openai(model, messages),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        result = await ollama.chat(model=model, messages=messages)

        # llama.cpp 的非流式响应已经是 OpenAI Chat Completion 格式。
        # 保留模型返回的 id、choices、usage 等字段。
        return result

    except Exception as exc:
        logger.exception("llama.cpp chat request failed")
        raise HTTPException(
            status_code=503,
            detail="LLM service unavailable",
        ) from exc
