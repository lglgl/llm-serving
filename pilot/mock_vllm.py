"""Deterministic OpenAI-compatible backend used only by the CI/CD pilot."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import time


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": "Qwen/Qwen3-8B", "object": "model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self._send(200, {
            "id": "chatcmpl-ci-pilot",
            "object": "chat.completion",
            "created": int(time()),
            "model": request.get("model", "Qwen/Qwen3-8B"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "CI/CD pilot mock response"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
        })

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
