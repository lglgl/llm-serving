# LLM Serving

基于 FastAPI + Ollama 的 OpenAI-compatible LLM Serving 实验。

## Architecture

```text
Client -> FastAPI -> Ollama API -> Qwen -> Apple Silicon
```

## Start Ollama

```bash
ollama pull qwen3:8b
ollama run qwen3:8b
```

## Start API

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Test

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"Explain Kubernetes Deployment."}]}'
```

## Streaming

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"Explain Kubernetes Scheduler."}],"stream":true}'
```

## Tests

```bash
pytest -v
```

## Benchmark

```bash
python scripts/benchmark.py
```

## Docker

```bash
docker build -t llm-serving:0.1.0 .
docker run --rm -p 8000:8000 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  llm-serving:0.1.0
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
