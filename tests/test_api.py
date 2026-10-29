from fastapi.testclient import TestClient
from app.main import app
from types import SimpleNamespace

client = TestClient(app)


def test_health_endpoint(monkeypatch):
    async def mock_health(api_base):
        return True
    monkeypatch.setattr("app.main._backend_health", mock_health)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_endpoint(monkeypatch):
    async def mock_health(api_base):
        return True
    monkeypatch.setattr("app.main._backend_health", mock_health)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_fails_when_backend_is_unavailable(monkeypatch):
    async def mock_health(api_base):
        return False
    monkeypatch.setattr("app.main._backend_health", mock_health)
    response = client.get("/readyz")
    assert response.status_code == 503


def test_models_endpoint(monkeypatch):
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "qwen3:8b"


def test_chat_endpoint(monkeypatch):
    async def mock_completion(**kwargs):
        return SimpleNamespace(model_dump=lambda exclude_none=True: {
            "id": "chatcmpl-test", "object": "chat.completion", "model": kwargs["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from test."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })
    monkeypatch.setattr("app.main.acompletion", mock_completion)
    response = client.post("/v1/chat/completions", json={"model": "qwen3:8b", "messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "qwen3:8b"
    assert data["choices"][0]["message"]["content"] == "Hello from test."
    assert data["usage"]["total_tokens"] == 15


def test_unknown_model_is_rejected():
    response = client.post("/v1/chat/completions", json={
        "model": "unknown-model",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert response.status_code == 404


def test_chat_returns_503_when_backend_fails(monkeypatch):
    async def mock_completion(**kwargs):
        raise RuntimeError("test backend unavailable")
    monkeypatch.setattr("app.main.acompletion", mock_completion)
    response = client.post("/v1/chat/completions", json={
        "model": "qwen3:8b",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert response.status_code == 503


def test_streaming_chat_returns_server_sent_events(monkeypatch):
    async def mock_completion(**kwargs):
        async def chunks():
            yield SimpleNamespace(model_dump_json=lambda exclude_none=True: '{"choices":[{"delta":{"content":"Hello"}}]}')
        return chunks()
    monkeypatch.setattr("app.main.acompletion", mock_completion)
    response = client.post("/v1/chat/completions", json={
        "model": "qwen3:8b",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text
