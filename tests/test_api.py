from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint(monkeypatch):
    async def mock_health():
        return True
    monkeypatch.setattr("app.main.ollama.health", mock_health)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_endpoint_degraded(monkeypatch):
    # Ollama 不可用时，/health 应返回 503，
    # 使 Kubernetes 就绪探针将 Pod 从 Service 后端摘除（fail-closed）。
    async def mock_health():
        return False
    monkeypatch.setattr("app.main.ollama.health", mock_health)
    response = client.get("/health")
    assert response.status_code == 503


def test_models_endpoint(monkeypatch):
    async def mock_list_models():
        return {"models": [{"name": "qwen2:0.5b"}]}
    monkeypatch.setattr("app.main.ollama.list_models", mock_list_models)
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "qwen2:0.5b"


def test_chat_endpoint(monkeypatch):
    async def mock_chat(model, messages):
        return {"message": {"role": "assistant", "content": "Hello from test."}, "prompt_eval_count": 10, "eval_count": 5}
    monkeypatch.setattr("app.main.ollama.chat", mock_chat)
    response = client.post("/v1/chat/completions", json={"model": "qwen2:0.5b", "messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "qwen2:0.5b"
    assert data["choices"][0]["message"]["content"] == "Hello from test."
    assert data["usage"]["total_tokens"] == 15
