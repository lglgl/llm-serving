#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="llm-serving-pilot"
NAMESPACE="llm-serving-pilot"
CHART="$ROOT_DIR/chart/llm-serving-pilot"
APP_TAG="${1:?usage: scripts/cd-pilot.sh <app-tag> <mock-tag>}"
MOCK_TAG="${2:?usage: scripts/cd-pilot.sh <app-tag> <mock-tag>}"
REGISTRY="${REGISTRY:-harbor.local:30080/library}"
APP_IMAGE="${REGISTRY}/llm-serving:${APP_TAG}"
MOCK_IMAGE="${REGISTRY}/llm-serving-mock:${MOCK_TAG}"

if [[ "$(kubectl config current-context)" != "docker-desktop" ]]; then
  echo "Refusing CD pilot: expected kubectl context docker-desktop" >&2
  exit 1
fi

helm lint "$CHART"
helm upgrade --install "$RELEASE" "$CHART" \
  --namespace "$NAMESPACE" --create-namespace \
  --set-string image.repository="${APP_IMAGE%:*}" \
  --set-string image.tag="${APP_IMAGE##*:}" \
  --set-string mockBackend.image.repository="${MOCK_IMAGE%:*}" \
  --set-string mockBackend.image.tag="${MOCK_IMAGE##*:}" \
  --set-string deploymentStamp="pilot-${APP_TAG}" \
  --wait --timeout 180s

kubectl rollout status deployment/"$RELEASE" -n "$NAMESPACE" --timeout=180s
kubectl rollout status deployment/"$RELEASE"-mock -n "$NAMESPACE" --timeout=180s

BASE_REVISION="$(helm history "$RELEASE" -n "$NAMESPACE" -o json | python3 -c 'import json,sys; print(max(int(x["revision"]) for x in json.load(sys.stdin)))')"
LOCAL_PORT="${CD_SMOKE_PORT:-18081}"
PORT_FORWARD_LOG="${TMPDIR:-/tmp}/llm-serving-pilot-port-forward.log"
kubectl port-forward -n "$NAMESPACE" "svc/$RELEASE" "$LOCAL_PORT:8000" >"$PORT_FORWARD_LOG" 2>&1 &
PORT_FORWARD_PID=$!
cleanup() {
  kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

python3 "$ROOT_DIR/scripts/smoke_api.py" "http://127.0.0.1:$LOCAL_PORT"

# Exercise Helm's recorded rollback path using a harmless Pod-template stamp change.
helm upgrade "$RELEASE" "$CHART" \
  --namespace "$NAMESPACE" \
  --set-string image.repository="${APP_IMAGE%:*}" \
  --set-string image.tag="${APP_IMAGE##*:}" \
  --set-string mockBackend.image.repository="${MOCK_IMAGE%:*}" \
  --set-string mockBackend.image.tag="${MOCK_IMAGE##*:}" \
  --set-string deploymentStamp="rollback-probe-${APP_TAG}" \
  --wait --timeout 180s
helm rollback "$RELEASE" "$BASE_REVISION" -n "$NAMESPACE" --wait --timeout 180s
kubectl rollout status deployment/"$RELEASE" -n "$NAMESPACE" --timeout=180s
python3 "$ROOT_DIR/scripts/smoke_api.py" "http://127.0.0.1:$LOCAL_PORT"

printf 'CD_PILOT_RESULT=passed\nNAMESPACE=%s\nRELEASE=%s\nAPP_IMAGE=%s\nMOCK_IMAGE=%s\nROLLBACK_TO_REVISION=%s\n' \
  "$NAMESPACE" "$RELEASE" "$APP_IMAGE" "$MOCK_IMAGE" "$BASE_REVISION"
