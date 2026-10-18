# LLM Serving Grafana 面板与 PromQL

Dashboard 仅包含 8 个推理性能面板：TTFT、TPOT、ITL 近似值、E2E、Output Tokens/s、Prompt Processing Throughput、后端并发/队列深度、FastAPI 模型槽位等待时间。错误率、超时与流式中断指标不放在此性能 Dashboard 中；FastAPI `/metrics` 仍保留这些应用诊断指标。

查询优先采用 llama.cpp 原生指标；后端没有对应口径时使用 FastAPI 指标。Dashboard 源文件为 `k8s/dashboards/llm-serving-performance.json`。所有原生 llama.cpp 查询依赖 ServiceMonitor 注入 `model` 标签；Docker Compose ServiceMonitor 和 Helm Chart 都已配置此标签。

## 面板数据源一览

| 面板 | 来源 | 口径 |
| --- | --- | --- |
| TTFT · 流式首个内容块 | FastAPI | 收到请求到首个非空 SSE 内容块的 P50/P95/P99 |
| TPOT · 原生服务平均与单请求分位数 | llama.cpp + FastAPI | 原生总生成耗时/生成 Token 数；辅助显示 FastAPI 单请求 P50/P95 |
| ITL 近似值 · SSE 内容块间隔 | FastAPI | 相邻非空 SSE 内容块间隔 P50/P95/P99，不等于逐 Token ITL |
| 端到端延迟 · E2E | FastAPI | 包含应用模型槽位等待和后端推理的请求时长，按 stream 区分 |
| Output Tokens/s · 单请求与服务聚合 | FastAPI + llama.cpp | 单请求 P50/P95 与服务聚合生成 Token/s 分开展示 |
| Prompt Processing Throughput | llama.cpp | 原生 Prompt tokens/s Gauge 与输入 Token Counter 的 5 分钟速率 |
| 并发请求数与模型后端排队深度 | llama.cpp | `requests_processing` 与 `requests_deferred` 原生 Gauge |
| FastAPI 模型槽位排队时间 | FastAPI | 请求等待应用并发槽位的 P50/P95，按 stream 区分 |

## TTFT · 首个流式内容块 P50/P95/P99

llama.cpp 没有与 API 接收请求到首个 SSE 内容块等价的原生指标，因此使用 FastAPI Histogram。它包含等待 FastAPI 模型槽位的时间。

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_ttft_seconds_bucket{model=~"$model", stream="true"}[$__rate_interval])
  )
)
```

将 `0.95` 替换为 `0.50` 或 `0.99` 可查看 P50/P99。

## TPOT · 原生服务平均与单请求分位数

主口径使用 llama.cpp 原生累计生成耗时和生成 Token 数之比，是 Token 加权的服务级平均秒/Token，不是单请求 P 分位数：

```promql
sum by (model) (rate(llamacpp:tokens_predicted_seconds_total{model=~"$model"}[5m]))
/
clamp_min(sum by (model) (rate(llamacpp:tokens_predicted_total{model=~"$model"}[5m])), 1e-9)
```

FastAPI 依赖返回的 Token usage 计算单请求平均生成耗时，面板辅助展示其 P50/P95：

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_tpot_seconds_bucket{model=~"$model", stream="true"}[$__rate_interval])
  )
)
```

如果推理后端未返回 usage，FastAPI 单请求 TPOT 不会有新样本；原生服务级平均仍可以由 llama.cpp Counter 计算。

## ITL 近似值 · SSE 内容块间隔

llama.cpp 不报告下游 FastAPI 收到的 SSE 内容块时间间隔。该面板使用 FastAPI 对相邻非空内容块间隔的 P50/P95/P99。SSE 内容块可能包含多个 Token，故不应解读为精确逐 Token ITL。

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_inter_chunk_interval_seconds_bucket{model=~"$model", stream="true"}[$__rate_interval])
  )
)
```

## 端到端延迟 · E2E P50/P95/P99

使用 FastAPI 完整请求时长，按流式与非流式分组：

```promql
histogram_quantile(
  0.95,
  sum by (le, stream) (
    rate(llm_request_duration_seconds_bucket{model=~"$model"}[$__rate_interval])
  )
)
```

## Output Tokens/s · 单请求与服务聚合

单请求 P95：

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_output_tokens_per_second_bucket{model=~"$model", stream="true"}[$__rate_interval])
  )
)
```

服务聚合生成吞吐使用 llama.cpp 原生 Token Counter：

```promql
sum by (model) (rate(llamacpp:tokens_predicted_total{model=~"$model"}[5m]))
```

## Prompt Processing Throughput

llama.cpp 原生即时报告值：

```promql
llamacpp:prompt_tokens_seconds{model=~"$model"}
```

5 分钟服务聚合输入 Token 速率：

```promql
sum by (model) (rate(llamacpp:prompt_tokens_total{model=~"$model"}[5m]))
```

第一条是后端原生 Gauge，空闲时可能为 0；第二条是 Counter 的窗口速率，刚启动或窗口内没有 Prompt 请求时可能没有有效值。llama.cpp 的 `prompt_tokens_total` 明确不计入从缓存复用的 Prompt Token，因此高缓存命中场景下它会低于客户端提交的输入 Token 数。

## 后端并发请求与排队深度

两条均来自 llama.cpp 原生 Gauge：

```promql
sum by (model) (llamacpp:requests_processing{model=~"$model"})
```

```promql
sum by (model) (llamacpp:requests_deferred{model=~"$model"})
```

## FastAPI 模型槽位排队时间

llama.cpp 只提供后端当前 deferred 请求数，不提供 FastAPI 槽位等待耗时。因此此面板用 FastAPI Queue Histogram：

```promql
histogram_quantile(
  0.95,
  sum by (le, stream) (
    rate(llm_queue_wait_seconds_bucket{model=~"$model"}[$__rate_interval])
  )
)
```

## 无数据检查

1. 先确认 Grafana Dashboard 使用平台 Prometheus 数据源 `prometheus`，模型变量能解析出 `qwen2:0.5b`。
2. 检查 Prometheus Targets 中 API 与 llama.cpp 两个目标均为 `UP`。Docker Compose 抓取时分别确认 Docker host gateway 的 `8002` 和 `8081` 可达。
3. 直接检查 API `/metrics` 是否有 `llm_ttft_seconds_bucket`、`llm_request_duration_seconds_bucket` 等样本；检查 llama.cpp `/metrics` 是否有 `llamacpp:tokens_predicted_total`、`llamacpp:requests_processing` 等指标。
4. 运行流式请求产生 TTFT/ITL/请求延迟样本，再等待抓取间隔和至少一个 PromQL rate 窗口。Histogram 分位数在窗口内没有观测时不会返回数据。
5. 检查 ServiceMonitor 的 `release` 标签、namespace selector、Service selector/命名端口，以及原生指标的 `model` relabeling。

## 抓取与 Dashboard 配置

- llama.cpp 启动参数必须包含 `--metrics`。
- Kubernetes ServiceMonitor 由应用 Helm Chart 创建；平台 Prometheus 要允许跨 Namespace 发现 ServiceMonitor，并选中对应 release 标签。
- Dashboard JSON 由 Helm Chart 作为 `grafana_dashboard: "1"` ConfigMap 发布；Grafana sidecar 必须跨 Namespace 搜索 ConfigMap。
- Docker Compose 临时抓取资源位于平台仓库 `observability/kube-prometheus-stack/llm-serving-docker.yaml`。仅在抓取本机 Compose 实例时使用，Kubernetes 正式部署不要重复应用。
- 建议 15 秒抓取间隔。直方图使用 `$__rate_interval`，样本少或时间范围过短时分位数会显示 No data。
