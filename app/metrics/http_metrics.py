"""FastAPI HTTP 通用指标。"""

from fastapi import FastAPI, Request
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator

# 当前正在处理的 HTTP 请求数，用于观察服务并发情况。
HTTP_IN_PROGRESS = Gauge(
    "app_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
)


async def track_http_concurrency(request: Request, call_next):
    """统计 HTTP 请求并发数，并确保请求结束后正确减一。"""
    HTTP_IN_PROGRESS.inc()
    try:
        return await call_next(request)
    finally:
        HTTP_IN_PROGRESS.dec()


def setup_http_metrics(app: FastAPI) -> None:
    """注册 HTTP 请求指标和 Prometheus /metrics 端点。"""
    Instrumentator().instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )
    app.middleware("http")(track_http_concurrency)
