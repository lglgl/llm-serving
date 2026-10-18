# LLM Serving

基于 FastAPI 与 llama.cpp 的 OpenAI-compatible 推理服务，默认运行 Qwen2 0.5B GGUF 模型。仓库包含应用 API、容器构建、Helm Chart、性能指标和 Grafana Dashboard。Prometheus、Grafana、Loki、Alloy 与 Tempo 属于共享平台设施，由 [`devops-platform`](../devops-platform/README.md) 管理；本项目不再启动独立 Prometheus 或 Grafana。

## 架构与边界

```text
客户端 -> FastAPI :8000 -> llama.cpp OpenAI API :8080 -> Qwen2 GGUF
                  |                         |
                  +------ /metrics ---------+  Prometheus 原生指标
                           ServiceMonitor -> 平台 Prometheus -> Grafana
```

FastAPI 负责 OpenAI-compatible API、并发槽位、HTTP 与请求级 LLM 指标，以及可选 Langfuse generation tracing。llama.cpp 负责模型推理，并通过原生 `/metrics` 暴露后端资源和推理计数器。两类指标不要混淆：请求延迟、TTFT、排队和 API 错误由 FastAPI 记录；Prompt/生成 Token 计数与处理速率优先使用 llama.cpp 原生指标。

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 检查 API 与 llama.cpp 后端连通性；后端不可用时返回 503 |
| `GET /v1/models` | 返回后端可用模型 |
| `POST /v1/chat/completions` | OpenAI-compatible 聊天补全，支持 SSE 流式响应 |
| `GET /metrics` | FastAPI HTTP 与 LLM Prometheus 指标 |
| llama.cpp `GET /metrics` | 后端原生指标；Compose 宿主机端口为 8081 |

## Docker Compose 本地运行

默认 API 地址为 `http://127.0.0.1:8000`，llama.cpp 映射到宿主机 `8081`。`llama/Dockerfile` 在构建阶段从 Hugging Face 下载 Qwen2 0.5B GGUF，因此首次构建需要网络连接，模型会打包进 llama.cpp 镜像；模型权重不纳入 Git。

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api llm-serving-llama
```

Compose 会等待 llama.cpp 健康检查通过后再启动 API。并发槽位默认 4；API 的 `LLAMA_PARALLEL_SLOTS` 和 llama.cpp `--parallel` 使用同一配置，修改时保持一致。

若宿主机 `8000` 被占用：

```bash
API_HOST_PORT=8002 docker compose up --build -d
curl -fsS http://127.0.0.1:8002/health
```

停止 Compose 服务：

```bash
docker compose down
```

### API 快速验证

非流式请求：

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2:0.5b","messages":[{"role":"user","content":"Reply with OK"}],"stream":false}'
```

流式请求：

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen2:0.5b","messages":[{"role":"user","content":"Reply with OK"}],"stream":true}'
```

检查 FastAPI 指标：

```bash
curl -fsS http://127.0.0.1:8000/metrics
curl -fsS http://127.0.0.1:8081/metrics
```

## Metrics 与 Dashboard

HTTP 指标由 `app/metrics/http_metrics.py` 管理，包括请求总数、请求耗时、状态码和并发请求。LLM 指标由 `app/metrics/llm_metrics.py` 管理，包括按模型/流式状态区分的请求数、端到端耗时、正在处理请求、FastAPI 槽位排队时间、超时、流式中断、TTFT、TPOT、输出 Token/s 和 SSE 内容块间隔。

当前 Dashboard 保留 8 个性能面板，不显示错误率、超时或流式中断：

| 面板 | 优先指标来源 |
| --- | --- |
| TTFT、ITL 近似值、E2E、FastAPI 槽位排队 | FastAPI Histogram |
| TPOT | llama.cpp 原生服务级平均值，并显示 FastAPI 单请求 P50/P95 |
| 单请求与聚合 Output Tokens/s | FastAPI 单请求分布 + llama.cpp 原生聚合 Counter |
| Prompt Processing Throughput | llama.cpp 原生 Gauge + Prompt Token Counter 速率 |
| 后端并发与排队深度 | llama.cpp 原生 `requests_processing` / `requests_deferred` |

TTFT 从 API 收到请求到首个非空内容块；TPOT 原生值是服务级按 Token 加权平均，FastAPI 单请求值依赖后端返回的 Token usage；ITL 是相邻 SSE 非空内容块间隔的近似值，内容块未必与单个 Token 一一对应。PromQL 及每项口径说明见 [指标查询文档](docs/observability/promql.md)。

Kubernetes 安装时，Chart 会创建 API 与 llama.cpp ServiceMonitor，并可发布 LLM Dashboard ConfigMap：

- Dashboard 源文件：`k8s/dashboards/llm-serving-performance.json`
- ServiceMonitor：`k8s/templates/servicemonitor.yaml`、`k8s/templates/llama-servicemonitor.yaml`
- Prometheus 和 Grafana 平台配置：`k8s/values.yaml` 下的 `monitoring`

平台 Prometheus 必须允许跨 Namespace 发现应用 ServiceMonitor，并发现 `release` 标签；平台 Grafana Dashboard sidecar 必须跨 Namespace 发现带 `grafana_dashboard: "1"` 标签的 ConfigMap。默认设置指向 `observability` Namespace 与 `kube-prometheus-stack` Release。部署后在 Prometheus Targets 确认两个目标均为 `UP`，然后在 Grafana 检查 LLM Serving Dashboard。更完整的接入步骤及 Docker 开发抓取配置见 [devops-platform 说明](../devops-platform/README.md#应用接入观测平台)。

如果当前运行的是 Docker Compose，应从 `devops-platform` 仓库运行 `observability/kube-prometheus-stack/sync-llm-serving-dashboard.sh`，将此处的 JSON 发布为 Grafana sidecar 可发现的 ConfigMap；该操作只同步 Dashboard，不会安装 Kubernetes 推理工作负载。

Docker Compose 实例的集群抓取清单在平台仓库，目标是 Docker Desktop host gateway `192.168.65.254` 的 API `8002` 和 llama.cpp `8081`。要先以 `API_HOST_PORT=8002` 启动 Compose；本机开发抓取和 Kubernetes ServiceMonitor 只选择其一，避免重复采集同一实例。

## Kubernetes 部署

Chart 位于 `k8s/`。默认镜像地址为本地 Harbor 示例 `harbor.local:30080/library/`；先构建并推送 API 与 llama.cpp 镜像，按目标集群修改 `k8s/values.yaml` 中的镜像仓库、标签、模型配置和资源限制，再安装：

```bash
docker login harbor.local:30080
docker build -t harbor.local:30080/library/llm-serving:latest -f Dockerfile .
docker build -t harbor.local:30080/library/llm-serving-llama:latest -f llama/Dockerfile llama
docker push harbor.local:30080/library/llm-serving:latest
docker push harbor.local:30080/library/llm-serving-llama:latest

helm upgrade --install llm-serving ./k8s \
  --namespace llm-serving \
  --create-namespace \
  --values k8s/values.yaml
```

在发布前确认目标集群能拉取镜像、GGUF 模型可由 llama.cpp 镜像提供，并按平台 NetworkPolicy 配置允许 FastAPI 到 llama.cpp、Prometheus 到两个 metrics Service 的流量。检查发布状态：

Chart 的 namespaced 资源使用 Helm 的 `--namespace` 作为唯一 Namespace 来源；正常安装时 Chart 不创建或接管 Namespace。上面的 `--create-namespace` 仅在本地首次安装时创建目标 Namespace。Jenkins CD 会在创建 Harbor Pull Secret 前先创建 Namespace。Jenkins 还会检测旧 Helm 清单是否曾管理 Namespace；若是，会先执行带 `helm.sh/resource-policy: keep` 的迁移升级，再执行常规升级，避免 Helm 删除 Namespace 及其中其他应用资源。手动升级这类旧 Release 时，也必须先执行一次带 `--set namespaceMigration.keepLegacyResource=true` 的 `helm upgrade`，然后再执行不带该参数的常规升级。

Chart 创建的 Ingress 通过 `/llm-serving/` 暴露 API，并在转发时去掉此前缀。例如 `/llm-serving/v1/chat/completions` 会转发为 FastAPI 路由 `/v1/chat/completions`。平台 Ingress Controller 的 Namespace 默认设为 `ingress`，可通过 `k8s/values.yaml` 的 `ingress.namespace` 调整；它必须与 NetworkPolicy 放行的 Namespace 一致。

```bash
kubectl get pods,svc,servicemonitor -n llm-serving
kubectl rollout status deployment/llm-serving -n llm-serving
kubectl rollout status deployment/llm-serving-llama -n llm-serving
```

Chart 不包含 Prometheus 或 Grafana 本体；部署到已有平台时由平台发现应用 ServiceMonitor 和 Dashboard ConfigMap。卸载应用：

```bash
helm uninstall llm-serving -n llm-serving
```

## Langfuse（可选）

配置 Langfuse 公钥、私钥后，应用为每次聊天请求记录 generation、模型、请求 ID、流式状态、Token 用量和结果。密钥未配置时追踪关闭，不影响推理。项目默认可以记录 Prompt/Response；生产或敏感数据场景应先评估内容采集策略，必要时设置 `LANGFUSE_CAPTURE_CONTENT=false`。

下面的 `.env` 和 Compose 示例适用于本地开发。当前 Helm Chart 尚未将 Langfuse 密钥或配置注入 Kubernetes Deployment；集群启用前需扩展 Chart，以 Kubernetes Secret 安全注入配置，不能把密钥直接写进 ConfigMap 或提交到 `values.yaml`。

`.env` 示例（不要提交真实密钥）：

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_CAPTURE_CONTENT=false
```

重建 API 容器以载入配置：

```bash
docker compose up --build -d api
```

## 本地 Python 开发

先启动可访问的 llama.cpp OpenAI-compatible 服务，并设置 `LLAMA_BASE_URL`（默认 `http://127.0.0.1:8081/v1`）：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 压测与回归工具

`tests/load_metrics.py` 用于制造有足够样本的指标流量；端口需匹配当前 API：

```bash
BASE_URL=http://127.0.0.1:8000 python tests/load_metrics.py --duration 120 --concurrency 8
```

`scripts/benchmark.py` 是基准请求工具，`scripts/client.py` 是交互/请求客户端。API 测试位于 `tests/test_api.py`。这些命令说明如何运行工具；具体验收应按所需测试计划单独执行。

## 文件结构

```text
app/
  main.py                 FastAPI 路由、并发控制和模型请求生命周期
  llama_client.py         llama.cpp HTTP 客户端
  langfuse_tracing.py     可选 Langfuse generation tracing
  metrics/                HTTP 与 LLM Prometheus 指标定义
  models.py               API 请求/响应模型
compose.yaml              本地 API + llama.cpp 开发环境
llama/Dockerfile          构建带模型服务的 llama.cpp 镜像
k8s/                      Helm Chart、ServiceMonitor、Dashboard
docs/observability/        PromQL 查询与指标口径
scripts/                  基准和客户端工具
tests/                    API 测试与压测流量工具
Jenkinsfile.ci            CI 构建/检查流水线
Jenkinsfile.cd            Kubernetes Helm 发布流水线
```
