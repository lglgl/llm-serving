# LLM 指标查询

FastAPI 通过 `/metrics` 暴露 Prometheus 指标。请求指标带有 `model`、`status`、`stream` 标签；
Token 与流式性能指标带有 `model`、`stream` 标签。传入非默认模型名时，应用会将 `model` 收敛为 `other`，
避免 Prometheus 时序数量无限增长。

下面表达式可直接放入 Grafana Prometheus 面板。假设 Grafana 变量 `$model` 默认值为 `qwen2:0.5b`，
`$stream` 的值为 `false` 或 `true`。

## LLM 请求速率

按模型、结果和流式状态显示每秒请求数。每个 `model/status/stream` 组合会单独形成一条时间序列。

```promql
sum by (model, status, stream) (
  rate(llm_requests_total{model="$model"}[$__rate_interval])
)
```

可以分别筛选 `status="success"`、`status="error"` 和 `stream="false"` / `"true"`。

## LLM 请求延迟 P50 / P90 / P95

分别将 `0.50`、`0.90`、`0.95` 替换为需要的分位数；`$stream` 可选 `false` 或 `true`。

```promql
histogram_quantile(
  0.50,
  sum by (le) (
    rate(llm_request_duration_seconds_bucket{model="$model", stream="$stream"}[$__rate_interval])
  )
)
```

直方图需有多个样本才适合观察分位数。没有请求或只有刚启动的服务时，面板可能暂时显示 No data。

## Input / Output / Total Tokens per second

Token/s 根据 Token Counter 的变化率计算。总 Token/s 是输入和输出速率相加，无需另设重复 Counter。

```promql
sum(rate(llm_input_tokens_total{model="$model", stream="$stream"}[$__rate_interval]))
```

```promql
sum(rate(llm_output_tokens_total{model="$model", stream="$stream"}[$__rate_interval]))
```

```promql
sum(rate(llm_input_tokens_total{model="$model", stream="$stream"}[$__rate_interval]))
+ sum(rate(llm_output_tokens_total{model="$model", stream="$stream"}[$__rate_interval]))
```

Token 计数依赖 llama.cpp 返回 `usage`。后端未提供用量时，Token/s 不会伪造数值，而由用量缺失指标记录。

## TTFT P95

TTFT 表示请求开始到首个非空生成内容的时间。当前只对流式生成记录观测值。

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_ttft_seconds_bucket{model="$model", stream="true"}[$__rate_interval])
  )
)
```

## TPOT P95

TPOT 用生成区间除以首 Token 之后的输出 Token 数计算；至少需要两个输出 Token 和有效 usage。

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_tpot_seconds_bucket{model="$model", stream="true"}[$__rate_interval])
  )
)
```

## 单请求输出速度 P95

每个流式请求的输出 Token/s 作为一个 Histogram 样本，再计算请求分布的 P95。

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(llm_output_tokens_per_second_bucket{model="$model", stream="true"}[$__rate_interval])
  )
)
```

## Token 用量缺失计数（窗口增量）

下面示例显示近 5 分钟缺少有效 usage 的请求数。

```promql
sum by (model, stream) (
  increase(llm_token_usage_missing_total{model="$model", stream="$stream"}[5m])
)
```

## LLM 请求并发

这是瞬时 Gauge，不要对它使用 `rate()`。

```promql
llm_requests_in_progress{model="$model", stream="$stream"}
```

## 所选时间范围内的 LLM 请求总数

Grafana `$__range` 会展开为当前面板时间范围。

```promql
sum by (model, status, stream) (
  increase(llm_requests_total{model="$model"}[$__range])
)
```

## 验证采集链路

1. 直接访问 FastAPI 的 `http://<服务地址>:8000/metrics`，确认出现 `llm_requests_total`、
   `llm_input_tokens_total`、`llm_ttft_seconds_bucket` 和 `llm_tpot_seconds_bucket`。
2. Prometheus Targets 中确认 FastAPI `/metrics` target 为 `UP`。
3. 先制造几次流式及非流式请求，再运行上述查询。Prometheus 的抓取间隔为 30 秒，刚产生的样本可能要等一次抓取。

注意：仓库里的 `ServiceMonitor` 只发现 Kubernetes Service。使用 Docker Compose 时，
集群 Prometheus 不会自动发现宿主机上的 Compose API；需要让 Prometheus 能访问 Compose 主机并添加静态抓取目标，
或将更新后的应用部署进 Kubernetes。Counter/Histogram 的 `rate()`、`increase()` 和分位数查询也需要足够的抓取样本。
