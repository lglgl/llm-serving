# LLM Serving

基于 FastAPI 与 llama.cpp 的 OpenAI-compatible 推理服务，默认运行 Qwen2 0.5B GGUF 模型。仓库包含应用 API、容器构建、Helm Chart、性能指标和 Grafana Dashboard。Prometheus、Grafana、Loki、Alloy 与 Tempo 属于共享平台设施，由 [`devops-platform`](../devops-platform/README.md) 管理；本项目不再启动独立 Prometheus 或 Grafana。

## 仓库结构

仓库按可独立构建、发布的组件划分。两个组件只通过 OpenAI-compatible HTTP 接口和模型别名约定通信，各自有独立的镜像标签和 Helm Release。

| 目录 | 组件 | 内容 |
| --- | --- | --- |
| `gateway/` | FastAPI 网关 | API、指标、Langfuse 追踪、单元测试、镜像 |
| `inference/` | 推理后端 | 引擎配置（`engines/llamacpp`、`engines/vllm-dtk`）、模型登记表 `models.yaml`、权重下载脚本；不含权重 |
| `bench/` | 实验工具 | 并发扫描、gateway 指标压测、客户端；结果写入 `bench/results/`（不纳入 Git） |
| `deploy/` | 部署 | `charts/gateway`、`charts/inference` 两个 Chart，共享模型配置 `values/model.yaml`，部署与迁移脚本 |

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

默认 API 地址为 `http://127.0.0.1:8000`，llama.cpp 映射到宿主机 `8081`。`inference/engines/llamacpp/Dockerfile` 在构建阶段从 Hugging Face 下载 Qwen2 0.5B GGUF，因此首次构建需要网络连接，模型会打包进 llama.cpp 镜像；模型权重不纳入 Git。

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api llm-serving-llama
```

Compose 会等待 llama.cpp 健康检查通过后再启动 API。并发槽位默认 4，模型别名默认 `qwen2:0.5b`；API 与 llama.cpp 分别从同一个 `LLAMA_PARALLEL_SLOTS`、`MODEL_ALIAS` 环境变量取值，无需分别修改。

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

HTTP 指标由 `gateway/app/metrics/http_metrics.py` 管理，包括请求总数、请求耗时、状态码和并发请求。LLM 指标由 `gateway/app/metrics/llm_metrics.py` 管理，包括按模型/流式状态区分的请求数、端到端耗时、正在处理请求、FastAPI 槽位排队时间、超时、流式中断、TTFT、TPOT、输出 Token/s 和 SSE 内容块间隔。

当前 Dashboard 保留 8 个性能面板，不显示错误率、超时或流式中断：

| 面板 | 优先指标来源 |
| --- | --- |
| TTFT、ITL 近似值、E2E、FastAPI 槽位排队 | FastAPI Histogram |
| TPOT | llama.cpp 原生服务级平均值，并显示 FastAPI 单请求 P50/P95 |
| 单请求与聚合 Output Tokens/s | FastAPI 单请求分布 + llama.cpp 原生聚合 Counter |
| Prompt Processing Throughput | llama.cpp 原生 Gauge + Prompt Token Counter 速率 |
| 后端并发与排队深度 | llama.cpp 原生 `requests_processing` / `requests_deferred` |

TTFT 从 API 收到请求到首个非空内容块；TPOT 原生值是服务级按 Token 加权平均，FastAPI 单请求值依赖后端返回的 Token usage；ITL 是相邻 SSE 非空内容块间隔的近似值，内容块未必与单个 Token 一一对应。PromQL 及每项口径说明见 [指标查询文档](docs/observability/promql.md)。

Kubernetes 安装时，两个 Chart 分别创建 API 与 llama.cpp ServiceMonitor，gateway Chart 可发布 LLM Dashboard ConfigMap：

- Dashboard 源文件：`deploy/charts/gateway/dashboards/llm-serving-performance.json`
- ServiceMonitor：`deploy/charts/gateway/templates/servicemonitor.yaml`、`deploy/charts/inference/templates/servicemonitor.yaml`
- Prometheus 和 Grafana 平台配置：两个 Chart `values.yaml` 下的 `monitoring`

平台 Prometheus 必须允许跨 Namespace 发现应用 ServiceMonitor，并发现 `release` 标签；平台 Grafana Dashboard sidecar 必须跨 Namespace 发现带 `grafana_dashboard: "1"` 标签的 ConfigMap。默认设置指向 `observability` Namespace 与 `kube-prometheus-stack` Release。部署后在 Prometheus Targets 确认两个目标均为 `UP`，然后在 Grafana 检查 LLM Serving Dashboard。更完整的接入步骤及 Docker 开发抓取配置见 [devops-platform 说明](../devops-platform/README.md#应用接入观测平台)。

如果当前运行的是 Docker Compose，应从 `devops-platform` 仓库运行 `observability/kube-prometheus-stack/sync-llm-serving-dashboard.sh`，将此处的 JSON 发布为 Grafana sidecar 可发现的 ConfigMap；该操作只同步 Dashboard，不会安装 Kubernetes 推理工作负载。

Docker Compose 实例的集群抓取清单在平台仓库，目标是 Docker Desktop host gateway `192.168.65.254` 的 API `8002` 和 llama.cpp `8081`。要先以 `API_HOST_PORT=8002` 启动 Compose；本机开发抓取和 Kubernetes ServiceMonitor 只选择其一，避免重复采集同一实例。

## Kubernetes 部署

两个组件各有一个 Chart 和 Helm Release：

| Release | Chart | 工作负载 |
| --- | --- | --- |
| `llm-serving` | `deploy/charts/gateway` | FastAPI Deployment、Service、HPA、Ingress、ServiceMonitor、Dashboard |
| `llm-serving-inference` | `deploy/charts/inference` | llama.cpp Deployment、Service、ServiceMonitor |

模型别名和并发槽位只在 `deploy/values/model.yaml` 中配置，两个 Release 部署时都传入该文件。默认镜像地址为本地 Harbor 示例 `harbor.local:30080/library/`；先构建并推送镜像，再用部署脚本逐个发布：

```bash
docker login harbor.local:30080
docker build -t harbor.local:30080/library/llm-serving:latest gateway
docker build -t harbor.local:30080/library/llm-serving-llama:latest inference/engines/llamacpp
docker push harbor.local:30080/library/llm-serving:latest
docker push harbor.local:30080/library/llm-serving-llama:latest

kubectl create namespace llm-serving
deploy/scripts/deploy.sh inference latest
deploy/scripts/deploy.sh gateway latest
```

在发布前确认目标集群能拉取镜像、GGUF 模型可由 llama.cpp 镜像提供，并按平台 NetworkPolicy 配置允许 FastAPI 到 llama.cpp、Prometheus 到两个 metrics Service 的流量。

### 从单一 Release 迁移

旧版本把 FastAPI 与 llama.cpp 放在同一个 `llm-serving` Release 中。`deploy/scripts/migrate-split-release.sh` 会检测这种旧 Release，先给 llama.cpp 资源加 `helm.sh/resource-policy: keep` 并改写归属注解，再按当前运行的镜像标签依次升级 gateway、安装 `llm-serving-inference` 接管这些资源，最后移除 keep 注解。迁移过程中推理 Pod 不会被删除重建。Jenkins CD 每次部署前都会运行该脚本；已迁移时脚本直接退出。手动升级旧集群时，先运行一次：

```bash
K8S_NAMESPACE=llm-serving deploy/scripts/migrate-split-release.sh
```

Chart 的 namespaced 资源使用 Helm 的 `--namespace` 作为唯一 Namespace 来源；正常安装时 Chart 不创建或接管 Namespace。上面的 `--create-namespace` 仅在本地首次安装时创建目标 Namespace。Jenkins CD 会在创建 Harbor Pull Secret 前先创建 Namespace。`deploy/scripts/deploy.sh gateway` 还会检测旧 Helm 清单是否曾管理 Namespace；若是，会先执行带 `helm.sh/resource-policy: keep` 的迁移升级，再执行常规升级，避免 Helm 删除 Namespace 及其中其他应用资源。

Chart 创建的 Ingress 通过 `/llm-serving/` 暴露 API，并在转发时去掉此前缀。例如 `/llm-serving/v1/chat/completions` 会转发为 FastAPI 路由 `/v1/chat/completions`。平台 Ingress Controller 的 Namespace 默认设为 `ingress`，可通过 `deploy/charts/gateway/values.yaml` 的 `ingress.namespace` 调整；它必须与 NetworkPolicy 放行的 Namespace 一致。

```bash
kubectl get pods,svc,servicemonitor -n llm-serving
kubectl rollout status deployment/llm-serving -n llm-serving
kubectl rollout status deployment/llm-serving-llama -n llm-serving
```

Chart 不包含 Prometheus 或 Grafana 本体；部署到已有平台时由平台发现应用 ServiceMonitor 和 Dashboard ConfigMap。卸载应用：

```bash
helm uninstall llm-serving -n llm-serving
helm uninstall llm-serving-inference -n llm-serving
```

## CI/CD

`Jenkinsfile.ci` 按改动路径决定构建哪些镜像，对比基线为上一次成功构建的提交（`GIT_PREVIOUS_SUCCESSFUL_COMMIT`）：

| 改动路径 | 构建 |
| --- | --- |
| `gateway/**` | Python 测试 + FastAPI 镜像 |
| `inference/engines/llamacpp/**` | llama.cpp 镜像 |
| `Jenkinsfile.ci`、`deploy/scripts/detect-changes.sh`，或没有可用基线 | 全部 |
| `bench/`、`docs/`、`deploy/charts/` 等其他路径 | 不构建镜像 |

Helm 校验每次都运行。参数 `BUILD_COMPONENTS` 可强制构建 `all`、`gateway` 或 `inference`。构建成功后 CI 归档 `ci-tags.env`，其中只包含本次实际构建的组件标签（Jenkins 构建号）。

`Jenkinsfile.cd` 使用 `GATEWAY_TAG`、`INFERENCE_TAG` 两个参数，留空表示该组件保持现状不部署。两者都填时先部署 inference，再部署 gateway；安全扫描只扫描本次部署的镜像，冒烟测试始终验证完整链路。

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
cd gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 压测与多卡性能实验

`bench/tools/load_metrics.py` 用于制造有足够样本的指标流量；端口需匹配当前 API：

```bash
pip install -r bench/requirements.txt
BASE_URL=http://127.0.0.1:8000 python bench/tools/load_metrics.py --duration 120 --concurrency 8
```

在 BW（DTK）等加速卡环境测试不同模型时，用 `inference/scripts/download_models.sh` 从 ModelScope 下载 `inference/models.yaml` 中登记的权重，用 `inference/engines/vllm-dtk/serve.sh` 启动 vLLM，再用 `bench/scripts/run_perf.sh` 做并发扫描。详见 [bench/README.md](bench/README.md)。

## 文件结构

```text
gateway/
  app/                     FastAPI 路由、llama.cpp 客户端、Langfuse、指标
  tests/                   API 单元测试
  Dockerfile               API 镜像
  requirements.txt         运行时依赖（requirements-dev.txt 额外包含 pytest）
inference/
  models.yaml              模型登记表：ModelScope ID、目录、dtype、量化、允许的 TP
  engines/llamacpp/        llama.cpp + Qwen2 0.5B GGUF 镜像（本地开发与 K8s）
  engines/vllm-dtk/        海光 DCU 上的 vLLM 启动脚本
  scripts/                 权重下载、模型登记表读取
bench/
  scripts/run_perf.sh      vLLM 并发扫描
  tools/                   gateway 压测、基准与客户端
deploy/
  charts/gateway/          gateway Helm Chart 与 Grafana Dashboard
  charts/inference/        llama.cpp Helm Chart
  values/model.yaml        两个 Chart 共用的模型别名与并发槽位
  scripts/                 部署、单 Release 迁移、CI 改动检测
compose.yaml               本地 API + llama.cpp 开发环境
docs/observability/        PromQL 查询与指标口径
Jenkinsfile.ci             按路径触发的 CI
Jenkinsfile.cd             按组件发布的 CD
```
