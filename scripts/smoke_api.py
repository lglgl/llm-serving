"""Small HTTP smoke check for the gateway, run from the host against a port-forward or container port."""
from __future__ import annotations

import json
import http.client
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


base = sys.argv[1].rstrip("/")
for attempt in range(30):
    try:
        with urlopen(f"{base}/readyz", timeout=3) as response:
            assert response.status == 200
            assert json.load(response)["status"] == "ready"
        break
    except (URLError, http.client.HTTPException, OSError, TimeoutError, AssertionError):
        if attempt == 29:
            raise
        time.sleep(2)

with urlopen(f"{base}/health", timeout=3) as response:
    health = json.load(response)
assert response.status == 200 and health["status"] == "ok", health

with urlopen(f"{base}/v1/models", timeout=3) as response:
    models = json.load(response)
assert response.status == 200 and models["data"][0]["id"] == "qwen3:8b", models

request = Request(
    f"{base}/v1/chat/completions",
    data=json.dumps({"model": "qwen3:8b", "messages": [{"role": "user", "content": "Reply briefly"}]}).encode(),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=30) as response:
    payload = json.load(response)
assert response.status == 200
assert payload["choices"][0]["message"]["content"] == "CI/CD pilot mock response", payload
print("smoke=passed readiness=ready model=qwen3:8b chat=mock-response")
