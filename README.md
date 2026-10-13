# LLM Serving

基于 FastAPI + llama.cpp 的 OpenAI-compatible LLM Serving 实验。

## Architecture

```text
Client -> FastAPI -> llama.cpp API -> Qwen -> Apple Silicon
```

## Docker Compose

```bash
docker compose up --build -d
docker compose ps
```

Compose 会在同一个 Docker 网络中启动 FastAPI 和 llama.cpp。FastAPI 通过
`http://llm-serving-llama:8080/v1` 访问模型后端；只有 llama.cpp 健康检查通过后，
FastAPI 才会启动。llama.cpp 的 8080 端口映射到宿主机 8081，便于本地直接调试。
若宿主机的 8000 端口已被占用，可改用 `API_HOST_PORT=8002 docker compose up --build -d`，
并将下面示例中的 API 地址端口改为 8002。

停止服务：

```bash
docker compose down
```

API 指标和 Grafana PromQL 示例见 [LLM 指标查询](docs/observability/promql.md)。

## Langfuse Tracing

FastAPI 为每次聊天请求创建一个 Langfuse `generation`，记录模型、请求 ID、
流式状态、输入输出和 llama.cpp 返回的 Token 用量。API 当前没有独立的会话 ID，
因此不会人为生成 `session_id`。未配置 API Key 时追踪自动关闭，不影响推理服务。

在项目根目录的 `.env` 中配置 Langfuse 项目密钥和部署地址（不要提交 `.env`）：

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_CAPTURE_CONTENT=true
```

`LANGFUSE_CAPTURE_CONTENT=true` 会将用户消息和模型回复发送到 Langfuse，便于逐请求排查；
若内容包含敏感信息，请先配置脱敏，或设为 `false` 仅记录消息角色和长度、回复长度及 Token 用量。
设置后重建 API 容器：

```bash
docker compose up --build -d api
```

也可以在本地启动 FastAPI 前导出相同环境变量。Langfuse 的 API Key 可在项目设置中创建。

## Test

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2:0.5b","messages":[{"role":"user","content":"Explain Kubernetes Deployment."}]}'
```

## Streaming

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2:0.5b","messages":[{"role":"user","content":"Explain Kubernetes Scheduler."}],"stream":true}'
```

## Tests

```bash
pytest -v
```

## Benchmark

```bash
python scripts/benchmark.py
```

## Local Python Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

## Next Steps

- Kubernetes Deployment
- Helm Chart
- Prometheus
- OpenTelemetry
- Grafana
- Langfuse
- vLLM
- GPU inference
