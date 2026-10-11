
from fastapi.testclient import TestClient

from app.main import app


# 创建 FastAPI 测试客户端。
# TestClient 直接调用应用，不需要启动真实 HTTP 服务或模型容器。
client = TestClient(app)


def test_health_endpoint(monkeypatch):
    """测试后端正常时，健康检查返回 200。"""

    async def mock_health():
        # 模拟 llama.cpp 后端正常，避免测试依赖真实模型服务。
        return True

    monkeypatch.setattr("app.main.ollama.health", mock_health)

    response = client.get("/health")

    # 验收：接口返回成功，并标记服务状态为正常。
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["backend"] == "llama.cpp"


def test_health_endpoint_degraded(monkeypatch):
    """测试模型后端不可用时，健康检查返回 503。"""

    async def mock_health():
        # 模拟 llama.cpp 不可用。
        return False

    monkeypatch.setattr("app.main.ollama.health", mock_health)

    response = client.get("/health")

    # 验收：后端不可用时返回 503。
    # Kubernetes Readiness Probe 可据此将 Pod 从 Service 后端摘除。
    assert response.status_code == 503


def test_models_endpoint(monkeypatch):
    """测试模型列表接口返回 OpenAI 兼容的数据结构。"""

    async def mock_list_models():
        # 模拟 llama.cpp 的 /v1/models 响应格式。
        return {
            "object": "list",
            "data": [
                {
                    "id": "qwen2:0.5b",
                    "object": "model",
                }
            ],
        }

    monkeypatch.setattr(
        "app.main.ollama.list_models",
        mock_list_models,
    )

    response = client.get("/v1/models")

    # 验收：模型列表结构正确，模型 ID 能正常读取。
    assert response.status_code == 200
    assert response.json()["object"] == "list"
    assert response.json()["data"][0]["id"] == "qwen2:0.5b"


def test_chat_endpoint(monkeypatch):
    """测试非流式聊天接口正确返回 OpenAI 格式和 Token 用量。"""

    async def mock_chat(model, messages):
        # 模拟 llama.cpp 的 OpenAI Chat Completion 响应。
        # 注意：不再使用 Ollama 的 message、prompt_eval_count 等字段。
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

    monkeypatch.setattr(
        "app.main.ollama.chat",
        mock_chat,
    )

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

    # 验收：请求成功，响应符合 OpenAI Chat Completion 格式。
    assert response.status_code == 200

    data = response.json()

    assert data["object"] == "chat.completion"
    assert data["model"] == "qwen2:0.5b"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["message"]["content"] == "Hello from test."

    # Token 用量应由后端返回，并保留在最终响应中。
    assert data["usage"]["prompt_tokens"] == 10
    assert data["usage"]["completion_tokens"] == 5
    assert data["usage"]["total_tokens"] == 15
