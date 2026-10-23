#!/usr/bin/env bash
# 部署单个组件的 Helm Release，并等待其 Deployment 就绪。
#
# 用法：
#   deploy/scripts/deploy.sh gateway 42
#   deploy/scripts/deploy.sh inference 37
#
# 环境变量：
#   K8S_NAMESPACE  目标 Namespace，默认 llm-serving（需已存在）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAMESPACE="${K8S_NAMESPACE:-llm-serving}"
SHARED_VALUES="$REPO_ROOT/deploy/values/model.yaml"

if [ "$#" -ne 2 ]; then
    echo "usage: $0 <gateway|inference> <image-tag>" >&2
    exit 2
fi

component="$1"
tag="$2"

case "$tag" in
    "" | *[!a-zA-Z0-9_.-]*)
        echo "Invalid image tag: '$tag'" >&2
        exit 1
        ;;
esac

case "$component" in
    gateway)
        release=llm-serving
        deployment=llm-serving
        rollout_timeout=240s
        ;;
    inference)
        release=llm-serving-inference
        deployment=llm-serving-llama
        rollout_timeout=360s
        ;;
    *)
        echo "Unknown component: $component" >&2
        exit 2
        ;;
esac
chart="$REPO_ROOT/deploy/charts/$component"

helm_upgrade() {
    helm upgrade --install "$release" "$chart" \
        --namespace "$NAMESPACE" \
        --values "$SHARED_VALUES" \
        --set-string image.tag="$tag" \
        "$@"
}

# One-time safe handoff for releases whose old manifest managed the Namespace.
if [ "$component" = gateway ] &&
    helm get manifest "$release" --namespace "$NAMESPACE" 2>/dev/null | grep -q '^kind: Namespace$'; then
    echo "Protecting the legacy Namespace resource before handing ownership to Kubernetes."
    helm_upgrade --set namespaceMigration.keepLegacyResource=true
fi

echo "Deploying $component ($release) with image tag $tag"
helm_upgrade

# Attach the pull secret used for private Harbor images.
kubectl -n "$NAMESPACE" patch deployment "$deployment" \
    --type=merge \
    -p '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"harbor-pull-secret"}]}}}}'
kubectl -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout="$rollout_timeout"
