#!/usr/bin/env bash
# 在海光 DCU（DTK）上启动 vLLM OpenAI-compatible 服务。
#
# 必须在平台或光合社区提供的 DTK 适配 vLLM 镜像中运行；
# 直接 pip install 的 CUDA 版 vLLM 不能在 DCU 上运行。
#
# 用法：
#   MODEL_ROOT=/data/models inference/engines/vllm-dtk/serve.sh qwen3-32b 2
#
# 环境变量：
#   MODEL_ROOT           权重根目录（必填）
#   PORT                 服务端口，默认 8000
#   MAX_MODEL_LEN        最大上下文，默认 8192
#   GPU_MEM_UTIL         显存利用率，默认 0.9
#   HIP_VISIBLE_DEVICES  使用哪些卡，默认按 TP 取前 N 张
#   EXTRA_ARGS           追加给 vllm serve 的参数（不同 vLLM 版本参数有差异）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFERENCE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ "$#" -ne 2 ]; then
    echo "usage: MODEL_ROOT=... $0 <model-key> <tensor-parallel-size>" >&2
    exit 2
fi

: "${MODEL_ROOT:?set MODEL_ROOT to the persistent model directory}"
key="$1"
tp="$2"

eval "$(python3 "$INFERENCE_DIR/scripts/model_info.py" env "$key")"

case " $MODEL_TP " in
    *" $tp "*) ;;
    *)
        echo "TP=$tp is not allowed for $key (allowed: $MODEL_TP)" >&2
        exit 1
        ;;
esac

model_path="$MODEL_ROOT/$MODEL_DIR"
test -d "$model_path" || {
    echo "model not found: $model_path; run inference/scripts/download_models.sh $key" >&2
    exit 1
}

if [ -z "${HIP_VISIBLE_DEVICES:-}" ]; then
    HIP_VISIBLE_DEVICES="$(seq -s, 0 $((tp - 1)))"
    export HIP_VISIBLE_DEVICES
fi

args=(
    "$model_path"
    --served-model-name "$MODEL_KEY"
    --tensor-parallel-size "$tp"
    --dtype "$MODEL_DTYPE"
    --max-model-len "${MAX_MODEL_LEN:-8192}"
    --gpu-memory-utilization "${GPU_MEM_UTIL:-0.9}"
    --host 0.0.0.0
    --port "${PORT:-8000}"
)
if [ -n "$MODEL_QUANTIZATION" ]; then
    args+=(--quantization "$MODEL_QUANTIZATION")
fi

echo "HIP_VISIBLE_DEVICES=$HIP_VISIBLE_DEVICES"
set -x
# EXTRA_ARGS 需要按空格拆分成多个参数。
# shellcheck disable=SC2086
exec vllm serve "${args[@]}" ${EXTRA_ARGS:-}
