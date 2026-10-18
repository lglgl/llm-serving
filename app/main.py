
import json
import logging
import time
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

from app.config import settings
from app.models import ChatRequest, ModelInfo, ModelListResponse
from app.llama_client import LlamaClient
from app.metrics.http_metrics import setup_http_metrics
from app.metrics.llm_metrics import (
    LLM_GENERATION_DURATION,
    LLM_IN_PROGRESS,
    LLM_INTER_CHUNK_INTERVAL,
    LLM_OUTPUT_TOKENS_PER_SECOND,
    LLM_QUEUE_WAIT,
    LLM_REQUEST_DURATION,
    LLM_REQUESTS,
    LLM_REQUEST_TIMEOUTS,
    LLM_STREAM_INTERRUPTED,
    LLM_TPOT,
    LLM_TTFT,
    extract_usage,
    metric_model,
    record_usage,
)
from app.langfuse_tracing import (
    shutdown_langfuse,
    trace_error,
    trace_generation,
    trace_output,
)


logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Serving API", version="0.1.0")
app.add_event_handler("shutdown", shutdown_langfuse)

# HTTP 指标模块负责 /metrics、HTTP 请求指标和并发中间件。
setup_http_metrics(app)


llama = LlamaClient()
_MODEL_SLOTS = asyncio.Semaphore(settings.llama_parallel_slots)


class LLMQueueTimeout(TimeoutError):
    """FastAPI 等待可用模型槽位超时。"""


@asynccontextmanager
async def _model_slot(model: str, stream: bool):
    """测量 FastAPI 侧模型槽位等待时间，并限制排队后进入后端的请求数。"""
    label_model = metric_model(model)
    stream_label = str(stream).lower()
    queued_at = time.perf_counter()
    try:
        await asyncio.wait_for(
            _MODEL_SLOTS.acquire(),
            timeout=settings.llm_queue_timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        LLM_QUEUE_WAIT.labels(
            model=label_model,
            stream=stream_label,
        ).observe(time.perf_counter() - queued_at)
        LLM_REQUEST_TIMEOUTS.labels(
            model=label_model,
            stream=stream_label,
            stage="queue",
        ).inc()
        raise LLMQueueTimeout from exc

    LLM_QUEUE_WAIT.labels(
        model=label_model,
        stream=stream_label,
    ).observe(time.perf_counter() - queued_at)
    try:
        yield
    finally:
        _MODEL_SLOTS.release()


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


def _stream_error_event(message: str) -> str:
    event = {"error": {"message": message, "type": "server_error"}}
    return f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n"


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
    generated_parts: list[str] = []

    LLM_IN_PROGRESS.labels(
        model=label_model,
        stream=stream_label,
    ).inc()

    logger.info(
        "LLM stream started request_id=%s model=%s",
        request_id,
        model,
    )

    with trace_generation(
        model=model,
        request_id=request_id,
        stream=True,
        messages=messages,
    ) as generation:
        try:
            async with _model_slot(model, stream=True):
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

                    # 首个内容块用于 TTFT，后续块间隔作为 ITL 的近似值。
                    choices = data.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            generated_parts.append(content)
                            now = time.perf_counter()
                            if first_content_at is None:
                                first_content_at = now
                                LLM_TTFT.labels(
                                    model=label_model,
                                    stream=stream_label,
                                ).observe(now - started)
                            elif last_content_at is not None:
                                LLM_INTER_CHUNK_INTERVAL.labels(
                                    model=label_model,
                                    stream=stream_label,
                                ).observe(now - last_content_at)
                            last_content_at = now

                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            status = "error"
            LLM_STREAM_INTERRUPTED.labels(model=label_model).inc()
            trace_error(generation, "streaming request cancelled by client")
            raise
        except LLMQueueTimeout:
            status = "error"
            trace_error(generation, "timed out waiting for a model slot")
            yield _stream_error_event("LLM request timed out waiting for capacity")
        except httpx.TimeoutException:
            status = "error"
            LLM_REQUEST_TIMEOUTS.labels(
                model=label_model,
                stream=stream_label,
                stage="backend",
            ).inc()
            trace_error(generation, "llama.cpp streaming request timed out")
            logger.exception(
                "LLM streaming request timed out request_id=%s model=%s",
                request_id,
                model,
            )
            yield _stream_error_event("LLM streaming request timed out")
        except Exception:
            status = "error"
            trace_error(generation, "llama.cpp streaming request failed")
            logger.exception(
                "LLM streaming request failed request_id=%s model=%s",
                request_id,
                model,
            )

            yield _stream_error_event("LLM streaming request failed")

        finally:
            trace_output(generation, "".join(generated_parts), usage)
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
                    stream=stream_label,
                ).observe(generation_duration)

                if usage is not None:
                    output_tokens = usage[1]

                    if output_tokens > 0 and generation_duration > 0:
                        LLM_OUTPUT_TOKENS_PER_SECOND.labels(
                            model=label_model,
                            stream=stream_label,
                        ).observe(output_tokens / generation_duration)

                    # TPOT 以首 Token 之后的输出 Token 数作为分母。
                    if output_tokens > 1 and generation_duration > 0:
                        LLM_TPOT.labels(
                            model=label_model,
                            stream=stream_label,
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

    with trace_generation(
        model=model,
        request_id=request_id,
        stream=False,
        messages=messages,
    ) as generation:
        try:
            async with _model_slot(model, stream=False):
                result = await llama.chat(model=model, messages=messages)

            usage = extract_usage(result)
            record_usage(model, usage, stream=False)
            choices = result.get("choices") or []
            output = None
            if choices:
                output = (choices[0].get("message") or {}).get("content")
            trace_output(generation, output, usage)

            LLM_REQUESTS.labels(
                model=label_model,
                status="success",
                stream=stream_label,
            ).inc()

            return JSONResponse(
                content=jsonable_encoder(result),
                headers={"X-Request-ID": request_id},
            )

        except httpx.TimeoutException as exc:
            LLM_REQUEST_TIMEOUTS.labels(
                model=label_model,
                stream=stream_label,
                stage="backend",
            ).inc()
            trace_error(generation, "llama.cpp chat request timed out")
            LLM_REQUESTS.labels(
                model=label_model,
                status="error",
                stream=stream_label,
            ).inc()
            logger.exception(
                "LLM chat request timed out request_id=%s model=%s",
                request_id,
                model,
            )
            raise HTTPException(
                status_code=503,
                detail="LLM service unavailable",
            ) from exc
        except Exception as exc:
            trace_error(generation, "llama.cpp chat request failed")
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
