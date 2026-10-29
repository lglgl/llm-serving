import asyncio
import statistics
import time
import httpx

API_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "qwen3:8b"
REQUESTS = 5


async def run_once(client: httpx.AsyncClient, index: int) -> float:
    payload = {"model": MODEL, "messages": [{"role": "user", "content": f"Explain Kubernetes Service in 100 words. Request {index}."}], "stream": False}
    start = time.perf_counter()
    response = await client.post(API_URL, json=payload, timeout=300.0)
    response.raise_for_status()
    return time.perf_counter() - start


async def main() -> None:
    latencies = []
    async with httpx.AsyncClient() as client:
        for index in range(1, REQUESTS + 1):
            try:
                latency = await run_once(client, index)
                latencies.append(latency)
                print(f"request={index} latency={latency * 1000:.2f} ms")
            except Exception as exc:
                print(f"request={index} error={exc}")
    if not latencies:
        print("No successful requests.")
        return
    print("\n=== Benchmark Result ===")
    print(f"Requests: {REQUESTS}")
    print(f"Success: {len(latencies)}")
    print(f"Average: {statistics.mean(latencies) * 1000:.2f} ms")
    print(f"P50: {statistics.median(latencies) * 1000:.2f} ms")
    print(f"Min: {min(latencies) * 1000:.2f} ms")
    print(f"Max: {max(latencies) * 1000:.2f} ms")


if __name__ == "__main__":
    asyncio.run(main())
