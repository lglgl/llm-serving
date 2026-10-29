# LLM Serving with LiteLLM

基于 FastAPI + LiteLLM + vLLM 的 OpenAI-compatible 模型服务。

## Architecture

```text
Client -> FastAPI -> LiteLLM -> vLLM -> GPU model
```

默认客户端模型名 `qwen3:8b` 路由到 vLLM。

## Start the inference backends

### vLLM

在支持的 NVIDIA GPU 环境启动 OpenAI-compatible API：

```bash
vllm serve Qwen/Qwen3-8B --served-model-name Qwen/Qwen3-8B --port 8001
```

默认监听 `http://localhost:8001/v1`，与 FastAPI 的 8000 端口区分开。如果 vLLM 配置了 API key，设置 `VLLM_API_KEY`。

## Start the API

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Configuration

| Variable | Default | Description |
|---|---|---|
| `VLLM_API_BASE` | `http://localhost:8001/v1` | vLLM OpenAI API base |
| `VLLM_API_KEY` | empty | Optional vLLM key |
| `VLLM_MODEL` | `Qwen/Qwen3-8B` | Model name served by vLLM |
| `DEFAULT_MODEL` | `qwen3:8b` | Public alias routed to vLLM |
| `REQUEST_TIMEOUT` | `300` | Upstream request timeout in seconds |

### Use the APIs

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

请求使用默认模型别名 `qwen3:8b`：

```bash
curl http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"Explain Kubernetes Deployment."}]}'
```

## Docker

```bash
docker build -t llm-serving:0.2.0 .
docker run --rm -p 8000:8000 \
  -e VLLM_API_BASE=http://host.docker.internal:8001/v1 \
  llm-serving:0.2.0
```

The vLLM inference server runs separately from this API container. Set its URL to an address reachable from the container.

## Tests and benchmark

```bash
pytest -v
python scripts/benchmark.py
```

Benchmark requests use the default model alias (`qwen3:8b`), which routes to vLLM.

## Change log

See [CHANGELOG.md](CHANGELOG.md) for the recorded architecture and API changes.

## CI/CD 小范围试点

首轮试点用 `pilot/mock_vllm.py` 模拟 OpenAI-compatible 推理后端，验证网关测试、镜像构建、扫描、请求转发和 Kubernetes Helm 发布/回滚。它不包含真实模型权重或 GPU 推理。

本地执行：

```bash
bash scripts/ci-pilot.sh
bash scripts/cd-pilot.sh <gateway-image-tag> <mock-image-tag>
```

详细方案、逐步过程、故障和边界记录见 [`docs/ci-cd-pilot-2026-10-29.md`](docs/ci-cd-pilot-2026-10-29.md)。
