#!/usr/bin/env bash
# 对已启动的 vLLM 服务做并发扫描，每个并发点保存一份结果。
#
# 用法：
#   MODEL_ROOT=/data/models bench/scripts/run_perf.sh qwen3-32b 2
#   第二个参数是服务启动时的 TP，只用于记录结果，不会改变服务。
#
# 环境变量：
#   BASE_URL         vLLM 地址，默认 http://127.0.0.1:8000
#   CONCURRENCY      并发点，默认 "1 4 8 16 32 64 100"
#   INPUT_LEN        随机输入长度，默认 1024
#   OUTPUT_LEN       固定输出长度（忽略 EOS），默认 512
#   PROMPTS_PER_LEVEL 每个并发点的请求数 = max(50, 并发 × 本值)，默认 5
#   BENCH_CMD        压测命令，默认 "vllm bench serve"；
#                    旧版 vLLM 可设为 "python benchmarks/benchmark_serving.py"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ "$#" -ne 2 ]; then
    echo "usage: MODEL_ROOT=... $0 <model-key> <tensor-parallel-size>" >&2
    exit 2
fi

: "${MODEL_ROOT:?set MODEL_ROOT to the persistent model directory}"
key="$1"
tp="$2"
eval "$(python3 "$REPO_ROOT/inference/scripts/model_info.py" env "$key")"

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
CONCURRENCY="${CONCURRENCY:-1 4 8 16 32 64 100}"
INPUT_LEN="${INPUT_LEN:-1024}"
OUTPUT_LEN="${OUTPUT_LEN:-512}"
PROMPTS_PER_LEVEL="${PROMPTS_PER_LEVEL:-5}"
BENCH_CMD="${BENCH_CMD:-vllm bench serve}"

run_id="$(date +%Y%m%d-%H%M%S)-${key}-tp${tp}-in${INPUT_LEN}-out${OUTPUT_LEN}"
result_dir="$REPO_ROOT/bench/results/$run_id"
mkdir -p "$result_dir"

# 记录本次运行的环境，保证结果可复现。
{
    echo "model=$key"
    echo "model_path=$MODEL_ROOT/$MODEL_DIR"
    echo "dtype=$MODEL_DTYPE"
    echo "quantization=${MODEL_QUANTIZATION:-none}"
    echo "tp=$tp"
    echo "input_len=$INPUT_LEN"
    echo "output_len=$OUTPUT_LEN"
    echo "concurrency=$CONCURRENCY"
    echo "git_commit=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "vllm_version=$(python3 -c 'import vllm; print(vllm.__version__)' 2>/dev/null || echo unknown)"
} >"$result_dir/meta.env"
if command -v hy-smi >/dev/null; then
    hy-smi >"$result_dir/hy-smi-before.txt" 2>&1 || true
fi

curl -fsS "$BASE_URL/v1/models" >/dev/null || {
    echo "vLLM is not reachable at $BASE_URL" >&2
    exit 1
}

for concurrency in $CONCURRENCY; do
    num_prompts=$((concurrency * PROMPTS_PER_LEVEL))
    if [ "$num_prompts" -lt 50 ]; then
        num_prompts=50
    fi
    echo "==> concurrency=$concurrency prompts=$num_prompts"
    # BENCH_CMD 需要按空格拆分成命令和子命令。
    # shellcheck disable=SC2086
    $BENCH_CMD \
        --base-url "$BASE_URL" \
        --model "$MODEL_ROOT/$MODEL_DIR" \
        --served-model-name "$MODEL_KEY" \
        --dataset-name random \
        --random-input-len "$INPUT_LEN" \
        --random-output-len "$OUTPUT_LEN" \
        --ignore-eos \
        --max-concurrency "$concurrency" \
        --num-prompts "$num_prompts" \
        --percentile-metrics ttft,tpot,itl,e2el \
        --metric-percentiles 50,95,99 \
        --save-result \
        --result-dir "$result_dir" \
        --result-filename "c${concurrency}.json" \
        2>&1 | tee "$result_dir/c${concurrency}.log"
done

if command -v hy-smi >/dev/null; then
    hy-smi >"$result_dir/hy-smi-after.txt" 2>&1 || true
fi
echo "Results: $result_dir"
