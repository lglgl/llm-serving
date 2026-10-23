# bench

性能与质量实验工具。实验结果写入 `bench/results/`，该目录不纳入 Git。

| 路径 | 用途 |
| --- | --- |
| `scripts/run_perf.sh` | 对已启动的 vLLM 做并发扫描（默认 1→100），每个并发点保存 JSON 结果、日志和运行环境 |
| `tools/load_metrics.py` | 对 gateway 做限时并发压测，并核对 FastAPI Prometheus 指标 |
| `tools/benchmark.py` | 单请求流式基准，打印 TTFT 和 Token/s |
| `tools/client.py` | 调用 gateway 的命令行客户端 |
| `results/` | 实验输出（已忽略） |

## 多卡性能测试流程

在 BW（DTK）实例上，使用平台提供的 DTK 适配 vLLM 镜像：

```bash
export MODEL_ROOT=/持久化文件存储/models
pip install -U modelscope
inference/scripts/download_models.sh qwen3-8b

# 终端 1：启动服务（模型 key 见 inference/models.yaml）
inference/engines/vllm-dtk/serve.sh qwen3-8b 1

# 终端 2：并发扫描
bench/scripts/run_perf.sh qwen3-8b 1
```

性能测试直接访问 vLLM，不经过 gateway：gateway 的模型槽位信号量会把并发限制在
`LLAMA_PARALLEL_SLOTS`，测出来的是排队时间而不是推理性能。

`run_perf.sh` 使用固定长度的随机输入并忽略 EOS，保证每轮输出长度一致。
Qwen3 默认开启思考模式，输出长度波动很大，不能用自然对话做吞吐对比。

## gateway 指标压测

```bash
pip install -r bench/requirements.txt
BASE_URL=http://127.0.0.1:8000 python bench/tools/load_metrics.py --duration 120 --concurrency 8
```
