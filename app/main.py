import json
import time
import uuid
from collections.abc import AsyncIterator
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from app.config import settings
from app.models import ChatRequest, ModelInfo, ModelListResponse
from app.ollama_client import OllamaClient

app = FastAPI(title="LLM Serving API", version="0.1.0")
ollama = OllamaClient()


@app.get("/health")
async def health() -> dict:
    ollama_ok = await ollama.health()
    return {"status": "ok" if ollama_ok else "degraded", "service": "llm-serving", "ollama": "ok" if ollama_ok else "unavailable"}


@app.get("/v1/models", response_model=ModelListResponse)
async def models() -> ModelListResponse:
    try:
        result = await ollama.list_models()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}") from exc
    return ModelListResponse(data=[ModelInfo(id=model["name"]) for model in result.get("models", [])])


def _openai_response(model: str, content: str, prompt_tokens: int | None = None, completion_tokens: int | None = None) -> dict:
    usage = {}
    if prompt_tokens is not None:
        usage["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        usage["completion_tokens"] = completion_tokens
    if usage:
        usage["total_tokens"] = sum(usage.values())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": usage or None,
    }


async def _stream_openai(model: str, messages: list[dict]) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    async for line in ollama.chat_stream(model, messages):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = data.get("message", {}).get("content", "")
        if content:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        if data.get("done"):
            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    model = request.model or settings.default_model
    messages = [{"role": message.role, "content": message.content} for message in request.messages]
    try:
        if request.stream:
            return StreamingResponse(_stream_openai(model, messages), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
        result = await ollama.chat(model=model, messages=messages)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {exc}") from exc
    response_message = result.get("message", {})
    return _openai_response(model, response_message.get("content", ""), result.get("prompt_eval_count"), result.get("eval_count"))
