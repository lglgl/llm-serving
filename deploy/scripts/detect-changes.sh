#!/usr/bin/env bash
# 根据改动路径判断需要构建哪些镜像，每行输出一个组件名（gateway / inference）。
#
# 用法：
#   deploy/scripts/detect-changes.sh <base-commit>   # 与 HEAD 比较
#   deploy/scripts/detect-changes.sh                 # 没有基线：全部构建
#
# 规则：
#   gateway/**                      -> gateway
#   inference/engines/llamacpp/**   -> inference
#   Jenkinsfile.ci 或本脚本         -> 全部（流水线自身变化需要完整验证）
#   其他路径（bench/、docs/、README 等）不触发镜像构建
set -euo pipefail

base="${1:-}"

if [ -z "$base" ] || ! changed="$(git diff --name-only "$base" HEAD 2>/dev/null)"; then
    # 首次构建、基线提交不在本地（浅克隆或被改写）时，保守地全部构建。
    echo gateway
    echo inference
    exit 0
fi

gateway=false
inference=false
while IFS= read -r path; do
    case "$path" in
        Jenkinsfile.ci | deploy/scripts/detect-changes.sh)
            gateway=true
            inference=true
            ;;
        gateway/*) gateway=true ;;
        inference/engines/llamacpp/*) inference=true ;;
    esac
done <<EOF
$changed
EOF

if [ "$gateway" = true ]; then echo gateway; fi
if [ "$inference" = true ]; then echo inference; fi
