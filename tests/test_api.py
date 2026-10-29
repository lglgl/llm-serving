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
