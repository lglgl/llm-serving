import requests
import sys
import time


BASE_URL = "http://localhost:8000"
MODEL = "qwen2:0.5b"


def chat(message: str):
    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": message,
                }
            ],
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    print(data["choices"][0]["message"]["content"])


def stream_chat(message: str):
    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": message,
                }
            ],
            "stream": True,
        },
        stream=True,
        timeout=120,
    )

    response.raise_for_status()

    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            data = line[6:]

            if data == "[DONE]":
                break

            import json

            chunk = json.loads(data)
            content = chunk["choices"][0].get("delta", {}).get("content", "")

            if content:
                print(content, end="", flush=True)

    print()


if __name__ == "__main__":
    message = " ".join(sys.argv[1:]) or "Explain Kubernetes in 100 words."

    print("=== Normal Request ===")
    chat(message)

    print("\n=== Streaming Request ===")
    stream_chat(message)