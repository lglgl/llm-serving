import json
import time
import requests


BASE_URL = "http://localhost:8000"
MODEL = "qwen2:0.5b"


def benchmark(prompt: str):
    start_time = time.perf_counter()
    first_token_time = None
    end_time = None

    output_tokens = 0
    content = []

    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": True,
        },
        stream=True,
        timeout=120,
    )

    response.raise_for_status()

    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue

        data = line[6:]

        if data == "[DONE]":
            end_time = time.perf_counter()
            break

        chunk = json.loads(data)

        delta = chunk["choices"][0].get("delta", {})
        text = delta.get("content", "")

        if text:
            if first_token_time is None:
                first_token_time = time.perf_counter()

            content.append(text)

            # 简单 Token 估算
            output_tokens += len(text)

    if end_time is None:
        end_time = time.perf_counter()

    if first_token_time is None:
        raise RuntimeError("No token received")

    ttft = first_token_time - start_time
    latency = end_time - start_time
    generation_time = end_time - first_token_time

    tokens_per_second = (
        output_tokens / generation_time
        if generation_time > 0
        else 0
    )

    print()
    print("===== LLM Benchmark =====")
    print(f"TTFT:          {ttft:.3f} s")
    print(f"Latency:       {latency:.3f} s")
    print(f"Output Tokens: {output_tokens}")
    print(f"Tokens/s:      {tokens_per_second:.2f}")
    print("==========================")
    print()
    print("Response:")
    print("".join(content))


if __name__ == "__main__":
    benchmark(
        "Explain Kubernetes architecture and its main components "
        "in approximately 300 words."
    )