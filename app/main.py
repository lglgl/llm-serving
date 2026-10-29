import httpx
from collections.abc import AsyncIterator
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from litellm import acompletion
from app.config import settings, resolve_litellm_target
from app.models import ChatRequest, ModelInfo, ModelListResponse

app = FastAPI(title="LLM Serving API", version="0.2.0")


async def _backend_health(api_base: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            base = api_base.rstrip("/")
            health_url = f"{base[:-3]}/health" if base.endswith("/v1") else f"{base}/health"
            response = await client.get(health_url)
            response.raise_for_status()
            return True
    except (httpx.HTTPError, OSError):
        return False


@app.get("/health")
async def health() -> dict:
    vllm_ok = await _backend_health(settings.vllm_api_base)
    return {
        "status": "ok" if vllm_ok else "degraded",
        "service": "llm-serving",
        "vllm": "ok" if vllm_ok else "unavailable",
    }


@app.get("/v1/models", response_model=ModelListResponse)
async def models() -> ModelListResponse:
    return ModelListResponse(data=[ModelInfo(id=settings.default_model)])


async def _stream_openai(stream: AsyncIterator) -> AsyncIterator[str]:
    async for chunk in stream:
        yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    model = request.model or settings.default_model
    messages = [{"role": message.role, "content": message.content} for message in request.messages]
    try:
        litellm_model, api_base, api_key = resolve_litellm_target(model)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        completion = await acompletion(
            model=litellm_model,
            messages=messages,
            api_base=api_base,
            api_key=api_key,
            timeout=settings.request_timeout,
            stream=request.stream,
        )
        if request.stream:
            return StreamingResponse(_stream_openai(completion), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM service unavailable: {exc}") from exc
    # LiteLLM returns OpenAI-compatible response objects; expose the caller's model alias.
    result = completion.model_dump(exclude_none=True)
    result["model"] = model
    return result
