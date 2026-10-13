"""Langfuse 追踪封装，避免把观测 SDK 耦合到 llama.cpp HTTP 客户端。"""

from contextlib import contextmanager
import logging
import os
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """只有配置了项目密钥时才初始化 Langfuse。"""
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
    )


def _capture_content() -> bool:
    return os.getenv("LANGFUSE_CAPTURE_CONTENT", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }


@contextmanager
def trace_generation(
    *,
    model: str,
    request_id: str,
    stream: bool,
    messages: list[dict[str, Any]],
) -> Iterator[Any | None]:
    """创建单次聊天请求的 generation；未配置密钥时透明关闭。"""
    if not _is_configured():
        yield None
        return

    try:
        from langfuse import get_client, propagate_attributes

        client = get_client()
        input_data: Any = messages
        if not _capture_content():
            input_data = {
                "messages": [
                    {
                        "role": message.get("role"),
                        "content_length": len(
                            str(message.get("content", ""))
                        ),
                    }
                    for message in messages
                ]
            }

        # 一次 API 调用就是一个 trace；单请求 API 不伪造会话 ID。
    except Exception:
        # 初始化失败时关闭追踪，不能影响模型请求。
        logger.exception("Langfuse tracing failed; continuing without tracing")
        yield None
        return

    emitted = False
    try:
        with propagate_attributes(
            trace_name="chat-completion",
            metadata={"request_id": request_id, "stream": stream},
            tags=["fastapi", "llama.cpp", "stream" if stream else "non-stream"],
        ):
            with client.start_as_current_observation(
                as_type="generation",
                name="llama.cpp chat completion",
                model=model,
                input=input_data,
            ) as generation:
                emitted = True
                yield generation
    except Exception:
        # 如果上下文在 yield 前初始化失败，可无追踪继续；业务异常照常抛出。
        if emitted:
            raise
        logger.exception("Langfuse observation could not be started")
        yield None


def shutdown_langfuse() -> None:
    """应用退出时刷新 SDK 队列，避免丢失尚未发送的 trace。"""
    if not _is_configured():
        return
    try:
        from langfuse import get_client

        get_client().shutdown()
    except Exception:
        logger.exception("Failed to shut down Langfuse client cleanly")


def trace_output(generation: Any | None, output: Any, usage: tuple[int, int] | None) -> None:
    """补齐 generation 输出及 llama.cpp 返回的 token 用量。"""
    if generation is None:
        return
    data: dict[str, Any] = {}
    if _capture_content():
        data["output"] = output
    else:
        data["output"] = {"content_length": len(output) if isinstance(output, str) else None}
    if usage is not None:
        data["usage_details"] = {"input": usage[0], "output": usage[1]}
    try:
        generation.update(**data)
    except Exception:
        logger.exception("Failed to add output details to Langfuse generation")


def trace_error(generation: Any | None, status: str) -> None:
    if generation is not None:
        try:
            generation.update(level="ERROR", status_message=status)
        except Exception:
            logger.exception("Failed to mark Langfuse generation as failed")
