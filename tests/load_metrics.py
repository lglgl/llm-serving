#!/usr/bin/env python3
"""对 FastAPI + llama.cpp 执行有限时长的并发压测并核对 Prometheus 指标。

用法：
  BASE_URL=http://127.0.0.1:8002 python tests/load_metrics.py
  python tests/load_metrics.py --duration 120 --concurrency 3 --stream-every 2

环境变量可使用 BASE_URL、DURATION_SECONDS、CONCURRENCY、REQUEST_TIMEOUT、
MODEL 和 STREAM_EVERY 设置默认值。默认运行 60 秒、并发 2，适合本地模型。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx

PROMPT = (
    "Explain in 3 short bullet points what Prometheus metrics are, "
    "and end with the word OK. Keep the answer under 80 words."
)

stats: Counter[str] = Counter()
latencies: dict[str, list[float]] = {"http": [], "chat": []}
ttft_samples: list[float] = []
errors: list[str] = []
request_id = 0
stop_at = 0.0


def parse_args() -> argparse.Namespace:
    """合并命令行参数与环境变量，便于本地和 CI 调整负载。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--duration", type=float, default=float(os.getenv("DURATION_SECONDS", "60")))
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("CONCURRENCY", "2")))
    parser.add_argument("--request-timeout", type=float, default=float(os.getenv("REQUEST_TIMEOUT", "120")))
    parser.add_argument("--model", default=os.getenv("MODEL", "qwen2:0.5b"))
    parser.add_argument("--stream-every", type=int, default=int(os.getenv("STREAM_EVERY", "2")))
    parser.add_argument("--health-every", type=int, default=17)
    parser.add_argument("--models-every", type=int, default=17)
    args = parser.parse_args()

    if args.duration <= 0 or args.request_timeout <= 0:
        parser.error("duration 和 request-timeout 必须大于 0")
    if args.concurrency < 1 or args.stream_every < 1:
        parser.error("concurrency 和 stream-every 必须至少为 1")
    if args.health_every < 0 or args.models_every < 0:
        parser.error("health-every 和 models-every 不能为负数")
    args.base_url = args.base_url.rstrip("/")
    return args


def percentile(values: list[float], q: float) -> float | None:
    """计算最近秩分位数。"""
    if not values:
        return None
    data = sorted(values)
    index = min(len(data) - 1, max(0, int(round((len(data) - 1) * q))))
    return data[index]


def note_error(where: str, message: str) -> None:
    """统计全部错误，只保留少量样例，避免压测输出被错误刷屏。"""
    stats[f"{where}_errors"] += 1
    if len(errors) < 8:
        errors.append(f"{where}: {message[:240]}")


async def get_next_request_id() -> int:
    global request_id
    request_id += 1
    return request_id


async def request_health(client: httpx.AsyncClient, base_url: str) -> None:
    started = time.perf_counter()
    try:
        response = await client.get(f"{base_url}/health", timeout=10)
        stats[f"health_status_{response.status_code}"] += 1
        stats["health_requests"] += 1
        if response.is_success:
            stats["health_ok"] += 1
        else:
            note_error("health", f"HTTP {response.status_code}: {response.text[:200]}")
    except httpx.HTTPError as exc:
        note_error("health", f"{type(exc).__name__}: {exc}")
    finally:
        latencies["http"].append(time.perf_counter() - started)


async def request_models(client: httpx.AsyncClient, base_url: str) -> None:
    started = time.perf_counter()
    try:
        response = await client.get(f"{base_url}/v1/models", timeout=15)
        stats[f"models_status_{response.status_code}"] += 1
        stats["models_requests"] += 1
        if response.is_success:
            stats["models_ok"] += 1
        else:
            note_error("models", f"HTTP {response.status_code}: {response.text[:200]}")
    except httpx.HTTPError as exc:
        note_error("models", f"{type(exc).__name__}: {exc}")
    finally:
        latencies["http"].append(time.perf_counter() - started)


async def request_chat(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    rid: int,
    stream: bool,
) -> None:
    url = f"{args.base_url}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [{
            "role": "user",
            "content": f"{PROMPT}\nTest request ID: {rid}",
        }],
        "stream": stream,
    }
    started = time.perf_counter()
    first_content_at: float | None = None
    response_bytes = 0
    mode = "stream" if stream else "nonstream"

    try:
        if not stream:
            response = await client.post(url, json=payload, timeout=args.request_timeout)
            stats[f"chat_nonstream_status_{response.status_code}"] += 1
            stats["chat_nonstream_requests"] += 1
            response_bytes = len(response.content)
            if response.is_success:
                stats["chat_nonstream_ok"] += 1
                body = response.json()
                record_usage(body.get("usage"))
            else:
                note_error("chat_nonstream", f"HTTP {response.status_code}: {response.text[:200]}")
        else:
            async with client.stream(
                "POST", url, json=payload, timeout=args.request_timeout
            ) as response:
                stats[f"chat_stream_status_{response.status_code}"] += 1
                stats["chat_stream_requests"] += 1
                if not response.is_success:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    note_error("chat_stream", f"HTTP {response.status_code}: {body[:200]}")
                else:
                    stats["chat_stream_ok"] += 1
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        response_bytes += len(line.encode("utf-8"))
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            stats["stream_done"] += 1
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        usage = chunk.get("usage")
                        if isinstance(usage, dict):
                            record_usage(usage)
                        for choice in chunk.get("choices") or []:
                            content = (choice.get("delta") or {}).get("content")
                            if content:
                                stats["stream_content_chunks"] += 1
                                if first_content_at is None:
                                    first_content_at = time.perf_counter()
                                    ttft_samples.append(first_content_at - started)

    except (httpx.HTTPError, ValueError, TypeError) as exc:
        note_error(f"chat_{mode}", f"{type(exc).__name__}: {exc}")
    finally:
        elapsed = time.perf_counter() - started
        latencies["chat"].append(elapsed)
        stats["chat_response_bytes"] += response_bytes
        stats["chat_total_latency_ms"] += int(elapsed * 1000)


def record_usage(usage: Any) -> None:
    """累加后端 usage，用于和 Prometheus Token Counter 对账。"""
    if not isinstance(usage, dict):
        return
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if isinstance(input_tokens, (int, float)):
        stats["client_input_tokens_reported"] += int(input_tokens)
    if isinstance(output_tokens, (int, float)):
        stats["client_output_tokens_reported"] += int(output_tokens)


def metric_total(metrics_text: str, metric_name: str) -> float:
    """从 Prometheus exposition 文本聚合指定 counter 或 histogram count。"""
    total = 0.0
    for line in metrics_text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        sample, _, raw_value = line.partition(" ")
        if sample == metric_name or sample.startswith(f"{metric_name}{{"):
            try:
                total += float(raw_value)
            except ValueError:
                pass
    return total


async def scrape_metrics(client: httpx.AsyncClient, base_url: str) -> str:
    response = await client.get(f"{base_url}/metrics", timeout=10)
    response.raise_for_status()
    return response.text


async def worker(worker_id: int, client: httpx.AsyncClient, args: argparse.Namespace) -> None:
    while time.monotonic() < stop_at:
        rid = await get_next_request_id()
        if args.health_every and rid % args.health_every == 0:
            await request_health(client, args.base_url)
        elif args.models_every and rid % args.models_every == 1:
            await request_models(client, args.base_url)
        else:
            await request_chat(client, args, rid, rid % args.stream_every == 0)
        await asyncio.sleep(0.05)


async def main() -> None:
    global stop_at
    args = parse_args()
    timeout = httpx.Timeout(args.request_timeout, connect=10.0)
    limits = httpx.Limits(
        max_connections=args.concurrency + 4,
        max_keepalive_connections=args.concurrency + 2,
    )
    print(f"Target: {args.base_url}")
    print(
        f"Duration: {args.duration:g}s; concurrency: {args.concurrency}; "
        f"model: {args.model}; stream every {args.stream_every} request(s)"
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=False) as client:
        # 后端未就绪时立即终止，避免把无效请求当作压测结果。
        response = await client.get(f"{args.base_url}/health", timeout=10)
        print(f"Initial /health: HTTP {response.status_code} {response.text[:160]}")
        response.raise_for_status()
        before_metrics = await scrape_metrics(client, args.base_url)

        started = time.perf_counter()
        stop_at = started + args.duration
        tasks = [
            asyncio.create_task(worker(index, client, args), name=f"load-worker-{index}")
            for index in range(args.concurrency)
        ]
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - started
        after_metrics = await scrape_metrics(client, args.base_url)

    print("\n========== CLIENT-SIDE LOAD SUMMARY ==========")
    print(f"Finished at: {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}")
    print(f"Elapsed: {elapsed:.1f}s; issued operations: {request_id}; throughput: {request_id / elapsed:.2f} ops/s")
    for key in sorted(stats):
        print(f"{key}: {stats[key]}")

    for kind, values in latencies.items():
        print(f"{kind} latency samples: {len(values)}")
        for name, quantile in [("P50", .50), ("P90", .90), ("P95", .95), ("P99", .99)]:
            value = percentile(values, quantile)
            if value is not None:
                print(f"{kind} latency {name}: {value:.3f}s")
    print(f"Streaming first-content samples: {len(ttft_samples)}")
    for name, quantile in [("P50", .50), ("P90", .90), ("P95", .95)]:
        value = percentile(ttft_samples, quantile)
        if value is not None:
            print(f"Client observed first-content {name}: {value:.3f}s")

    print("\n========== PROMETHEUS COUNTER DELTAS ==========")
    for metric in [
        "llm_requests_total",
        "llm_input_tokens_total",
        "llm_output_tokens_total",
        "llm_request_duration_seconds_count",
        "llm_ttft_seconds_count",
    ]:
        delta = metric_total(after_metrics, metric) - metric_total(before_metrics, metric)
        print(f"{metric}: +{delta:g}")

    if errors:
        print("\nError samples:")
        for error in errors:
            print(f"  {error}")
    print("\nPromQL: sum(rate(llm_requests_total[1m]))")
    print("PromQL: histogram_quantile(0.95, sum by (le) (rate(llm_ttft_seconds_bucket[5m])))")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
