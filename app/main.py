
import json
import logging
import time
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import settings
from app.models import ChatRequest, ModelInfo, ModelListResponse
from app.llama_client import LlamaClient


logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Serving API", version="0.1.0")

# 保留现有 HTTP 指标和 /metrics 端点。
Instrumentator().instrument(app).expose(
    app,
    endpoint="/metrics",
    include_in_schema=False,
)

# 当前只将默认模型作为独立指标标签，其他模型归为 other，
# 避免客户端传入任意 model 导致 Prometheus 时序数量失控。
def metric_model(model: str) -> str:
    return model if model == settings.default_model else "other"


# HTTP 并发数。Instrumentator 已经负责请求总数、状态和延迟。
HTTP_IN_PROGRESS = Gauge(
    "app_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
)


@app.middleware("http")
async def track_http_concurrency(request: Request, call_next):
    HTTP_IN_PROGRESS.inc()
    try:
        return await call_next(request)
    finally:
        HTTP_IN_PROGRESS.dec()


# LLM 指标与 Instrumentator 的 http_* 指标分开命名。
LLM_REQUESTS = Counter(
    "llm_requests",
    "Total LLM requests",
    ["model", "status", "stream"],
)

LLM_IN_PROGRESS = Gauge(
    "llm_requests_in_progress",
    "LLM requests currently being processed",
    ["model", "stream"],
)

LLM_REQUEST_DURATION = Histogram(
    "llm_request_duration_seconds",
    "End-to-end LLM request duration in seconds",
    ["model", "stream"],
)

LLM_INPUT_TOKENS = Counter(
    "llm_input_tokens",
    "Total input tokens reported by the model backend",
    ["model"],
)

LLM_OUTPUT_TOKENS = Counter(
    "llm_output_tokens",
    "Total output tokens reported by the model backend",
    ["model"],
)

LLM_TOKEN_USAGE_MISSING = Counter(
    "llm_token_usage_missing",
    "LLM requests without usable token usage information",
    ["model", "stream"],
)

LLM_TTFT = Histogram(
    "llm_ttft_seconds",
    "Time from request start to first non-empty generated content",
    ["model"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

LLM_GENERATION_DURATION = Histogram(
    "llm_generation_duration_seconds",
    "Time between first and last non-empty generated content",
    ["model"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

LLM_TPOT = Histogram(
    "llm_tpot_seconds",
    "Average time per output token after the first token",
    ["model"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
)

LLM_OUTPUT_TOKENS_PER_SECOND = Histogram(
    "llm_output_tokens_per_second",
    "Output tokens per second for an individual streaming request",
    ["model"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 40, 80, 160),
)

llama = LlamaClient()


def get_field(value, name, default=None):
    """兼容 dict 和具有属性的响应对象。"""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def extract_usage(value) -> tuple[int, int] | None:
    """
    读取 OpenAI-compatible usage。
    没有有效 usage 时返回 None，不伪造 Token 数。
    """
    usage = get_field(value, "usage")
    if usage is None:
        return None

    input_tokens = get_field(usage, "prompt_tokens")
    output_tokens = get_field(usage, "completion_tokens")

    if input_tokens is None or output_tokens is None:
        return None

    try:
        input_tokens = int(input_tokens)
        output_tokens = int(output_tokens)
    except (TypeError, ValueError):
        return None

    if input_tokens < 0 or output_tokens < 0:
        return None

    return input_tokens, output_tokens


def record_usage(model: str, usage: tuple[int, int] | None, stream: bool):
    label_model = metric_model(model)

    if usage is None:
        LLM_TOKEN_USAGE_MISSING.labels(
            model=label_model,
            stream=str(stream).lower(),
        ).inc()
        return

    input_tokens, output_tokens = usage

    LLM_INPUT_TOKENS.labels(model=label_model).inc(input_tokens)
    LLM_OUTPUT_TOKENS.labels(model=label_model).inc(output_tokens)


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
    request_id: str,
) -> AsyncIterator[str]:
    label_model = metric_model(model)
    stream_label = "true"

    started = time.perf_counter()
    first_content_at: float | None = None
    last_content_at: float | None = None
    usage: tuple[int, int] | None = None
    status = "success"

    LLM_IN_PROGRESS.labels(
        model=label_model,
        stream=stream_label,
    ).inc()

    logger.info(
        "LLM stream started request_id=%s model=%s",
        request_id,
        model,
    )

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
                logger.warning(
                    "Invalid SSE JSON request_id=%s",
                    request_id,
                )
                continue

            # 部分 OpenAI-compatible 后端会在最终 chunk 中返回 usage。
            chunk_usage = extract_usage(data)
            if chunk_usage is not None:
                usage = chunk_usage

            # chunk 不等于 Token。这里测量首个非空输出内容的到达时间。
            choices = data.get("choices") or []
            if choices:
                delta = choices[0].get("delta") or {}
                content = delta.get("content")

                if isinstance(content, str) and content:
                    now = time.perf_counter()

                    if first_content_at is None:
                        first_content_at = now
                        LLM_TTFT.labels(
                            model=label_model,
                        ).observe(now - started)

                    last_content_at = now

            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    except Exception:
        status = "error"
        logger.exception(
            "LLM streaming request failed request_id=%s model=%s",
            request_id,
            model,
        )

        error_event = {
            "error": {
                "message": "LLM streaming request failed",
                "type": "server_error",
            }
        }
        yield f"data: {json.dumps(error_event)}\n\n"
        yield "data: [DONE]\n\n"

    finally:
        ended = time.perf_counter()
        total_duration = ended - started

        LLM_REQUESTS.labels(
            model=label_model,
            status=status,
            stream=stream_label,
        ).inc()

        LLM_REQUEST_DURATION.labels(
            model=label_model,
            stream=stream_label,
        ).observe(total_duration)

        record_usage(model, usage, stream=True)

        if first_content_at is not None and last_content_at is not None:
            generation_duration = max(
                0.0,
                last_content_at - first_content_at,
            )

            LLM_GENERATION_DURATION.labels(
                model=label_model,
            ).observe(generation_duration)

            if usage is not None:
                output_tokens = usage[1]

                if output_tokens > 0 and generation_duration > 0:
                    LLM_OUTPUT_TOKENS_PER_SECOND.labels(
                        model=label_model,
                    ).observe(output_tokens / generation_duration)

                # TPOT 以首 Token 之后的输出 Token 数作为分母。
                if output_tokens > 1 and generation_duration > 0:
                    LLM_TPOT.labels(
                        model=label_model,
                    ).observe(
                        generation_duration / (output_tokens - 1)
                    )

        LLM_IN_PROGRESS.labels(
            model=label_model,
            stream=stream_label,
        ).dec()

        logger.info(
            "LLM stream finished request_id=%s model=%s status=%s "
            "duration_seconds=%.4f",
            request_id,
            model,
            status,
            total_duration,
        )


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest):
    model = request.model or settings.default_model
    request_id = str(uuid4())

    messages = [
        {
            "role": message.role,
            "content": message.content,
        }
        for message in request.messages
    ]

    if request.stream:
        return StreamingResponse(
            _stream_openai(model, messages, request_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Request-ID": request_id,
            },
        )

    label_model = metric_model(model)
    stream_label = "false"
    started = time.perf_counter()

    LLM_IN_PROGRESS.labels(
        model=label_model,
        stream=stream_label,
    ).inc()

    try:
        result = await llama.chat(model=model, messages=messages)

        usage = extract_usage(result)
        record_usage(model, usage, stream=False)

        LLM_REQUESTS.labels(
            model=label_model,
            status="success",
            stream=stream_label,
        ).inc()

        return JSONResponse(
            content=jsonable_encoder(result),
            headers={"X-Request-ID": request_id},
        )

    except Exception as exc:
        LLM_REQUESTS.labels(
            model=label_model,
            status="error",
            stream=stream_label,
        ).inc()

        logger.exception(
            "LLM chat request failed request_id=%s model=%s",
            request_id,
            model,
        )

        raise HTTPException(
            status_code=503,
            detail="LLM service unavailable",
        ) from exc

    finally:
        LLM_REQUEST_DURATION.labels(
            model=label_model,
            stream=stream_label,
        ).observe(time.perf_counter() - started)

        LLM_IN_PROGRESS.labels(
            model=label_model,
            stream=stream_label,
        ).dec()
