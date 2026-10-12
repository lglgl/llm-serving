import json
import logging
from prometheus_fastapi_instrumentator import Instrumentator
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models import ChatRequest, ModelInfo, ModelListResponse
from app.llama_client import LlamaClient


logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Serving API", version="0.1.0")
# 注册 HTTP 指标采集，并暴露 Prometheus /metrics 端点
Instrumentator().instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False,
)

llama = LlamaClient()


@app.get("/health")
async def health() -> dict:
    backend_ok = await llama.health()

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
    try:
        result = await llama.list_models()
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
    try:
        async for line in llama.chat_stream(model, messages):
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
        return await llama.chat(model=model, messages=messages)
    except Exception as exc:
        logger.exception("llama.cpp chat request failed")
        raise HTTPException(
            status_code=503,
            detail="LLM service unavailable",
        ) from exc
