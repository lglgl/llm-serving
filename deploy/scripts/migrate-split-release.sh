#!/usr/bin/env bash
# 一次性迁移：把旧的单一 Release（llm-serving）中的 llama.cpp 资源
# 交给新的 llm-serving-inference Release，过程中不删除、不重建推理 Pod。
#
# 步骤：
#   1. 给旧资源加 helm.sh/resource-policy=keep，并把归属注解改成新 Release；
#   2. 用当前正在运行的镜像标签升级 gateway，旧 Release 清单不再包含 llama 资源，
#      keep 注解让 Helm 跳过删除；
#   3. 用当前标签安装 inference Release，Helm 按归属注解接管已有资源；
#   4. 去掉 keep 注解，之后卸载 inference Release 会正常清理资源。
#
# 已迁移或全新安装时直接退出，可重复执行。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NAMESPACE="${K8S_NAMESPACE:-llm-serving}"
LEGACY_RELEASE=llm-serving
INFERENCE_RELEASE=llm-serving-inference
RESOURCES=(
    deployment/llm-serving-llama
    service/llm-serving-llama
    serviceaccount/llm-serving-llama
    networkpolicy/llm-serving-llama
    servicemonitor.monitoring.coreos.com/llm-serving-llama
)

if ! helm get manifest "$LEGACY_RELEASE" --namespace "$NAMESPACE" 2>/dev/null |
    grep -q '^  name: llm-serving-llama$'; then
    echo "No split-release migration needed."
    exit 0
fi

echo "Legacy release $LEGACY_RELEASE still manages llama.cpp resources; migrating."

# 迁移时保持两个组件的当前版本，新版本由后续常规部署发布。
current_tag() {
    helm get values "$LEGACY_RELEASE" --namespace "$NAMESPACE" -o json |
        python3 -c 'import json, sys; v = json.load(sys.stdin) or {}; print((v.get(sys.argv[1]) or {}).get("tag") or "latest")' "$1"
}
gateway_tag="$(current_tag image)"
inference_tag="$(current_tag llamaImage)"
echo "Current tags: gateway=$gateway_tag inference=$inference_tag"

existing=()
for resource in "${RESOURCES[@]}"; do
    if kubectl -n "$NAMESPACE" get "$resource" >/dev/null 2>&1; then
        existing+=("$resource")
    fi
done

for resource in ${existing[@]+"${existing[@]}"}; do
    kubectl -n "$NAMESPACE" annotate --overwrite "$resource" \
        helm.sh/resource-policy=keep \
        meta.helm.sh/release-name="$INFERENCE_RELEASE" \
        meta.helm.sh/release-namespace="$NAMESPACE"
done

K8S_NAMESPACE="$NAMESPACE" "$SCRIPT_DIR/deploy.sh" gateway "$gateway_tag"
K8S_NAMESPACE="$NAMESPACE" "$SCRIPT_DIR/deploy.sh" inference "$inference_tag"

for resource in ${existing[@]+"${existing[@]}"}; do
    kubectl -n "$NAMESPACE" annotate "$resource" helm.sh/resource-policy-
done

echo "Migration complete: $INFERENCE_RELEASE now owns llama.cpp resources."
