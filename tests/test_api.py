from fastapi.testclient import TestClient

from app.main import app, llama


client = TestClient(app)


def test_health_endpoint(monkeypatch):
    """后端正常时，健康检查返回 200。"""

    async def mock_health():
        return True

    monkeypatch.setattr(llama, "health", mock_health)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["backend"] == "llama.cpp"


def test_health_endpoint_degraded(monkeypatch):
    """后端不可用时，健康检查返回 503。"""

    async def mock_health():
        return False

    monkeypatch.setattr(llama, "health", mock_health)

    response = client.get("/health")

    assert response.status_code == 503


def test_models_endpoint(monkeypatch):
    """模型列表接口返回 OpenAI 兼容的数据结构。"""

    async def mock_list_models():
        return {
            "object": "list",
            "data": [
                {
                    "id": "qwen2:0.5b",
                    "object": "model",
                }
            ],
        }

    monkeypatch.setattr(llama, "list_models", mock_list_models)

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json()["object"] == "list"
    assert response.json()["data"][0]["id"] == "qwen2:0.5b"


def test_chat_endpoint(monkeypatch):
    """非流式聊天接口返回 OpenAI 格式及 Token 用量。"""

    async def mock_chat(model, messages):
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello from test.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    monkeypatch.setattr(llama, "chat", mock_chat)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "qwen2:0.5b",
            "messages": [
                {
                    "role": "user",
                    "content": "Hello",
                }
            ],
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["object"] == "chat.completion"
    assert data["model"] == "qwen2:0.5b"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "Hello from test."

    assert data["usage"]["prompt_tokens"] == 10
    assert data["usage"]["completion_tokens"] == 5
    assert data["usage"]["total_tokens"] == 15