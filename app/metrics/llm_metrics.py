"""LLM 推理指标及其记录辅助函数。"""

from prometheus_client import Counter, Gauge, Histogram

from app.config import settings

# 将非默认模型归并为 other，避免任意模型名造成时序数量失控。
def metric_model(model: str) -> str:
    return model if model == settings.default_model else "other"


# LLM 请求总数按模型、结果和是否流式区分。
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
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300),
)
LLM_QUEUE_WAIT = Histogram(
    "llm_queue_wait_seconds",
    "Time spent waiting for an application model slot",
    ["model", "stream"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
LLM_INPUT_TOKENS = Counter(
    "llm_input_tokens",
    "Total input tokens reported by the model backend",
    ["model", "stream"],
)
LLM_OUTPUT_TOKENS = Counter(
    "llm_output_tokens",
    "Total output tokens reported by the model backend",
    ["model", "stream"],
)
LLM_TOKEN_USAGE_MISSING = Counter(
    "llm_token_usage_missing",
    "LLM requests without usable token usage information",
    ["model", "stream"],
)
LLM_TTFT = Histogram(
    "llm_ttft_seconds",
    "Time from request start to first non-empty generated content",
    ["model", "stream"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120),
)
LLM_INTER_CHUNK_INTERVAL = Histogram(
    "llm_inter_chunk_interval_seconds",
    "Interval between non-empty streaming content chunks; an approximation of ITL",
    ["model", "stream"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
LLM_GENERATION_DURATION = Histogram(
    "llm_generation_duration_seconds",
    "Time between first and last non-empty generated content",
    ["model", "stream"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
LLM_TPOT = Histogram(
    "llm_tpot_seconds",
    "Average time per output token after the first token",
    ["model", "stream"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
)
LLM_REQUEST_TIMEOUTS = Counter(
    "llm_request_timeouts",
    "LLM requests that timed out, grouped by timeout stage",
    ["model", "stream", "stage"],
)
LLM_STREAM_INTERRUPTED = Counter(
    "llm_stream_interrupted",
    "Streaming requests cancelled before normal completion",
    ["model"],
)
LLM_OUTPUT_TOKENS_PER_SECOND = Histogram(
    "llm_output_tokens_per_second",
    "Output tokens per second for an individual streaming request",
    ["model", "stream"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 40, 80, 160),
)


# 预初始化默认模型的 Counter 和 Gauge 标签组合。
# 这样还没有错误或 Token 缺失时也会显示 0，而不是整条时间序列都不存在。
for _stream in ("false", "true"):
    LLM_IN_PROGRESS.labels(model=settings.default_model, stream=_stream).set(0)
    LLM_INPUT_TOKENS.labels(model=settings.default_model, stream=_stream).inc(0)
    LLM_OUTPUT_TOKENS.labels(model=settings.default_model, stream=_stream).inc(0)
    LLM_TOKEN_USAGE_MISSING.labels(model=settings.default_model, stream=_stream).inc(0)
    for _status in ("success", "error"):
        LLM_REQUESTS.labels(
            model=settings.default_model,
            status=_status,
            stream=_stream,
        ).inc(0)


def get_field(value, name, default=None):
    """兼容从字典或具有属性的响应对象读取字段。"""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def extract_usage(value) -> tuple[int, int] | None:
    """读取后端返回的 Token 用量；无效或缺失时不伪造数据。"""
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


def record_usage(model: str, usage: tuple[int, int] | None, stream: bool) -> None:
    """记录输入和输出 Token；缺少 usage 时单独计数。"""
    label_model = metric_model(model)
    if usage is None:
        LLM_TOKEN_USAGE_MISSING.labels(
            model=label_model,
            stream=str(stream).lower(),
        ).inc()
        return

    input_tokens, output_tokens = usage
    stream_label = str(stream).lower()
    LLM_INPUT_TOKENS.labels(model=label_model, stream=stream_label).inc(input_tokens)
    LLM_OUTPUT_TOKENS.labels(model=label_model, stream=stream_label).inc(output_tokens)
