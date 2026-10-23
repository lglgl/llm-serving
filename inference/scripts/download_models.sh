#!/usr/bin/env bash
# 从 ModelScope 国内源多线程下载 models.yaml 中登记的模型权重。
#
# 用法：
#   MODEL_ROOT=/data/models inference/scripts/download_models.sh qwen3-8b qwen3-8b-awq
#   MODEL_ROOT=/data/models inference/scripts/download_models.sh --all
#
# 环境变量：
#   MODEL_ROOT   权重根目录（必填，放在持久化文件存储上，不要用系统盘）
#   MAX_WORKERS  每个模型的下载线程数，默认 8
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
: "${MODEL_ROOT:?set MODEL_ROOT to the persistent model directory}"
MAX_WORKERS="${MAX_WORKERS:-8}"

if [ "$#" -eq 0 ]; then
    echo "usage: MODEL_ROOT=... $0 <model-key>... | --all" >&2
    echo "models:" >&2
    python3 "$SCRIPT_DIR/model_info.py" list | sed 's/^/  /' >&2
    exit 2
fi

if [ "$1" = "--all" ]; then
    set -- $(python3 "$SCRIPT_DIR/model_info.py" list)
fi

command -v modelscope >/dev/null || {
    echo "modelscope CLI not found: pip install -U modelscope" >&2
    exit 1
}

mkdir -p "$MODEL_ROOT"
for key in "$@"; do
    eval "$(python3 "$SCRIPT_DIR/model_info.py" env "$key")"
    target="$MODEL_ROOT/$MODEL_DIR"
    echo "==> $MODEL_KEY: $MODEL_MODELSCOPE_ID -> $target"
    # modelscope 会跳过已完整下载的文件，中断后重跑即可续传。
    modelscope download \
        --model "$MODEL_MODELSCOPE_ID" \
        --local_dir "$target" \
        --max-workers "$MAX_WORKERS"
    du -sh "$target"
done

df -h "$MODEL_ROOT"
